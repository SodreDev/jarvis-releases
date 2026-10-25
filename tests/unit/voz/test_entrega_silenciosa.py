"""A entrega silenciosa do fim de uma tarefa (dono, 2026-10-25; ADR-0046).

O relato: "quando a tarefa conclui, a notificação de conclusão chega ao cérebro e ele responde DE
NOVO (a resposta dele + uma nova)". O fim de uma tarefa só vai à voz se traz algo que o dono ainda
não ouviu deste pedido; o resto muda só o card e a tela. E sai uma vez por tarefa, pelo id.

Laço de texto de verdade (TTS paramétrico, sem rede), a máquina falsa de janelas e processos dos
testes de fechar e encerrar, e o motor roteirizado.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from jarvis.agentd.fila_de_avisos import Entrega
from jarvis.executor.desfazer import Contaminacao
from jarvis.executor.lancador import RegistroDeApps
from jarvis.s2.cerebro import FRASE_AO_DELEGAR
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.tarefas.gestor import EstadoDaTarefa, Tarefa
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from tests.unit.executor.test_fechar_e_encerrar import CATALOGO, _ligar

PRAZO_S = 10.0


@pytest.fixture
def app(tmp_path: Path) -> Aplicativo:
    lar = tmp_path / "casa"
    lar.mkdir()
    aplicativo = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco", acesso="padrao"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _linha: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=lar,
    )
    aplicativo.abrir(com_asr=False)
    aplicativo.avisos.piso_livre_s = 0.0  # o teste não espera o 1,5 s de silêncio do D22
    return aplicativo


def _tarefa(
    estado: EstadoDaTarefa, *, resposta: str = "", ja_dito: str = "", aviso: str | None = None
) -> Tarefa:
    return Tarefa(
        id="t-teste01",
        descricao="encerra o Steam",
        tool_id="",
        parametros={},
        motor="objetivo",
        estado=estado,
        de_objetivo=True,
        resposta=resposta,
        ja_dito=ja_dito,
        aviso=aviso,
        contaminacao=Contaminacao(),
        turno="t-01a17000-0000-7000-8000-000000000001",
    )


def _entregas(app: Aplicativo) -> list[dict[str, object]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    if not arquivo.exists():
        return []
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, linhas) if e["evento"] == "entrega"]


def test_o_fim_que_repete_o_aviso_do_passo_fica_so_no_card(app: Aplicativo) -> None:
    tarefa = _tarefa(
        EstadoDaTarefa.CONCLUIDA, resposta="O Steam foi encerrado.", ja_dito=FRASE_AO_DELEGAR
    )
    app._aviso_da_tarefa(tarefa, "aviso-t-teste01-1", "evento", "Encerrei o Steam.")

    app._tarefa_concluida(tarefa)

    aviso = app.avisos.avisos["tarefa-t-teste01"]
    assert aviso.entrega is Entrega.SO_CARD, "repetição: só o card"
    (entrega,) = _entregas(app)
    assert entrega["decisao"] == "silenciosa" and entrega["motivo"] == "ja_dito"
    assert "Steam" not in json.dumps(entrega), "a trilha não guarda o texto"


def test_o_fim_com_algo_novo_vai_a_voz_uma_vez(app: Aplicativo) -> None:
    tarefa = _tarefa(
        EstadoDaTarefa.CONCLUIDA,
        resposta="Abri o vídeo «Como investir» do canal Primo Rico.",
        ja_dito="Abri a busca do YouTube por Primo Rico.",
    )

    app._tarefa_concluida(tarefa)
    app._tarefa_concluida(tarefa)  # o mesmo fim de novo (dedup por id)

    aviso = app.avisos.avisos["tarefa-t-teste01"]
    assert aviso.entrega is Entrega.NA_FILA, "novidade: vai à voz"
    assert [e["decisao"] for e in _entregas(app)] == ["falada"], "uma vez por id"


def test_recusada_ou_cancelada_pelo_dono_acaba_calada(app: Aplicativo) -> None:
    recusada = _tarefa(EstadoDaTarefa.FALHOU, aviso="")
    app._tarefa_concluida(recusada)
    assert app.avisos.avisos["tarefa-t-teste01"].entrega is Entrega.SO_CARD
    cancelada = _tarefa(EstadoDaTarefa.CANCELADA)
    cancelada.id = "t-teste02"
    app._tarefa_concluida(cancelada)
    assert app.avisos.avisos["tarefa-t-teste02"].entrega is Entrega.SO_CARD
    assert [e["motivo"] for e in _entregas(app)] == ["recusada_pelo_dono", "cancelada_pelo_dono"]


def test_a_falha_e_dita_mesmo_depois_da_frase_curta(app: Aplicativo) -> None:
    tarefa = _tarefa(
        EstadoDaTarefa.FALHOU,
        resposta="Não consegui: nenhum navegador com a extensão do Jarvis está aberto.",
        ja_dito=FRASE_AO_DELEGAR,
    )
    app._tarefa_concluida(tarefa)
    assert app.avisos.avisos["tarefa-t-teste01"].entrega is Entrega.NA_FILA
    assert [e["motivo"] for e in _entregas(app)] == ["falha"]


# --- a regressão de ponta a ponta: o trabalho longo não fala duas vezes ---------------------------
def _roteiro(final: str) -> Callable[[Contexto], Sequence[Parte]]:
    def responder(contexto: Contexto) -> Sequence[Parte]:
        feitas = sum(m.papel == "ferramenta" for m in contexto.mensagens)
        if feitas == 0:
            return [PedidoDeTool("window.list", {})]
        if feitas == 1:
            return [PedidoDeTool("apps.quit", {"app": "Discord"})]
        return [final]

    return responder


def _rodar(app: Aplicativo, final: str, esperado: str) -> tuple[list[str], list[str]]:
    linhas: list[str] = []
    app.escrever_na_tela = linhas.append
    app._motor = MotorRoteirizado(resposta=_roteiro(final))
    assert app.ferramentas is not None and app._cerebro is not None
    tabela, _janelas = _ligar(app.ferramentas)
    # O Discord está na lista que o dono liberou: encerrá-lo a pedido não pede o sim (ADR-0046).
    app.ferramentas.registro_de_apps = RegistroDeApps(
        autorizados={"discord": CATALOGO["discord"]},
        instalados=frozenset(CATALOGO),
        catalogo=CATALOGO,
    )
    app._cerebro.passos_no_turno = 1  # o segundo passo já é trabalho longo: vira tarefa

    def dono() -> Iterator[str | None]:
        yield "olha as janelas e fecha o discord todo"
        limite = time.monotonic() + PRAZO_S
        while esperado not in "\n".join(linhas) and time.monotonic() < limite:
            yield None  # o tique sem nada digitado: é aqui que os avisos vão à voz
            threading.Event().wait(0.02)
        for _ in range(10):  # mais uns tiques: nada mais pode ser dito
            yield None
            threading.Event().wait(0.02)

    app.rodar_texto(dono())
    assert tabela.sinais, "o Discord recebeu o sinal"
    assert esperado in "\n".join(linhas), "a tarefa chegou ao fim dentro do prazo"
    return [linha for linha in linhas if linha.startswith("Jarvis: ")], linhas


def test_a_tarefa_que_so_repete_o_aviso_nao_fala_de_novo(app: Aplicativo) -> None:
    falas, linhas = _rodar(
        app, "Pronto, o Discord foi encerrado.", "(Pronto, o Discord foi encerrado.)"
    )
    assert falas == [f"Jarvis: {FRASE_AO_DELEGAR}", "Jarvis: Encerrei o Discord."], falas
    assert "  (Pronto, o Discord foi encerrado.)" in linhas, "o fim foi à tela, calado"


def test_a_tarefa_com_resultado_novo_fala_o_resultado_uma_vez(app: Aplicativo) -> None:
    final = "Encerrei o Discord; ficaram abertas só a Konsole e o Steam."
    falas, _linhas = _rodar(app, final, "a Konsole e o Steam")
    assert falas[:2] == [f"Jarvis: {FRASE_AO_DELEGAR}", "Jarvis: Encerrei o Discord."], falas
    assert len(falas) == 3 and "Konsole" in falas[2], falas
