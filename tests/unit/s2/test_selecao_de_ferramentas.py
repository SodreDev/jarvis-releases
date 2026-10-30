"""Ensinar as ferramentas, não só tê-las (dono, 2026-10-30; ADR-0047 emendada): pedidos-tipo →
a família certa, a receita certa no prompt do turno e as ferramentas que ela ensina existindo de
verdade no catálogo. O roteador de método é o classificador local de sempre (regras, ADR-0035);
o classificador de decisão (o Jev, ADR-0029) entra só no pedido que as regras não reconhecem — aqui,
o falso. O Jev de verdade é remoto (OpenRouter): sem cache local, não roda na suíte."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import Pergunta, Resposta, RespostaEscolha
from jarvis.politica.metodo import ContextoDoMetodo, escolher_metodo
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.receitas import (
    LIMITE_DO_BLOCO,
    RECEITAS,
    familias_do_pedido,
    primeiras_ferramentas,
    receitas_do_turno,
)

RAIZ = Path(__file__).resolve().parents[3]
CATALOGO = frozenset(p.stem for p in (RAIZ / "catalogo").glob("*.yaml"))
LIGADO = ContextoDoMetodo(navegador=True, entrada=True, apps=frozenset({"discord", "brave"}))

PEDIDOS: tuple[tuple[str, str, str], ...] = (
    # pedido do dono → família → a ferramenta que a receita tem de ensinar
    (
        "abre o canal do Thiago Nigro no YouTube e toca o último vídeo",
        "navegador",
        "browser.navigate",
    ),
    ("entra no site da receita federal", "navegador", "browser.navigate"),
    ("clica no botão de inscrever", "navegador", "browser.click"),
    ("abre o console da página e vê o erro", "navegador", "browser.console"),
    ("pesquisa quem ganhou o jogo do Flamengo ontem", "web", "web.buscar"),
    ("abre o Discord", "app", "apps.launch"),
    ("volta para o Brave", "app", "window.focus_app"),
    ("fecha o Discord de vez", "app", "apps.quit"),
    ("aperta enter", "entrada", "input.key.press"),
    ("lembra que eu prefiro café sem açúcar", "memoria", "memoria.lembrar"),
    ("o que eu te disse ontem sobre a viagem?", "memoria", "memoria.buscar_historico"),
    ("aumenta o volume", "sistema", "system.volume.set"),
    ("calcula 15% de 2380 com um script", "script", "script.rodar"),
    ("usa o preset rápido", "preset", "modelo.preset"),
    ("aprende que se escreve Kubernetes", "vocabulario", "vocabulario.aprender"),
    ("delega isso para o Claude Code", "delegar", "delegar.claude_code"),
)
CONVERSA: tuple[str, ...] = ("bom dia, tudo bem?", "me conta uma piada", "obrigado, Jarvis")


@pytest.mark.parametrize(("pedido", "familia", "ferramenta"), PEDIDOS)
def test_o_pedido_tipo_traz_a_receita_da_familia_certa(
    pedido: str, familia: str, ferramenta: str
) -> None:
    escolha = escolher_metodo(pedido, LIGADO)

    assert familia in familias_do_pedido(pedido, escolha), escolha
    bloco = receitas_do_turno(pedido, escolha, CATALOGO)
    assert RECEITAS[familia].titulo in bloco
    ensinadas = primeiras_ferramentas(bloco)
    assert ferramenta in ensinadas, ensinadas
    assert set(ensinadas) <= CATALOGO, set(ensinadas) - CATALOGO  # nada que não exista
    assert "nunca o mesmo igual" in bloco  # a recuperação de falha vai junto
    assert len(bloco) <= LIMITE_DO_BLOCO


@pytest.mark.parametrize("pedido", CONVERSA)
def test_conversa_nao_ganha_receita_e_custa_o_mesmo(pedido: str) -> None:
    assert receitas_do_turno(pedido, escolher_metodo(pedido, LIGADO), CATALOGO) == ""


def test_linha_com_ferramenta_desligada_sai_da_receita() -> None:
    sem_cdp = CATALOGO - {"browser.console", "browser.rede", "browser.avaliar"}
    pedido = "abre o canal do X no YouTube"
    bloco = receitas_do_turno(pedido, escolher_metodo(pedido, LIGADO), sem_cdp)
    assert "browser.console" not in bloco and "browser.navigate" in bloco
    sem_navegador = frozenset(i for i in CATALOGO if not i.startswith("browser."))
    assert "browser." not in receitas_do_turno(
        pedido, escolher_metodo(pedido, LIGADO), sem_navegador
    )


def _escolhe(familia: str, confianca: float) -> Any:
    def roteiro(_estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        return {nome: RespostaEscolha(familia, confianca) for nome in perguntas}

    return roteiro


def test_o_classificador_escolhe_a_familia_que_as_regras_nao_reconhecem() -> None:
    pedido = "acha pra mim aquele vídeo de culinária que eu vi"
    escolha = escolher_metodo(pedido, LIGADO)
    assert familias_do_pedido(pedido, escolha) == ()
    falso = ClassificadorFalso(roteiro=_escolhe("navegador", 0.9))

    bloco = receitas_do_turno(pedido, escolha, CATALOGO, classificador=falso)

    assert RECEITAS["navegador"].titulo in bloco
    assert len(falso.chamadas) == 1


def test_o_classificador_inseguro_ou_sem_verbo_de_acao_nao_escolhe() -> None:
    pedido = "acha pra mim aquele vídeo de culinária"
    escolha = escolher_metodo(pedido, LIGADO)
    inseguro = ClassificadorFalso(roteiro=_escolhe("navegador", 0.4))
    assert receitas_do_turno(pedido, escolha, CATALOGO, classificador=inseguro) == ""
    conversa = ClassificadorFalso(roteiro=_escolhe("navegador", 0.95))
    receitas_do_turno("que dia lindo hoje", escolher_metodo("que dia", LIGADO), CATALOGO,
                      classificador=conversa)  # fmt: skip
    assert conversa.chamadas == []  # sem verbo de ação, o classificador nem é chamado
    quebrado = ClassificadorFalso(roteiro=_escolhe("navegador", 0.9), falhar_com="sem rede")
    assert receitas_do_turno(pedido, escolha, CATALOGO, classificador=quebrado) == ""


def test_o_jev_de_verdade_sem_cache_local_fica_de_fora() -> None:
    pytest.skip("o Jev é remoto (OpenRouter) e não há cache local de respostas: só o falso aqui")


def test_a_receita_chega_ao_prompt_do_turno_so_no_assunto_dela(tmp_path: Path) -> None:
    from jarvis.executor.ferramentas import ExecutorDeFerramentas
    from jarvis.politica.auditoria import LogDeAuditoria
    from jarvis.politica.catalogo import carregar_catalogo
    from jarvis.politica.modos import Modo
    from jarvis.politica.pdp import Pdp

    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=tmp_path,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(pdp=pdp, lar=tmp_path)
        executor.preparar()
        motor = MotorRoteirizado(resposta=lambda _c: ["Certo."])
        cerebro = Cerebro(motor=motor, ferramentas=executor)

        cerebro.responder("aumenta o volume", epoch=0, publicar=lambda _p: None)
        cerebro.responder("me conta uma piada", epoch=1, publicar=lambda _p: None)

    sistemas: list[Contexto] = list(motor.pedidos)
    assert RECEITAS["sistema"].titulo in sistemas[0].sistema
    assert "Receitas" not in sistemas[-1].sistema
