"""O tom de voz do dono (ADR-0058): o núcleo de DSP sobre áudio sintético, sem microfone."""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import numpy as np
import pytest
from tools.sinais_de_tom import (
    AFIRMACAO,
    PERGUNTA,
    Cena,
    base_do_dono,
    cenas,
    sussurro,
    trecho,
    voz,
)

from jarvis.voz.tom import (
    NEUTRO,
    Achados,
    AnalisadorDeTom,
    Energia,
    Entonacao,
    MedidaDoTom,
    Evento,
    LinhaDeBase,
    RepositorioDaLinhaDeBase,
    Ritmo,
    Tom,
    Volume,
    aplicar_ganho,
    com_pergunta,
    ganho_da_resposta_db,
    medir,
    rotular,
    silabas,
    taxa_de_silabas,
    yin,
)


def _base(semente: int = 100) -> LinhaDeBase:
    base = LinhaDeBase()
    for audio, texto in base_do_dono(semente):
        prosodia = medir(audio)
        base.aprender(prosodia, taxa_de_silabas(prosodia, texto))
    return base


@pytest.fixture(scope="module")
def base() -> LinhaDeBase:
    return _base()


@pytest.fixture(scope="module")
def banco() -> dict[str, Cena]:
    return {cena.nome: cena for cena in cenas(semente=3)}


def _rotulo(cena: Cena, base: LinhaDeBase) -> Tom:
    return rotular(medir(cena.audio), base, texto=cena.texto)


# --- a medida --------------------------------------------------------------------------------
def test_o_yin_acompanha_a_f0() -> None:
    tempo = np.arange(16_000) / 16_000
    for hz in (90.0, 150.0, 240.0):
        f0, aperiodicidade = yin(0.3 * np.sin(2 * np.pi * hz * tempo).astype(np.float32))
        assert abs(float(np.median(f0)) - hz) / hz < 0.01
        assert float(np.median(aperiodicidade)) < 0.1


def test_ruido_e_silencio_nao_tem_tom(base: LinhaDeBase) -> None:
    rng = np.random.default_rng(0)
    chiado = trecho(0.05 * rng.standard_normal(32_000))
    assert rotular(medir(chiado), base, texto="").neutro()
    assert rotular(medir(bytes(32_000)), base, texto="") == NEUTRO
    assert medir(b"").fala_ms == 0.0


def test_a_analise_e_barata() -> None:
    audio = trecho(voz(AFIRMACAO, 5.0, semente=1))
    medir(audio)
    comeco = time.perf_counter()
    prosodia = medir(audio)
    gasto_ms = (time.perf_counter() - comeco) * 1000
    # Medido nesta máquina: ~7 ms p50 para 2 s (docs/medicoes/tom-de-voz.md). O teto aqui é
    # folgado para a CI lenta; o que importa é a ordem de grandeza — o ASR leva centenas de ms.
    assert gasto_ms < 150
    assert 0 < prosodia.analise_ms < 150


# --- a entonação --------------------------------------------------------------------------------
@pytest.mark.parametrize("nome", ["pergunta", "pergunta_oxitona"])
def test_a_subida_na_ultima_tonica_e_pergunta(
    nome: str, banco: dict[str, Cena], base: LinhaDeBase
) -> None:
    cena = banco[nome]
    assert _rotulo(cena, base).entonacao is Entonacao.PERGUNTA
    # A entonação não depende da base: vale desde o primeiro turno.
    assert _rotulo(cena, LinhaDeBase()).entonacao is Entonacao.PERGUNTA


def test_a_queda_na_ultima_tonica_e_afirmacao(banco: dict[str, Cena], base: LinhaDeBase) -> None:
    tom = _rotulo(banco["afirmacao"], base)
    assert tom.entonacao is Entonacao.AFIRMACAO
    assert tom.neutro()
    assert tom.linha() == ""


def test_o_ponto_do_asr_tambem_vale() -> None:
    prosodia = medir(trecho(voz(AFIRMACAO, 2.0)))
    assert rotular(prosodia, LinhaDeBase(), texto="vai chover?").entonacao is Entonacao.PERGUNTA
    exclamado = rotular(prosodia, LinhaDeBase(), texto="que beleza!")
    assert exclamado.entonacao is Entonacao.EXCLAMACAO


# --- o volume, contra a base do dono -----------------------------------------------------------
def test_grito_e_voz_baixa_contra_a_base(banco: dict[str, Cena], base: LinhaDeBase) -> None:
    assert _rotulo(banco["grito"], base).volume is Volume.GRITO
    assert _rotulo(banco["voz_baixa"], base).volume is Volume.BAIXO
    assert _rotulo(banco["afirmacao"], base).volume is Volume.NORMAL


