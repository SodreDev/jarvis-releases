"""O motor `tts-omnivoice`: interface única, ordem dos lotes, cancelamento e a reserva (ADR-0039).

O trabalhador é o **de verdade** (`tools/omnivoice_trabalhador.py`), num processo à parte, com
um `torch` e um `omnivoice` de mentira (`omnivoice_falso`): o que se prova é o caminho do Jarvis
— subir o processo com ambiente fechado, esperar a carga, mandar um lote por vez na ordem de
chegada, converter 24 kHz em PCM16 16 kHz — e o pedido do dono de que **qualquer** falta ou
falha (sem declaração, sem instalação, sem voz, sem GPU, erro, processo que morre, prazo) caia
no motor padrão sem derrubar nada.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from tools import omnivoice_trabalhador

from jarvis.agentd.tts import MotorParametrico, SintetizadorEmStreaming
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA
from jarvis.voz import app as modulo_app
from jarvis.voz import omnivoice as modulo
from jarvis.voz.app import AplicativoIndisponivel, motor_de_tts
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import MotorDeTts, Onde
from jarvis.voz.omnivoice import (
    ErroDoOmniVoice,
    Instalacao,
    MotorComReserva,
    MotorTtsOmniVoice,
    PesosRegistrados,
    VozDeReferencia,
    _Vez,
    cadastrar_voz,
    motor_omnivoice,
)
from tests.unit.voz.omnivoice_falso import criar_bibliotecas_falsas, criar_lancador

TRABALHADOR = str(Path(omnivoice_trabalhador.__file__))
CHAVE_FALSA = "sk_" + "0123456789abcdef" * 3


def gravar_wav(caminho: Path, segundos: float = 4.0, taxa: int = 24_000) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    quadros = bytearray()
    for i in range(int(segundos * taxa)):
        quadros += int(8000 * math.sin(2 * math.pi * 180 * i / taxa)).to_bytes(
            2, "little", signed=True
        )
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(bytes(quadros))
    return caminho


@dataclass
class Bancada:
    """Tudo o que o motor precisa, em `tmp_path`: casa, vozes, pesos, bibliotecas falsas."""

    raiz: Path
    falsos: Path
    lancador: Path
    pesos: Path
    casa: Path
    vozes: Path
    voz: VozDeReferencia
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def ambiente(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.casa),
            "JARVIS_ELEVENLABS_API_KEY": CHAVE_FALSA,
        }

    def comando(self, dispositivo: str = "cpu", **variaveis: str) -> list[str]:
        configuracao = self.raiz / f"lancador-{len(list(self.raiz.glob('lancador-*.json')))}.json"
        configuracao.write_text(
            json.dumps(
                {
                    "ambiente": {**self.extra, **variaveis},
                    "despejo": str(self.raiz / "ambiente.json"),
                }
            ),
            encoding="utf-8",
        )
        return [
            sys.executable,
            str(self.lancador),
            str(self.falsos),
            str(configuracao),
            TRABALHADOR,
            "--pesos",
            str(self.pesos),
            "--dispositivo",
            dispositivo,
        ]

    def motor(self, *, dispositivo: str = "cpu", **variaveis: str) -> MotorTtsOmniVoice:
        return MotorTtsOmniVoice(
            instalacao=Instalacao(self.raiz / "omnivoice"),
            pesos=PESOS,
            voz_de_referencia=self.voz,
            comando=self.comando(dispositivo, **variaveis),
            ambiente=self.ambiente,
        )


PESOS = PesosRegistrados(
    ids=("exemplo/OmniVoice",),
    licencas=("CC-BY-NC",),
    revisao="r",
    instalar_de="https://x/",
    arquivos=(),
)


@pytest.fixture
def bancada(tmp_path: Path) -> Iterator[Bancada]:
    casa = tmp_path / "casa"
    gravacao = gravar_wav(tmp_path / "gravacoes" / "eu.wav")
    voz = cadastrar_voz(
        "minha",
        audio=str(gravacao),
        texto="Esta é a minha voz, gravada por mim.",
        declaracao="minha",
        agora="2026-10-21",
        ambiente={"HOME": str(casa)},
    )
    pesos = tmp_path / "pesos"
    pesos.mkdir()
    (tmp_path / "omnivoice").mkdir()
    yield Bancada(
        raiz=tmp_path,
        falsos=criar_bibliotecas_falsas(tmp_path / "falsos"),
        lancador=criar_lancador(tmp_path),
        pesos=pesos,
        casa=casa,
        vozes=casa / ".local" / "share" / "jarvis" / "vozes",
        voz=voz,
    )


@pytest.fixture
def motor(bancada: Bancada) -> Iterator[MotorTtsOmniVoice]:
    m = bancada.motor()
    yield m
    m.fechar()


def amostras_de(texto: str) -> int:
    """O falso gera 240 amostras a 24 kHz por caractere; o motor entrega a 16 kHz."""
    return math.floor(240 * len(texto) * 16_000 / 24_000)


# --- o motor ------------------------------------------------------------------------------------


def test_satisfaz_a_interface_unica(motor: MotorTtsOmniVoice) -> None:
    assert isinstance(motor, MotorDeTts)
    assert motor.onde.value == "local" and motor.registrado == "tts-omnivoice"
    assert "CC-BY-NC" in motor.licenca


def test_sintetiza_pcm16_16k_a_partir_dos_24k_do_modelo(motor: MotorTtsOmniVoice) -> None:
    texto = "Bom dia, tudo certo?"
    pcm = motor.sintetizar(texto)
    assert len(pcm) == amostras_de(texto) * BYTES_POR_AMOSTRA
    assert (
        max(abs(int.from_bytes(pcm[i : i + 2], "little", signed=True)) for i in range(0, 400, 2))
        > 0
    )
    assert motor.dispositivo == "cpu" and motor.nome == "omnivoice@cpu+minha"
    assert motor.sinteses == 1 and motor.segundos_de_carga > 0


def test_texto_vazio_nao_sobe_o_trabalhador(motor: MotorTtsOmniVoice) -> None:
    assert motor.sintetizar("   ") == b""
    assert motor.sinteses == 0


def test_o_trabalhador_recebe_ambiente_fechado(bancada: Bancada, motor: MotorTtsOmniVoice) -> None:
    """Chave de API do dono não entra num processo de biblioteca de terceiro."""
    motor.sintetizar("oi")
    variaveis = set(json.loads((bancada.raiz / "ambiente.json").read_text(encoding="utf-8")))
    assert "JARVIS_ELEVENLABS_API_KEY" not in variaveis
    assert {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PATH", "HOME"} <= variaveis
    assert variaveis <= set(modulo.VARIAVEIS_DO_TRABALHADOR) | set(modulo.OFFLINE)


def test_cancelado_antes_nao_sobe_nem_manda_nada(bancada: Bancada) -> None:
    motor = bancada.motor()
    motor.cancelado = lambda: True
    assert motor.sintetizar("não era para falar isto") == b""
    assert motor.descartadas_por_cancelamento == 1 and motor._processo is None


def test_lotes_vao_na_ordem_de_chegada_com_a_janela_de_tres(bancada: Bancada) -> None:
    """O `SintetizadorEmStreaming` põe três ao mesmo tempo; o trabalhador recebe em ordem."""
    ordem = bancada.raiz / "ordem.txt"
    motor = bancada.motor(FALSO_ORDEM=str(ordem), FALSO_DORMIR="0.05")
    trechos = ["um dois três", "quatro cinco seis sete", "oito", "nove dez onze doze treze", "fim"]
    inicio, entrada = 0, []
    for trecho in trechos:
        entrada.append((inicio, trecho))
        inicio += len(trecho) + 1
    try:
        sintetizador = SintetizadorEmStreaming(motor=motor)
        pedacos = list(sintetizador.pedacos_do_stream(entrada))
    finally:
        motor.fechar()
    assert [t.texto for _, t in pedacos] == trechos
    assert [p.n_amostras for p, _ in pedacos] == [amostras_de(t) for t in trechos]
    assert ordem.read_text(encoding="utf-8").splitlines() == trechos


def test_a_vez_atende_na_ordem_de_chegada() -> None:
    vez = _Vez()
    atendidos: list[str] = []
    liberar = threading.Event()

    def primeiro() -> None:
        with vez():
            liberar.wait(5)
            atendidos.append("a")

    def outro(nome: str) -> Callable[[], None]:
        def corpo() -> None:
            with vez():
                atendidos.append(nome)

        return corpo

    linhas = [threading.Thread(target=primeiro)]
    linhas[0].start()
    for esperado, nome in enumerate("bcd", start=2):
        linha = threading.Thread(target=outro(nome))
        linha.start()
        linhas.append(linha)
        prazo = time.monotonic() + 5
        while vez._proxima < esperado and time.monotonic() < prazo:  # tirou a senha
            time.sleep(0.005)
    liberar.set()
    for linha in linhas:
        linha.join(5)
    assert atendidos == ["a", "b", "c", "d"]


def test_erro_de_sintese_e_definitivo_para_o_motor(motor: MotorTtsOmniVoice) -> None:
    with pytest.raises(ErroDoOmniVoice, match="sintese"):
        motor.sintetizar("isto explode")
    with pytest.raises(ErroDoOmniVoice, match="sintese"):
        motor.sintetizar("e este nem é mandado")
    assert motor.sinteses == 0


def test_sem_gpu_vira_erro_do_omnivoice(bancada: Bancada) -> None:
    motor = bancada.motor(dispositivo="cuda")
    with pytest.raises(ErroDoOmniVoice, match="sem_gpu"):
        motor.sintetizar("oi")
    motor.fechar()


def test_trabalhador_que_morre_vira_erro(motor: MotorTtsOmniVoice) -> None:
    with pytest.raises(ErroDoOmniVoice, match="encerrou"):
        motor.sintetizar("e agora ele morre")


def test_prazo_estourado_mata_o_trabalhador(bancada: Bancada) -> None:
    motor = bancada.motor(FALSO_DORMIR="3")
    motor.prazo_por_sintese_s = 0.5
    motor.abrir()
    processo = motor._processo
    assert processo is not None
    with pytest.raises(ErroDoOmniVoice, match="passou de"):
        motor.sintetizar("demora demais")
    assert processo.poll() is not None, "o filho foi encerrado pelo PID que o motor guardou"


def test_protocolo_diferente_recusa(
    motor: MotorTtsOmniVoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo, "PROTOCOLO", 99)
    with pytest.raises(ErroDoOmniVoice, match="outro protocolo"):
        motor.sintetizar("oi")


def test_fechar_encerra_e_o_motor_sobe_de_novo_quando_o_laco_volta(
    motor: MotorTtsOmniVoice,
) -> None:
    motor.sintetizar("primeira")
    processo = motor._processo
    assert processo is not None
    motor.fechar()
    assert processo.wait(timeout=10) == 0, "pediu para sair e ele saiu"
    assert len(motor.sintetizar("segunda")) == amostras_de("segunda") * BYTES_POR_AMOSTRA


def test_carga_que_falha_vira_erro(bancada: Bancada) -> None:
    motor = bancada.motor(FALSO_CARGA="quebrada")
    with pytest.raises(ErroDoOmniVoice, match="carga"):
        motor.sintetizar("oi")
    motor.fechar()


# --- a reserva ----------------------------------------------------------------------------------


@dataclass
class MotorQueFalha:
    nome: str = "principal@teste"
    voz: str = "minha"
    licenca: str = "CC-BY-NC"
    onde: Onde = Onde.LOCAL
    falhar_a_partir_de: int = 1
    chamadas: int = 0
    fechado: bool = False

    def sintetizar(self, texto: str) -> bytes:
        self.chamadas += 1
        if self.chamadas >= self.falhar_a_partir_de:
            raise ErroDoOmniVoice("sem_gpu: CUDA out of memory")
        return b"\x01\x00" * 10

    def fechar(self) -> None:
        self.fechado = True


def test_a_reserva_assume_na_primeira_falha_e_a_sessao_fica_nela() -> None:
    principal = MotorQueFalha(falhar_a_partir_de=2)
    motor = MotorComReserva(principal=principal, fabricar_reserva=MotorParametrico)
    assert motor.sintetizar("primeira") == b"\x01\x00" * 10
    segunda = motor.sintetizar("segunda frase")
    assert segunda and segunda != b"\x01\x00" * 10, "falou com a reserva, sem exceção"
    motor.sintetizar("terceira")
    assert principal.chamadas == 2 and principal.fechado
    assert motor.na_reserva and motor.nome == "parametrico@1"
    assert "CUDA out of memory" in motor.motivo_da_reserva
    assert "caiu" in motor.observacao


def test_falhas_simultaneas_fabricam_a_reserva_uma_vez_so() -> None:
    fabricadas: list[MotorParametrico] = []

    def fabricar() -> MotorParametrico:
        time.sleep(0.05)
        fabricadas.append(MotorParametrico())
        return fabricadas[-1]

    motor = MotorComReserva(principal=MotorQueFalha(), fabricar_reserva=fabricar)
    linhas = [threading.Thread(target=motor.sintetizar, args=("oi",)) for _ in range(3)]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join(5)
    assert len(fabricadas) == 1


def test_ja_na_reserva_diz_o_motivo() -> None:
    motor = MotorComReserva.ja_na_reserva(MotorParametrico, "não está instalado")
    assert motor.na_reserva and motor.nome == "parametrico@1"
    assert motor.observacao.endswith("não está instalado")


# --- `tts = "tts-omnivoice"`: o que a configuração monta ------------------------------------


def test_sem_a_declaracao_do_dono_fala_o_padrao(bancada: Bancada) -> None:
    motor = motor_omnivoice(
        aceito=False,
        voz="minha",
        reserva=MotorParametrico,
        pasta_das_vozes=bancada.vozes,
        comando=bancada.comando(),
    )
    assert motor.na_reserva and "omnivoice_uso_pessoal = true" in motor.motivo_da_reserva
    assert not (bancada.raiz / "ambiente.json").exists(), "nenhum trabalhador subiu"


def test_sem_instalacao_fala_o_padrao(bancada: Bancada) -> None:
    motor = motor_omnivoice(
        aceito=True,
        voz="minha",
        reserva=MotorParametrico,
        instalacao=Instalacao(bancada.raiz / "nao-instalado"),
        pasta_das_vozes=bancada.vozes,
    )
    assert motor.na_reserva and "não está instalado" in motor.motivo_da_reserva


@pytest.mark.parametrize(
    ("voz", "motivo"), [("", "falta escolher"), ("outra", "não está cadastrada")]
)
def test_sem_voz_cadastrada_fala_o_padrao(bancada: Bancada, voz: str, motivo: str) -> None:
    motor = motor_omnivoice(
        aceito=True,
        voz=voz,
        reserva=MotorParametrico,
        pasta_das_vozes=bancada.vozes,
        comando=bancada.comando(),
    )
    assert motor.na_reserva and motivo in motor.motivo_da_reserva


def test_com_tudo_fala_com_a_voz_do_dono(bancada: Bancada) -> None:
    motor = motor_omnivoice(
        aceito=True,
        voz="minha",
        reserva=MotorParametrico,
        pasta_das_vozes=bancada.vozes,
        comando=bancada.comando(),
        ambiente=bancada.ambiente,
    )
    try:
        assert not motor.na_reserva
        assert len(motor.sintetizar("Olá")) == amostras_de("Olá") * BYTES_POR_AMOSTRA
        assert motor.nome == "omnivoice@cpu+minha"
        assert "uso pessoal" in motor.observacao and "a voz é minha" in motor.observacao
    finally:
        motor.fechar()


def test_gpu_que_falta_no_meio_cai_no_padrao_sem_excecao(bancada: Bancada) -> None:
    motor = motor_omnivoice(
        aceito=True,
        voz="minha",
        reserva=MotorParametrico,
        pasta_das_vozes=bancada.vozes,
        comando=bancada.comando(dispositivo="cuda"),
        ambiente=bancada.ambiente,
    )
    antes = motor.na_reserva
    assert motor.sintetizar("ainda fala")  # o padrão falou
    depois = motor.na_reserva
    assert not antes and depois and "sem_gpu" in motor.motivo_da_reserva


def test_motor_de_tts_do_app_cai_no_padrao_do_produto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O padrão é o `tts-piper-epitran`: sem a voz dele baixada, a frase é a do piper."""
    configuracao = Configuracao(tts="tts-omnivoice")
    monkeypatch.setattr(modulo_app, "PASTA_DE_VOZES", tmp_path / "sem-vozes")
    with pytest.raises(AplicativoIndisponivel, match=r"pt_BR-faber-medium|falta a biblioteca"):
        motor_de_tts(
            configuracao, raiz=tmp_path, cancelado=lambda: False, ambiente={"HOME": str(tmp_path)}
        )
    monkeypatch.setattr(modulo_app, "TTS_PADRAO", "tts-parametrico")
    motor = motor_de_tts(
        configuracao, raiz=tmp_path, cancelado=lambda: False, ambiente={"HOME": str(tmp_path)}
    )
    assert isinstance(motor, MotorComReserva) and motor.na_reserva
    assert motor.nome == "parametrico@1" and "omnivoice_uso_pessoal" in motor.observacao


def test_cancelamento_no_meio_da_resposta_descarta_o_resto(bancada: Bancada) -> None:
    cancelado = threading.Event()
    motor = bancada.motor(FALSO_DORMIR="0.05")
    motor.cancelado = cancelado.is_set
    trechos = [(0, "primeiro lote"), (14, "segundo lote"), (27, "terceiro lote"), (41, "quarto")]
    sintetizador = SintetizadorEmStreaming(motor=motor, cancelado=cancelado.is_set)
    entregues = []
    try:
        for _pedaco, trecho in sintetizador.pedacos_do_stream(trechos):
            entregues.append(trecho.texto)
            cancelado.set()
    finally:
        motor.fechar()
    assert entregues == ["primeiro lote"]
