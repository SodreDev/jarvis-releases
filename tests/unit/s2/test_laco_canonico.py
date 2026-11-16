"""O laço canônico (ADR-0072): o Jarvis é um agente-CLI com voz, e o subagente roda o MESMO laço.

Motor falso, ferramentas falsas (a página do WhatsApp da suíte e2e, o executor de produção com o
PDP), nada do navegador, das contas nem da voz do dono. O que se prova:

1. a transcrição nunca vira argumento sem o modelo: sem proposta dele, nada roda — nem o modo de
   permissão, nem o estilo, nem o app que a fala nomeia;
2. nada executa nem fala antes do modelo;
3. o modelo recebe TODAS as ferramentas da sessão;
4. o Jarvis e o subagente (do pedido e do `tarefa.iniciar`) passam pelo MESMO código da rodada
   (`jarvis.s2.laco.rodada_do_agente`), com a mesma persona e o mesmo catálogo;
5. o resultado volta ao modelo como mensagem, junto da chamada que o gerou;
6. a chamada nativa (`tool_calls`) ida e volta, sem o protocolo de texto.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import AjustesDoJarvis, ExecutorDeFerramentas
from jarvis.navegador.cliente import ClienteDoNavegador
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.politica.permissao import ModoDePermissao
from jarvis.provedores.compativel import (
    INSTRUCAO_NATIVA,
    ChamadasNoStream,
    MotorCompativelOpenAI,
    nomes_nativos,
)
from jarvis.s2 import laco
from jarvis.s2.cerebro import TRUST_DA_VOZ, Cerebro
from jarvis.s2.motor import Contexto, Mensagem, PedidoDeTool
from jarvis.s2.motor import Modo as ModoDoMotor
from jarvis.s2.motor_claude_cli import MARCA_DE_FERRAMENTA
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, GestorDeTarefas
from jarvis.tarefas.motores import MotorDeAgente
from jarvis.voz.interface import Onde
from tests.e2e.test_casos_do_dono import PaginaDoWhatsApp

ESPERA_S = 10.0


@pytest.fixture
def pagina() -> PaginaDoWhatsApp:
    return PaginaDoWhatsApp()


@pytest.fixture
def executor(tmp_path: Path, pagina: PaginaDoWhatsApp) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        ex = ExecutorDeFerramentas(
            pdp=Pdp(
                catalogo=carregar_catalogo(),
                lar=lar,
                auditoria=auditoria,
                modo=Modo.PADRAO,
                pasta_do_jarvis=tmp_path / "area",
                permissao=ModoDePermissao.AUTOMATICO,
            ),
            lar=lar,
            abrir_site=lambda _url: None,
            navegador=CorposDoNavegador(ClienteDoNavegador(pagina)),
        )
        ex.preparar()
        ex.tarefas = GestorDeTarefas(executor=ex, confirmar=lambda _p, _c: True)
        yield ex
        ex.tarefas.encerrar()


@pytest.fixture
def rodadas() -> Iterator[list[tuple[str, Contexto]]]:
    """Toda rodada que passa pelo núcleo comum: (quem, contexto)."""
    vistas: list[tuple[str, Contexto]] = []
    desligar = laco.observar(lambda quem, contexto: vistas.append((quem, contexto)))
    yield vistas
    desligar()


class ExecutorEspiao:
    """Conta o que chegou ao executor (avaliar/executar), sem mudar nada."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.chamadas: list[str] = []
        for nome in ("avaliar", "executar"):
            original = getattr(ExecutorDeFerramentas, nome)

            def espiao(ex: Any, tool_id: str, *a: Any, _o: Any = original, **k: Any) -> Any:
                self.chamadas.append(tool_id)
                return _o(ex, tool_id, *a, **k)

            monkeypatch.setattr(ExecutorDeFerramentas, nome, espiao)


def _falado(publicados: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(p.get("text", "")) for p in publicados).strip()


