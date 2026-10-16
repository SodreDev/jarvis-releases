"""Dispositivo real: a proibição em CI, as duas recusas e a ponte com os adaptadores do F1-01.

**O que estes testes NÃO provam:** que o microfone e o alto-falante do dono funcionam. Não há
placa de som nesta máquina e o PortAudio nem está instalado — o caminho de dispositivo real
continua **não verificado** até o dono rodar. O que dá para provar sem hardware é tudo o que
acontece antes de tocar na placa: a recusa sob CI, a diferença entre "falta o extra" e "falta
a biblioteca do sistema", e que a ponte entrega o backend certo.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any

import pytest

from jarvis.audio_io.dispositivo import (
    BibliotecaDeAudioAusente,
    CapturaDoDispositivo,
    Dispositivo,
    ReproducaoNoDispositivo,
    importar_sounddevice,
    listar_dispositivos,
)
from jarvis.audio_io.erros import DispositivoIndisponivel, DispositivoProibidoEmCI
from jarvis.audio_io.fontes import FonteDeDispositivo
from jarvis.audio_io.quadro import AMOSTRAS_POR_QUADRO, BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.audio_io.sumidouros import SumidouroDeDispositivo
from jarvis.relogio import RelogioFalso

FORA_DO_CI: dict[str, str] = {}


def test_ci_continua_barrando_antes_de_qualquer_biblioteca() -> None:
    """A proibição do F1-01 é a primeira linha, e vale também para listar dispositivos."""
    with pytest.raises(DispositivoProibidoEmCI):
        CapturaDoDispositivo(relogio=RelogioFalso(), ambiente={"CI": "1"}).abrir()
    with pytest.raises(DispositivoProibidoEmCI):
        ReproducaoNoDispositivo(ambiente={"CI": "1"}).abrir()
    with pytest.raises(DispositivoProibidoEmCI):
        listar_dispositivos({"CI": "1"})


def _sem_modulo(nome: str, erro: Exception) -> Callable[..., Any]:
    importar = builtins.__import__

    def fingir(alvo: str, *resto: Any, **chaves: Any) -> Any:
        if alvo == nome:
            raise erro
        return importar(alvo, *resto, **chaves)

    return fingir


def test_extra_ausente_e_biblioteca_do_sistema_ausente_sao_recusas_diferentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A segunda é a comum no Linux, e mandar reinstalar o pacote Python não resolveria."""
    monkeypatch.setattr(
        builtins, "__import__", _sem_modulo("sounddevice", ImportError("sem pacote"))
    )
    with pytest.raises(BibliotecaDeAudioAusente, match="uv sync --group dispositivo"):
        importar_sounddevice()

    monkeypatch.setattr(
        builtins,
        "__import__",
        _sem_modulo("sounddevice", OSError("PortAudio library not found")),
    )
    with pytest.raises(BibliotecaDeAudioAusente) as erro:
        importar_sounddevice()
    assert "dnf install portaudio" in str(erro.value)
    assert "--texto" in str(erro.value), "a recusa tem de oferecer o caminho que funciona"


def test_a_fonte_do_f1_01_delega_para_o_backend_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ponte: `audio-io` conhece `FonteDeAudio`, e quem abre a placa é o módulo do extra."""
    abertos: list[object] = []

    class CapturaFalsa:
        device_id = "dispositivo:7"

        def __init__(self, **argumentos: Any) -> None:
            self.argumentos = argumentos
            abertos.append(self)

        def abrir(self) -> None:
            return None

        def quadros(self) -> Any:
            from jarvis.audio_io.quadro import Quadro

            yield Quadro(
                indice=0,
                amostras=bytes(AMOSTRAS_POR_QUADRO * BYTES_POR_AMOSTRA),
                ts_mono_ns=1,
                taxa=TAXA_PADRAO,
            )

        def fechar(self) -> None:
            return None

    import jarvis.audio_io.dispositivo as modulo

    monkeypatch.setattr(modulo, "CapturaDoDispositivo", CapturaFalsa)
    fonte = FonteDeDispositivo(relogio=RelogioFalso(), ambiente=FORA_DO_CI, dispositivo=7)
    fonte.abrir()

    assert fonte.device_id == "dispositivo:7"
    assert abertos[0].argumentos["dispositivo"] == 7  # type: ignore[attr-defined]
    assert len(list(fonte.quadros())) == 1
    fonte.fechar()


def test_fonte_fechada_nao_entrega_quadro() -> None:
    fonte = FonteDeDispositivo(relogio=RelogioFalso(), ambiente=FORA_DO_CI)
    with pytest.raises(DispositivoIndisponivel):
        next(iter(fonte.quadros()))


def test_sumidouro_fechado_recusa_escrever() -> None:
    with pytest.raises(DispositivoIndisponivel):
        SumidouroDeDispositivo(ambiente=FORA_DO_CI).escrever(b"\x00\x00")


def test_limpar_sem_fluxo_nao_explode() -> None:
    """A `ui` chama `limpar` no `Cancel` mesmo com o playback fechado (F1-03)."""
    assert SumidouroDeDispositivo(ambiente=FORA_DO_CI).limpar() == 0


def test_o_sumidouro_delega_e_declara_que_nao_sabe_o_que_o_driver_descartou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReproducaoFalsa:
        device_id = "dispositivo:3"
        amostras_consumidas = 0

        def __init__(self, **argumentos: Any) -> None:
            self.abortos = 0

        def abrir(self) -> None:
            return None

        def escrever(self, amostras: bytes) -> int:
            consumidas = len(amostras) // BYTES_POR_AMOSTRA
            self.amostras_consumidas += consumidas
            return consumidas

        def limpar(self) -> int:
            self.abortos += 1
            return 0

        def fechar(self) -> None:
            return None

    import jarvis.audio_io.dispositivo as modulo

    monkeypatch.setattr(modulo, "ReproducaoNoDispositivo", ReproducaoFalsa)
    sumidouro = SumidouroDeDispositivo(ambiente=FORA_DO_CI, dispositivo=3)
    sumidouro.abrir()

    assert sumidouro.escrever(b"\x00\x00" * 160) == 160
    assert sumidouro.amostras_consumidas == 160
    # 0 aqui quer dizer "não sei quantas o driver jogou fora", e isso é o F1-16.
    assert sumidouro.limpar() == 0
    sumidouro.fechar()


def test_dispositivo_se_descreve_para_o_diagnostico() -> None:
    linha = str(
        Dispositivo(
            indice=2,
            nome="Placa do dono",
            entradas=2,
            saidas=0,
            taxa_padrao=48000.0,
            padrao_de_entrada=True,
        )
    )
    assert "2: Placa do dono" in linha
    assert "entrada×2" in linha and "saída" not in linha
    assert "padrão de entrada" in linha
