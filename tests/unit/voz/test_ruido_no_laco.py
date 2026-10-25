"""O filtro de ruído no laço de voz (ADR-0043): o que não é fala não chega ao ASR nem vira pedido.

Mesmo banco do `test_app_escuta.py` — WAV no lugar do microfone, VAD falso que diz "fala" nos
quadros escolhidos —, mas agora o WAV tem **conteúdo**: ruído de sala sintético com um estalo, ou
com a `fala_simulada` de uma palavra curta. O ASR falso devolve texto **e** sinais, como o whisper
e a Groq. Nenhum microfone é aberto e nada do dono é lido.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from random import Random

import numpy as np
import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import fala_simulada
from jarvis.executor.ferramentas import Confirmacao
from jarvis.voz.app import Aplicativo, Turno
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.interface import Hipotese, Onde, Sinais, Transcricao
from tests.unit.voz.test_app import aplicativo_de
from tests.unit.voz.test_app_escuta import VadComRajadas

FORTE = Sinais(sem_fala=0.03, logprob=-0.4, compressao=0.5)
FRACO = Sinais(sem_fala=0.25, logprob=-0.85, compressao=0.5)
INVENTADO = Sinais(sem_fala=0.55, logprob=-1.1, compressao=0.9)
RNG = np.random.default_rng(7)
QUADRO_DO_EVENTO = 21
"""O evento entra aos 400 ms: o quadro 21 (o VAD falso conta a partir de 1)."""


class AsrComSinais:
    """Devolve, a cada trecho, a próxima transcrição da lista — texto e sinais."""

    nome = "asr-com-sinais"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, *respostas: tuple[str, Sinais], dica: str = "") -> None:
        self.respostas = list(respostas)
        self.dica = dica
        self.chamadas = 0

    def transcrever_com_sinais(self, amostras: bytes) -> Transcricao:
        self.chamadas += 1
        texto, sinais = self.respostas.pop(0) if self.respostas else ("", Sinais())
        return Transcricao(Hipotese(texto, 0.9), sinais)

    def transcrever(self, amostras: bytes) -> Hipotese:
        return self.transcrever_com_sinais(amostras).hipotese


def _wav(caminho: Path, evento: np.ndarray, segundos: float = 3.0) -> Path:
    sinal = RNG.normal(0.0, 10 ** (-62 / 20), int(segundos * TAXA_PADRAO))
    inicio = int(0.4 * TAXA_PADRAO)
    sinal[inicio : inicio + len(evento)] += evento
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(np.clip(np.rint(sinal * 32767), -32768, 32767).astype("<i2").tobytes())
    return caminho


def _clique() -> np.ndarray:
    n = int(0.03 * TAXA_PADRAO)
    return RNG.normal(0.0, 1.0, n) * np.exp(-np.arange(n) / (0.004 * TAXA_PADRAO)) * 0.4


def _palavra(ms: float = 300.0) -> np.ndarray:
    bruto = fala_simulada(ms, aleatorio=Random(11), pico=0.35, f0_hz=140.0)
    fala: np.ndarray = np.frombuffer(bruto, dtype="<i2").astype(np.float64) / 32768
    return fala


def _app(
    tmp_path: Path, modo: ModoDeEscuta, evento: np.ndarray, asr: AsrComSinais
) -> tuple[Aplicativo, list[str]]:
    linhas: list[str] = []
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app.escrever_na_tela = linhas.append
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", evento)
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=modo)
    app._asr = asr
    return app, linhas


def _eventos_de_ruido(app: Aplicativo) -> list[dict[str, object]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    if not arquivo.exists():
        return []
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, linhas) if e.get("evento") == "ruido"]


def test_o_estalo_nao_chega_ao_asr_e_o_descarte_e_silencioso(tmp_path: Path) -> None:
    asr = AsrComSinais(("Obrigado.", FORTE))
    app, linhas = _app(tmp_path, ModoDeEscuta.CONTINUA, _clique(), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 2)))

    assert asr.chamadas == 0, "o estalo foi transcrito"
    assert app.turnos == []
    assert not any(linha.startswith("Você") or "não entendi" in linha for linha in linhas)
    assert app.escuta is not None and app.escuta.ruidos == 1
    (evento,) = _eventos_de_ruido(app)
    assert evento["etapa"] == "trecho" and evento["motivo"] in {"impulso", "fundo"}
    assert evento["turno"] == "escuta"


def test_a_palavra_curta_chega_ao_asr_e_vira_pedido(tmp_path: Path) -> None:
    asr = AsrComSinais(("Sim.", FORTE))
    app, linhas = _app(tmp_path, ModoDeEscuta.CONTINUA, _palavra(250), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 13)))

    assert asr.chamadas == 1
    assert [t.falou for t in app.turnos] == ["Sim."]
    assert "Você: Sim." in linhas
    assert app.escuta is not None and app.escuta.ruidos == 0
    assert _eventos_de_ruido(app) == []


def test_a_legenda_que_o_asr_inventa_cai_em_silencio(tmp_path: Path) -> None:
    asr = AsrComSinais(("Legendas pela comunidade Amara.org", FORTE))
    app, linhas = _app(tmp_path, ModoDeEscuta.CONTINUA, _palavra(), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 15)))

    assert asr.chamadas == 1
    assert app.turnos == []
    assert not any("Amara" in linha or "Legendas" in linha for linha in linhas), "o texto vazou"
    assert not any("não entendi" in linha for linha in linhas), "o descarte não é silencioso"
    (evento,) = _eventos_de_ruido(app)
    assert evento["etapa"] == "texto" and evento["motivo"] == "alucinacao"


def test_a_trilha_do_ruido_leva_so_codigos_e_numeros(tmp_path: Path) -> None:
    asr = AsrComSinais(("Clique no clipe para ver o que está acontecendo no clipe.", INVENTADO))
    app, _ = _app(tmp_path, ModoDeEscuta.CONTINUA, _palavra(), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 15)))

    (evento,) = _eventos_de_ruido(app)
    assert evento["motivo"] == "sem_fala"
    assert evento["sem_fala"] == 0.55 and evento["logprob"] == -1.1
    permitidos = {"t", "turno", "evento", "etapa", "motivo", "modo", "ms"} | {
        "maior_fala_ms",
        "contraste_db",
        "sem_fala",
        "logprob",
    }
    assert set(evento) <= permitidos, set(evento) - permitidos
    texto = json.dumps(evento, ensure_ascii=False)
    assert "clipe" not in texto.lower()


def test_jarvis_obrigado_e_so_a_chamada(tmp_path: Path) -> None:
    """O "Obrigado." que o ASR põe no silêncio depois do nome não vira pedido: a escuta arma."""
    asr = AsrComSinais(("Jarvis. Obrigado.", FORTE))
    app, linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, _palavra(), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 15)))

    assert app.turnos == []
    assert any("pode falar" in linha for linha in linhas)


def test_o_pedido_depois_do_nome_continua_valendo(tmp_path: Path) -> None:
    asr = AsrComSinais(("Jarvis, que horas são?", FORTE))
    app, _ = _app(tmp_path, ModoDeEscuta.PALAVRA, _palavra(), asr)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 15)))

    assert [t.falou for t in app.turnos] == ["que horas são"]


def test_o_filtro_desligado_deixa_tudo_como_era(tmp_path: Path) -> None:
    asr = AsrComSinais(("Obrigado.", INVENTADO))
    app, _ = _app(tmp_path, ModoDeEscuta.CONTINUA, _clique(), asr)
    app.configuracao = app.configuracao.com(filtro_de_ruido=False)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 2)))

    assert asr.chamadas == 1
    assert [t.falou for t in app.turnos] == ["Obrigado."]


def _com_pergunta_pendente(app: Aplicativo) -> None:
    """O cérebro de verdade, com a pergunta de uma ação perigosa aberta (a do PDP)."""
    app.abrir()
    assert app._cerebro is not None
    app._cerebro.pendencias.abrir(
        Confirmacao(
            id="c-0001",
            tool_id="files.move_to_trash",
            titulo="Mandar para a lixeira",
            detalhe="mandar notas.md para a lixeira",
            motivo="apagar pede o seu sim",
            prazo_s=60.0,
        )
    )


def test_o_sim_sem_certeza_nao_confirma_a_pergunta_pendente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O pior caso de ruído virando ação: "Sim." inventado respondendo ao pedido de confirmação."""
    asr = AsrComSinais(("Sim.", FRACO))
    app, linhas = _app(tmp_path, ModoDeEscuta.CONTINUA, _palavra(250), asr)
    _com_pergunta_pendente(app)
    respondidos: list[str] = []

    def responder(_app: Aplicativo, texto: str, *, fila: object = None) -> None:
        respondidos.append(texto)

    monkeypatch.setattr(Aplicativo, "responder", responder)

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 13)))

    assert respondidos == [], "o «sim» sem certeza chegou ao cérebro"
    assert any("não tive certeza" in linha for linha in linhas)
    (evento,) = _eventos_de_ruido(app)
    assert evento["motivo"] == "sim_incerto"


