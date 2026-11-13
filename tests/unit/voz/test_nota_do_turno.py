"""ADR-0063: a nota do dono no laço de verdade — a frase anota o turno anterior e segue ao
cérebro; o botão anota o último; a trilha guarda só o código, e o diagnóstico conta por dia."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.s2.motor import Contexto
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.trilha import ARQUIVO, notas_por_dia
from jarvis.voz.app import PASTA_DA_TRILHA, Aplicativo
from jarvis.voz.config import Configuracao

SEGREDO = "o pin do cartão é 4455"


def _app(tmp_path: Path) -> tuple[Aplicativo, list[str]]:
    ouvidas: list[str] = []

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        ouvidas.append(contexto.mensagens[-1].texto)
        return ["Feito."]

    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco", acesso="padrao"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=tmp_path / "casa",
    )
    app.abrir(com_asr=False)
    app._motor = MotorRoteirizado(resposta=roteiro)
    return app, ouvidas


def _eventos(app: Aplicativo) -> list[dict[str, object]]:
    texto = (app.raiz / PASTA_DA_TRILHA / ARQUIVO).read_text("utf-8")
    assert SEGREDO not in texto and "ficou ruim" not in texto
    return [json.loads(linha) for linha in texto.splitlines()]


def _dizer(app: Aplicativo, fala: str) -> None:
    app.responder(
        fala, fila=FilaDePlayback(sumidouro=SumidouroEmMemoria(), session_id=app.session_id)
    )


def test_a_frase_anota_o_turno_anterior_e_segue_ao_cerebro(tmp_path: Path) -> None:
    app, ouvidas = _app(tmp_path)
    assert app.anotar_turno(True) is False, "antes do primeiro turno não há o que avaliar"

    _dizer(app, f"lembra que {SEGREDO}")
    primeiro = app.turno_para_nota
    _dizer(app, "ficou ruim, refaz do outro jeito")

    eventos = _eventos(app)
    [nota] = [e for e in eventos if e["evento"] == "turno.nota"]
    assert nota["turno"] == primeiro and nota["nota"] == "ruim" and nota["origem"] == "voz"
    assert set(nota) == {"t", "turno", "evento", "nota", "origem"}
    assert ouvidas[-1].startswith("ficou ruim"), "a frase de nota continua sendo fala ao cérebro"
    assert app.turno_para_nota != primeiro and app.nota_do_ultimo_turno == ""


def test_o_botao_anota_o_ultimo_turno_e_o_clique_corrige(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    _dizer(app, "abre o calendário")
    turno = app.turno_para_nota

    assert app.anotar_turno(False) is True and app.nota_do_ultimo_turno == "ruim"
    assert app.anotar_turno(True) is True and app.nota_do_ultimo_turno == "boa"

    notas = [e for e in _eventos(app) if e["evento"] == "turno.nota"]
    assert [(n["turno"], n["nota"], n["origem"]) for n in notas] == [
        (turno, "ruim", "botao"),
        (turno, "boa", "botao"),
    ]
    [linha] = notas_por_dia(app.raiz / PASTA_DA_TRILHA)
    assert linha.endswith("1 boa(s) · 0 ruim(ns)"), "vale a última nota de cada turno"


def test_fala_que_nao_e_nota_nao_anota_nada(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    _dizer(app, "que horas são?")
    _dizer(app, "valeu")
    _dizer(app, "não ficou ruim não")
    assert not [e for e in _eventos(app) if e["evento"] == "turno.nota"]
    assert notas_por_dia(app.raiz / PASTA_DA_TRILHA) == ["  notas: nenhuma nota do dono na trilha"]
