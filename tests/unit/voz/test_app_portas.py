"""As três portas que a janela usa (ADR-0019): estado, PTT de verdade e texto no mesmo laço.

O que está em jogo aqui não é a tela — é a promessa de que a tela **não** reimplementa o laço.
Se estas três portas fizerem o que prometem, a janela vira apresentação; se não fizerem,
alguém vai escrever um segundo laço na interface, e a primeira coisa que um segundo laço perde
é o cancelamento (F1-11).

Sem placa de som: tudo roda com `JARVIS_AUDIO_BACKEND=arquivo`, o banco de teste do F1-01.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from jarvis.voz.app import Aplicativo
from jarvis.voz.estado import Estado
from tests.unit.voz.test_app import VadQueFala, aplicativo_de, wav_de


class VadMudo(VadQueFala):
    """Nunca acusa fala: com ele, só o PTT pode fechar um turno."""

    def __init__(self) -> None:
        super().__init__(quadros_falando=0)


def _app_de_audio(tmp_path: Path, **extras: object) -> Aplicativo:
    app = aplicativo_de(tmp_path, **extras)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = wav_de(tmp_path / "entrada.wav", segundos=3.0)
    app.caminho_de_saida = tmp_path / "saida.wav"
    return app


# --- porta 1: o laço diz o que está fazendo ------------------------------------------------


def test_o_laco_anuncia_ouvindo_pensando_falando_e_parado(tmp_path: Path) -> None:
    vistos: list[Estado] = []
    app = _app_de_audio(tmp_path, ao_mudar_estado=vistos.append)

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5))

    assert vistos[0] is Estado.OUVINDO, "a fonte abriu e ninguém avisou"
    assert Estado.PENSANDO in vistos and Estado.FALANDO in vistos
    assert vistos.index(Estado.PENSANDO) < vistos.index(Estado.FALANDO)
    assert vistos[-1] is Estado.PARADO, "o laço terminou e a tela ficaria mostrando outra coisa"
    assert app.estado is Estado.PARADO


def test_o_estado_so_e_anunciado_quando_muda(tmp_path: Path) -> None:
    """Tela que recebe o mesmo estado cem vezes por segundo é tela que repinta à toa."""
    vistos: list[Estado] = []
    app = _app_de_audio(tmp_path, ao_mudar_estado=vistos.append)

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5))

    assert all(a is not b for a, b in pairwise(vistos))


def test_sem_observador_o_laco_e_o_de_antes(tmp_path: Path) -> None:
    app = _app_de_audio(tmp_path)

    assert app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5)) == 0
    assert app.ao_mudar_estado is None
    assert app.estado is Estado.PARADO
    assert app.turnos and app.turnos[0].respondeu


def test_interromper_tira_a_tela_de_falando(tmp_path: Path) -> None:
    """Depois do barge-in a tela não pode continuar dizendo "falando"."""
    vistos: list[Estado] = []
    app = aplicativo_de(tmp_path, ao_mudar_estado=vistos.append)
    app.abrir(com_asr=False)

    app.falar("uma frase inteira para interromper", epoch=app.epoch)
    durante = app.estado
    app.interromper("tecla")
    depois = app.estado

    assert durante is Estado.FALANDO
    assert depois is Estado.PARADO
    assert vistos[-1] is Estado.PARADO


# --- porta 2: o PTT de verdade -------------------------------------------------------------


def test_soltar_o_botao_fecha_o_turno_sem_esperar_silencio(tmp_path: Path) -> None:
    """No PTT o fim do turno é o dedo saindo do botão — o VAD aqui nunca acusa fala."""
    apertos = iter([True] * 5 + [False] * 200)
    app = _app_de_audio(tmp_path, pressionado=lambda: next(apertos, False))

    app.rodar_audio(limite_de_turnos=1, vad=VadMudo())

    assert len(app.turnos) == 1, "o botão foi solto e o turno não fechou"
    turno = app.turnos[0]
    # 5 quadros de 20 ms apertado + o quadro em que soltou: ~120 ms, muito abaixo dos 700 ms
    # que o modo VAD espera de silêncio.
    assert 80.0 <= turno.ouvido_ms <= 200.0, f"ouviu {turno.ouvido_ms} ms"


def test_sem_apertar_o_botao_nenhum_turno_nasce(tmp_path: Path) -> None:
    app = _app_de_audio(tmp_path, pressionado=lambda: False)

    app.rodar_audio(limite_de_turnos=1, vad=VadMudo())

    assert app.turnos == [], "nasceu turno sem o dono apertar nada"


def test_no_modo_vad_quem_manda_continua_sendo_o_vad(tmp_path: Path) -> None:
    """Sem `pressionado`, o fechamento é o do silêncio — o PTT não muda o laço de quem não o usa."""
    app = _app_de_audio(tmp_path)

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5))

    assert len(app.turnos) == 1
    assert app.turnos[0].ouvido_ms >= 700.0, "fechou antes dos 700 ms de silêncio"


# --- porta 3: o texto digitado entra no mesmo laço -----------------------------------------


def test_linha_digitada_vira_turno_no_laco_de_audio(tmp_path: Path) -> None:
    linhas = iter(["que horas são"])
    app = _app_de_audio(tmp_path, texto_digitado=lambda: next(linhas, None))

    app.rodar_audio(limite_de_turnos=1, vad=VadMudo())

    assert len(app.turnos) == 1
    turno = app.turnos[0]
    assert turno.falou == "que horas são"
    assert turno.respondeu == "Você disse: que horas são"
    assert turno.amostras_tocadas > 0, "o texto digitado não virou voz"
    assert turno.epoch == app.epoch, "o turno digitado nasceu fora do epoch do laço"


def test_fila_de_texto_vazia_nao_atrapalha_o_microfone(tmp_path: Path) -> None:
    app = _app_de_audio(tmp_path, texto_digitado=lambda: None)

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5))

    assert len(app.turnos) == 1
    assert app.turnos[0].falou == "bom dia, Jarvis"
