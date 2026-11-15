"""O pedido que o Jarvis formula ao subagente (ADR-0069): a régua da cópia e as seções."""

from __future__ import annotations

import pytest

from jarvis.delegacao.pedido import PedidoFormulado, copia_do_dono, do_args, recusa, texto

FALA = "manda pra minha mãe no zap que eu chego tarde hoje"


@pytest.mark.parametrize(
    "enviado",
    [
        FALA,
        "Manda pra minha mãe no Zap que eu chego tarde hoje!",
        "manda pra minha mae no zap que chego tarde hoje",
        "minha mãe no zap que eu chego tarde",  # a fala recortada
    ],
)
def test_e_copia(enviado: str) -> None:
    assert copia_do_dono(enviado, FALA)


@pytest.mark.parametrize(
    "enviado",
    [
        "Avisar a mãe do dono (contato «Maria» no WhatsApp Web) de que ele vai chegar tarde hoje",
        "abrir o WhatsApp Web e achar a conversa de Maria",
        "",
    ],
)
def test_nao_e_copia(enviado: str) -> None:
    assert not copia_do_dono(enviado, FALA)


def test_fala_curta_so_conta_igual() -> None:
    assert copia_do_dono("abre o YouTube", "abre o youtube")
    assert not copia_do_dono("abrir o YouTube na aba atual e conferir o título", "abre o YouTube")


def test_recusa_e_texto() -> None:
    formulado = do_args(
        {
            "tarefa": "Avisar a Maria (mãe do dono) que ele chega tarde hoje",
            "passos": ["abrir o WhatsApp Web", " ", "achar a conversa de Maria"],
            "pronto_quando": "a mensagem aparece enviada na conversa de Maria",
            "devolver": "se enviou e o texto que foi",
        }
    )
    assert formulado.passos == ("abrir o WhatsApp Web", "achar a conversa de Maria")
    assert recusa(formulado, FALA) == ""
    assert recusa(PedidoFormulado(FALA, ("x",), "y", "z"), FALA) != ""
    assert recusa(formulado, "") == ""
    montado = texto(formulado)
    assert (
        montado.splitlines()[0] == "OBJETIVO: Avisar a Maria (mãe do dono) que ele chega tarde hoje"
    )
    assert "PASSOS:\n1. abrir o WhatsApp Web\n2. achar a conversa de Maria" in montado