def test_sem_base_o_volume_nao_chuta(banco: dict[str, Cena]) -> None:
    """Antes de a base ficar pronta, o nível absoluto não diz nada: o ganho do microfone e a
    distância mudam dezenas de dB. Só o estouro (o microfone saturou) vale."""
    nova = LinhaDeBase()
    assert _rotulo(banco["grito"], nova).volume is Volume.NORMAL
    assert _rotulo(banco["voz_baixa"], nova).volume is Volume.NORMAL
    estouro = trecho(voz(AFIRMACAO, 1.5, nivel_db=-3.0))
    assert rotular(medir(estouro), nova, texto="para com isso").volume is Volume.GRITO


def test_mais_alto_sem_subir_o_tom_e_voz_alta_nao_grito(base: LinhaDeBase) -> None:
    """Chegar perto do microfone sobe o nível, não a F0: é «voz alta», nunca «gritando»."""
    perto = trecho(voz(AFIRMACAO, 2.0, nivel_db=-14.0, semente=9))
    assert rotular(medir(perto), base, texto="abre o navegador").volume is Volume.ALTO


@pytest.mark.parametrize("nivel_db", [-40.0, -24.0])
def test_sussurro_nao_depende_do_ganho(nivel_db: float, base: LinhaDeBase) -> None:
    audio = trecho(sussurro(1.8, nivel_db=nivel_db, semente=2))
    assert rotular(medir(audio), base, texto="abre a música").volume is Volume.SUSSURRO
    # Sem palavras no texto, sopro não é sussurro (é o que o ASR não ouviu).
    assert rotular(medir(audio), base, texto="").volume is not Volume.SUSSURRO


# --- eventos e ritmo ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("nome", "evento"),
    [("risada", Evento.RISADA), ("tosse", Evento.TOSSE), ("suspiro", Evento.SUSPIRO)],
)
def test_eventos_pelo_dsp(
    nome: str, evento: Evento, banco: dict[str, Cena], base: LinhaDeBase
) -> None:
    tom = _rotulo(banco[nome], base)
    assert tom.evento is evento
    assert tom.ritmo is Ritmo.NORMAL  # com evento no meio, o ritmo não é julgado


def test_silabas_contra_o_tempo_com_voz(banco: dict[str, Cena], base: LinhaDeBase) -> None:
    assert silabas("abre o calendário") == 7
    assert _rotulo(banco["rapido"], base).ritmo is Ritmo.RAPIDO
    assert _rotulo(banco["lento"], base).ritmo is Ritmo.LENTO


def test_a_voz_de_sempre_e_neutra(base: LinhaDeBase) -> None:
    for audio, texto in base_do_dono(semente=900):
        assert rotular(medir(audio), base, texto=texto).neutro()


# --- a linha que vai ao cérebro -----------------------------------------------------------------
def test_a_linha_e_curta_e_so_aparece_fora_do_neutro() -> None:
    assert NEUTRO.linha() == "" and NEUTRO.resumo() == ""
    cheio = Tom(
        volume=Volume.SUSSURRO,
        entonacao=Entonacao.PERGUNTA,
        evento=Evento.RISADA,
        ritmo=Ritmo.RAPIDO,
        energia=Energia.ALTA,
        confianca=0.7,
    )
    linha = cheio.linha()
    assert linha.startswith("[tom da voz do dono: ") and linha.endswith("]")
    assert len(linha) <= 120
    assert cheio.linha(("volume", "entonacao")) == (
        "[tom da voz do dono: sussurrando, entonação de pergunta]"
    )
    assert cheio.resumo(("evento",)) == "rindo"
    # A trilha recebe códigos, nunca números da voz.
    assert set(cheio.codigos()) == {
        "volume", "entonacao", "som", "ritmo", "energia", "confianca", "fonte", "base_pronta",
    }  # fmt: skip


def test_com_pergunta_poe_o_que_o_asr_nao_pos() -> None:
    pergunta = Tom(entonacao=Entonacao.PERGUNTA, confianca=0.8)
    assert com_pergunta("Vai chover amanhã.", pergunta) == "Vai chover amanhã?"
    assert com_pergunta("vai chover amanhã", pergunta) == "vai chover amanhã?"
    assert com_pergunta("Vai chover?", pergunta) == "Vai chover?"
    assert com_pergunta("Que beleza!", pergunta) == "Que beleza!"
    assert com_pergunta("Vai chover amanhã.", NEUTRO) == "Vai chover amanhã."
    # Resposta curta nunca vira pergunta: o tom não mexe numa confirmação.
    for curta in ("Sim.", "Pode.", "Jarvis, sim.", "não"):
        assert com_pergunta(curta, pergunta) == curta


