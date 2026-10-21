"""Ruído não vira pedido (ADR-0043): o portão do trecho e o filtro da transcrição.

Áudio só sintético, gerado aqui em memória (`numpy` com semente fixa e a `fala_simulada` do F1-01):
nenhum microfone, nenhum arquivo do dono. Os números dos sinais do ASR são os medidos no whisper
small com áudio sintético (`docs/medicoes/ruido-e-dica.md`).
"""

from __future__ import annotations

from pathlib import Path
from random import Random

import numpy as np
import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import fala_simulada
from jarvis.voz.interface import Sinais
from jarvis.voz.ruido import (
    Motivo,
    PoliticaDeRuido,
    julgar_audio,
    julgar_texto,
    medir_trecho,
    palavras_da_dica,
    sinais_fortes,
    so_cortesia,
)

RNG = np.random.default_rng(20261021)
FALA_FORTE = Sinais(sem_fala=0.03, logprob=-0.4, compressao=0.5)
"""Como a fala sintética saiu no whisper small: `no_speech_prob` baixo, logprob alto."""
INVENTADO = Sinais(sem_fala=0.5, logprob=-1.42, compressao=1.0)
"""Como o texto inventado no meio da respiração saiu (com a dica de apps)."""
INCERTO = Sinais(sem_fala=0.25, logprob=-0.85, compressao=0.5)
"""Nem um nem outro: não é "não era fala", mas também não é certeza."""


def _pcm(sinal: np.ndarray) -> bytes:
    return np.clip(np.rint(sinal * 32767), -32768, 32767).astype("<i2").tobytes()


def _sala(segundos: float, nivel_db: float = -62.0) -> np.ndarray:
    return RNG.normal(0.0, 10 ** (nivel_db / 20), int(segundos * TAXA_PADRAO))


def _com(fundo: np.ndarray, evento: np.ndarray, em_s: float) -> np.ndarray:
    saida = fundo.copy()
    inicio = int(em_s * TAXA_PADRAO)
    saida[inicio : inicio + len(evento)] += evento[: len(saida) - inicio]
    return saida


def _clique(nivel_db: float = -20.0) -> np.ndarray:
    n = int(0.03 * TAXA_PADRAO)
    envelope = np.exp(-np.arange(n) / (0.004 * TAXA_PADRAO))
    return RNG.normal(0.0, 1.0, n) * envelope * 10 ** (nivel_db / 20) * 4


def _teclado(segundos: float = 2.0, por_s: float = 7.0) -> np.ndarray:
    sinal = np.zeros(int(segundos * TAXA_PADRAO))
    instante = 0.1
    while instante < segundos - 0.05:
        sinal = _com(sinal, _clique(-28.0 + RNG.uniform(-4, 2)), instante)
        instante += RNG.uniform(0.6, 1.4) / por_s
    return sinal


def _ventilador(segundos: float = 3.0, nivel_db: float = -40.0) -> np.ndarray:
    branco = RNG.normal(0.0, 1.0, int(segundos * TAXA_PADRAO))
    marrom = np.cumsum(branco)
    marrom -= np.convolve(marrom, np.ones(400) / 400, mode="same")
    marrom /= np.sqrt(np.mean(marrom**2))
    zumbido = 0.3 * np.sin(2 * np.pi * 120 * np.arange(len(marrom)) / TAXA_PADRAO)
    return (marrom + zumbido) * 10 ** (nivel_db / 20)


def _fala_curta(ms: float, semente: int = 3) -> np.ndarray:
    """Uma palavra curta ("sim", "não", "para") como o laço a manda: 400 ms antes e 1,3 s depois."""
    bruto = fala_simulada(ms, aleatorio=Random(semente), pico=0.35, f0_hz=140.0)
    fala = np.frombuffer(bruto, dtype="<i2").astype(np.float64) / 32768
    return _com(_sala(0.4 + ms / 1000 + 1.3), fala, 0.4)


# --- 1. o portão do trecho ------------------------------------------------------------------------
QUALQUER = {Motivo.FUNDO, Motivo.IMPULSO}
"""O ventilador fica a ~6 dB do próprio fundo e o estalo isolado nem chega ao percentil 95: saem
como `fundo` ou `impulso` conforme a semente. O que o teste exige é que não cheguem ao ASR."""


