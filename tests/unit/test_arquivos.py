"""Troca atômica de arquivo pequeno — e o caminho do Windows, **simulado** (P11).

Não há Windows aqui, então a disputa de arquivo (`ERROR_SHARING_VIOLATION`, que lá faz o
`replace` falhar quando o destino está aberto) é simulada levantando `PermissionError` no lugar
certo. É simulação, e está dito: o que confirma de verdade é o CI nos dois sistemas. O que estes
testes garantem é que **o nosso lado** se comporta — tenta de novo, não levanta no laço de áudio,
e não confunde "não deu agora" com "não existe".
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.arquivos import (
    ESPERA_S,
    TENTATIVAS,
    LeituraOcupada,
    escrever_atomico,
    ler_texto,
    tranca_exclusiva,
)
from jarvis.microfone import ARQUIVO_ESTADO, Modo, Pedido, escrever_pedido, ler_pedido
from jarvis.ui.painel import PainelDoMicrofone


def test_escreve_inteiro_e_nao_deixa_temporario(tmp_path: Path) -> None:
    alvo = tmp_path / "estado.json"

    assert escrever_atomico(alvo, '{"a": 1}') is True
    assert alvo.read_text(encoding="utf-8") == '{"a": 1}'
    assert list(tmp_path.glob("*.tmp")) == [], "temporário não pode ficar para trás"


def test_o_temporario_leva_o_pid_porque_ha_dois_escritores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`degradacao.json` é escrito pelo `s2` e pelo `agentd`: um `.tmp` só intercalaria bytes."""
    alvo = tmp_path / "degradacao.json"
    vistos: list[str] = []
    original = Path.replace

    def espiar(self: Path, destino: Path) -> Path:
        vistos.append(self.name)
        return original(self, destino)

    monkeypatch.setattr(Path, "replace", espiar)
    escrever_atomico(alvo, "{}")

    assert vistos == [f"degradacao.json.{os.getpid()}.tmp"]


def test_tenta_de_novo_quando_o_destino_esta_ocupado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Windows o destino aberto por outro processo faz o `replace` falhar. Insistir resolve."""
    alvo = tmp_path / "estado.json"
    original = Path.replace
    falhas = [0]

    def ocupado_duas_vezes(self: Path, destino: Path) -> Path:
        falhas[0] += 1
        if falhas[0] <= 2:
            raise PermissionError("WinError 32: o arquivo está sendo usado por outro processo")
        return original(self, destino)

    monkeypatch.setattr(Path, "replace", ocupado_duas_vezes)

    assert escrever_atomico(alvo, "valeu") is True
    assert alvo.read_text(encoding="utf-8") == "valeu"
    assert falhas[0] == 3


def test_desiste_em_silencio_em_vez_de_derrubar_o_laco_de_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quem escreve o estado é o laço de 20 ms: ele não pode morrer por disputa de arquivo."""
    alvo = tmp_path / "estado.json"

    def sempre_ocupado(self: Path, destino: Path) -> Path:
        raise PermissionError("WinError 32")

    monkeypatch.setattr(Path, "replace", sempre_ocupado)

    assert escrever_atomico(alvo, "nada", espera_s=0.0) is False
    assert not alvo.exists()
    assert list(tmp_path.glob("*.tmp")) == [], "a desistência limpa o temporário"
    assert TENTATIVAS >= 3 and ESPERA_S <= 0.01


def test_ler_texto_separa_ausente_de_ocupado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ausente = ler_texto(tmp_path / "nao-existe")
    alvo = tmp_path / "existe"
    alvo.write_text("oi", encoding="utf-8")
    assert (ausente, ler_texto(alvo)) == (None, "oi")

    def ocupado(self: Path, **_kwargs: object) -> str:
        raise PermissionError("WinError 32")

    monkeypatch.setattr(Path, "read_text", ocupado)

    with pytest.raises(LeituraOcupada):
        ler_texto(alvo)


def test_pedido_ocupado_mantem_o_anterior_e_corrompido_desliga(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A distinção que importa: ruído de um instante não pode virar ordem de desligar."""
    escrever_pedido(tmp_path, Pedido(modo=Modo.ESCUTA))
    original = Path.read_text

    def ocupado(self: Path, **kwargs: object) -> str:
        if self.name.startswith("microfone-pedido"):
            raise PermissionError("WinError 32")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", ocupado)
    ocupado_devolve = ler_pedido(tmp_path)
    monkeypatch.undo()

    (tmp_path / "microfone-pedido.json").write_text("{não é json", encoding="utf-8")
    corrompido_devolve = ler_pedido(tmp_path)

    assert ocupado_devolve is None, "None = siga com o que tinha, não = desligue"
    assert corrompido_devolve == Pedido(modo=Modo.DESLIGADO)


def test_o_indicador_nao_pisca_quando_o_arquivo_esta_ocupado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Indicador que pisca porque alguém estava escrevendo o arquivo é indicador que mente."""
    from jarvis.microfone import EstadoDaFonte, escrever_estado

    painel = PainelDoMicrofone(raiz=tmp_path)
    escrever_estado(tmp_path, EstadoDaFonte(aberta=True, amostras=320, modo=Modo.PTT))
    ligado_antes = painel.ouvindo
    original = Path.read_text

    def ocupado(self: Path, **kwargs: object) -> str:
        if self.name.startswith(ARQUIVO_ESTADO):
            raise PermissionError("WinError 32")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", ocupado)

    assert ligado_antes is True
    assert painel.ouvindo is True, "o último estado conhecido tem um tick de idade, não mente"
    assert painel.estado.amostras == 320


# --- trava do par ler→escrever (achado 5 da revisão F0+F1) ------------------------
def test_so_um_entra_na_tranca_por_vez(tmp_path: Path) -> None:
    """A trava é por descritor, então vale entre processos — e entre descritores daqui."""
    alvo = tmp_path / "estado.json"

    with tranca_exclusiva(alvo) as dentro:
        assert dentro
        with tranca_exclusiva(alvo, tentativas=1, espera_s=0.0) as tambem_dentro:
            assert not tambem_dentro, "dois escritores dentro da mesma trava"

    with tranca_exclusiva(alvo, tentativas=1, espera_s=0.0) as depois:
        assert depois, "soltar a trava tem de deixar o próximo entrar"


def test_a_trava_e_um_arquivo_ao_lado_e_nao_o_arquivo_trocado(tmp_path: Path) -> None:
    """`replace` cria inode novo: travar o próprio arquivo deixaria os dois lados entrarem."""
    alvo = tmp_path / "estado.json"

    with tranca_exclusiva(alvo):
        escrever_atomico(alvo, "{}")

    assert (tmp_path / "estado.json.lock").exists()
    assert alvo.read_text(encoding="utf-8") == "{}"
