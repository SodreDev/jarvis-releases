"""O tom de voz no laço (ADR-0058): medido no mesmo trecho do ASR, vira uma nota ao cérebro e
nunca aprova nada.

Mesmo banco do `test_ruido_no_laco.py` — WAV no lugar do microfone, VAD falso, ASR falso com
sinais —, com a fala sintética de `tools/sinais_de_tom.py` (contorno de F0 conhecido). Nenhum
microfone é aberto e nada do dono é lido.
"""

from __future__ import annotations

import json
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tools.sinais_de_tom import AFIRMACAO, PERGUNTA, sussurro, trecho, voz

from jarvis.s2.cerebro import Cerebro
from jarvis.voz.app import Aplicativo
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.tom import AnalisadorDeTom, MedidaDoTom
from tests.unit.voz.test_app import aplicativo_de
from tests.unit.voz.test_app_escuta import VadComRajadas
from tests.unit.voz.test_ruido_no_laco import FORTE, FRACO, AsrComSinais

QUADRO_DA_FALA = 21
"""A fala entra aos 400 ms (o quadro 21; o VAD falso conta a partir de 1)."""


def _wav(caminho: Path, fala: np.ndarray, segundos: float = 4.0) -> Path:
    pcm = trecho(fala)
    falta = int(segundos * 16_000) * 2 - len(pcm)
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(16_000)
        arquivo.writeframes(pcm + bytes(max(falta, 0)))
    return caminho


