"""A orientação da tarefa de navegador (ADR-0066 → ADR-0070 → ADR-0072). Só texto: nenhuma página.

Desde a ADR-0072 (dono, 2026-11-16: «a fala do STT não vira parâmetro») nada da fala do dono entra
aqui: nem o contato nem a mensagem tirados por regex. Vão a orientação de como trabalhar numa
página, as travas do envio (que valem sempre) e o jeito de o dono escrever, das memórias fixas.
"""

from __future__ import annotations

import inspect

from jarvis.s2 import roteiro_do_navegador
from jarvis.s2.roteiro_do_navegador import Contato, roteiro

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


def test_a_orientacao_nao_recebe_a_fala_do_dono() -> None:
    """O roteiro nem tem como receber a fala: o que vai ao subagente não sai da transcrição."""
    parametros = inspect.signature(roteiro).parameters
    assert "fala" not in parametros
    assert not hasattr(roteiro_do_navegador, "pedido_de_envio")


def test_leva_orientacao_e_travas_sem_passos_numerados_nem_fatos_da_fala() -> None:
    texto = roteiro(FERRAMENTAS, CONTATOS)
    assert "LEIA A PÁGINA antes de agir" in texto and "não roteiro" in texto
    assert "TEM de mostrar o contato certo" in texto
    assert "nunca digite na conversa errada" in texto
    assert "sem perguntar" in texto and "modo ausente" in texto
    assert "Redija a mensagem" in texto and "sem copiar a fala dele" in texto
    assert "DICA DO CÓDIGO" not in texto
    assert "Maria Sodré" not in texto, "contato é decisão do modelo, com a memória à mão"
    assert not any(f"\n{n}. " in texto for n in range(1, 7)), "sem passos numerados"


def test_o_jeito_de_escrever_vem_das_memorias_fixas() -> None:
    contatos = (*CONTATOS, Contato("tom", "escrevo curto, sem ponto final", "instrucao"))
    texto = roteiro(FERRAMENTAS, contatos)
    assert "«escrevo curto, sem ponto final»" in texto


def test_sem_ferramenta_de_navegador_nao_ha_orientacao() -> None:
    assert roteiro(("system.clock.now",)) == ""
