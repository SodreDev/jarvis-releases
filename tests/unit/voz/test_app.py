"""O laço do `jarvis-voz`: modo texto, modo áudio com arquivo, barge-in e indicador honesto.

Sem placa de som aqui: o modo áudio roda com `JARVIS_AUDIO_BACKEND=arquivo`, que é o banco de
teste do F1-01 — WAV entra como se fosse microfone, e o que o Jarvis fala sai num WAV. É o que
dá para provar sem hardware, e é bastante: transcrição, resposta, síntese, epoch, descarte do
que não tocou e o arquivo de estado do microfone.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, Quadro, de_int16
from jarvis.microfone import ler_estado
from jarvis.relogio import RelogioFalso
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo, AplicativoIndisponivel, Turno
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import Hipotese, Onde
from jarvis.voz.teclado import ESPACO, TecladoFalso

TEXTO = "bom dia, Jarvis"


class MotorDeAsrFalso:
    """Devolve sempre a mesma frase: o que se mede aqui é o laço, não o reconhecimento."""

    nome = "asr-falso"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, texto: str = TEXTO) -> None:
        self.texto = texto
        self.chamadas = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        self.chamadas += 1
        return Hipotese(self.texto, 1.0)


class VadQueFala:
    """Fala nos primeiros `quadros_falando` quadros e cala depois: turno determinístico.

    Implementa o `Vad` do F1-05 inteiro (`nome`, `falando`, `ultima_probabilidade`, `ver`),
    porque quem o chama é o `Captura.tick` de verdade, não um laço de teste.
    """

    def __init__(self, quadros_falando: int = 10) -> None:
        self.nome = "vad-de-teste"
        self.quadros_falando = quadros_falando
        self.vistos = 0
        self.falando: bool | None = False
        self.ultima_probabilidade = 0.0

    def ver(self, quadro: Quadro) -> bool | None:
        self.vistos += 1
        agora = self.vistos <= self.quadros_falando
        self.ultima_probabilidade = 1.0 if agora else 0.0
        if agora == self.falando:
            return None
        self.falando = agora
        return agora


def wav_de(caminho: Path, segundos: float = 2.0) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(de_int16([700] * int(TAXA_PADRAO * segundos)))
    return caminho


def aplicativo_de(tmp_path: Path, **extras: object) -> Aplicativo:
    configuracao = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco")
    app = Aplicativo(
        configuracao=configuracao,
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _: None,
        relogio=RelogioFalso(),
        **extras,  # type: ignore[arg-type]
    )
    # O motor entra montado: `abrir` é idempotente e não troca quem já está lá. O alvo
    # destes testes é o **laço**, não o reconhecimento.
    app._asr = MotorDeAsrFalso()
    return app


# --- modo texto ----------------------------------------------------------------------------


def test_modo_texto_responde_e_sintetiza(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    saidas: list[str] = []
    app.escrever_na_tela = saidas.append

    assert app.rodar_texto(["bom dia", "/sair", "nunca chega aqui"]) == 0

    assert len(app.turnos) == 1
    turno = app.turnos[0]
    assert turno.falou == "bom dia"
    assert turno.respondeu == "Você disse: bom dia"
    assert turno.amostras_tocadas > 0, "o TTS não produziu áudio"
    assert any("Jarvis: Você disse: bom dia" in linha for linha in saidas)


def test_status_do_laco_entra_na_fila_de_avisos_sem_virar_fala_direta(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.abrir(com_asr=False)
    assert app._cerebro is not None and app._cerebro.ao_status is not None

    app._cerebro.ao_status("Passo 2 terminou; avaliando o resultado.")

    avisos = app.dados_dos_avisos()["avisos"]
    assert avisos[0]["origem"] == "raciocínio"
    assert avisos[0]["entrega"] == "na_fila"
    assert (app._cerebro.maximo_de_passos, app._cerebro.prazo_do_laco_de_ferramentas_s) == (
        app.configuracao.laco_max_passos,
        app.configuracao.laco_prazo_s,
    )


def test_modo_texto_fala_de_verdade_quando_ha_onde_tocar(tmp_path: Path) -> None:
    # Bug do dono (2026-10-17): a janela cai no modo texto quando o ASR escolhido não roda, e
    # o modo texto sintetizava a resposta e a jogava fora — a voz "nunca saía".
    saida = tmp_path / "fala.wav"
    app = aplicativo_de(
        tmp_path,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_saida=saida,
    )
    app.rodar_texto(["bom dia", "/sair"])

    with wave.open(str(saida), "rb") as arquivo:
        quadros = arquivo.getnframes()
    assert quadros > 0, "o modo texto não entregou áudio ao alto-falante"
    assert app.turnos[0].amostras_tocadas == quadros


def test_modo_texto_sem_placa_diz_o_que_faltou_e_continua(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path, ambiente={"JARVIS_AUDIO_BACKEND": "dispositivo", "CI": "1"})
    saidas: list[str] = []
    app.escrever_na_tela = saidas.append
    app.rodar_texto(["bom dia", "/sair"])

    assert any(linha.strip().startswith("sem som:") for linha in saidas)
    assert app.turnos[0].respondeu == "Você disse: bom dia"


def test_linha_vazia_nao_vira_turno(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.rodar_texto(["", "   ", "/sair"])
    assert app.turnos == []


def test_o_que_esta_ligado_aparece_antes_do_primeiro_turno(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    saidas: list[str] = []
    app.escrever_na_tela = saidas.append
    app.rodar_texto(["/sair"])

    texto = "\n".join(saidas)
    assert "ouvindo com:" in texto and "falando com:" in texto
    assert "local" in texto


def test_nuvem_sem_chave_vira_frase_e_nao_traceback(tmp_path: Path) -> None:
    """Motor desligado e chave ausente chegam ao dono como a mesma coisa: "não deu, e por quê".

    Sem `CI` no ambiente deste aplicativo — é o caso do dono. Nenhum socket é aberto: a chave
    é conferida antes, e é ela que falta.
    """
    app = aplicativo_de(tmp_path)
    app.ambiente = {}
    app.configuracao = app.configuracao.com(
        tts="tts-elevenlabs", voz_elevenlabs="voz-do-dono", nuvem_ligada=("tts-elevenlabs",)
    )

    with pytest.raises(AplicativoIndisponivel) as erro:
        app.rodar_texto(["oi"])
    assert "JARVIS_ELEVENLABS_API_KEY" in str(erro.value)
    assert "export" in str(erro.value)


def test_sob_ci_a_nuvem_de_verdade_nem_e_tentada(tmp_path: Path) -> None:
    """A trava estrutural também chega ao dono como frase, não como traceback."""
    app = aplicativo_de(tmp_path)
    app.ambiente = {"CI": "1", "JARVIS_ELEVENLABS_API_KEY": "sk_chave_de_teste_1234567890"}
    app.configuracao = app.configuracao.com(
        tts="tts-elevenlabs", voz_elevenlabs="voz-do-dono", nuvem_ligada=("tts-elevenlabs",)
    )

    with pytest.raises(AplicativoIndisponivel, match="não é local"):
        app.rodar_texto(["oi"])


def test_nuvem_desligada_recusa_citando_a_configuracao(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.ambiente = {"CI": "1"}
    app.configuracao = app.configuracao.com(tts="tts-elevenlabs", voz_elevenlabs="voz-do-dono")

    with pytest.raises(AplicativoIndisponivel, match="desligado"):
        app.rodar_texto(["oi"])


# --- epoch e barge-in ------------------------------------------------------------------------


def test_interromper_mata_o_epoch_e_para_a_fala(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.abrir()
    epoch = app.epoch

    turno = app.falar("uma resposta bem comprida, com várias palavras para fatiar", epoch=epoch)
    assert not turno.cancelado

    app.interromper("barge_in")
    assert app.epoch == epoch + 1
    morto = app.falar("esta não pode sair", epoch=epoch)
    assert morto.amostras_tocadas == 0, "sintetizou áudio de epoch morto"
    assert morto.cancelado


def test_a_barra_interrompe_no_meio_da_fala(tmp_path: Path) -> None:
    teclado = TecladoFalso(teclas=[ESPACO])
    app = aplicativo_de(tmp_path, teclado=teclado)
    app.abrir()
    epoch = app.epoch

    turno = app.falar(
        "primeira parte da resposta, segunda parte da resposta, terceira parte ainda",
        epoch=epoch,
    )

    assert turno.cancelado, "a barra não interrompeu"
    assert app.epoch == epoch + 1
    assert teclado.lidas == [ESPACO]


def test_o_gerador_cancelado_nao_vira_turno_falado(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.abrir()

    # Desde a ADR-0025 o motor é do cérebro: um motor que encerra sem texto nenhum.
    app._motor = MotorRoteirizado(resposta="", nome="cancelado")
    turno = app.responder("alguma coisa")

    assert turno.respondeu == ""
    assert turno.cancelado
    assert turno.amostras_tocadas == 0


# --- modo áudio com o banco de teste do F1-01 -------------------------------------------------


def test_laco_de_audio_com_arquivo_fecha_um_turno(tmp_path: Path) -> None:
    entrada = wav_de(tmp_path / "entrada.wav")
    saida = tmp_path / "saida.wav"
    app = aplicativo_de(tmp_path)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = entrada
    app.caminho_de_saida = saida

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=10))

    assert app.turnos, "nenhum turno fechou"
    turno = app.turnos[0]
    assert turno.falou == TEXTO
    assert turno.ouvido_ms > 0
    assert turno.respondeu == f"Você disse: {TEXTO}"
    assert saida.exists() and saida.stat().st_size > 44, "nada foi gravado no WAV de saída"


def test_o_indicador_de_microfone_vem_do_que_a_fonte_faz(tmp_path: Path) -> None:
    """F1-13: o indicador é o estado **observado**, e fonte fechada é zero amostra."""
    app = aplicativo_de(tmp_path)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = wav_de(tmp_path / "entrada.wav", segundos=1.5)
    app.caminho_de_saida = tmp_path / "saida.wav"

    app.rodar_audio(limite_de_turnos=1, vad=VadQueFala(quadros_falando=5))

    estado = ler_estado(app.raiz)
    assert not estado.aberta, "o laço terminou com o indicador aceso"
    assert estado.amostras == 0, "indicador apagado tem de ser zero amostra"
    assert estado.amostras_totais > 0, "mas a abertura anterior contou amostra"


def test_sem_dispositivo_a_recusa_oferece_o_modo_texto(tmp_path: Path) -> None:
    app = aplicativo_de(tmp_path)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "dispositivo", "CI": "1"}

    with pytest.raises(AplicativoIndisponivel, match="--texto"):
        app.rodar_audio(limite_de_turnos=1)


def test_resumo_do_turno_diz_o_que_mediu() -> None:
    turno = Turno(falou="a", respondeu="b", ouvido_ms=1000, asr_ms=50, resposta_ms=30, tts_ms=20)
    resumo = turno.resumo()
    assert "ouvi 1000 ms" in resumo and "asr 50 ms" in resumo
    assert (
        Turno(falou="a", respondeu="", cancelado=True, epoch=3)
        .resumo()
        .startswith("  (interrompido no epoch 3")
    )


def test_o_resumo_do_turno_mostra_cada_trecho_desde_o_enviado() -> None:
    from jarvis.voz.app import Turno

    resumo = Turno(
        falou="oi",
        respondeu="Oi.",
        contexto_ms=3,
        primeiro_token_ms=1411,
        resposta_ms=1412,
        primeiro_pedaco_ms=1587,
        tts_ms=1749,
    ).resumo()
    assert resumo == (
        "  [enviado → contexto 3 ms · 1º token 1411 ms · 1ª fronteira 1412 ms · "
        "1º áudio 1587 ms · fala inteira 1749 ms]"
    )


# --- ASR de nuvem desligado: o ouvido não some (bug do dono, 2026-10-17) ------------------------


def test_com_a_groq_desligada_o_laco_ouve_pelo_asr_local_e_diz_numa_linha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.voz import app as modulo_app

    abertos: list[str] = []

    def montar(configuracao: Configuracao, **_: object) -> MotorDeAsrFalso:
        abertos.append(configuracao.asr)
        if configuracao.asr != "asr-whisper-local":
            raise modulo_app.OuvidoIndisponivel(f"{configuracao.asr} está desligado")
        return MotorDeAsrFalso()

    monkeypatch.setattr(modulo_app, "motor_de_asr", montar)
    app = Aplicativo(
        configuracao=Configuracao(
            asr="asr-groq-whisper-large-v3-turbo", tts="tts-parametrico", s2="eco"
        ),
        raiz=tmp_path / "sessao",
        relogio=RelogioFalso(),
    )
    saidas: list[str] = []
    app.escrever_na_tela = saidas.append

    app.abrir()

    assert abertos == ["asr-groq-whisper-large-v3-turbo", "asr-whisper-local"]
    assert app._asr is not None
    avisos = [linha for linha in saidas if "ASR local" in linha]
    assert len(avisos) == 1 and len(avisos[0]) < 120, avisos


class VadQueComecaDepois(VadQueFala):
    """Fala entre os quadros `inicio` e `inicio + quadros_falando`: o VAD que dispara tarde."""

    def __init__(self, inicio: int, quadros_falando: int = 10) -> None:
        super().__init__(quadros_falando)
        self.inicio = inicio

    def ver(self, quadro: Quadro) -> bool | None:
        self.vistos += 1
        agora = self.inicio < self.vistos <= self.inicio + self.quadros_falando
        self.ultima_probabilidade = 1.0 if agora else 0.0
        if agora == self.falando:
            return None
        self.falando = agora
        return agora


def test_o_turno_leva_os_quadros_de_antes_de_o_vad_disparar(tmp_path: Path) -> None:
    # Bug do dono (2026-10-17): "Jarvis, que horas são" chegava ao ASR como "que hoje são": o
    # VAD notava a fala na segunda palavra e o turno começava ali, sem a palavra de ativação.
    app = aplicativo_de(tmp_path)
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}
    app.caminho_de_entrada = wav_de(tmp_path / "entrada.wav", segundos=4.0)
    app.caminho_de_saida = tmp_path / "saida.wav"

    app.rodar_audio(limite_de_turnos=1, vad=VadQueComecaDepois(inicio=30))

    assert app.turnos, "nenhum turno fechou"
    # 20 quadros guardados + 10 de fala + 700 ms de silêncio (35 quadros): sem o guardado, 900 ms.
    assert app.turnos[0].ouvido_ms >= 1200.0, app.turnos[0].ouvido_ms


def test_o_aviso_de_privacidade_sai_uma_vez_e_nao_a_cada_conversa(tmp_path: Path) -> None:
    # Bug do dono (2026-10-17): a conversa voltava a mostrar o texto longo de privacidade da
    # Groq/ElevenLabs a cada sessão; depois da primeira vez ele só vive no painel.
    ja_ditos: set[str] = set()
    sessoes: list[list[str]] = []
    for numero in range(2):
        app = aplicativo_de(tmp_path / str(numero))
        app.configuracao = Configuracao(
            asr="asr-groq-whisper-large-v3-turbo", tts="tts-parametrico", s2="eco"
        )
        app.avisos_dados = ja_ditos
        linhas: list[str] = []
        app.escrever_na_tela = linhas.append
        app.abrir(com_asr=False)
        app._dizer_o_que_esta_ligado()
        sessoes.append(linhas)

    assert any("DESLIGADO" in linha for linha in sessoes[0])
    assert not any("DESLIGADO" in linha for linha in sessoes[1]), sessoes[1]
    assert any("falando com:" in linha for linha in sessoes[1]), "o resumo continua aparecendo"