def _app(tmp_path: Path, fala: np.ndarray, asr: AsrComSinais) -> tuple[Aplicativo, list[str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    linhas: list[str] = []
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app.escrever_na_tela = linhas.append
    # Ambiente explícito: nem os presets nem o vocabulário do dono são lidos (o cérebro é o eco).
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", fala)
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=ModoDeEscuta.CONTINUA)
    app._asr = asr
    return app, linhas


def _rodar(app: Aplicativo, segundos_de_fala: float = 2.0) -> None:
    fim = QUADRO_DA_FALA + int(segundos_de_fala * 50)
    app.rodar_audio(vad=VadComRajadas((QUADRO_DA_FALA, fim)))


@pytest.fixture
def cerebro_espiado(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """O que o cérebro recebeu em cada turno: o texto e a nota do tom."""
    chamadas: list[dict[str, Any]] = []
    original = Cerebro.responder

    def responder(self: Cerebro, texto: str, **kwargs: Any) -> Any:
        chamadas.append({"texto": texto, "tom": kwargs.get("tom", "")})
        return original(self, texto, **kwargs)

    monkeypatch.setattr(Cerebro, "responder", responder)
    return chamadas


def _eventos(app: Aplicativo, tipo: str) -> list[dict[str, object]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    if not arquivo.exists():
        return []
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, linhas) if e.get("evento") == tipo]


def test_a_pergunta_pela_entonacao_chega_com_o_ponto_e_a_nota(
    tmp_path: Path, cerebro_espiado: list[dict[str, Any]]
) -> None:
    asr = AsrComSinais(("Vai chover amanhã de manhã.", FORTE))
    app, linhas = _app(tmp_path, voz(PERGUNTA, 2.0, semente=3), asr)

    _rodar(app)

    assert "Você: Vai chover amanhã de manhã?" in linhas
    (chamada,) = cerebro_espiado
    assert chamada["texto"] == "Vai chover amanhã de manhã?"
    assert chamada["tom"] == "[tom da voz do dono: entonação de pergunta]"
    (evento,) = _eventos(app, "tom")
    assert evento["entonacao"] == "pergunta" and evento["fonte"] == "dsp"
    # Na trilha, só os códigos do rótulo: nunca a F0, o nível ou o áudio.
    assert set(evento) <= {
        "t", "turno", "evento", "volume", "entonacao", "som", "ritmo", "energia", "confianca",
        "fonte", "base_pronta",
    }  # fmt: skip
    # A base aprendeu com o turno aceito — só números, no estado da sessão.
    base = json.loads((app.raiz / "tom.json").read_text(encoding="utf-8"))
    assert base["turnos"] == 1


def test_a_afirmacao_nao_custa_nada_no_prompt(
    tmp_path: Path, cerebro_espiado: list[dict[str, Any]]
) -> None:
    asr = AsrComSinais(("Vou sair um pouco mais tarde hoje.", FORTE))
    app, linhas = _app(tmp_path, voz(AFIRMACAO, 2.0, semente=4), asr)

    _rodar(app)

    assert "Você: Vou sair um pouco mais tarde hoje." in linhas
    (chamada,) = cerebro_espiado
    assert chamada["tom"] == ""
    (evento,) = _eventos(app, "tom")
    assert evento["entonacao"] == "afirmacao"


def test_o_tom_nunca_responde_a_pergunta_pendente(
    tmp_path: Path, cerebro_espiado: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Um «sim» que o ASR não teve certeza de ouvir não confirma — com qualquer tom. E o tom nem
    é lido: a resposta à pergunta é decidida antes, pelas defesas da ADR-0043/0048."""
    asr = AsrComSinais(("Sim.", FRACO))
    app, linhas = _app(tmp_path, voz(PERGUNTA, 1.0, semente=5), asr)
    monkeypatch.setattr(Aplicativo, "_pergunta_aberta", lambda _self: "Posso fechar o Discord?")

    _rodar(app, 1.0)

    assert cerebro_espiado == []
    assert any("não tive certeza de ter ouvido o seu «sim»" in linha for linha in linhas)
    assert _eventos(app, "tom") == []


def test_o_sim_firme_com_entonacao_de_pergunta_segue_sim(
    tmp_path: Path, cerebro_espiado: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    asr = AsrComSinais(("Sim.", FORTE))
    app, _ = _app(tmp_path, voz(PERGUNTA, 1.0, semente=6), asr)
    monkeypatch.setattr(Aplicativo, "_pergunta_aberta", lambda _self: "Posso fechar o Discord?")

    _rodar(app, 1.0)

    (chamada,) = cerebro_espiado
    # A resposta lida (ADR-0048), sem «?» e sem nota: o tom não entrou na confirmação.
    assert chamada == {"texto": "sim", "tom": ""}


def _nivel_db(caminho: Path) -> float:
    with wave.open(str(caminho), "rb") as arquivo:
        valores = np.frombuffer(arquivo.readframes(arquivo.getnframes()), dtype="<i2")
    ativos = valores[np.abs(valores) > 0].astype(np.float64)
    return float(10 * np.log10(np.mean(ativos**2)))


def test_sussurro_faz_o_jarvis_responder_mais_baixo(tmp_path: Path) -> None:
    normal = AsrComSinais(("Abre a música baixinho no quarto.", FORTE))
    app, _ = _app(tmp_path / "normal", voz(AFIRMACAO, 2.0, semente=7), normal)
    _rodar(app)
    sussurrado = AsrComSinais(("Abre a música baixinho no quarto.", FORTE))
    baixo, _ = _app(tmp_path / "baixo", sussurro(2.0, semente=7), sussurrado)
    _rodar(baixo)

    assert _eventos(baixo, "tom")[0]["volume"] == "sussurro"
    diferenca = _nivel_db(app.raiz.parent / "saida.wav") - _nivel_db(
        baixo.raiz.parent / "saida.wav"
    )
    assert 7.0 <= diferenca <= 11.0  # −9 dB nos pedaços do TTS


def test_a_analise_atrasada_nao_atrasa_o_turno(
    tmp_path: Path, cerebro_espiado: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = AnalisadorDeTom.medir

    def devagar(self: AnalisadorDeTom, amostras: bytes) -> MedidaDoTom:
        time.sleep(0.6)
        return original(self, amostras)

    monkeypatch.setattr(AnalisadorDeTom, "medir", devagar)
    asr = AsrComSinais(("Vai chover amanhã de manhã.", FORTE))
    app, _ = _app(tmp_path, voz(PERGUNTA, 2.0, semente=8), asr)

    comeco = time.monotonic()
    _rodar(app)
    gasto = time.monotonic() - comeco

    (chamada,) = cerebro_espiado
    assert chamada == {"texto": "Vai chover amanhã de manhã.", "tom": ""}
    assert _eventos(app, "tom") == []
    assert gasto < 5.0  # o laço não esperou os 0,6 s da análise (só o prazo de 50 ms)
