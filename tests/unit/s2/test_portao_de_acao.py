"""Portão contextual das ferramentas (dono, 2026-10-19): Jarvis → Jev → PDP → pendência → tarefa.

Sem rede: o Jev é o `ClassificadorFalso` com respostas roteirizadas, o motor é roteirizado, o
site "abre" numa lista, e o relógio das pendências e das autorizações é de mentira.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import Pergunta, Resposta, RespostaEscolha, RespostaNoul
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.fluxo_de_acao import _sim_de_uso_unico
from jarvis.s2.motor import Contexto, Mensagem, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.pendencias import PendenciaOcupada, RegistroDePendencias
from jarvis.s2.portao import (
    AutorizacoesExplicitas,
    Classe,
    PortaoDeAcao,
    RespostaDoDono,
    cobre_literalmente,
    resposta_literal,
)
from jarvis.tarefas.gestor import EstadoDaTarefa, GestorDeTarefas, Tarefa

YOUTUBE = "https://www.youtube.com"


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def _jev(
    classe: str = "fazer",
    p: float = 0.95,
    *,
    explicito: float = 0.0,
    resposta: str = "outra_coisa",
    p_resposta: float = 0.95,
    falhar: str = "",
) -> ClassificadorFalso:
    def roteiro(_estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        if "acao" in perguntas:
            return {
                "acao": RespostaEscolha(classe, p, {classe: p}),
                "pedido_explicito": RespostaNoul(explicito),
            }
        return {"resposta": RespostaEscolha(resposta, p_resposta, {resposta: p_resposta})}

    return ClassificadorFalso(roteiro=roteiro, falhar_com=falhar)


def _roteiro(*rodadas: Sequence[str | PedidoDeTool]) -> MotorRoteirizado:
    """Rodada N = número de resultados de ferramenta no contexto; o último se repete."""

    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        return rodadas[min(feitas, len(rodadas) - 1)]

    return MotorRoteirizado(resposta=resposta)


@pytest.fixture
def abertos() -> list[str]:
    return []


@pytest.fixture
def concluidas() -> list[Tarefa]:
    return []


@pytest.fixture
def executor(
    tmp_path: Path, abertos: list[str], concluidas: list[Tarefa]
) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    (lar / "Documentos" / "notas.txt").write_text("comprar café\n", "utf-8")
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar, abrir_site=abertos.append)
        executor.preparar()
        executor.tarefas = GestorDeTarefas(
            executor=executor,
            confirmar=lambda _pergunta, _cancelada: False,  # a janela, se chamada, diz não
            ao_concluir=concluidas.append,
        )
        yield executor
        executor.tarefas.encerrar()


def _cerebro(
    executor: ExecutorDeFerramentas,
    motor: MotorRoteirizado,
    jev: ClassificadorFalso,
    relogio: Relogio | None = None,
) -> Cerebro:
    relogio = relogio or Relogio()
    return Cerebro(
        motor=motor,
        ferramentas=executor,
        portao=PortaoDeAcao(classificador=jev),
        pendencias=RegistroDePendencias(relogio=relogio),
        autorizacoes=AutorizacoesExplicitas(relogio=relogio),
    )


def _dizer(cerebro: Cerebro, texto: str) -> tuple[Any, str]:
    publicados: list[dict[str, Any]] = []
    resposta = cerebro.responder(texto, epoch=0, publicar=publicados.append)
    falado = " ".join(str(p["text"]) for p in publicados)
    cerebro.ouvido(resposta.response_id, falado, interrompida=False)
    return resposta, falado


def _esperar_tarefas(executor: ExecutorDeFerramentas) -> None:
    assert executor.tarefas is not None
    for tarefa_id in list(executor.tarefas.tarefas):
        assert executor.tarefas.esperar(tarefa_id, 5.0)


# --- o Jev classifica: fazer / pedir permissão / não fazer ------------------------------------
@pytest.mark.parametrize(
    ("escolha", "p", "esperado"),
    [
        ("fazer", 0.95, Classe.FAZER),
        ("fazer", 0.50, Classe.PEDIR_PERMISSAO),
        ("nao_fazer", 0.90, Classe.NAO_FAZER),
        ("nao_fazer", 0.40, Classe.PEDIR_PERMISSAO),
        ("pedir_permissao", 0.90, Classe.PEDIR_PERMISSAO),
    ],
)
def test_classificacao_com_limiar(escolha: str, p: float, esperado: Classe) -> None:
    portao = PortaoDeAcao(classificador=_jev(escolha, p))
    classificacao = portao.classificar(
        tool_id="sites.open",
        titulo="Abrir site",
        argumentos={"url": YOUTUBE},
        pedido_do_dono="abre o youtube",
        mensagens=(),
        situacao={},
    )
    assert classificacao.classe is esperado


def test_jev_fora_do_ar_e_pedir_permissao() -> None:
    portao = PortaoDeAcao(classificador=_jev(falhar="sem rede"))
    classificacao = portao.classificar(
        tool_id="sites.open",
        titulo="Abrir site",
        argumentos={"url": YOUTUBE},
        pedido_do_dono="abre o youtube",
        mensagens=(),
        situacao={},
    )
    assert classificacao.classe is Classe.PEDIR_PERMISSAO
    assert "indisponível" in classificacao.motivo


def test_o_estado_leva_pedido_conversa_e_situacao_mas_nao_resultado_de_ferramenta() -> None:
    jev = _jev()
    PortaoDeAcao(classificador=jev).classificar(
        tool_id="sites.open",
        titulo="Abrir site",
        argumentos={"url": YOUTUBE},
        pedido_do_dono="abre o youtube",
        mensagens=(
            Mensagem("dono", "oi"),
            Mensagem("ferramenta", "SEGREDO de terceiros"),
            Mensagem("jarvis", "olá"),
        ),
        situacao={"modo_de_acesso": "padrao"},
    )
    estado, perguntas = jev.chamadas[0]
    assert set(perguntas) == {"acao", "pedido_explicito"}
    assert estado["pedido_do_dono"] == "abre o youtube"
    assert estado["conversa"] == ["dono: oi", "jarvis: olá"]
    assert estado["situacao"] == {"modo_de_acesso": "padrao"}
    assert "SEGREDO" not in json.dumps(estado, ensure_ascii=False)


# --- no cérebro, com o executor e o PDP de verdade ------------------------------------------
def test_fazer_com_allow_do_pdp_roda_no_turno(executor: ExecutorDeFerramentas) -> None:
    motor = _roteiro([PedidoDeTool("files.list_dir", {"path": "~/Documentos"})], ["Tem notas."])
    resposta, _ = _dizer(_cerebro(executor, motor, _jev("fazer")), "o que tem em Documentos?")
    assert [r.status for r in resposta.ferramentas] == ["ok"]


def test_nao_fazer_veta_o_que_o_pdp_deixaria(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    motor = _roteiro([PedidoDeTool("sites.open", {"url": YOUTUBE})], ["Não abri."])
    resposta, _ = _dizer(_cerebro(executor, motor, _jev("nao_fazer", 0.9)), "que dia é hoje?")
    assert [r.status for r in resposta.ferramentas] == ["negado"]
    assert "não fazer" in resposta.ferramentas[0].motivo
    assert abertos == []
    assert executor.pdp.grants == {}, "o grant do allow vetado foi solto na hora"


def test_pedir_permissao_vira_pendencia_e_o_turno_acaba_na_pergunta(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    motor = _roteiro([PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})], ["x"])
    cerebro = _cerebro(executor, motor, _jev("pedir_permissao", 0.9))
    resposta, falado = _dizer(cerebro, "dá uma olhada naquilo")
    assert [r.status for r in resposta.ferramentas] == ["pendente"]
    assert abertos == []
    assert falado.rstrip().endswith("Posso?")
    assert len(motor.pedidos) == 1, "depois da pergunta, o motor não é chamado de novo"
    pendencia = cerebro.pendencias.valida()
    assert pendencia is not None and pendencia.pergunta.tool_id == "sites.open"
    assert dict(pendencia.pergunta.argumentos) == {"url": "https://exemplo.com.br"}


def test_deny_do_pdp_nem_chega_ao_jev(executor: ExecutorDeFerramentas) -> None:
    jev = _jev("fazer", 0.99)
    motor = _roteiro([PedidoDeTool("files.read_text", {"path": "~/.ssh/id_rsa"})], ["Não."])
    resposta, _ = _dizer(_cerebro(executor, motor, jev), "lê a minha chave")
    assert [r.status for r in resposta.ferramentas] == ["negado"]
    assert jev.chamadas == []


def test_confirm_do_pdp_vale_mesmo_com_fazer_do_jev(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    """O turno leu um arquivo (conteúdo de terceiros): abrir site fora da lista é `confirm` no
    PDP. O Jev dizer "fazer" com certeza, e o dono ter dito o site, não abre nada."""
    motor = _roteiro(
        [PedidoDeTool("files.read_text", {"path": "~/Documentos/notas.txt"})],
        [PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})],
        ["x"],
    )
    cerebro = _cerebro(executor, motor, _jev("fazer", 0.99, explicito=0.99))
    resposta, _ = _dizer(cerebro, "lê as notas e abre exemplo.com.br")
    assert [r.status for r in resposta.ferramentas] == ["ok", "pendente"]
    assert abertos == []
    pendencia = cerebro.pendencias.valida()
    assert pendencia is not None and pendencia.contaminado
    assert "terceiros" in pendencia.pergunta.motivo


# --- autorização explícita: estreita, uma vez, no turno, com prazo ----------------------------
def test_pedido_explicito_autoriza_a_acao_simples_uma_vez(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    motor = _roteiro(
        [PedidoDeTool("sites.open", {"url": YOUTUBE})],
        [PedidoDeTool("sites.open", {"url": YOUTUBE})],
        ["Abri."],
    )
    cerebro = _cerebro(executor, motor, _jev("pedir_permissao", 0.9, explicito=0.95))
    resposta, _ = _dizer(cerebro, "abre o youtube")
    assert [r.status for r in resposta.ferramentas] == ["ok", "pendente"]
    assert abertos == [YOUTUBE], "a segunda abertura não herda a autorização da primeira"


def test_pedido_explicito_nao_cobre_argumento_diferente(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    motor = _roteiro([PedidoDeTool("sites.open", {"url": "https://mal.example"})], ["x"])
    cerebro = _cerebro(executor, motor, _jev("pedir_permissao", 0.9, explicito=0.99))
    resposta, _ = _dizer(cerebro, "abre o youtube")
    assert [r.status for r in resposta.ferramentas] == ["pendente"]
    assert abertos == []


def test_pedido_explicito_nao_passa_para_o_turno_seguinte(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    motor = _roteiro(["Ok."])
    cerebro = _cerebro(executor, motor, _jev("pedir_permissao", 0.9, explicito=0.99))
    _dizer(cerebro, "abre o youtube depois")
    motor.resposta = lambda _c: [PedidoDeTool("sites.open", {"url": YOUTUBE})]
    resposta, _ = _dizer(cerebro, "agora")
    assert resposta.ferramentas[0].status == "pendente"
    assert abertos == []


def test_autorizacao_explicita_tem_prazo_e_exige_o_jev_e_a_fala_literal() -> None:
    relogio = Relogio()
    autorizacoes = AutorizacoesExplicitas(prazo_s=60.0, relogio=relogio)
    autorizacoes.novo_turno("abre o youtube")
    args = {"url": YOUTUBE}
    assert not autorizacoes.consumir("sites.open", args, p_explicito=0.5, limiar=0.8)
    relogio.agora += 61
    assert not autorizacoes.consumir("sites.open", args, p_explicito=0.99, limiar=0.8)
    autorizacoes.novo_turno("abre o youtube")
    assert autorizacoes.consumir("sites.open", args, p_explicito=0.99, limiar=0.8)
    assert not autorizacoes.consumir("sites.open", args, p_explicito=0.99, limiar=0.8)
    autorizacoes.encerrar()
    assert not autorizacoes.consumir("apps.launch", {"nome": "youtube"}, p_explicito=1, limiar=0)


def test_cobre_literalmente() -> None:
    assert cobre_literalmente({"url": "https://www.youtube.com/x"}, "Abre o YouTube")
    assert cobre_literalmente({"nivel": 30}, "volume em 30")
    assert not cobre_literalmente({"nivel": 80}, "volume em 30")
    assert cobre_literalmente({"nome": "Brave"}, "abre o brave")
    assert not cobre_literalmente({"nome": "Brave"}, "abre o braveiro")
    assert not cobre_literalmente({"texto": "um rascunho longo"}, "escreve algo")


# --- o "sim" falado: só a pendência exata, válida, uma vez --------------------------------------
def _pendencia_de_site(
    executor: ExecutorDeFerramentas, jev: ClassificadorFalso, relogio: Relogio | None = None
) -> tuple[Cerebro, MotorRoteirizado]:
    motor = _roteiro([PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})], ["Ok."])
    cerebro = _cerebro(executor, motor, jev, relogio)
    _dizer(cerebro, "dá uma olhada naquilo")
    assert cerebro.pendencias.valida() is not None
    motor.resposta = lambda _c: ["Respondi outra coisa."]
    return cerebro, motor


def test_sim_falado_resolve_a_pendencia_e_despacha_tarefa(
    executor: ExecutorDeFerramentas, abertos: list[str], concluidas: list[Tarefa]
) -> None:
    cerebro, motor = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9))
    resposta, falado = _dizer(cerebro, "Sim, pode.")
    assert resposta.motor == "portao" and len(motor.pedidos) == 1, "o motor não é chamado"
    assert [r.status for r in resposta.ferramentas] == ["despachado"]
    assert falado.startswith("Certo, estou fazendo")
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]
    assert [t.estado for t in concluidas] == [EstadoDaTarefa.CONCLUIDA]
    # Consumida: outro "sim" não autoriza mais nada.
    resposta, _ = _dizer(cerebro, "sim")
    assert resposta.motor != "portao" and resposta.ferramentas == []
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]


def test_sim_depois_do_prazo_e_rejeitado(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    relogio = Relogio()
    cerebro, motor = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9), relogio)
    relogio.agora += executor.prazo_de_confirmacao_s + 1
    resposta, _ = _dizer(cerebro, "sim")
    assert resposta.motor != "portao" and len(motor.pedidos) == 2
    _esperar_tarefas(executor)
    assert abertos == [] and executor.tarefas is not None and executor.tarefas.tarefas == {}


def test_sim_pelo_jev_precisa_de_probabilidade_alta(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    jev = _jev("pedir_permissao", 0.9, resposta="sim", p_resposta=0.6)
    cerebro, motor = _pendencia_de_site(executor, jev)
    _resposta, _ = _dizer(cerebro, "acho que dá, manda ver nisso aí")
    assert cerebro.pendencias.valida() is None, "fala que não é sim cancela a pendência"
    assert "foi cancelada" in motor.pedidos[-1].sistema
    _esperar_tarefas(executor)
    assert abertos == []


def test_sim_contextual_pelo_jev_resolve(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    jev = _jev("pedir_permissao", 0.9, resposta="sim", p_resposta=0.95)
    cerebro, _motor = _pendencia_de_site(executor, jev)
    resposta, _ = _dizer(cerebro, "manda bala, pode abrir esse aí")
    assert [r.status for r in resposta.ferramentas] == ["despachado"]
    estado, perguntas = jev.chamadas[-1]
    assert set(perguntas) == {"resposta"}
    assert "exemplo.com.br" in estado["acao_pendente"]
    assert any("Posso?" in linha for linha in estado["conversa"])
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]


def test_nao_e_outro_assunto_cancelam_e_o_sim_seguinte_nao_vale(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    cerebro, _motor = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9))
    _resposta, falado = _dizer(cerebro, "não")
    assert falado.startswith("Tudo bem")
    cerebro2, _ = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9))
    _dizer(cerebro2, "que horas são?")
    _dizer(cerebro2, "sim")
    _esperar_tarefas(executor)
    assert abertos == []


def test_sim_por_cima_da_pergunta_cortada_nao_vale(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    """O dono interrompeu antes de ouvir a pergunta inteira: ela não foi feita."""
    motor = _roteiro([PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})], ["x"])
    cerebro = _cerebro(executor, motor, _jev("pedir_permissao", 0.9))
    resposta = cerebro.responder("dá uma olhada naquilo", epoch=0, publicar=lambda _p: None)
    assert cerebro.pendencias.valida() is not None
    cerebro.ouvido(resposta.response_id, "Preciso do seu", interrompida=True)
    assert cerebro.pendencias.valida() is None
    _dizer(cerebro, "sim")
    _esperar_tarefas(executor)
    assert abertos == []


def test_clique_resolve_so_o_id_certo_e_uma_vez(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    cerebro, _ = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9))
    pendencia = cerebro.pendencias.valida()
    assert pendencia is not None
    assert not cerebro.resolver_pendencia("outro-id", True)
    assert cerebro.resolver_pendencia(pendencia.id, True)
    assert not cerebro.resolver_pendencia(pendencia.id, True)
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]


def test_sim_depois_de_confirm_do_pdp_roda_com_o_pdp_de_novo(
    executor: ExecutorDeFerramentas, abertos: list[str]
) -> None:
    """A tarefa passa pelo PDP outra vez (turno contaminado → `confirm`): o "sim" dado vale para
    aquela pergunta exata, e só ela."""
    motor = _roteiro(
        [PedidoDeTool("files.read_text", {"path": "~/Documentos/notas.txt"})],
        [PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})],
        ["x"],
    )
    cerebro = _cerebro(executor, motor, _jev("fazer", 0.99))
    _dizer(cerebro, "lê as notas e abre exemplo.com.br")
    resposta, _ = _dizer(cerebro, "sim")
    assert [r.status for r in resposta.ferramentas] == ["despachado"]
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]


def test_nao_abre_segunda_pendencia_por_cima_da_primeira() -> None:
    registro = RegistroDePendencias(relogio=Relogio())
    pergunta = Confirmacao("c-1", "sites.open", "Abrir site", "abrir x", "m", 30.0)
    registro.abrir(pergunta)
    with pytest.raises(PendenciaOcupada):
        registro.abrir(Confirmacao("c-2", "sites.open", "Abrir site", "abrir y", "m", 30.0))


def test_sim_de_uso_unico_so_casa_a_chamada_exata() -> None:
    feita = Confirmacao("c-1", "sites.open", "t", "d", "m", 30.0, {"url": YOUTUBE})
    responder = _sim_de_uso_unico(feita)
    assert not responder(
        Confirmacao("x", "sites.open", "t", "d", "m", 30.0, {"url": "https://a.b"})
    )
    assert not responder(Confirmacao("x", "apps.launch", "t", "d", "m", 30.0, {"url": YOUTUBE}))
    assert responder(Confirmacao("x", "sites.open", "t", "d", "m", 30.0, {"url": YOUTUBE}))
    assert not responder(Confirmacao("x", "sites.open", "t", "d", "m", 30.0, {"url": YOUTUBE}))


def test_sim_de_uso_unico_nao_responde_a_pergunta_por_acao() -> None:
    """O "sim" à pergunta do portão («posso clicar?») não vale para a do risco dinâmico («o foco
    é um terminal: clicar?»): com argumentos vazios nas duas, ela casava (revisão, 2026-10-19)."""
    feita = Confirmacao("c-1", "input.mouse.click", "t", "clicar", "m", 30.0, {})
    responder = _sim_de_uso_unico(feita)
    terminal = Confirmacao("c-1-s1", "input.mouse.click", "t", "Konsole", "m", 30.0, por_acao=True)
    assert not responder(terminal)
    assert responder(Confirmacao("c-1", "input.mouse.click", "t", "clicar", "m", 30.0, {}))


@pytest.mark.parametrize(
    ("fala", "esperado"),
    [
        ("Sim!", RespostaDoDono.SIM),
        ("pode sim", RespostaDoDono.SIM),
        ("Não.", RespostaDoDono.NAO),
        ("cancela", RespostaDoDono.NAO),
        ("sim, e apaga também o resto", None),
    ],
)
def test_resposta_literal(fala: str, esperado: RespostaDoDono | None) -> None:
    assert resposta_literal(fala) is esperado


# --- execução delegada: a conversa segue enquanto a tarefa roda --------------------------------
def test_execucao_confirmada_nao_prende_a_conversa(
    executor: ExecutorDeFerramentas, concluidas: list[Tarefa]
) -> None:
    liberar = threading.Event()
    comecou = threading.Event()
    abertos: list[str] = []

    def abrir_devagar(url: str) -> None:
        comecou.set()
        assert liberar.wait(5.0)
        abertos.append(url)

    executor.abrir_site = abrir_devagar
    cerebro, _motor = _pendencia_de_site(executor, _jev("pedir_permissao", 0.9))
    resposta, _ = _dizer(cerebro, "sim")
    assert resposta.ferramentas[0].status == "despachado"
    assert comecou.wait(5.0)
    assert executor.tarefas is not None
    (tarefa,) = executor.tarefas.tarefas.values()
    assert tarefa.estado is EstadoDaTarefa.RODANDO
    # O Jarvis continua respondendo com a tarefa rodando.
    resposta, falado = _dizer(cerebro, "e o tempo amanhã?")
    assert falado == "Respondi outra coisa." and tarefa.estado is EstadoDaTarefa.RODANDO
    assert concluidas == []
    liberar.set()
    _esperar_tarefas(executor)
    assert abertos == ["https://exemplo.com.br"]
    assert [t.estado for t in concluidas] == [EstadoDaTarefa.CONCLUIDA]
