"""O roteiro concreto da tarefa de navegador, montado pelo código a partir da fala do dono
(ADR-0066; dono, 2026-11-14). Só texto: nenhuma página, nenhum navegador."""

from __future__ import annotations

import pytest

from jarvis.s2.roteiro_do_navegador import Contato, pedido_de_envio, roteiro

CONTATOS = (Contato("Maria Sodré", "minha mãe"), Contato("Ana", "amiga da faculdade"))
FERRAMENTAS = (
    "browser.tabs",
    "browser.navigate",
    "browser.read",
    "browser.type",
    "browser.click",
    "browser.acionar",
    "system.clock.now",
)


@pytest.mark.parametrize(
    ("fala", "rede", "contato", "mensagem"),
    [
        ("abre o contato da minha mãe e diz eu te amo", "whatsapp", "Maria Sodré", "eu te amo"),
        ("abre o contato da Ana no whatsapp e manda bom dia", "whatsapp", "Ana", "bom dia"),
        ("manda uma mensagem pra Ana dizendo que vou atrasar", "whatsapp", "Ana", "vou atrasar"),
        ("manda pra minha mãe que chego às 8 no zap", "zap", "Maria Sodré", "chego às 8"),
        ("diz eu te amo pra minha mãe no instagram", "instagram", "Maria Sodré", "eu te amo"),
        ("manda bom dia pro João", "whatsapp", "João", "bom dia"),
    ],
)
def test_a_fala_do_dono_vira_rede_contato_e_mensagem(
    fala: str, rede: str, contato: str, mensagem: str
) -> None:
    envio = pedido_de_envio(fala, CONTATOS)
    assert envio is not None
    assert (envio.rede, envio.contato, envio.mensagem) == (rede, contato, mensagem)


@pytest.mark.parametrize("fala", ["abre o youtube e procura música", "fala com a minha mãe", ""])
def test_sem_contato_e_mensagem_nao_e_envio(fala: str) -> None:
    assert pedido_de_envio(fala, CONTATOS) is None


def test_sem_par_nas_memorias_procura_pelo_que_o_dono_disse() -> None:
    envio = pedido_de_envio("abre o contato da minha mãe e diz eu te amo")
    assert envio is not None and envio.contato == "mãe"


def test_o_roteiro_do_envio_tem_os_passos_e_a_conferencia_do_contato() -> None:
    texto = roteiro("abre o contato da minha mãe e diz eu te amo", FERRAMENTAS, CONTATOS)

    assert "browser.tabs" in texto and "https://web.whatsapp.com/" in texto
    assert "«Maria Sodré»" in texto and "«eu te amo»" in texto
    assert "TEM de bater" in texto and "procure o contato certo" in texto
    assert "sem perguntar" in texto and "modo ausente" in texto
    assert "Pronto quando" in texto
    assert "system.clock.now" not in texto  # só as do navegador são listadas


def test_pedido_de_navegador_que_nao_e_envio_ganha_o_roteiro_geral() -> None:
    texto = roteiro("abre o youtube e procura música", FERRAMENTAS)
    assert "aba atual" in texto and "Pronto quando" in texto
    assert "whatsapp" not in texto.lower()


def test_sem_ferramenta_de_navegador_nao_ha_roteiro() -> None:
    assert roteiro("abre o contato da minha mãe e diz eu te amo", ("system.clock.now",)) == ""
