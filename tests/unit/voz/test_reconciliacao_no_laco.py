"""A reconciliação por som no laço de voz (ADR-0067): o pedido chega ao cérebro com a palavra
que o ASR trocou já corrigida, a nota do turno diz o que foi feito, e a trilha guarda o antes e o
depois. Tudo com falsos: nenhum microfone abre, nenhuma pasta do dono é lida. Os exemplos são os do
dono (2026-11-14): «mãe» ouvido «ma i», «WhatsApp» ouvido «note pad».
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.s2.cerebro import Cerebro
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.interface import Sinais
from jarvis.voz.reconciliar import NOTA_DA_VOZ
from tests.unit.voz.test_app import aplicativo_de
from tests.unit.voz.test_app_escuta import VadComRajadas
from tests.unit.voz.test_ruido_no_laco import QUADRO_DO_EVENTO, AsrComSinais, _palavra, _wav

FORTE = Sinais(sem_fala=0.03, logprob=-0.4, compressao=0.5)


def _laco(tmp_path: Path, texto: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str]]:
    notas: list[str] = []
    original = Cerebro.responder

    def responder(self: Cerebro, texto_do_dono: str, **opcoes: Any) -> Any:
        notas.append(str(opcoes.get("tom", "")))
        return original(self, texto_do_dono, **opcoes)

    monkeypatch.setattr(Cerebro, "responder", responder)
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", _palavra(600))
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=ModoDeEscuta.CONTINUA)
    app._asr = AsrComSinais((texto, FORTE))
    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 30)))
    return app, notas


def _eventos(app: Any, tipo: str) -> list[dict[str, Any]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    if not arquivo.exists():
        return []
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, linhas) if e.get("evento") == tipo]


def test_o_pedido_chega_ao_cerebro_com_o_som_reconciliado_e_a_nota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, notas = _laco(tmp_path, "manda mensagem no note pad pra minha ma i", monkeypatch)

    assert [t.falou for t in app.turnos] == ["manda mensagem no WhatsApp pra minha mãe"]
    (nota,) = notas
    assert NOTA_DA_VOZ in nota
    assert "Ouvi «note pad» e entendi «WhatsApp»" in nota
    assert "Ouvi «ma i» e corrigi para «mãe»" in nota
    (evento,) = _eventos(app, "ouvido")
    assert evento["bruto"] == "manda mensagem no note pad pra minha ma i"
    assert evento["corrigido"] == "manda mensagem no WhatsApp pra minha mãe"
    assert (evento["trocas"], evento["duvidas"], evento["certeza"]) == (2, 0, "palpite")


def test_turno_sem_som_trocado_leva_so_a_nota_geral_e_nada_na_trilha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, notas = _laco(tmp_path, "que horas são", monkeypatch)

    assert [t.falou for t in app.turnos] == ["que horas são"]
    assert notas == [NOTA_DA_VOZ]
    assert _eventos(app, "ouvido") == []


def test_o_turno_digitado_nao_leva_a_nota_da_voz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notas: list[str] = []
    original = Cerebro.responder

    def responder(self: Cerebro, texto_do_dono: str, **opcoes: Any) -> Any:
        notas.append(str(opcoes.get("tom", "")))
        return original(self, texto_do_dono, **opcoes)

    monkeypatch.setattr(Cerebro, "responder", responder)
    app = aplicativo_de(tmp_path)
    app.responder("abre o note pad")
    assert notas == [""]
