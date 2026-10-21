"""O que falta para um motor rodar **agora** — uma resposta só, para o laço e para a janela.

Bug do dono (2026-10-16): a janela dizia "ligado"/"desligado" a partir do interruptor da nuvem,
enquanto o laço recusava o motor por outro motivo (chave fora do ambiente, voz não baixada,
biblioteca ausente) — e, no caso do ASR, caía calado no modo texto. Agora o laço chama
`o_que_falta` antes de montar o motor e levanta com a mesma frase que a janela mostra ao lado do
provedor: o estado exibido sai da mesma fonte que o laço usa.

Nada aqui carrega modelo nem abre rede: é registro (`exigir_motor`), presença de chave
(`Chave.presente`, ambiente e chaveiro, sem ler valor para fora), `find_spec` das bibliotecas e
existência de arquivo.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from jarvis.voz.chaves import Chave
from jarvis.voz.config import TTS_OMNIVOICE, Configuracao
from jarvis.voz.registro import MotorRecusado, exigir_motor, motor_registrado

PASTA_DE_VOZES: Final = Path.home() / ".cache" / "jarvis" / "vozes"
BIBLIOTECAS: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "tts-piper-epitran": (("epitran", "voz"), ("onnxruntime", "voz")),
    "asr-whisper-local": (("faster_whisper", "asr"),),
}


def caminho_da_voz(voz: str, pasta: Path = PASTA_DE_VOZES) -> Path:
    return pasta / voz / f"{voz}.onnx"


def o_que_falta(
    motor_id: str,
    configuracao: Configuracao,
    *,
    ambiente: Mapping[str, str] | None = None,
    pasta_de_vozes: Path = PASTA_DE_VOZES,
) -> str:
    """Vazio quando dá para rodar; senão a frase, que já diz o que fazer."""
    registro = motor_registrado(motor_id)
    if registro is None:
        return f"{motor_id} não está no registro de motores"
    try:
        exigir_motor(
            motor_id,
            nuvem_ligada=configuracao.nuvem_ligada,
            sem_termos_aceitos=configuracao.nuvem_sem_termos,
            uso_pessoal_aceito=configuracao.uso_pessoal_aceito,
        )
    except MotorRecusado as erro:
        if "está desligado" in str(erro):
            return (
                f"está desligado: nada sai daqui. Para usar, ligue {motor_id} em Configuração "
                '("li o aviso — ligar") e salve, ou escolha um motor local'
            )
        return str(erro)
    if registro.variavel_da_chave and not Chave.presente(
        registro.variavel_da_chave, ambiente=ambiente
    ):
        return (
            f"falta a chave {registro.variavel_da_chave} (não está no ambiente nem no chaveiro do "
            "sistema): guarde em Configuração → Chaves de API ou exporte no shell"
        )
    if motor_id == "tts-elevenlabs" and not configuracao.voz_elevenlabs:
        return 'falta escolher a voz da ElevenLabs: Configuração → "buscar vozes da conta"'
    if motor_id == "asr-oraculo":
        return "o oráculo não transcreve voz de verdade (devolve o texto do corpus de teste)"
    if motor_id == TTS_OMNIVOICE:
        # O laço não para por isto: cai no motor padrão (ADR-0039). A frase é para a janela e o
        # diagnóstico dizerem por quê.
        from jarvis.voz.omnivoice import o_que_falta_ao_omnivoice

        return o_que_falta_ao_omnivoice(configuracao.voz_omnivoice, ambiente=ambiente)
    for modulo, grupo in BIBLIOTECAS.get(motor_id, ()):
        if importlib.util.find_spec(modulo) is None:
            return f"falta a biblioteca {modulo}: `uv sync --group {grupo}`"
    if motor_id == "tts-piper-epitran":
        voz = caminho_da_voz(configuracao.voz, pasta_de_vozes)
        if not voz.exists():
            return (
                f"falta baixar a voz {configuracao.voz}: botão na aba Diagnóstico ou "
                "`jarvis-voz --baixar-voz`"
            )
    return ""
