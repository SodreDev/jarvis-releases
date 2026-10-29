"""O motor do Edge: implementado, barrado por padrão, e honesto sobre o que ele é.

Nenhum teste aqui fala com a Microsoft: o trecho que toca a rede é uma função injetada
(`fluxo`), e é ela que os testes substituem. O que se prova é o portão, o aviso, o
cancelamento, a decodificação e as duas licenças que este caminho custa.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.rede import SondaInjetada, ler_degradacao
from jarvis.voz.edge import (
    REGISTRADO,
    DecodificadorAusente,
    MotorTtsEdge,
    licenca_do_ffmpeg,
    mp3_para_pcm16,
)
from jarvis.voz.interface import MotorDeTts, Onde
from jarvis.voz.registro import MotorRecusado, motor_registrado

TEXTO = "Quer que eu avise o João agora?"
sem_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg não está nesta máquina"
)


def fluxo_falso(pedacos: int = 3, tamanho: int = 64) -> object:
    def fluxo(texto: str, voz: str, prazo: float) -> Iterator[bytes]:
        for indice in range(pedacos):
            yield bytes([indice % 256]) * tamanho

    return fluxo


def motor(tmp_path: Path, **extras: object) -> MotorTtsEdge:
    padroes: dict[str, object] = {
        "raiz": tmp_path,
        "nuvem_ligada": [REGISTRADO],
        "sem_termos_aceitos": [REGISTRADO],
        "fluxo": fluxo_falso(),
        "decodificar": lambda mp3: b"\x00\x01" * (len(mp3) // 2),
    }
    padroes.update(extras)
    return MotorTtsEdge(**padroes)  # type: ignore[arg-type]


# --- o portão: barrado por falta de termos ------------------------------------------------


def test_barrado_por_padrao_mesmo_com_a_nuvem_ligada(tmp_path: Path) -> None:
    """Ligar nuvem não basta: os quatro campos de termo estão vazios, e vazio barra."""
    with pytest.raises(MotorRecusado) as erro:
        MotorTtsEdge(raiz=tmp_path, nuvem_ligada=[REGISTRADO]).abrir()
    assert "não verificado" in str(erro.value)
    assert "uso_comercial" in str(erro.value)


def test_so_a_aceitacao_explicita_do_dono_abre(tmp_path: Path) -> None:
    aberto = motor(tmp_path).abrir()
    assert aberto.id == REGISTRADO
    assert aberto.onde is Onde.NUVEM


def test_aceitar_outro_motor_nao_abre_este(tmp_path: Path) -> None:
    with pytest.raises(MotorRecusado):
        motor(tmp_path, sem_termos_aceitos=["tts-elevenlabs"]).abrir()


def test_aceitar_sem_termos_nao_dispensa_procedencia() -> None:
    """Fonte e data nunca são dispensáveis: sem elas não dá para saber o que se aceitou."""
    from jarvis.voz.registro import exigir_motor

    for motor_do_registro in (motor_registrado(REGISTRADO),):
        assert motor_do_registro is not None
        assert motor_do_registro.fonte and motor_do_registro.data_de_acesso
    with pytest.raises(MotorRecusado):
        exigir_motor("motor-que-nao-existe", sem_termos_aceitos=["motor-que-nao-existe"])


# --- o aviso: isto não é local ------------------------------------------------------------


def test_o_aviso_abre_dizendo_que_nao_ha_termos(tmp_path: Path) -> None:
    aviso = motor(tmp_path).aviso
    assert aviso.startswith("ATENÇÃO: este serviço não publica termos")
    assert "**não verificado**" in aviso


def test_o_aviso_diz_que_o_texto_vai_para_a_microsoft(tmp_path: Path) -> None:
    """O dono acreditava que o Edge fosse local. A frase existe para desfazer isso."""
    aviso = motor(tmp_path).aviso
    assert "sai desta máquina para Microsoft" in aviso
    assert "o texto que o Jarvis vai falar" in aviso


def test_o_registro_explica_as_duas_barreiras() -> None:
    registro = motor_registrado(REGISTRADO)
    assert registro is not None
    assert registro.licenca_do_cliente == "LGPL-3.0"
    assert registro.estado == "extra_opcional"
    assert "não é local" in registro.nota.lower() or "Não é local" in registro.nota


# --- síntese, cancelamento e degradação ---------------------------------------------------


def test_satisfaz_a_interface_unica(tmp_path: Path) -> None:
    assert isinstance(motor(tmp_path), MotorDeTts)


def test_sintetiza_juntando_os_pedacos_e_decodificando(tmp_path: Path) -> None:
    edge = motor(tmp_path)
    amostras = edge.sintetizar(TEXTO)

    assert amostras == b"\x00\x01" * 96  # 3 pedaços de 64 bytes, decodificados
    assert edge.caracteres_enviados == len(TEXTO)


def test_epoch_morto_nao_manda_o_texto(tmp_path: Path) -> None:
    pedidos: list[str] = []

    def fluxo(texto: str, voz: str, prazo: float) -> Iterator[bytes]:
        pedidos.append(texto)
        yield b"\x00" * 64

    edge = motor(tmp_path, fluxo=fluxo, cancelado=lambda: True)
    assert edge.sintetizar(TEXTO) == b""
    assert pedidos == []
    assert edge.caracteres_enviados == 0


def test_cancelamento_no_meio_descarta_o_que_chegou(tmp_path: Path) -> None:
    chamadas = {"n": 0}

    def cancelado() -> bool:
        chamadas["n"] += 1
        return chamadas["n"] > 2

    decodificou: list[bytes] = []

    def decodificar(mp3: bytes) -> bytes:
        decodificou.append(mp3)
        return b"\x00\x01"

    edge = motor(
        tmp_path, fluxo=fluxo_falso(pedacos=8), cancelado=cancelado, decodificar=decodificar
    )

    assert edge.sintetizar(TEXTO) == b""
    assert decodificou == [], "pedaço em voo não pode nem chegar ao decodificador"
    assert edge.descartadas_por_cancelamento == 1
    assert edge.bytes_descartados > 0


def test_servico_mudo_nao_vira_audio(tmp_path: Path) -> None:
    edge = motor(tmp_path, fluxo=fluxo_falso(pedacos=0))
    assert edge.sintetizar(TEXTO) == b""


def test_sonda_apagada_declara_degradacao(tmp_path: Path) -> None:
    edge = motor(tmp_path, sonda=SondaInjetada(ligada=False))
    assert edge.sintetizar(TEXTO) == b""
    assert ler_degradacao(tmp_path).ativa


def test_o_que_caiu_numa_sessao_nao_cala_a_fala_de_mesmo_numero_da_seguinte(
    tmp_path: Path,
) -> None:
    """Os descartados da regra 5 ficam no disco entre sessões (2026-10-29): a 1ª fala de hoje
    não pode ser recusada porque a 1ª de ontem caiu."""
    assert motor(tmp_path, sonda=SondaInjetada(ligada=False)).sintetizar(TEXTO) == b""
    assert ler_degradacao(tmp_path).descartados
    assert motor(tmp_path).sintetizar(TEXTO) != b""


# --- as duas licenças que este caminho custa ----------------------------------------------


@sem_ffmpeg
def test_a_licenca_do_decodificador_e_lida_do_build_local() -> None:
    """O registro não sabe qual build o dono tem: quem diz é o `-version` da máquina."""
    licenca = licenca_do_ffmpeg()
    assert licenca.startswith(("GPL", "LGPL"))
    assert "build local" in licenca


@sem_ffmpeg
def test_decodifica_mp3_de_verdade_para_pcm16(tmp_path: Path) -> None:
    """Um MP3 gerado na hora pelo próprio ffmpeg, para o teste não versionar áudio."""
    mp3 = tmp_path / "tom.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-ac",
            "1",
            "-ar",
            "24000",
            str(mp3),
        ],
        check=True,
        timeout=30,
    )

    amostras = mp3_para_pcm16(mp3.read_bytes())

    assert len(amostras) % BYTES_POR_AMOSTRA == 0
    esperado = TAXA_PADRAO * 0.5 * BYTES_POR_AMOSTRA
    assert esperado * 0.8 < len(amostras) < esperado * 1.2, "duração fora do esperado"
    assert any(amostras), "decodificou silêncio"


def test_sem_decodificador_a_recusa_diz_o_que_fazer() -> None:
    with pytest.raises(DecodificadorAusente, match="piper"):
        mp3_para_pcm16(b"qualquer coisa", executavel="ffmpeg-que-nao-existe-aqui")