def test_sussurro_baixa_a_resposta() -> None:
    assert ganho_da_resposta_db(Tom(volume=Volume.SUSSURRO)) < 0
    assert ganho_da_resposta_db(Tom(volume=Volume.GRITO)) == 0.0
    pcm = np.array([1000, -1000, 32767, -32768], dtype="<i2").tobytes()
    mais_baixo = np.frombuffer(aplicar_ganho(pcm, -6.0), dtype="<i2")
    assert list(mais_baixo[:2]) == [501, -501]
    assert aplicar_ganho(pcm, 0.0) is pcm
    alto = np.frombuffer(aplicar_ganho(pcm, 12.0), dtype="<i2")
    assert alto.max() == 32767 and alto.min() == -32768  # satura, não dá a volta


# --- a linha de base -----------------------------------------------------------------------------
def test_a_base_aprende_aos_poucos_e_o_grito_nao_a_arrasta() -> None:
    base = _base()
    antes = base.nivel_db
    grito = medir(trecho(voz(AFIRMACAO, 2.0, nivel_db=-6.0, semente=5)))
    base.aprender(grito, None)
    assert base.nivel_db - antes < 1.0  # 22 dB acima, e a média andou menos de 1 dB


def test_a_base_grava_so_numeros_em_0600(tmp_path: Path) -> None:
    repositorio = RepositorioDaLinhaDeBase(tmp_path / "estado")
    analisador = AnalisadorDeTom(repositorio)
    for audio, texto in base_do_dono():
        analisador.aprender(analisador.medir(audio), texto)
    analisador.fechar()
    dados = json.loads(repositorio.caminho.read_text(encoding="utf-8"))
    assert all(isinstance(v, int | float) for v in dados.values())
    assert dados["turnos"] == 6
    assert stat.S_IMODE(repositorio.caminho.stat().st_mode) == 0o600
    assert stat.S_IMODE(repositorio.caminho.parent.stat().st_mode) == 0o700
    assert len(repositorio.caminho.read_bytes()) < 400  # números, nunca áudio
    assert AnalisadorDeTom(repositorio).base.pronta


@pytest.mark.parametrize(
    "conteudo", ["não é json", "[]", '{"versao": 9}', '{"versao": 1, "turnos": "x"}']
)
def test_arquivo_torto_e_base_nova(tmp_path: Path, conteudo: str) -> None:
    repositorio = RepositorioDaLinhaDeBase(tmp_path)
    repositorio.caminho.write_text(conteudo, encoding="utf-8")
    assert repositorio.ler() == LinhaDeBase()


# --- o classificador opcional, atrás do mesmo contrato ----------------------------------------
class _Classificador:
    def __init__(self, achados: Achados | None) -> None:
        self.achados = achados
        self.ouviu = 0

    @property
    def nome(self) -> str:
        return "falso"

    def ouvir(self, amostras: bytes) -> Achados:
        self.ouviu += 1
        if self.achados is None:
            raise RuntimeError("o modelo caiu")
        return self.achados


def test_o_classificador_vence_a_heuristica_e_a_falha_e_silenciosa(
    banco: dict[str, Cena],
) -> None:
    risada = _Classificador(Achados("falso", eventos={Evento.RISADA: 0.9}))
    quebrado = _Classificador(None)
    analisador = AnalisadorDeTom(classificadores=(quebrado, risada))
    escuta = analisador.medir(banco["afirmacao"].audio)
    assert quebrado.ouviu == risada.ouviu == 1
    assert len(escuta.achados) == 1
    tom = analisador.rotular(escuta, banco["afirmacao"].texto)
    assert tom.evento is Evento.RISADA and tom.fonte == "dsp+falso"


def test_o_nenhum_do_classificador_apaga_o_evento_inventado(
    banco: dict[str, Cena], base: LinhaDeBase
) -> None:
    prosodia = medir(banco["tosse"].audio)
    nenhum = Achados("falso", eventos={Evento.NENHUM: 0.95, Evento.TOSSE: 0.02})
    assert rotular(prosodia, base, texto="abre", achados=(nenhum,)).evento is Evento.NENHUM


def test_trecho_sem_fala_nao_chama_o_classificador() -> None:
    classificador = _Classificador(Achados("falso", eventos={Evento.RISADA: 0.9}))
    escuta = AnalisadorDeTom(classificadores=(classificador,)).medir(bytes(16_000))
    assert classificador.ouviu == 0 and escuta == MedidaDoTom(escuta.prosodia, ())


def test_pergunta_do_banco_tambem_passa_sem_texto(base: LinhaDeBase) -> None:
    audio = trecho(voz(PERGUNTA, 2.0, semente=11))
    assert rotular(medir(audio), base).entonacao is Entonacao.PERGUNTA
