"""A chave no chaveiro do sistema (ADR-0019): guardada, nunca mostrada, nunca em `os.environ`.

**Nenhum destes testes toca no chaveiro do dono.** O `keyring` é injetado por um falso — o
que se prova aqui é a nossa regra (precedência, recusa, redação, mapa em memória), não a
biblioteca dos outros.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from _pytest.capture import CaptureFixture

from jarvis.gui import chaveiro
from jarvis.voz.chaves import VARIAVEL_GROQ, SegredoAusente

SEGREDO = "gsk_chave_de_teste_1234567890"


class ChaveiroFalso:
    """O mínimo da interface do `keyring` que o nosso código usa."""

    def __init__(self, *, funciona: bool = True) -> None:
        self.guardado: dict[tuple[str, str], str] = {}
        self.funciona = funciona

    # a API do keyring
    def get_keyring(self) -> object:
        return self if self.funciona else KeyringFail()

    def set_password(self, servico: str, conta: str, valor: str) -> None:
        self.guardado[(servico, conta)] = valor

    def get_password(self, servico: str, conta: str) -> str | None:
        return self.guardado.get((servico, conta))

    def delete_password(self, servico: str, conta: str) -> None:
        del self.guardado[(servico, conta)]


class KeyringFail:
    """É assim que o `keyring` diz "não há chaveiro aqui": o back-end `backends.fail.Keyring`,
    que não levanta na escolha — só na hora de usar."""


@pytest.fixture
def falso(monkeypatch: pytest.MonkeyPatch) -> ChaveiroFalso:
    chaveiro_falso = ChaveiroFalso()
    monkeypatch.setattr(chaveiro, "_modulo", lambda: chaveiro_falso)
    return chaveiro_falso


def test_guarda_e_le_sem_passar_pelo_disco_do_projeto(falso: ChaveiroFalso) -> None:
    chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)

    assert chaveiro.valor(VARIAVEL_GROQ) == SEGREDO
    assert falso.guardado == {(chaveiro.SERVICO, VARIAVEL_GROQ): SEGREDO}


def test_pedaco_de_chave_e_recusado_antes_de_sair_daqui(falso: ChaveiroFalso) -> None:
    """Meia chave colada por engano viraria um 401, e o dono procuraria no lugar errado."""
    with pytest.raises(SegredoAusente):
        chaveiro.guardar(VARIAVEL_GROQ, "gsk_123")

    assert falso.guardado == {}


def test_sem_chaveiro_a_recusa_diz_o_que_fazer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaveiro, "_modulo", lambda: ChaveiroFalso(funciona=False))

    pode, frase = chaveiro.disponivel()

    assert not pode
    assert "KWallet" in frase and "exporte a chave" in frase
    with pytest.raises(chaveiro.ChaveiroIndisponivel):
        chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)
    assert chaveiro.fonte_da_chave(VARIAVEL_GROQ, ambiente={}) is chaveiro.Fonte.AUSENTE


def test_a_variavel_exportada_ganha_do_chaveiro(falso: ChaveiroFalso) -> None:
    """O shell é o caminho mais explícito: trocar a chave numa sessão não mexe no guardado."""
    chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)
    ambiente = {VARIAVEL_GROQ: "gsk_a_do_shell_0987654321"}

    assert chaveiro.fonte_da_chave(VARIAVEL_GROQ, ambiente=ambiente) is chaveiro.Fonte.AMBIENTE
    assert chaveiro.ambiente_com_chaves(ambiente)[VARIAVEL_GROQ] == "gsk_a_do_shell_0987654321"


def test_o_mapa_entregue_ao_laco_tem_a_chave_e_o_processo_nao(falso: ChaveiroFalso) -> None:
    """A chave vai por parâmetro, não por `os.environ`: nada de `/proc/<pid>/environ`."""
    chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)

    ambiente = chaveiro.ambiente_com_chaves({"PATH": "/usr/bin"})

    assert ambiente[VARIAVEL_GROQ] == SEGREDO
    assert ambiente["PATH"] == "/usr/bin"
    assert VARIAVEL_GROQ not in os.environ, "a chave vazou para o ambiente do processo"


def test_sem_chave_em_lugar_nenhum_a_fonte_e_ausente(falso: ChaveiroFalso) -> None:
    assert chaveiro.fonte_da_chave(VARIAVEL_GROQ, ambiente={}) is chaveiro.Fonte.AUSENTE
    assert chaveiro.ambiente_com_chaves({}).get(VARIAVEL_GROQ) is None


def test_nada_neste_modulo_imprime_o_valor(
    falso: ChaveiroFalso, capsys: CaptureFixture[str]
) -> None:
    chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)
    fonte = chaveiro.fonte_da_chave(VARIAVEL_GROQ, ambiente={})
    print(f"estado: {fonte.frase}")
    print(chaveiro.disponivel()[1])

    escrito = capsys.readouterr()

    assert SEGREDO not in escrito.out + escrito.err
    assert "definida (chaveiro do sistema)" in escrito.out


def test_esquecer_apaga_e_nao_reclama_do_que_nao_existe(falso: ChaveiroFalso) -> None:
    chaveiro.guardar(VARIAVEL_GROQ, SEGREDO)

    chaveiro.esquecer(VARIAVEL_GROQ)
    chaveiro.esquecer(VARIAVEL_GROQ)

    assert chaveiro.valor(VARIAVEL_GROQ) is None


def test_o_keyring_de_verdade_e_o_que_o_produto_usa() -> None:
    """Sanidade: o módulo importado é o `keyring` (MIT), não um embrulho nosso esquecido."""
    modulo: Any = chaveiro._modulo()

    assert modulo.__name__ == "keyring"
    assert hasattr(modulo, "set_password") and hasattr(modulo, "get_password")