@pytest.mark.parametrize(
    ("nome", "sinal", "motivos"),
    [
        ("silêncio digital", np.zeros(2 * TAXA_PADRAO), {Motivo.FUNDO}),
        ("sala quieta", _sala(2.0), {Motivo.FUNDO}),
        ("chiado alto", _sala(2.0, -42.0), {Motivo.FUNDO}),
        ("ventilador", _ventilador(), QUALQUER),
        ("clique do mouse", _com(_sala(2.0), _clique(), 0.6), QUALQUER),
        ("teclado", _com(_sala(2.6), _teclado(), 0.4), {Motivo.IMPULSO}),
    ],
)
def test_o_que_nao_e_fala_nao_chega_ao_asr(
    nome: str, sinal: np.ndarray, motivos: set[Motivo]
) -> None:
    medida = medir_trecho(_pcm(sinal))
    assert julgar_audio(medida) in motivos, f"{nome}: {medida}"


@pytest.mark.parametrize("ms", [150.0, 250.0, 400.0])
def test_fala_curta_passa_no_portao(ms: float) -> None:
    """ "Sim", "não", "para": a fala curta de verdade tem de chegar ao ASR."""
    medida = medir_trecho(_pcm(_fala_curta(ms)))
    assert julgar_audio(medida) is None, medida
    assert medida.maior_fala_ms >= 0.8 * ms
    assert medida.contraste_db > 20


def test_fala_baixa_e_longe_do_microfone_tambem_passa() -> None:
    bruto = fala_simulada(300, aleatorio=Random(9), pico=0.02)  # ~ -40 dBFS de pico
    fala = np.frombuffer(bruto, dtype="<i2").astype(np.float64) / 32768
    medida = medir_trecho(_pcm(_com(_sala(2.0), fala, 0.4)))
    assert julgar_audio(medida) is None, medida


def test_fala_por_cima_do_ventilador_passa_e_o_ventilador_sozinho_nao() -> None:
    bruto = fala_simulada(400, aleatorio=Random(5), pico=0.1)
    fala = np.frombuffer(bruto, dtype="<i2").astype(np.float64) / 32768
    so_ventilador = _ventilador(2.5)
    assert julgar_audio(medir_trecho(_pcm(so_ventilador))) is Motivo.FUNDO
    assert julgar_audio(medir_trecho(_pcm(_com(so_ventilador, fala, 0.5)))) is None


def test_trecho_vazio_e_fundo() -> None:
    assert julgar_audio(medir_trecho(b"")) is Motivo.FUNDO


def test_o_portao_desligado_deixa_tudo_passar() -> None:
    desligado = PoliticaDeRuido(ligada=False)
    assert julgar_audio(medir_trecho(_pcm(_sala(1.0)), desligado), desligado) is None


def test_a_fala_minima_e_a_margem_sao_do_dono() -> None:
    medida = medir_trecho(_pcm(_fala_curta(250)))
    assert julgar_audio(medida, PoliticaDeRuido(fala_minima_ms=600)) is Motivo.IMPULSO
    assert julgar_audio(medida, PoliticaDeRuido(fala_minima_ms=60)) is None


# --- 2. o filtro da transcrição -------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto",
    [
        "Legendas pela comunidade Amara.org",
        "Legenda Adriana Zanotto",
        "Obrigado por assistir!",
        "Obrigada por assistirem.",
        "Inscreva-se no canal!",
        "Se inscreva no canal e ative o sininho",
        "Thanks for watching!",
        "Sous-titres réalisés par la communauté d'Amara.org",
    ],
)
def test_frase_de_legenda_e_fim_de_video_cai_sempre(texto: str) -> None:
    """Mesmo com os sinais fortes: o dono não diz isso ao Jarvis."""
    assert julgar_texto(texto, FALA_FORTE).motivo is Motivo.ALUCINACAO


def test_a_legenda_no_fim_sai_e_o_pedido_fica() -> None:
    veredito = julgar_texto(
        "Jarvis, abre o Discord. Legendas pela comunidade Amara.org", FALA_FORTE
    )
    assert veredito.texto == "Jarvis, abre o Discord."
    assert veredito.aparado and not veredito.descartado


@pytest.mark.parametrize("texto", ["...", "♪", "♪ ♪ ♪", "[Música]", "(risos)", "  - "])
def test_so_simbolo_ou_anotacao_nao_e_fala(texto: str) -> None:
    assert julgar_texto(texto, FALA_FORTE).motivo is Motivo.SO_SIMBOLOS


