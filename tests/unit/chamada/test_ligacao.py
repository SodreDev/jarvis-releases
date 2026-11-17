"""ADR-0074, fatia C: a ligação lida pela extensão chega ao app; o dono passa a ligação ao Jarvis
(«Jarvis atende»), o áudio liga, a fala de quem liga vai ao agente e tudo é desfeito no fim.
Protocolo, monitor, central e áudio com peças falsas: nenhum navegador, conta ou áudio real."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from jarvis.audio_io.misturador import NOME_DO_MIX
from jarvis.chamada.agente import SaidaEmLista
from jarvis.chamada.voz import montar_audio
from jarvis.navegador.protocolo import PedidoInvalido, validar_estado_social
from jarvis.social.monitor import EstadoDaPagina, MonitorSocial
from tests.unit.chamada.test_agente import AVISO
from tests.unit.chamada.test_central import Mundo
from tests.unit.chamada.test_voz_e_escuta import (
    ALTO,
    MUDO,
    GrafoComApps,
    GravadorFalso,
    Sintetizador,
    TocadorFalso,
    Transcritor,
)

BASE = {"rede": "whatsapp", "logado": True, "naoLidas": 0, "conversas": []}


def test_protocolo_aceita_o_estado_da_ligacao_e_recusa_o_que_nao_cabe() -> None:
    sem = validar_estado_social(BASE)
    assert sem["chamada"] == {"estado": "nenhuma", "quem": ""}, "extensão de antes: nenhuma"
    com = validar_estado_social({**BASE, "chamada": {"estado": "tocando", "quem": "Bruno"}})
    assert com["chamada"] == {"estado": "tocando", "quem": "Bruno"}
    for ruim in (
        {"estado": "atendida", "quem": ""},
        {"estado": "tocando"},
        {"estado": "tocando", "quem": "x" * 200},
        {"estado": "tocando", "quem": "Bruno‮"},
        "tocando",
    ):
        with pytest.raises(PedidoInvalido):
            validar_estado_social({**BASE, "chamada": ruim})


def test_monitor_avisa_so_a_mudanca_do_estado_da_ligacao() -> None:
    # Não é iniciado (sem ponte nem configuração): só o repasse do estado da página.
    monitor = MonitorSocial(
        cast(Any, object()),
        configuracao=cast(Any, lambda: None),
        familia=lambda: "chromium",
        ao_notificar=lambda _a: None,
        ao_mudar=lambda: None,
    )
    vistos: list[tuple[str, str, str]] = []
    monitor.ao_chamada = lambda rede, estado, quem: vistos.append((rede, estado, quem))
    for estado in ("nenhuma", "tocando", "tocando", "em_andamento", "nenhuma"):
        evento = validar_estado_social(
            {**BASE, "chamada": {"estado": estado, "quem": "Bruno" if estado != "nenhuma" else ""}}
        )
        monitor._repassar(EstadoDaPagina.do_evento(evento))
    assert vistos == [
        ("whatsapp", "tocando", "Bruno"),
        ("whatsapp", "em_andamento", "Bruno"),
        ("whatsapp", "nenhuma", ""),
    ]


@dataclass
class AudioFalso:
    saida: SaidaEmLista = field(default_factory=SaidaEmLista)
    comecou: int = 0
    encerrou: int = 0
    falhar: bool = False

    def comecar(self) -> None:
        if self.falhar:
            raise RuntimeError("pactl não está instalado")
        self.comecou += 1

    def encerrar(self) -> None:
        self.encerrou += 1


def test_ligacao_vira_evento_e_jarvis_so_atende_quando_o_dono_passa(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path)
    audio = AudioFalso()
    mundo.central.abrir_audio = lambda _central: audio
    mundo.roteiro_chamada = [[AVISO]]
    central = mundo.central
    central.estado_da_chamada("whatsapp", "tocando", "Bruno")
    assert mundo.tipos() == ["ligacao_tocando"] and not central.pode_atender()
    assert central.atender() != "", "tocando: quem atende é o dono"
    central.estado_da_chamada("whatsapp", "em_andamento", "Bruno")
    assert central.pode_atender()
    assert central.atender() == ""
    assert audio.comecou == 1 and central.chamada is not None
    central.ouviu_quem_liga("alô, o Marcos está?")
    assert audio.saida.falas and "assistente virtual" in audio.saida.falas[0]
    central.dono_falou("deixa que eu falo")
    assert mundo.eventos[-1] == {
        "tipo": "dono_falou_na_ligacao",
        "de_terceiros": False,
        "texto": "deixa que eu falo",
        "origem": "chamada",
    }
    central.estado_da_chamada("whatsapp", "nenhuma", "")
    assert audio.encerrou == 1
    assert cast(Any, central).chamada is None, "a ligação acabou: o agente saiu"
    assert mundo.tipos()[-1] == "ligacao_nenhuma"


def test_chave_desligada_nao_atende_nem_avisa(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path, ativa=False)
    mundo.central.abrir_audio = lambda _central: AudioFalso()
    mundo.central.estado_da_chamada("whatsapp", "em_andamento", "Bruno")
    assert mundo.eventos == [] and not mundo.central.pode_atender()
    assert mundo.central.atender() != ""


def test_audio_que_nao_liga_vira_evento_e_nada_fica_pela_metade(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path)
    mundo.central.abrir_audio = lambda _central: AudioFalso(falhar=True)
    mundo.central.estado_da_chamada("whatsapp", "em_andamento", "Bruno")
    assert "não ligou" in mundo.central.atender()
    assert mundo.central.chamada is None
    assert mundo.tipos()[-1] == "chamada_sem_audio"


def test_montar_audio_com_pecas_falsas_liga_ouve_e_desfaz() -> None:
    grafo = GrafoComApps()
    ouvidas: list[str] = []
    tocador = TocadorFalso(grafo=grafo)
    gravadores = iter([GravadorFalso([ALTO] * 30 + [MUDO] * 25), GravadorFalso([MUDO] * 5)])
    audio = montar_audio(
        executor=grafo,
        sintetizador=Sintetizador(),
        transcritor=Transcritor({49: "alô"}),
        trava=threading.Lock(),
        fone="auto",
        ao_ouvir_quem_liga=ouvidas.append,
        ao_dono_falou=lambda _t: None,
        gravador=lambda: next(gravadores),
        tocador=tocador,
    )
    audio.comecar()
    for linha in audio.sessao._linhas:
        linha.join(timeout=5)
    assert ouvidas == ["alô"]
    audio.saida.falar("Sou o assistente virtual do dono.")
    assert tocador.tocados[0][0] == NOME_DO_MIX
    assert tocador.mudo_durante == [True], "o sistema não diz que é fone: age como sem fone"
    audio.encerrar()
    assert grafo.modulos == {} and tocador.paradas == 1
