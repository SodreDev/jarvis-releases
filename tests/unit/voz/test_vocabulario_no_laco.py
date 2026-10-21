"""O vocabulário do dono no laço de voz (ADR-0044): a dica, a transcrição corrigida e a pronúncia.

A pasta do vocabulário é a do teste (`tmp_path`), nunca a do dono. O TTS é um motor que anota o
texto que recebe: é assim que se prova que a pronúncia vai **só** para o motor, e a tela, a
conversa e a resposta ficam com a grafia certa.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.audio_io.quadro import de_int16
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.interface import Onde, Sinais
from jarvis.voz.vocabulario import ARQUIVO_DO_DONO, RepositorioDoVocabulario
from tests.unit.voz.test_app import aplicativo_de
from tests.unit.voz.test_app_escuta import VadComRajadas
from tests.unit.voz.test_ruido_no_laco import QUADRO_DO_EVENTO, AsrComSinais, _palavra, _wav

FORTE = Sinais(sem_fala=0.03, logprob=-0.4, compressao=0.5)
VOCABULARIO = """\
ignorar = ["fala galera"]

[[termo]]
escrita = "Steam"
ouvido = ["stim"]
fala = "Stím"
tipo = "app"

[[termo]]
escrita = "Thiago Nigro"
tipo = "pessoa"
"""


class TtsQueAnota:
    """Sintetiza um tom curto e guarda o texto que recebeu."""

    nome = "tts-que-anota"
    voz = "teste"
    licenca = "Apache-2.0"
    onde = Onde.LOCAL
    registrado = "tts-piper-epitran"

    def __init__(self) -> None:
        self.textos: list[str] = []

    def sintetizar(self, texto: str) -> bytes:
        self.textos.append(texto)
        return de_int16([800, -800] * 800)


def _repositorio(tmp_path: Path) -> RepositorioDoVocabulario:
    pasta = tmp_path / "config" / "jarvis"
    pasta.mkdir(parents=True)
    (pasta / ARQUIVO_DO_DONO).write_text(VOCABULARIO, encoding="utf-8")
    return RepositorioDoVocabulario(pasta)


def test_a_dica_do_asr_leva_os_termos_do_dono(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.vocabulario = _repositorio(tmp_path)

    app._ler_o_vocabulario()

    assert app._dica_do_asr() == "Jarvis, Steam, Thiago Nigro."


def test_a_transcricao_sai_com_os_nomes_do_dono(tmp_path: Path) -> None:
    asr = AsrComSinais(("manda mensagem para o Tiago Negro e abre o stim", FORTE))
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app.vocabulario = _repositorio(tmp_path)
    linhas: list[str] = []
    app.escrever_na_tela = linhas.append
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", _palavra(600))
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=ModoDeEscuta.CONTINUA)
    app._asr = asr

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 30)))

    assert [t.falou for t in app.turnos] == ["manda mensagem para o Thiago Nigro e abre o Steam"]
    assert "Você: manda mensagem para o Thiago Nigro e abre o Steam" in linhas


def test_a_frase_que_o_dono_manda_ignorar_cai_como_ruido(tmp_path: Path) -> None:
    asr = AsrComSinais(("Fala, galera!", FORTE))
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(filtro_de_ruido=True)
    app.vocabulario = _repositorio(tmp_path)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", _palavra(400))
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=ModoDeEscuta.CONTINUA)
    app._asr = asr

    app.rodar_audio(vad=VadComRajadas((QUADRO_DO_EVENTO, QUADRO_DO_EVENTO + 20)))

    assert app.turnos == []
    assert app.modo_de_escuta.ruidos == 1


def test_a_pronuncia_vai_so_para_o_motor_de_tts(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.vocabulario = _repositorio(tmp_path)
    tts = TtsQueAnota()
    app._tts = tts
    app._ler_o_vocabulario()

    turno = app.falar("Abri o Steam para você.", epoch=app.epoch)

    assert turno.respondeu == "Abri o Steam para você.", "a tela e a conversa ficam com a grafia"
    assert " ".join(tts.textos) == "Abri o Stím para você."


def test_a_pronuncia_respeita_o_motor_escolhido(tmp_path: Path) -> None:
    pasta = tmp_path / "config"
    pasta.mkdir()
    (pasta / ARQUIVO_DO_DONO).write_text(
        '[[termo]]\nescrita = "Spotify"\nfala = "Spótifai"\nmotores = ["tts-elevenlabs"]\n',
        encoding="utf-8",
    )
    app = aplicativo_de(tmp_path)
    app.vocabulario = RepositorioDoVocabulario(pasta)
    tts = TtsQueAnota()  # registrado como a piper: a pronúncia é só da ElevenLabs
    app._tts = tts
    app._ler_o_vocabulario()

    app.falar("Tocando no Spotify.", epoch=app.epoch)

    assert " ".join(tts.textos) == "Tocando no Spotify."


def test_sem_vocabulario_nada_muda(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    tts = TtsQueAnota()
    app._tts = tts
    app._ler_o_vocabulario()

    app.falar("Abri o Steam.", epoch=app.epoch)

    assert " ".join(tts.textos) == "Abri o Steam."
    assert app._dica_do_asr() == "Jarvis."


def test_a_correcao_aprendida_vale_ja_na_dica_e_na_correcao(tmp_path: Path) -> None:
    repositorio = _repositorio(tmp_path)
    app = aplicativo_de(tmp_path)
    app.vocabulario = repositorio
    asr = AsrComSinais(dica="")
    app._asr = asr
    app._ler_o_vocabulario()

    repositorio.aprender("Lutris", ouvido=["lutres"], tipo="app")
    app.recarregar_vocabulario()

    assert asr.dica == "Jarvis, Lutris, Steam, Thiago Nigro."
    assert app._vocabulario_lido.corrigir("abre o lutres") == "abre o Lutris"