def _respondidos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, texto: str, sinais: Sinais
) -> tuple[list[str], list[str]]:
    asr = AsrComSinais((texto, sinais))
    app, linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, _palavra(250), asr)
    _com_pergunta_pendente(app)
    respondidos: list[str] = []

    def responder(_app: Aplicativo, pedido: str, **_extra: object) -> object:
        respondidos.append(pedido)
        return Turno(falou=pedido, respondeu="")

    monkeypatch.setattr(Aplicativo, "responder", responder)
    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 13)))
    return respondidos, linhas


def test_o_sim_com_certeza_responde_mesmo_sem_a_palavra_de_ativacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com a pergunta aberta, a janela da resposta é um turno próprio (ADR-0048): no modo palavra,
    "sim" sem o nome é a resposta — e chega ao cérebro como o «sim» literal."""
    respondidos, _linhas = _respondidos(tmp_path, monkeypatch, "Sim.", FORTE)
    assert respondidos == ["sim"]


def test_o_sim_com_a_palavra_tambem_precisa_de_certeza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antes, «Jarvis, sim» escapava da defesa da ADR-0043 (não era o literal); agora o «sim»
    lido dele cobra os mesmos sinais fortes."""
    respondidos, linhas = _respondidos(tmp_path, monkeypatch, "Jarvis, sim.", FRACO)
    assert respondidos == [] and any("não tive certeza" in linha for linha in linhas)


def test_sem_pergunta_aberta_o_sim_sem_a_palavra_e_descartado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asr = AsrComSinais(("Sim.", FORTE))
    app, _linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, _palavra(250), asr)
    app.abrir()
    respondidos: list[str] = []
    monkeypatch.setattr(
        Aplicativo, "responder", lambda _a, pedido, **_k: respondidos.append(pedido)
    )
    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 13)))
    assert respondidos == [], "sem pergunta, «sim» sem o nome é fala que não era com ele"


def test_a_vigia_nao_corta_a_fala_pelo_eco_da_dica(tmp_path: Path) -> None:
    """O "Jarvis." que o ASR inventa na respiração (a dica dele) não interrompe o Jarvis."""
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app._asr = AsrComSinais(("Jarvis.", FRACO), ("Jarvis, para.", FORTE), dica="Jarvis.")

    vigia = app._montar_a_vigia()
    assert vigia is not None
    try:
        assert vigia.transcrever(b"\x00\x00" * 320) == ""
        assert vigia.transcrever(b"\x00\x00" * 320) == "Jarvis, para."
    finally:
        app._soltar_a_vigia()
