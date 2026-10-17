"""A caixa de correio entre a janela e o laço (ADR-0019), sem Qt e sem placa de som.

O que estes testes cobram é o contrato que a janela depende: digitar vira turno, segurar e
soltar fecham um turno, parar fecha a fonte pelo caminho normal (indicador apagado), e falha
de áudio **não** quebra a janela — ela cai para o texto dizendo o que faltou.

O áudio é o banco de teste do F1-01 (`JARVIS_AUDIO_BACKEND=arquivo`), com relógio de verdade,
porque o que está em jogo aqui é concorrência entre duas threads, e relógio falso a esconderia.
"""

from __future__ import annotations

import time
import wave
from collections.abc import Callable
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.gui.nucleo import SessaoDeVoz, TecladoDaJanela
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado
from jarvis.voz.teclado import ESPACO
from tests.unit.voz.test_app import MotorDeAsrFalso

LIMITE_S = 20.0


def esperar_ate(condicao: Callable[[], bool], limite: float = LIMITE_S) -> bool:
    """Espera uma condição de outra thread. Sem `sleep` cego: ou acontece, ou o teste cai."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.02)
    return False


def wav_longo(caminho: Path, segundos: float = 30.0) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(de_int16([400] * int(TAXA_PADRAO * segundos)))
    return caminho


@pytest.fixture
def sessao(tmp_path: Path) -> SessaoDeVoz:
    return SessaoDeVoz(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
    )


def aplicativo_de_teste(sessao: SessaoDeVoz, tmp_path: Path, **extras: object) -> Aplicativo:
    app = Aplicativo(
        configuracao=sessao.configuracao,
        raiz=sessao.raiz,
        ambiente=sessao.ambiente,
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
        **extras,  # type: ignore[arg-type]
    )
    app._asr = MotorDeAsrFalso()
    return app


def test_digitar_vira_turno_e_parar_encerra(sessao: SessaoDeVoz, tmp_path: Path) -> None:
    linhas: list[str] = []
    estados: list[Estado] = []
    sessao.ao_linha = linhas.append
    sessao.ao_estado = estados.append

    sessao.iniciar(aplicativo_de_teste(sessao, tmp_path))
    assert esperar_ate(lambda: Estado.OUVINDO in estados), "a sessão não chegou a ouvir"
    sessao.digitar("bom dia")

    assert esperar_ate(lambda: any("Jarvis: Você disse: bom dia" in linha for linha in linhas))
    sessao.parar()
    assert sessao.esperar(), "a thread não terminou depois do parar"
    assert not sessao.viva
    assert estados[-1] is Estado.PARADO


def test_parar_fecha_a_fonte_e_apaga_o_indicador(sessao: SessaoDeVoz, tmp_path: Path) -> None:
    """F1-13: terminar pela porta normal apaga o indicador; matar a thread o deixaria aceso."""
    sessao.iniciar(aplicativo_de_teste(sessao, tmp_path))
    assert esperar_ate(lambda: sessao.estado_do_microfone().aberta), "a fonte não abriu"

    sessao.parar()

    assert sessao.esperar()
    estado = sessao.estado_do_microfone()
    assert not estado.aberta
    assert estado.amostras == 0
    assert estado.amostras_totais > 0


def test_segurar_e_soltar_fecham_um_turno(sessao: SessaoDeVoz, tmp_path: Path) -> None:
    linhas: list[str] = []
    sessao.ao_linha = linhas.append
    app = aplicativo_de_teste(sessao, tmp_path)

    sessao.iniciar(app)
    assert esperar_ate(lambda: sessao.estado_do_microfone().aberta)
    sessao.segurar()
    time.sleep(0.2)  # ~10 quadros de 20 ms com o dedo no botão
    sessao.soltar()

    assert esperar_ate(lambda: any(linha.startswith("Você: ") for linha in linhas)), linhas
    sessao.parar()
    assert sessao.esperar()
    assert app.turnos and app.turnos[0].ouvido_ms > 0


def test_sem_audio_a_sessao_cai_para_o_texto_dizendo_o_que_faltou(
    sessao: SessaoDeVoz, tmp_path: Path
) -> None:
    linhas: list[str] = []
    sessao.ao_linha = linhas.append
    sessao.ambiente = {"JARVIS_AUDIO_BACKEND": "dispositivo", "CI": "1"}
    app = Aplicativo(configuracao=sessao.configuracao, raiz=sessao.raiz, ambiente=sessao.ambiente)
    app._asr = MotorDeAsrFalso()

    sessao.iniciar(app)

    assert esperar_ate(lambda: any("sem áudio:" in linha for linha in linhas)), linhas
    assert sessao.modo_texto, "caiu para o texto e não contou para a janela"
    sessao.digitar("oi")
    assert esperar_ate(lambda: any("Jarvis: Você disse: oi" in linha for linha in linhas))
    sessao.parar()
    assert sessao.esperar()


def test_falha_inesperada_chega_como_frase_e_nao_derruba_o_processo(
    sessao: SessaoDeVoz, tmp_path: Path
) -> None:
    fins: list[str] = []
    sessao.ao_terminar = fins.append

    class AplicativoQueExplode(Aplicativo):
        def rodar_audio(
            self, *, limite_de_turnos: int | None = None, vad: object | None = None
        ) -> int:
            raise RuntimeError("a placa de som pegou fogo")

    sessao.iniciar(
        AplicativoQueExplode(
            configuracao=sessao.configuracao, raiz=sessao.raiz, ambiente=sessao.ambiente
        )
    )

    assert esperar_ate(lambda: bool(fins))
    assert "RuntimeError: a placa de som pegou fogo" in fins[0]
    assert sessao.esperar()


def test_o_botao_de_falar_interrompe_pelo_mesmo_caminho_da_barra(tmp_path: Path) -> None:
    """Um jeito só de cancelar: o botão da janela vira a mesma tecla que o terminal manda."""
    teclado = TecladoDaJanela()
    sessao = SessaoDeVoz(configuracao=Configuracao(), raiz=tmp_path / "sessao")
    sessao.teclado = teclado

    sessao.segurar()
    sessao.interromper()

    assert teclado.tecla() == ESPACO
    assert teclado.tecla() == ESPACO
    assert teclado.tecla() is None


def test_a_sessao_liga_o_dedo_sempre_e_entrega_a_escuta_viva(tmp_path: Path) -> None:
    """ADR-0021: o modo troca com a sessão aberta, então a porta do dedo não pode depender do
    modo da montagem — e a escuta que a janela troca tem de ser a **mesma** que o laço lê."""
    from jarvis.voz.escuta import Escuta, ModoDeEscuta

    escuta = Escuta(modo=ModoDeEscuta.CONTINUA)
    sessao = SessaoDeVoz(
        configuracao=Configuracao(
            asr="asr-whisper-local", tts="tts-parametrico", s2="eco", escuta="vad"
        ),
        raiz=tmp_path / "sessao",
        escuta=escuta,
    )
    app = sessao._ligar(Aplicativo(configuracao=sessao.configuracao, raiz=sessao.raiz))
    assert app.pressionado is not None, "no modo contínuo a porta do dedo sumiu"
    assert app.escuta is escuta
    escuta.trocar(ModoDeEscuta.ATALHO)
    assert app.modo_de_escuta.modo is ModoDeEscuta.ATALHO


def test_asr_da_nuvem_desligado_diz_que_nao_ouve_e_o_caminho(
    sessao: SessaoDeVoz, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug do dono (2026-10-16): ASR = Groq fora de `nuvem_ligada` caía calado no texto ("sem
    áudio"). Agora a frase diz que o ouvido é o problema e como resolver, e o card guarda.

    Desde 2026-10-17 o laço tenta o ASR local antes de desistir; aqui nenhum ASR abre (nem o
    local), que é o caso em que a frase continua valendo."""
    from jarvis.voz import app as modulo_app

    def nenhum(configuracao: Configuracao, **_: object) -> None:
        raise modulo_app.OuvidoIndisponivel(
            f"o ASR escolhido ({configuracao.asr}) não roda: motor desligado"
        )

    monkeypatch.setattr(modulo_app, "motor_de_asr", nenhum)
    linhas: list[str] = []
    sessao.ao_linha = linhas.append
    sessao.configuracao = Configuracao(
        asr="asr-groq-whisper-large-v3-turbo", tts="tts-parametrico", s2="eco"
    )
    sessao.ambiente = {"JARVIS_AUDIO_BACKEND": "sintetico", "CI": "1"}

    sessao.iniciar()

    assert esperar_ate(lambda: any("não estou ouvindo" in linha for linha in linhas)), linhas
    frase = next(linha for linha in linhas if "não estou ouvindo" in linha)
    assert "asr-groq-whisper-large-v3-turbo" in frase and "desligado" in frase
    assert "asr-whisper-local" in frase
    assert sessao.modo_texto
    assert any("ouvir" in a["origem"] for a in sessao.dados_dos_avisos()["avisos"])
    sessao.parar()
    assert sessao.esperar()
