"""Encerrar o Jarvis a pedido (dono, 2026-10-21; ADR-0041): a tool `jarvis.encerrar`, limpo.

"encerra o sistema", "pode fechar o Jarvis", "desligar o Jarvis": o modelo chama a tool; o laço
diz a despedida e sai pelo caminho de sempre — tarefas canceladas, a entrada virtual e as abas
soltas —, e a janela fecha. Não é desligar o computador. Tier moderado: o sim só quando há tarefa
em andamento (ou pergunta esperando o dono). Tudo em modo texto, TTS paramétrico, sem rede.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import Confirmacao, Encerramento
from jarvis.gui.nucleo import SessaoDeVoz
from jarvis.politica.metodo import ContextoDoMetodo, escolher_metodo
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, MotorDireto, TarefaRecusada
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

PRAZO_S = 10.0


def _app(tmp_path: Path, linhas: list[str]) -> Aplicativo:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=linhas.append,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=lar,
    )
    app.abrir(com_asr=False)
    return app


def _encerra_quando_pedem(contexto: Contexto) -> Sequence[Parte]:
    """O modelo: "encerra…" propõe a tool; o resultado dela voltou → só a despedida (já dita)."""
    if any(m.papel == "ferramenta" for m in contexto.mensagens):
        return ""
    pedido = next(m.texto for m in reversed(contexto.mensagens) if m.papel == "dono")
    if "encerra" in pedido or "fechar o jarvis" in pedido.lower():
        return [PedidoDeTool("jarvis.encerrar", {})]
    return "Certo."


# --- o roteador (C1) -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fala",
    ["encerra o sistema", "pode fechar o Jarvis", "desligar o Jarvis", "Jarvis, pode se desligar"],
)
def test_os_pedidos_de_encerrar_vao_para_o_metodo_dele(fala: str) -> None:
    escolha = escolher_metodo(fala, ContextoDoMetodo(apps=frozenset({"discord"})))
    assert escolha.motivo == "encerra_o_jarvis"
    assert "window.close_app" in escolha.evitar, "fechar a janela do Jarvis não é encerrar limpo"
    assert "jarvis.encerrar" in escolha.nota()


@pytest.mark.parametrize(
    "fala",
    [
        "desliga o computador",
        "desliga o sistema operacional",
        "termina o que você estava fazendo",
        "fecha o discord, Jarvis",
    ],
)
def test_desligar_o_pc_ou_falar_com_o_jarvis_nao_e_encerrar(fala: str) -> None:
    assert escolher_metodo(fala, ContextoDoMetodo()).motivo != "encerra_o_jarvis"


# --- a tool no executor e no PDP ------------------------------------------------------------------
def test_sem_nada_no_ar_encerrar_nao_pergunta_e_avisa_em_voz(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    assert app.ferramentas is not None
    ids = [f["id"] for f in app.ferramentas.catalogo_para_o_modelo()]
    assert "jarvis.encerrar" in ids

    resultado = app.ferramentas.executar("jarvis.encerrar", {}, cancelado=lambda: False)

    assert resultado.status == "ok", resultado.motivo
    assert resultado.dados["encerrando"] is True
    assert resultado.aviso == "Encerrando o Jarvis. Até mais."
    assert app._encerrar_pedido and not app.encerrado, "o corpo só pede: quem encerra é o laço"


def test_com_tarefa_rodando_encerrar_pede_o_sim_dizendo_por_que(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    assert app.ferramentas is not None and app.ferramentas.tarefas is not None
    liberar = threading.Event()

    class Lenta(MotorDireto):
        def proximo(self, tarefa: Any, feitos: Any, cancelado: Any) -> Any:
            liberar.wait(PRAZO_S)
            return super().proximo(tarefa, feitos, cancelado)

    app.ferramentas.tarefas.iniciar(
        "procurar as fotos da viagem", "system.clock.now", {}, motor=Lenta()
    )
    perguntas: list[Confirmacao] = []

    def nao(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    try:
        negado = app.ferramentas.executar(
            "jarvis.encerrar", {}, cancelado=lambda: False, confirmar=nao
        )
        assert negado.status == "negado" and not app._fim_pedido()
        assert len(perguntas) == 1
        assert "«procurar as fotos da viagem»" in perguntas[0].razao_falada
        assert perguntas[0].pergunta_falada.startswith("Preciso do seu sim para encerrar o Jarvis:")

        sim = app.ferramentas.executar(
            "jarvis.encerrar", {}, cancelado=lambda: False, confirmar=lambda _p: True
        )
        assert sim.status == "ok" and app._fim_pedido()
        assert sim.dados["tarefas_canceladas"] == 1
    finally:
        liberar.set()


def test_acompanhar_o_foco_de_um_app_nao_pede_o_sim(tmp_path: Path) -> None:
    """A tarefa que só espera a janela de um app abrir (ADR-0037) não perde nada se parar."""
    app = _app(tmp_path, [])
    assert app.ferramentas is not None and app.ferramentas.tarefas is not None
    from jarvis.tarefas.gestor import Tarefa

    app.ferramentas.tarefas.tarefas["t-foco"] = Tarefa(
        id="t-foco", descricao="pôr o Steam em foco", tool_id="window.focus_app",
        parametros={}, motor="foco",
    )  # fmt: skip
    assert app._o_que_esta_no_ar() == ""


def test_tarefa_nao_encerra_o_jarvis(tmp_path: Path) -> None:
    assert "jarvis.encerrar".startswith(FORA_DA_ALLOWLIST)
    app = _app(tmp_path, [])
    assert app.ferramentas is not None and app.ferramentas.tarefas is not None
    with pytest.raises(TarefaRecusada):
        app.ferramentas.tarefas.iniciar("encerrar", "jarvis.encerrar", {}, motor=MotorDireto())


def test_sem_laco_que_possa_encerrar_a_tool_nao_existe(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    assert app.ferramentas is not None
    app.ferramentas.encerramento = None
    ids = [f["id"] for f in app.ferramentas.catalogo_para_o_modelo()]
    assert "jarvis.encerrar" not in ids
    resultado = app.ferramentas.executar("jarvis.encerrar", {}, cancelado=lambda: False)
    assert resultado.status == "negado"


# --- o laço --------------------------------------------------------------------------------------
def test_encerra_o_sistema_despede_e_sai_limpo(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)
    app._motor = MotorRoteirizado(resposta=_encerra_quando_pedem)
    paradas: list[str] = []
    app.interruptor_de_entrada.ao_parar(lambda: paradas.append("entrada"))
    depois: list[str] = []

    def dono() -> Iterator[str | None]:
        yield "encerra o sistema"
        depois.append("o laço pediu mais uma linha")
        yield "isto não pode virar turno"

    codigo = app.rodar_texto(dono())

    assert codigo == 0 and app.encerrado
    assert "Jarvis: Encerrando o Jarvis. Até mais." in linhas, linhas
    assert "  ⏻ Jarvis encerrado" in linhas
    assert depois == [], "o laço seguiu depois de encerrar"
    assert len(app.turnos) == 1
    assert paradas == ["entrada"], "o mouse e o teclado virtuais não foram soltos"
    assert app.interruptor_de_entrada.parado


def test_a_janela_fecha_quando_o_jarvis_encerra(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)
    app._motor = MotorRoteirizado(resposta=_encerra_quando_pedem)
    fechou = threading.Event()
    sessao = SessaoDeVoz(
        configuracao=app.configuracao,
        raiz=app.raiz,
        ambiente=app.ambiente,
        modo_texto=True,
        ao_encerrar=fechou.set,
    )
    sessao.iniciar(app)
    sessao.digitar("pode fechar o Jarvis")

    assert fechou.wait(PRAZO_S), "a sessão não avisou a janela para fechar"
    assert sessao.esperar(PRAZO_S) and app.encerrado


def test_parar_a_conversa_nao_e_encerrar_o_jarvis(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    fechou = threading.Event()
    sessao = SessaoDeVoz(
        configuracao=app.configuracao,
        raiz=app.raiz,
        ambiente=app.ambiente,
        modo_texto=True,
        ao_encerrar=fechou.set,
    )
    sessao.iniciar(app)
    time.sleep(0.05)
    sessao.parar()
    assert sessao.esperar(PRAZO_S)
    assert not fechou.is_set() and not app.encerrado


def test_a_porta_de_encerramento_e_do_aplicativo(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    assert app.ferramentas is not None
    assert isinstance(app.ferramentas.encerramento, Encerramento)
    antigo = app.ferramentas
    app.atualizar_acesso(app.configuracao)
    assert app.ferramentas is not antigo
    assert app.ferramentas.encerramento is antigo.encerramento, "mexer no acesso perdeu a porta"
