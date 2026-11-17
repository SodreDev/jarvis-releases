"""Caso (c) do dono, de ponta a ponta no aplicativo: o alerta de uma rede social (ADR-0070).

O monitor detecta a mudança e entrega a evidência crua (remetente, trecho, rótulos dos ícones); o
**agente monitor** (um subagente no laço canônico, ADR-0073) decide com as ferramentas dele se
encaminha ao Jarvis ou descarta; o evento estruturado vai à fila com a
confiança de terceiros; no piso livre, o **Jarvis** recebe os eventos e decide — fala com as
palavras dele, ou responde `[silencio]` e o card guarda. Nenhuma frase do código chega à voz.

O aplicativo é o de verdade, com o TTS paramétrico e o áudio em arquivo (nada no alto-falante nem
no microfone do dono); o motor é o roteirizado, no papel do agente monitor e do Jarvis.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.agentd.fila_de_avisos import Entrega
from jarvis.s2.avisos import MARCA_DO_SILENCIO
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.social.agente import ENCAMINHAR
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

ESPERA_S = 15.0
LIGACAO = "A Ana te ligou pelo WhatsApp agora há pouco e deixou recado dizendo que é urgente."


@pytest.fixture
def app(tmp_path: Path) -> Iterator[Aplicativo]:
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
    yield aplicativo


class JarvisDasRedes:
    """O modelo nos dois papéis: o agente monitor (encaminha) e o Jarvis (decide falar)."""

    def __init__(self) -> None:
        self.classificacoes = 0
        self.eventos: list[str] = []

    def __call__(self, contexto: Contexto) -> Sequence[Parte]:
        if ENCAMINHAR in {str(f.get("id")) for f in contexto.ferramentas}:
            self.classificacoes += 1
            dados = json.loads(contexto.mensagens[-1].texto)
            (conversa,) = dados["evento"]["remetentes"]
            ligacao = any("chamada" in s.casefold() for s in conversa["sinais"])
            return [
                PedidoDeTool(
                    ENCAMINHAR,
                    {
                        "resumo": f"{conversa['remetente']}: {conversa['trecho']}",
                        "tipo": "ligacao_perdida" if ligacao else "mensagem",
                        "urgencia": "alta" if "urgente" in conversa["trecho"] else "baixa",
                    },
                )
            ]
        if contexto.de_evento:
            self.eventos.append(contexto.sistema)
            # A decisão é do Jarvis: a ligação urgente merece a voz; o grupo, não.
            if (
                '"tipo": "ligacao_perdida"' in contexto.sistema
                and '"urgencia": "alta"' in contexto.sistema
            ):
                return [LIGACAO]
            return [MARCA_DO_SILENCIO]
        return ["Certo."]


def _ligar(app: Aplicativo) -> JarvisDasRedes:
    jarvis = JarvisDasRedes()
    motor = MotorRoteirizado(resposta=jarvis, conta_eventos=False)
    app._motor = motor
    assert app._cerebro is not None
    app._cerebro.motor = motor
    return jarvis


def _evento(remetente: str, trecho: str, sinais: list[str]) -> dict[str, Any]:
    return {
        "rede": "WhatsApp",
        "tipo": "nao_lidas_subiram",
        "novas": 1,
        "remetentes": [
            {"remetente": remetente, "nao_lidas": 1, "trecho": trecho, "sinais": sinais}
        ],
    }


def test_c_ligacao_urgente_o_agente_classifica_e_o_jarvis_decide_falar(app: Aplicativo) -> None:
    jarvis = _ligar(app)
    linhas: list[str] = []
    pronto = threading.Event()

    def na_tela(linha: str) -> None:
        linhas.append(linha)
        if linha.startswith("Jarvis: "):
            pronto.set()

    app.evento_de_rede(
        "WhatsApp",
        _evento("Ana", "me liga, é urgente", ["Chamada de voz perdida"]),
        ausente=False,
    )
    limite = time.monotonic() + ESPERA_S
    while not app.dados_dos_avisos()["avisos"] and time.monotonic() < limite:
        time.sleep(0.01)
    _rodar_ate_com(app, pronto, na_tela)

    falas = [linha for linha in linhas if linha.startswith("Jarvis: ")]
    assert falas == [f"Jarvis: {LIGACAO}"], "uma fala só, e com as palavras do Jarvis"
    assert jarvis.classificacoes == 1, "o agente monitor decidiu antes do Jarvis"
    (nota,) = jarvis.eventos
    assert '"tipo": "ligacao_perdida"' in nota and '"encaminhado_pelo_monitor": true' in nota
    assert "o dono está presente" in nota, "o modo do dono vai como contexto, não como filtro"
    _sem_frase_do_codigo(linhas)


def test_c_mensagem_comum_o_jarvis_decide_ficar_calado_e_o_card_guarda(app: Aplicativo) -> None:
    jarvis = _ligar(app)
    linhas: list[str] = []
    feito = threading.Event()

    app.evento_de_rede("WhatsApp", _evento("Grupo da família", "kkkk boa", []), ausente=False)
    limite = time.monotonic() + ESPERA_S
    while not app.dados_dos_avisos()["avisos"] and time.monotonic() < limite:
        time.sleep(0.01)

    def na_tela(linha: str) -> None:
        linhas.append(linha)

    def quando_decidir() -> None:
        while not jarvis.eventos and time.monotonic() < limite + ESPERA_S:
            time.sleep(0.01)
        feito.set()

    threading.Thread(target=quando_decidir, daemon=True).start()
    _rodar_ate_com(app, feito, na_tela)

    assert jarvis.classificacoes == 1 and len(jarvis.eventos) == 1, "o Jarvis decidiu"
    assert not [linha for linha in linhas if linha.startswith("Jarvis: ")], "ele ficou calado"
    (aviso,) = app.avisos.avisos.values()
    assert aviso.entrega is Entrega.SO_CARD, "calado, o card guarda"
    _sem_frase_do_codigo(linhas)


def _rodar_ate_com(app: Aplicativo, pronto: threading.Event, na_tela: Any) -> None:
    def dono() -> Iterator[str | None]:
        limite = time.monotonic() + ESPERA_S
        while not pronto.is_set() and time.monotonic() < limite:
            yield None
            threading.Event().wait(0.02)
        for _ in range(15):
            yield None
            threading.Event().wait(0.02)

    app.escrever_na_tela = na_tela
    app.rodar_texto(dono())


def _sem_frase_do_codigo(linhas: Sequence[str]) -> None:
    """A frase fixa de antes («WhatsApp: 2 mensagens novas — Ana (1)») não existe mais."""
    tudo = "\n".join(linhas)
    assert "mensagens novas" not in tudo and "mensagem nova" not in tudo


# --- uma resposta por estímulo, no aplicativo inteiro -------------------------------------------
NOTA = "Na pasta Documentos tem só o arquivo notas.txt."


def test_e_uma_resposta_por_estimulo_do_pedido_delegado_ao_fim_da_tarefa(
    app: Aplicativo,
) -> None:
    """O dono pede; a execução vai ao subagente (o turno não fala nada pelo código); o fim da tarefa
    vira evento ao Jarvis, que fala o resultado UMA vez — nada de cinco ou seis respostas ao mesmo
    pedido (a frase ao delegar, o aviso do passo, o fim, o fim de novo…)."""
    assert app.ferramentas is not None
    (app.ferramentas.lar / "Documentos").mkdir()
    (app.ferramentas.lar / "Documentos" / "notas.txt").write_text("café\n", "utf-8")
    eventos: list[str] = []

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        if contexto.de_evento:
            eventos.append(contexto.sistema)
            return [NOTA] if "concluida" in contexto.sistema else [MARCA_DO_SILENCIO]
        feitos = [m for m in contexto.mensagens if m.papel == "ferramenta"]
        if not feitos:
            return [PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]
        return [NOTA]

    motor = MotorRoteirizado(resposta=roteiro, conta_eventos=False)
    app._motor = motor
    assert app._cerebro is not None
    app._cerebro.motor = motor
    linhas: list[str] = []
    pronto = threading.Event()

    def na_tela(linha: str) -> None:
        linhas.append(linha)
        if linha.startswith("Jarvis: "):
            pronto.set()

    def dono() -> Iterator[str | None]:
        yield "o que tem na minha pasta Documentos?"
        limite = time.monotonic() + ESPERA_S
        while not pronto.is_set() and time.monotonic() < limite:
            yield None
            threading.Event().wait(0.02)
        for _ in range(40):  # mais tiques: nenhuma outra fala pode sair deste pedido
            yield None
            threading.Event().wait(0.02)

    app.escrever_na_tela = na_tela
    app.rodar_texto(dono())

    falas = [linha for linha in linhas if linha.startswith("Jarvis: ")]
    assert falas == [f"Jarvis: {NOTA}"], linhas
    assert len(eventos) == 1, "o fim da tarefa chegou ao Jarvis uma vez"
