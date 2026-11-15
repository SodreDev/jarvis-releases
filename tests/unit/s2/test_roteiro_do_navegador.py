"""O roteiro concreto da tarefa de navegador, montado pelo código a partir da fala do dono
(ADR-0066; dono, 2026-11-14). Só texto: nenhuma página, nenhum navegador."""

from __future__ import annotations

import pytest

from jarvis.s2.roteiro_do_navegador import Contato, copia_da_mensagem, pedido_de_envio, roteiro

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


def test_o_envio_leva_fatos_e_travas_sem_passos_numerados() -> None:
    """ADR-0070: orientação, não roteiro — os fatos resolvidos e as travas; o caminho é do motor."""
    texto = roteiro("abre o contato da minha mãe e diz eu te amo", FERRAMENTAS, CONTATOS)

    assert "https://web.whatsapp.com/" in texto
    assert "«Maria Sodré»" in texto and "«eu te amo»" in texto
    assert "TEM de mostrar «Maria Sodré»" in texto and "nunca digite na conversa errada" in texto
    assert "sem perguntar" in texto and "modo ausente" in texto
    assert "LEIA A PÁGINA antes de agir" in texto and "não roteiro" in texto
    assert not any(f"\n{n}. " in texto for n in range(1, 7)), "sem passos numerados"


def test_pedido_de_navegador_que_nao_e_envio_ganha_so_a_orientacao() -> None:
    texto = roteiro("abre o youtube e procura música", FERRAMENTAS)
    assert "COMO TRABALHAR NO NAVEGADOR" in texto and "releia" in texto
    assert "whatsapp" not in texto.lower()


def test_sem_ferramenta_de_navegador_nao_ha_roteiro() -> None:
    assert roteiro("abre o contato da minha mãe e diz eu te amo", ("system.clock.now",)) == ""


# --- a mensagem é redigida pelo Jarvis (ADR-0069 §3) ----------------------------------------------


@pytest.mark.parametrize(
    ("fala", "mensagem"),
    [
        ("manda pra Ana exatamente: vou atrasar", "vou atrasar"),
        ("diz pra minha mãe «chego às 8»", "chego às 8"),
        ('manda pra Ana "bom dia, flor"', "bom dia, flor"),
        ("manda pra Ana dizendo literalmente bom dia flor", "bom dia flor"),
    ],
)
def test_texto_ditado_vai_literal(fala: str, mensagem: str) -> None:
    envio = pedido_de_envio(fala, CONTATOS)
    assert envio is not None and envio.literal and envio.mensagem == mensagem
    texto = roteiro(fala, FERRAMENTAS, CONTATOS)
    assert f"EXATAMENTE como o dono ditou: «{mensagem}»" in texto and "REDIJA" not in texto


def test_pedido_de_envio_e_redigido_no_tom_do_dono_com_o_contato() -> None:
    contatos = (*CONTATOS, Contato("tom", "escrevo curto, sem ponto final", "instrucao"))
    envio = pedido_de_envio("manda pra minha mãe que chego tarde", contatos)
    assert envio is not None and not envio.literal and envio.nota == "minha mãe"
    texto = roteiro("manda pra minha mãe que chego tarde", FERRAMENTAS, contatos)
    assert "REDIJA a mensagem" in texto and "«chego tarde»" in texto
    assert "em primeira pessoa, em nome dele" in texto and "sem copiar a fala dele" in texto
    assert "O que ele anotou sobre «Maria Sodré»: «minha mãe»" in texto
    assert "«escrevo curto, sem ponto final»" in texto
    assert "EXATAMENTE" not in texto
    # A instrução de tom não vira contato.
    assert pedido_de_envio("manda pro tom que oi", contatos) is not None


def test_a_fala_copiada_na_caixa_de_mensagem_e_reconhecida() -> None:
    envio = pedido_de_envio("manda pra minha mãe que chego tarde", CONTATOS)
    assert copia_da_mensagem("browser.type", {"texto": "Chego tarde!"}, envio)
    assert not copia_da_mensagem("browser.type", {"texto": "Mãe, vou chegar tarde hoje"}, envio)
    assert not copia_da_mensagem("browser.click", {"texto": "chego tarde"}, envio)
    literal = pedido_de_envio("manda pra minha mãe exatamente: chego tarde", CONTATOS)
    assert not copia_da_mensagem("browser.type", {"texto": "chego tarde"}, literal)
    assert not copia_da_mensagem("browser.type", {"texto": "chego tarde"}, None)
