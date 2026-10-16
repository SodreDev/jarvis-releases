"""O laço de voz com os três modos de escuta, e a troca com a sessão aberta (ADR-0021).

Mesmo banco do `test_app.py`: WAV no lugar do microfone, ASR falso que devolve frases
escolhidas, VAD falso com rajadas de fala em quadros conhecidos. Nenhum microfone é aberto.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from jarvis.audio_io.quadro import Quadro
from jarvis.microfone import Modo, ler_estado
from jarvis.voz.app import Aplicativo
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.interface import Hipotese, Onde
from tests.unit.voz.test_app import aplicativo_de, wav_de


class AsrEmSequencia:
    """Cada trecho transcrito devolve a próxima frase da lista."""

    nome = "asr-em-sequencia"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, *frases: str) -> None:
        self.frases: Iterator[str] = iter(frases)
        self.chamadas = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        self.chamadas += 1
        return Hipotese(next(self.frases, ""), 1.0)


class VadComRajadas:
    """Fala nos quadros de cada rajada `(começo, fim)` e cala no resto."""

    def __init__(self, *rajadas: tuple[int, int]) -> None:
        self.nome = "vad-com-rajadas"
        self.rajadas = rajadas
        self.vistos = 0
        self.falando: bool | None = False
        self.ultima_probabilidade = 0.0

    def ver(self, quadro: Quadro) -> bool | None:
        self.vistos += 1
        agora = any(comeco <= self.vistos < fim for comeco, fim in self.rajadas)
        self.ultima_probabilidade = 1.0 if agora else 0.0
        if agora == self.falando:
            return None
        self.falando = agora
        return agora


def _app(
    tmp_path: Path,
    modo: ModoDeEscuta,
    *frases: str,
    segundos: float = 4.0,
    pressionado: Callable[[], bool] | None = None,
) -> tuple[Aplicativo, list[str]]:
    linhas: list[str] = []
    app = aplicativo_de(tmp_path, pressionado=pressionado)
    app.escrever_na_tela = linhas.append
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = wav_de(tmp_path / "entrada.wav", segundos=segundos)
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.escuta = Escuta(modo=modo)
    app._asr = AsrEmSequencia(*frases)
    return app, linhas


# --- palavra de ativação --------------------------------------------------------------------
def test_sem_a_palavra_o_trecho_e_descartado_sem_deixar_o_texto(tmp_path: Path) -> None:
    app, linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, "que horas são")
    app.rodar_audio(vad=VadComRajadas((1, 15)))

    assert app.turnos == [], "fala sem a chamada virou turno"
    assert app.escuta is not None and app.escuta.descartados == 1
    assert not any("que horas são" in linha for linha in linhas), "o texto descartado vazou"


def test_com_a_palavra_so_o_pedido_vira_turno(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.PALAVRA, "Járvis, que horas são?")
    app.rodar_audio(vad=VadComRajadas((1, 15)))

    assert len(app.turnos) == 1
    assert app.turnos[0].falou == "que horas são"
    assert app.turnos[0].respondeu == "Você disse: que horas são"


def test_so_o_nome_arma_e_o_trecho_seguinte_e_o_pedido(tmp_path: Path) -> None:
    app, linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, "jarvis", "abre a pasta de fotos")
    app.rodar_audio(vad=VadComRajadas((1, 15), (70, 90)))

    assert any("pode falar" in linha for linha in linhas)
    assert [t.falou for t in app.turnos] == ["abre a pasta de fotos"]
    assert app.escuta is not None and not app.escuta.armado(0), "continuou armado depois"


def test_ruido_sem_texto_no_modo_palavra_nao_enche_a_tela(tmp_path: Path) -> None:
    app, linhas = _app(tmp_path, ModoDeEscuta.PALAVRA, "")
    app.rodar_audio(vad=VadComRajadas((1, 15)))

    assert app.turnos == []
    assert not any("não entendi" in linha for linha in linhas)
    assert app.escuta is not None and app.escuta.descartados == 1


def test_o_asr_so_roda_quando_o_vad_abre_um_trecho(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.PALAVRA, "jarvis, que horas são")
    app.rodar_audio(vad=VadComRajadas())  # silêncio do começo ao fim

    asr = app._asr
    assert isinstance(asr, AsrEmSequencia)
    assert asr.chamadas == 0, "silêncio virou transcrição"


# --- os outros dois modos e a troca ---------------------------------------------------------
def test_escuta_continua_responde_a_tudo(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.CONTINUA, "que horas são")
    app.rodar_audio(vad=VadComRajadas((1, 15)))
    assert [t.falou for t in app.turnos] == ["que horas são"]


def test_no_atalho_o_dedo_manda_mesmo_com_o_vad_ouvindo(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.ATALHO, "que horas são", pressionado=lambda: False)
    app.rodar_audio(vad=VadComRajadas((1, 40)))
    assert app.turnos == [], "no atalho, VAD sozinho não pode abrir turno"


def test_trocar_de_modo_com_a_sessao_aberta_vale_no_tique_seguinte(tmp_path: Path) -> None:
    """Começa no atalho sem ninguém apertar; no meio, troca para contínua e a fala vira turno."""
    chamadas = 0
    app: Aplicativo

    def dedo() -> bool:
        nonlocal chamadas
        chamadas += 1
        if chamadas == 30:
            assert app.escuta is not None
            app.escuta.trocar(ModoDeEscuta.CONTINUA)  # como a janela faria, de outra thread
        return False

    app, _ = _app(tmp_path, ModoDeEscuta.ATALHO, "liga a luz", pressionado=dedo)
    app.rodar_audio(vad=VadComRajadas((10, 25), (60, 80)))

    # A primeira rajada caiu no atalho (sem dedo, nada); a segunda já na contínua.
    assert [t.falou for t in app.turnos] == ["liga a luz"]
    assert chamadas == 30, "depois da troca o dedo não manda mais"


def test_o_indicador_diz_o_modo_vivo(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.PALAVRA, segundos=1.0)
    app.rodar_audio(vad=VadComRajadas())
    assert ler_estado(app.raiz).modo is Modo.ESCUTA

    (tmp_path / "b").mkdir()
    outro, _ = _app(tmp_path / "b", ModoDeEscuta.ATALHO, segundos=1.0)
    outro.rodar_audio(vad=VadComRajadas())
    assert ler_estado(outro.raiz).modo is Modo.PTT


def test_sem_escuta_injetada_o_laco_monta_da_configuracao(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.configuracao = app.configuracao.com(escuta="palavra", palavra="sexta", atalho="F9")
    escuta = app.modo_de_escuta
    assert escuta.modo is ModoDeEscuta.PALAVRA
    assert escuta.detector.palavra == "sexta"
    assert escuta.atalho == "F9"
    assert app.modo_de_escuta is escuta
