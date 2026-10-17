"""Um ponto só para a chave: ambiente primeiro, depois o chaveiro — para TTS, ASR, diagnóstico e
a janela (bug do dono, 2026-10-16: a janela guardava no chaveiro e o resto só lia o ambiente).

O chaveiro aqui é falso; sob `CI` (a suíte inteira) o de verdade nunca é consultado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.gui import chaveiro
from jarvis.voz import aferir
from jarvis.voz.chaves import VARIAVEL_ELEVENLABS, Chave, SegredoAusente
from jarvis.voz.cli import diagnosticar
from jarvis.voz.config import Configuracao, escrever

GUARDADA = "chave-guardada-no-chaveiro-1234567890"
EXPORTADA = "chave-exportada-no-shell-0987654321"


class ChaveiroFalso:
    def __init__(self, guardadas: dict[str, str]) -> None:
        self.guardadas = guardadas
        self.lidas: list[str] = []

    def get_keyring(self) -> object:
        return self

    def get_password(self, servico: str, conta: str) -> str | None:
        self.lidas.append(conta)
        return self.guardadas.get(conta)


@pytest.fixture
def falso(monkeypatch: pytest.MonkeyPatch) -> ChaveiroFalso:
    guardado = ChaveiroFalso({VARIAVEL_ELEVENLABS: GUARDADA})
    monkeypatch.setattr(chaveiro, "_modulo", lambda: guardado)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(VARIAVEL_ELEVENLABS, raising=False)
    return guardado


def test_sem_variavel_a_chave_vem_do_chaveiro(falso: ChaveiroFalso) -> None:
    chave = Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente={})
    assert chave.usar() == GUARDADA
    assert Chave.origem(VARIAVEL_ELEVENLABS, ambiente={}) == "chaveiro"
    assert Chave.presente(VARIAVEL_ELEVENLABS, ambiente={})


def test_a_variavel_exportada_ganha(falso: ChaveiroFalso) -> None:
    ambiente = {VARIAVEL_ELEVENLABS: EXPORTADA}
    assert Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente=ambiente).usar() == EXPORTADA
    assert Chave.origem(VARIAVEL_ELEVENLABS, ambiente=ambiente) == "ambiente"


def test_sob_ci_o_chaveiro_nao_e_consultado(
    falso: ChaveiroFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "1")
    with pytest.raises(SegredoAusente):
        Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente={})
    assert falso.lidas == []


def test_sem_chave_em_lugar_nenhum_a_frase_diz_o_que_fazer(falso: ChaveiroFalso) -> None:
    falso.guardadas.clear()
    with pytest.raises(SegredoAusente) as erro:
        Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente={})
    frase = str(erro.value)
    assert "nem no chaveiro" in frase and "Guarde a chave na janela" in frase
    assert "export " in frase


def test_diagnostico_ve_a_chave_do_chaveiro_e_nao_a_mostra(
    falso: ChaveiroFalso, tmp_path: Path
) -> None:
    configuracao = tmp_path / "jarvis-voz.toml"
    escrever(Configuracao(tts="tts-elevenlabs", nuvem_ligada=("tts-elevenlabs",)), configuracao)
    linhas: list[str] = []
    diagnosticar(linhas.append, caminho=configuracao, ambiente={})
    texto = "\n".join(linhas)
    assert f"{VARIAVEL_ELEVENLABS}: definida (chaveiro do sistema)" in texto
    assert "tts-elevenlabs: a chave" not in texto
    assert GUARDADA not in texto


def test_testar_voz_sem_chave_diz_o_motivo_em_vez_de_quebrar(
    falso: ChaveiroFalso, tmp_path: Path
) -> None:
    falso.guardadas.clear()
    prova = aferir.provar_voz(
        Configuracao(
            tts="tts-elevenlabs", voz_elevenlabs="voz-de-teste", nuvem_ligada=("tts-elevenlabs",)
        ),
        raiz=tmp_path,
        ambiente={},
    )
    assert prova.erro.startswith("tts-elevenlabs:")
    assert "nem no chaveiro" in prova.erro