def test_texto_vazio_nao_tem_motivo_nenhum() -> None:
    """Vazio é o ASR sem resposta — o laço já trata (e diz, na contínua)."""
    assert julgar_texto("", FALA_FORTE) == julgar_texto("   ", FALA_FORTE)
    assert julgar_texto("", FALA_FORTE).motivo is None


def test_a_anotacao_sai_do_pedido() -> None:
    assert julgar_texto("[Música] abre o Spotify", FALA_FORTE).texto == "abre o Spotify"


@pytest.mark.parametrize(
    "texto",
    [
        "Me inscreve no canal do Thiago.",
        "Abre o link na descrição.",
        "Pula até o próximo vídeo.",
        "Deixa um like nesse vídeo.",
    ],
)
def test_pedido_que_parece_fim_de_video_passa(texto: str) -> None:
    assert julgar_texto(texto, INCERTO).motivo is None


def test_fim_de_video_inteiro_e_sem_certeza_cai() -> None:
    assert julgar_texto("Link na descrição.", INCERTO).motivo is Motivo.ALUCINACAO
    assert julgar_texto("Link na descrição.", FALA_FORTE).motivo is None


@pytest.mark.parametrize("texto", ["Obrigado.", "Tchau!", "Valeu.", "Tchau, tchau.", "Hmm."])
def test_cortesia_solta_cai_sem_certeza_e_passa_com_ela(texto: str) -> None:
    """O dono agradece de verdade: com os sinais fortes passa; o "Obrigado." do silêncio, não."""
    assert julgar_texto(texto, INCERTO).motivo is Motivo.ALUCINACAO
    assert julgar_texto(texto, FALA_FORTE).motivo is None


def test_motor_sem_sinais_e_julgado_so_pelas_frases_que_valem_sempre() -> None:
    """O oráculo e os falsos de teste não medem: nada do que já funcionava muda."""
    assert julgar_texto("Obrigado.").motivo is None
    assert julgar_texto("Jarvis.", dica={"jarvis"}).motivo is None
    assert julgar_texto("Legendas pela comunidade Amara.org").motivo is Motivo.ALUCINACAO


def test_o_asr_dizendo_que_nao_era_fala_derruba_o_texto() -> None:
    texto = "Clique no clipe para ver o que está acontecendo no clipe."
    assert julgar_texto(texto, INVENTADO).motivo is Motivo.SEM_FALA


def test_sem_fala_alto_com_logprob_bom_ainda_passa() -> None:
    """Fala depois de um silêncio longo pode ter `no_speech_prob` alto: sozinho ele não decide."""
    assert julgar_texto("que horas são", Sinais(sem_fala=0.5, logprob=-0.3)).motivo is None


@pytest.mark.parametrize(
    "texto",
    [
        "Bazaar, Bazaar, Bazaar, Bazaar.",
        "obrigado obrigado obrigado obrigado",
        "e aí e aí e aí e aí",
    ],
)
def test_o_modelo_em_laco_cai(texto: str) -> None:
    assert julgar_texto(texto, FALA_FORTE).motivo is Motivo.REPETICAO


@pytest.mark.parametrize("texto", ["Não, não, não.", "Para, para, para!", "Sim, sim, sim."])
def test_tres_vezes_e_do_dono(texto: str) -> None:
    assert julgar_texto(texto, FALA_FORTE).motivo is None


def test_a_compressao_que_o_asr_mediu_tambem_derruba() -> None:
    sinais = Sinais(sem_fala=0.05, logprob=-0.3, compressao=2.9)
    assert julgar_texto("isso é um texto comprido o bastante", sinais).motivo is Motivo.REPETICAO


def test_o_eco_da_dica_sem_certeza_cai_e_com_certeza_passa() -> None:
    dica = palavras_da_dica("Jarvis, Discord.")
    assert julgar_texto("Jarvis.", INCERTO, dica=dica).motivo is Motivo.ECO_DA_DICA
    assert julgar_texto("Discord, Jarvis", INCERTO, dica=dica).motivo is Motivo.ECO_DA_DICA
    assert julgar_texto("Jarvis.", FALA_FORTE, dica=dica).motivo is None


def test_ordem_de_parar_nao_e_eco_do_nome() -> None:
    dica = palavras_da_dica("Jarvis.")
    assert julgar_texto("Jarvis, para!", INCERTO, dica=dica).motivo is None
    assert julgar_texto("Abre o Discord", INCERTO, dica=palavras_da_dica("Discord")).motivo is None