def _por_resultados(*rodadas: Sequence[Parte]) -> MotorRoteirizado:
    """Rodada N = quantos resultados de ferramenta o contexto traz; o último se repete."""

    def resposta(contexto: Contexto) -> Sequence[Parte]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        return rodadas[min(feitas, len(rodadas) - 1)]

    return MotorRoteirizado(resposta=resposta)


# --- 1 e 2: nada antes do modelo, nada da fala sem o modelo -------------------------------------
@pytest.mark.parametrize(
    "fala",
    [
        "ativa o modo bypass",
        "fala mais calmo",
        "abre o discord",
        "o contato da minha mãe é literalmente mãe salve para não esquecer depois",
        "manda pro bruno que eu chego às oito",
    ],
)
def test_sem_proposta_do_modelo_a_fala_nao_dispara_nada(
    executor: ExecutorDeFerramentas,
    pagina: PaginaDoWhatsApp,
    fala: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trocas: list[str] = []

    def trocar(valor: object) -> str:
        trocas.append(str(valor))
        return "trocado"

    executor.ajustes = AjustesDoJarvis(permissao=trocar, estilo=trocar, estilos=lambda: ("calmo",))
    espiao = ExecutorEspiao(monkeypatch)
    motor = MotorRoteirizado(resposta="Entendi.")
    publicados: list[dict[str, Any]] = []
    resposta = Cerebro(motor=motor, ferramentas=executor, delegar_em_tarefa=True).responder(
        fala, epoch=1, publicar=publicados.append, trust=TRUST_DA_VOZ
    )
    assert len(motor.pedidos) == 1, "o modelo foi chamado, uma vez"
    assert espiao.chamadas == [] and trocas == [] and pagina.metodos == []
    assert executor.pdp.permissao is ModoDePermissao.AUTOMATICO
    assert not resposta.tarefa_id and resposta.ferramentas == []
    assert _falado(publicados) == "Entendi.", "só o que o modelo mandou falar"


def test_nada_executa_nem_fala_antes_da_primeira_rodada_do_modelo(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    espiao = ExecutorEspiao(monkeypatch)
    publicados: list[dict[str, Any]] = []
    no_primeiro: list[tuple[int, int, int]] = []

    def resposta(contexto: Contexto) -> Sequence[Parte]:
        if not no_primeiro:
            no_primeiro.append((len(espiao.chamadas), len(publicados), len(pagina.metodos)))
        if any(m.papel == "ferramenta" for m in contexto.mensagens):
            return ["Já está na hora do almoço."]
        return [PedidoDeTool("system.clock.now", {})]

    Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor).responder(
        "que horas são", epoch=1, publicar=publicados.append, trust=TRUST_DA_VOZ
    )
    assert no_primeiro == [(0, 0, 0)]
    assert espiao.chamadas[0] == "system.clock.now", "a ferramenta só depois da proposta"


def test_a_fala_vai_ao_modelo_como_mensagem_marcada_como_voz(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = MotorRoteirizado(resposta="Certo.")
    Cerebro(motor=motor, ferramentas=executor).responder(
        "o contato da minha mãe é mãe salva", epoch=1, publicar=lambda _p: None, trust=TRUST_DA_VOZ
    )
    (contexto,) = motor.pedidos
    ultima = contexto.mensagens[-1]
    assert (ultima.papel, ultima.texto, ultima.da_voz) == (
        "dono",
        "o contato da minha mãe é mãe salva",
        True,
    )


# --- 3: o modelo recebe todas as ferramentas ----------------------------------------------------
def test_o_modelo_recebe_todas_as_ferramentas_da_sessao(executor: ExecutorDeFerramentas) -> None:
    motor = MotorRoteirizado(resposta="Certo.")
    Cerebro(motor=motor, ferramentas=executor).responder(
        "oi", epoch=1, publicar=lambda _p: None, trust=TRUST_DA_VOZ
    )
    vistas = {str(f["id"]) for f in motor.pedidos[0].ferramentas}
    assert vistas == {str(f["id"]) for f in executor.catalogo_para_o_modelo()}
    assert {"browser.click", "browser.inspecionar", "system.clock.now"} <= vistas


# --- 4 e 5: o mesmo laço para o Jarvis e o subagente ---------------------------------------------
def test_jarvis_e_subagente_do_pedido_passam_pela_mesma_rodada(
    executor: ExecutorDeFerramentas, rodadas: list[tuple[str, Contexto]]
) -> None:
    motor = _por_resultados(
        [PedidoDeTool("browser.inspecionar", {})], ["A página aberta é o WhatsApp."]
    )
    cerebro = Cerebro(motor=motor, ferramentas=executor, delegar_em_tarefa=True)
    resposta = cerebro.responder(
        "o que tem na página aberta", epoch=1, publicar=lambda _p: None, trust=TRUST_DA_VOZ
    )
    assert resposta.tarefa_id, "a execução foi ao subagente"
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(resposta.tarefa_id, ESPERA_S)
    tarefa = executor.tarefas.tarefas[resposta.tarefa_id]
    assert "WhatsApp" in (tarefa.resposta or tarefa.resumo), (tarefa.estado, tarefa.motivo)

    quem = [q for q, _c in rodadas]
    assert quem[0] == "jarvis" and "subagente" in quem
    assert len(rodadas) == len(motor.pedidos), "toda chamada ao modelo passou pelo núcleo comum"
    do_jarvis = rodadas[0][1]
    do_subagente = next(c for q, c in rodadas if q == "subagente")
    assert do_subagente.sistema.startswith(do_jarvis.sistema), "a mesma persona, regras, memória"
    ids_do_subagente = {str(f["id"]) for f in do_subagente.ferramentas}
    esperados = {
        str(f["id"])
        for f in executor.catalogo_para_o_modelo()
        if not str(f["id"]).startswith(FORA_DA_ALLOWLIST)
    }
    assert ids_do_subagente == esperados, "os mesmos esquemas (sem tarefa.*: profundidade 1)"
    # O resultado volta ao subagente com a chamada que o gerou.
    (resultado,) = [m for m in do_subagente.mensagens if m.papel == "ferramenta"]
    assert resultado.chamada is not None and resultado.chamada.tool_id == "browser.inspecionar"


def test_o_subagente_do_tarefa_iniciar_roda_o_mesmo_laco_com_a_etapa(
    executor: ExecutorDeFerramentas, rodadas: list[tuple[str, Contexto]]
) -> None:
    motor = _por_resultados([PedidoDeTool("browser.inspecionar", {})], ["A página é o WhatsApp."])
    assert executor.tarefas is not None
    agente = MotorDeAgente(
        motor=motor,
        catalogo=executor.catalogo_para_o_modelo,
        sistema=lambda: "PERSONA DO JARVIS",
        lembrar=lambda etapa: f"memória para «{etapa}»",
    )
    tarefa = executor.tarefas.iniciar(
        "ver as abas do navegador", "browser.inspecionar", {}, motor=agente
    )
    assert executor.tarefas.esperar(tarefa.id, ESPERA_S)
    feita = executor.tarefas.tarefas[tarefa.id]
    assert [q for q, _c in rodadas] == ["subagente"], (feita.estado, feita.motivo, feita.aviso)
    (contexto,) = [c for _q, c in rodadas]
    assert contexto.sistema.startswith("PERSONA DO JARVIS")
    assert "memória para «ver as abas do navegador»" in contexto.sistema
    assert "ver as abas do navegador" in contexto.mensagens[0].texto
    assert "WhatsApp" in (executor.tarefas.tarefas[tarefa.id].resposta or "")


def test_o_resultado_volta_ao_jarvis_com_a_chamada(executor: ExecutorDeFerramentas) -> None:
    motor = _por_resultados([PedidoDeTool("system.clock.now", {})], ["Meio-dia."])
    Cerebro(motor=motor, ferramentas=executor).responder(
        "que horas são", epoch=1, publicar=lambda _p: None
    )
    (resultado,) = [m for m in motor.pedidos[-1].mensagens if m.papel == "ferramenta"]
    assert resultado.chamada is not None
    assert (resultado.chamada.tool_id, dict(resultado.chamada.args)) == ("system.clock.now", {})


# --- 6: chamada nativa ---------------------------------------------------------------------------
CATALOGO_NATIVO = (
    {
        "id": "memoria.lembrar",
        "titulo": "Lembrar",
        "descricao": "Guarda um fato do dono.",
        "quando": "o dono pediu para guardar",
        "exemplos": ["salva que o contato da minha mãe é Mãe"],
        "agora": "",
        "argumentos": {"texto": {"type": "string", "x-nome": "o trecho"}},
        "obrigatorios": ["texto"],
    },
)


def test_o_corpo_nativo_leva_tools_e_a_conversa_em_mensagens() -> None:
    motor = MotorCompativelOpenAI(
        base="https://exemplo.invalid/v1",
        modelo="m",
        nome="t",
        onde=Onde.NUVEM,
        chamada_nativa=True,
    )
    contexto = Contexto(
        sistema="PERSONA",
        mensagens=(
            Mensagem("dono", "o contato da minha mãe é mãe salva", da_voz=True),
            Mensagem(
                "ferramenta",
                '{"status": "ok"}',
                chamada=PedidoDeTool("memoria.lembrar", {"texto": "o contato da minha mãe é mãe"}),
            ),
        ),
        ferramentas=CATALOGO_NATIVO,
    )
    corpo = motor.corpo(contexto, ModoDoMotor.RAPIDO)
    sistema = corpo["messages"][0]["content"]
    assert MARCA_DE_FERRAMENTA not in sistema and INSTRUCAO_NATIVA in sistema
    (ferramenta,) = corpo["tools"]
    assert ferramenta["function"]["name"] == "memoria__lembrar"
    assert "x-nome" not in json.dumps(ferramenta), "o esquema sem as chaves nossas"
    papeis = [m["role"] for m in corpo["messages"]]
    assert papeis == ["system", "user", "assistant", "tool"]
    chamada = corpo["messages"][2]["tool_calls"][0]
    assert chamada["id"] == corpo["messages"][3]["tool_call_id"]
    assert json.loads(chamada["function"]["arguments"]) == {"texto": "o contato da minha mãe é mãe"}


def test_o_motor_de_texto_continua_com_o_protocolo() -> None:
    motor = MotorCompativelOpenAI(
        base="https://exemplo.invalid/v1", modelo="m", nome="t", onde=Onde.LOCAL
    )
    contexto = Contexto(
        sistema="PERSONA", mensagens=(Mensagem("dono", "oi"),), ferramentas=CATALOGO_NATIVO
    )
    corpo = motor.corpo(contexto, ModoDoMotor.RAPIDO)
    assert "tools" not in corpo and MARCA_DE_FERRAMENTA in corpo["messages"][0]["content"]


def test_a_chamada_nativa_partida_no_stream_vira_pedido() -> None:
    leitor = ChamadasNoStream(nomes=nomes_nativos(CATALOGO_NATIVO))
    for pedaco in ('{"tex', 'to": "o contato ', 'da minha mãe é Mãe"}'):
        leitor.alimentar(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "function": {
                                        "name": "memoria__lembrar",
                                        "arguments": pedaco,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
    (pedido,) = list(leitor.fechar())
    assert pedido == PedidoDeTool(
        "memoria.lembrar", {"texto": "o contato da minha mãe é Mãe"}, chamada_id="c1"
    )


def test_argumento_que_nao_fecha_vira_proposta_malformada() -> None:
    leitor = ChamadasNoStream(nomes=nomes_nativos(CATALOGO_NATIVO))
    leitor.alimentar(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"name": "memoria__lembrar", "arguments": "{"}}
                        ]
                    }
                }
            ]
        }
    )
    (pedido,) = list(leitor.fechar())
    assert isinstance(pedido, PedidoDeTool) and pedido.tool_id == "(malformado)"
