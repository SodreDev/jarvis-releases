"""Relato do dono (2026-11-16): «ao receber alguma notificação com o monitoramento ativo ele não me
fala». O caminho inteiro, com fakes: a página da rede (o evento da extensão, validado pelo
protocolo) → `EstadoDoMonitor` → `Aplicativo.evento_de_rede` → **agente monitor** (laço canônico,
motor roteirizado) → fila de avisos → turno do Jarvis (o mesmo motor roteirizado) → TTS paramétrico
num arquivo. Sem microfone, sem alto-falante, sem navegador, sem conta.

O diagnóstico (docs/estudos/monitor-ate-a-fala.md): o evento chegava ao turno do Jarvis e o modelo
respondia `[silencio]` — ninguém tinha decidido que aquilo importava ao dono — e a trilha gravava
`[fora_da_forma]` no lugar de `jarvis_calou`, escondendo a causa. E o teto de fala espontânea
(2 min) segurava o evento de rede que chegasse logo depois de o Jarvis falar.

O motor roteirizado faz os dois papéis, como o modelo de verdade: com as ferramentas do monitor no
contexto, decide como o agente (ligação = alta; repetido = descarta; propaganda = spam); no turno
de eventos do Jarvis, conta o resumo que o monitor escreveu — ou cala, quando o teste quer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.navegador.protocolo import validar_evento
from jarvis.s2.avisos import MARCA_DO_SILENCIO
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.social.agente import DESCARTAR, ENCAMINHAR
from jarvis.social.config import ConfiguracaoSocial
from jarvis.social.monitor import EstadoDaPagina, EstadoDoMonitor
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado


def _pagina(nao_lidas: int, *conversas: dict[str, Any]) -> EstadoDaPagina:
    """O que `extensao/social.js` manda, passando pelo contrato da ponte."""
    evento = {
        "evento": "social",
        "rede": "whatsapp",
        "logado": True,
        "naoLidas": nao_lidas,
        "conversas": list(conversas),
        "formato": "conhecido",
    }
    return EstadoDaPagina.do_evento(validar_evento(evento))


def _conversa(nome: str, trecho: str = "", *sinais: str) -> dict[str, Any]:
    return {"nome": nome, "naoLidas": 1, "trecho": trecho, "sinais": list(sinais)}


class Modelo:
    """O motor de teste nos dois papéis. `jarvis_cala` faz o Jarvis responder `[silencio]`."""

    def __init__(self) -> None:
        self.jarvis_cala = False
        self.turnos_do_jarvis: list[str] = []
        self.decisoes_do_monitor: list[str] = []

    def __call__(self, contexto: Contexto) -> Sequence[Parte]:
        ids = {str(f.get("id")) for f in contexto.ferramentas}
        if ENCAMINHAR in ids:
            return [self._monitor(contexto)]
        return self._jarvis(contexto)

    def _monitor(self, contexto: Contexto) -> PedidoDeTool:
        dados = json.loads(contexto.mensagens[-1].texto)
        recentes = contexto.mensagens[0].texto if len(contexto.mensagens) > 1 else ""
        (conversa, *_) = dados["evento"]["remetentes"]
        nome, trecho = conversa["remetente"], conversa["trecho"]
        sinais = " ".join(conversa["sinais"]).casefold()
        if "chamada" in sinais or "ligação" in sinais:
            tipo = "ligacao_em_andamento" if "recebendo" in sinais else "ligacao_perdida"
            pedido = PedidoDeTool(
                ENCAMINHAR,
                {"resumo": f"{nome}: {tipo}", "tipo": tipo, "urgencia": "alta"},
            )
        elif "promoção" in trecho:
            pedido = PedidoDeTool(DESCARTAR, {"motivo": "spam"})
        elif f'"remetente": "{nome}", "trecho": "{trecho}"' in recentes:
            pedido = PedidoDeTool(DESCARTAR, {"motivo": "repetido"})
        else:
            pedido = PedidoDeTool(
                ENCAMINHAR,
                {"resumo": f"{nome} mandou: {trecho}", "tipo": "mensagem", "urgencia": "baixa"},
            )
        self.decisoes_do_monitor.append(pedido.tool_id)
        return pedido

    def _jarvis(self, contexto: Contexto) -> Sequence[Parte]:
        self.turnos_do_jarvis.append(contexto.sistema)
        if self.jarvis_cala:
            return [MARCA_DO_SILENCIO]
        achado = re.search(r'"resumo_do_monitor": "(.*?)"', contexto.sistema)
        return [f"Olha, {achado.group(1)}." if achado else MARCA_DO_SILENCIO]


@pytest.fixture
def montado(tmp_path: Path) -> tuple[Aplicativo, Modelo, EstadoDoMonitor]:
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _l: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=tmp_path,
    )
    app.abrir(com_asr=False)
    app.avisos.piso_livre_s = 0.0
    modelo = Modelo()
    motor = MotorRoteirizado(resposta=modelo, conta_eventos=False)
    app._motor = motor
    assert app._cerebro is not None
    app._cerebro.motor = motor
    estado = EstadoDoMonitor()
    estado.ajustar(ConfiguracaoSocial().com_rede("whatsapp", monitorar=True, notificar=True))
    return app, modelo, estado


def _chega(app: Aplicativo, estado: EstadoDoMonitor, pagina: EstadoDaPagina) -> None:
    """O que `gui/ponte.py` faz com a notificação do monitor: o evento vai ao aplicativo."""
    aviso = estado.receber(pagina, notificar=True)
    assert aviso is not None, "a página não subiu a contagem"
    app.evento_de_rede(aviso.nome_da_rede, aviso.evento)
    assert app.agente_monitor.esperar(5.0), "o agente monitor não decidiu a tempo"


def _trilha(app: Aplicativo, evento: str) -> list[dict[str, Any]]:
    caminho = app.raiz / "diagnostico" / "turnos.jsonl"
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    return [d for d in map(json.loads, linhas) if d["evento"] == evento]


def test_a_ligacao_perdida_chega_ao_jarvis_e_vira_fala(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    app, modelo, estado = montado
    _chega(app, estado, _pagina(1, _conversa("Dani", "", "Chamada de voz perdida")))

    assert app.entregar_avisos(None), "ocioso, o Jarvis recebe o evento na hora"
    (sistema,) = modelo.turnos_do_jarvis
    assert "agente monitor das redes" in sistema and "triado" in sistema
    assert "de_terceiros=sim" in sistema, "o conteúdo da rede é dado, nunca ordem"
    turno = app.turnos[-1]
    assert turno.respondeu == "Olha, Dani: ligacao_perdida."
    assert turno.amostras_tocadas > 0, "o TTS não produziu áudio"
    (decisao,) = _trilha(app, "monitor.decisao")
    assert (decisao["decisao"], decisao["urgencia"], decisao["tipo_do_evento"]) == (
        "encaminhar",
        "alta",
        "ligacao_perdida",
    )
    assert "Dani" not in json.dumps(_trilha(app, "monitor.decisao")), "a trilha só leva código"
    (entrega,) = _trilha(app, "entrega")
    assert (entrega["decisao"], entrega["motivo"]) == ("falada", "jarvis_falou")


def test_a_mensagem_comum_pode_ser_descartada_pelo_monitor(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    app, modelo, estado = montado
    _chega(app, estado, _pagina(1, _conversa("Loja X", "promoção! só hoje")))

    assert not app.entregar_avisos(None), "o descartado não chega ao Jarvis"
    assert modelo.turnos_do_jarvis == [] and app.dados_dos_avisos()["avisos"] == []
    (decisao,) = _trilha(app, "monitor.decisao")
    assert (decisao["decisao"], decisao["motivo"]) == ("descartar", "spam")


def test_a_mensagem_de_gente_encaminhada_vira_fala(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    app, _modelo, estado = montado
    _chega(app, estado, _pagina(1, _conversa("Ana", "me liga quando puder")))

    assert app.entregar_avisos(None)
    assert app.turnos[-1].respondeu == "Olha, Ana mandou: me liga quando puder."


def test_o_spam_repetido_passa_uma_vez_e_depois_e_descartado(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    app, modelo, estado = montado
    for total in (1, 2, 3):
        _chega(app, estado, _pagina(total, _conversa("Bot", "ganhe um prêmio")))

    assert modelo.decisoes_do_monitor == [ENCAMINHAR, DESCARTAR, DESCARTAR]
    motivos = [d["motivo"] for d in _trilha(app, "monitor.decisao")]
    assert motivos == ["", "repetido", "repetido"]
    assert len(app.dados_dos_avisos()["avisos"]) == 1


def test_a_ligacao_em_andamento_espera_a_fronteira_quando_o_jarvis_esta_falando(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    app, modelo, estado = montado
    app._mudar(Estado.FALANDO)  # o Jarvis está no meio de uma resposta
    _chega(app, estado, _pagina(1, _conversa("Dani", "", "Chamada de voz", "recebendo")))

    assert not app.entregar_avisos(None), "nunca por cima da fala"
    assert modelo.turnos_do_jarvis == []
    app._mudar(Estado.OUVINDO)  # a fala acabou: a fronteira do turno
    assert app.entregar_avisos(None)
    assert app.turnos[-1].respondeu == "Olha, Dani: ligacao_em_andamento."


def test_o_evento_do_monitor_nao_espera_o_teto_de_fala_espontanea(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    """Antes: depois de um aviso falado, o evento de rede esperava 2 min (D22)."""
    app, _modelo, estado = montado
    _chega(app, estado, _pagina(1, _conversa("Ana", "oi")))
    assert app.entregar_avisos(None)
    _chega(app, estado, _pagina(2, _conversa("Dani", "", "Chamada de voz perdida")))
    assert app.entregar_avisos(None), "a ligação esperou o teto de fala"


def test_quando_o_jarvis_cala_a_trilha_diz_que_ele_calou(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    """A reprodução do diagnóstico: o motor respondia `[silencio]` e a trilha gravava
    `[fora_da_forma]` — não se sabia se o Jarvis calou ou se o motor caiu."""
    app, modelo, estado = montado
    modelo.jarvis_cala = True
    _chega(app, estado, _pagina(1, _conversa("Ana", "oi")))

    assert app.entregar_avisos(None)
    (entrega,) = _trilha(app, "entrega")
    assert (entrega["decisao"], entrega["motivo"]) == ("silenciosa", "jarvis_calou")
    (aviso,) = app.dados_dos_avisos()["avisos"]
    assert aviso["entrega"] == "so_card", "calado, o card guarda"


def test_sem_decisao_do_monitor_o_evento_chega_ao_jarvis_marcado(
    montado: tuple[Aplicativo, Modelo, EstadoDoMonitor],
) -> None:
    """O monitor que não decide (sem motor, motor caído) não some com o evento: o Jarvis recebe,
    marcado `sem_decisao`, e decide."""
    app, modelo, estado = montado
    app._motor = None  # o agente fica sem motor; o turno do Jarvis segue com o dele
    _chega(app, estado, _pagina(1, _conversa("Ana", "oi")))

    assert app.entregar_avisos(None)
    (sistema,) = modelo.turnos_do_jarvis
    assert '"decisao_do_monitor": "sem_decisao"' in sistema
    (decisao,) = _trilha(app, "monitor.decisao")
    assert (decisao["decisao"], decisao["motivo"]) == ("sem_decisao", "sem_motor")