def test_texto_curto_com_confianca_baixa_cai() -> None:
    assert julgar_texto("Vídeo.", Sinais(sem_fala=0.13, logprob=-1.01)).motivo is (
        Motivo.INCERTO_CURTO
    )
    assert julgar_texto("abre o Discord agora", Sinais(sem_fala=0.13, logprob=-1.01)).motivo is None


@pytest.mark.parametrize(
    ("texto", "sinais"),
    [
        ("Sim.", Sinais(sem_fala=0.03, logprob=-0.39)),
        ("Não.", Sinais(sem_fala=0.07, logprob=-0.42)),
        ("Para.", Sinais(sem_fala=0.05, logprob=-0.5)),
        ("Jarvis, que horas são?", Sinais(sem_fala=0.0, logprob=-0.5)),
        ("Abre o Discord.", Sinais(sem_fala=0.02, logprob=-0.59)),
    ],
)
def test_fala_curta_de_verdade_passa_no_filtro(texto: str, sinais: Sinais) -> None:
    """Os sinais da fala sintética medidos no whisper small: nada disso pode cair."""
    veredito = julgar_texto(texto, sinais, dica=palavras_da_dica("Jarvis, Discord."))
    assert veredito.motivo is None and veredito.texto == texto


def test_as_frases_que_o_dono_mandou_ignorar() -> None:
    politica = PoliticaDeRuido(ignorar=("Fala, galera!",))
    assert julgar_texto("fala galera", FALA_FORTE, politica=politica).motivo is Motivo.ALUCINACAO
    assert julgar_texto("fala comigo", FALA_FORTE, politica=politica).motivo is None


def test_o_filtro_desligado_devolve_o_texto_como_veio() -> None:
    desligado = PoliticaDeRuido(ligada=False)
    texto = "Legendas pela comunidade Amara.org"
    assert julgar_texto(texto, INVENTADO, politica=desligado).texto == texto


def test_sinais_fortes() -> None:
    assert sinais_fortes(Sinais())
    assert sinais_fortes(Sinais(sem_fala=0.1, logprob=-0.5))
    assert not sinais_fortes(Sinais(sem_fala=0.25, logprob=-0.5))
    assert not sinais_fortes(Sinais(sem_fala=0.1, logprob=-0.9))


def test_so_cortesia() -> None:
    assert so_cortesia("Obrigado.") and so_cortesia("Tchau, tchau!") and so_cortesia("valeu")
    assert so_cortesia("Legendas pela comunidade Amara.org")
    assert not so_cortesia("obrigado, abre o Discord")
    assert not so_cortesia("")


# --- 3. a configuração do dono -------------------------------------------------------------------
def test_o_filtro_vem_ligado_com_os_padroes_e_o_dono_troca_quatro_limiares(tmp_path: Path) -> None:
    from jarvis.voz.config import Configuracao, escrever, ler

    padrao = Configuracao().politica_de_ruido()
    assert padrao == PoliticaDeRuido()
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text("escuta = 'palavra'\n", encoding="utf-8")
    assert ler(arquivo).politica_de_ruido() == padrao, "arquivo antigo: os padrões"

    escolhida = Configuracao(
        filtro_de_ruido=False, fala_minima_ms=150.0, margem_de_fala_db=9.0, sem_fala_maximo=0.5
    )
    escrever(escolhida, arquivo)
    lida = ler(arquivo)
    assert lida.politica_de_ruido(ignorar=("Fala, galera!",)) == PoliticaDeRuido(
        ligada=False, fala_minima_ms=150.0, margem_db=9.0, sem_fala_maximo=0.5,
        ignorar=("Fala, galera!",),
    )  # fmt: skip
    assert "# Ruído do microfone não vira pedido (ADR-0043)" in arquivo.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("linha", "trecho"),
    [
        ("fala_minima_ms = 5000", "fala_minima_ms"),
        ("margem_de_fala_db = -3", "margem_de_fala_db"),
        ("sem_fala_maximo = 0.0", "sem_fala_maximo"),
        ("filtro_de_ruido = 'sim'", "filtro_de_ruido"),
    ],
)
def test_limiar_fora_da_faixa_recusa_o_arquivo(tmp_path: Path, linha: str, trecho: str) -> None:
    from jarvis.voz.config import ConfiguracaoInvalida, ler

    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text(linha + "\n", encoding="utf-8")
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        ler(arquivo)
