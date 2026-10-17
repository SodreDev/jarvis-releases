"""Escolha do backend de áudio em um lugar só (cartão F1-01).

`JARVIS_AUDIO_BACKEND=arquivo|sintetico|dispositivo`. Quem monta a cascata chama estas duas
funções e não precisa saber qual implementação veio — é o que deixa o mesmo teste rodar com
WAV do corpus, com sinal gerado e (na máquina do dono) com a placa de som.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from jarvis.audio_io.ambiente import Backend, backend_escolhido
from jarvis.audio_io.fontes import (
    FonteDeArquivo,
    FonteDeAudio,
    FonteDeDispositivo,
    FonteSintetica,
)
from jarvis.audio_io.sintese import ROTEIRO_PADRAO, Trecho
from jarvis.audio_io.sumidouros import (
    SumidouroDeArquivo,
    SumidouroDeAudio,
    SumidouroDeDispositivo,
    SumidouroEmMemoria,
)
from jarvis.relogio import Relogio


def fonte_do_ambiente(
    *,
    relogio: Relogio,
    caminho: Path | None = None,
    semente: int = 0,
    roteiro: Sequence[Trecho] = ROTEIRO_PADRAO,
    ambiente: Mapping[str, str] | None = None,
    de_produto: bool = False,
    dispositivo: int | str | None = None,
) -> FonteDeAudio:
    """A fonte que o ambiente pediu. Faltando o que ela precisa, erro explícito.

    `de_produto` e `dispositivo`: ver `backend_escolhido` e `dispositivo_pedido`.
    """
    backend = backend_escolhido(ambiente, de_produto=de_produto)
    if backend is Backend.ARQUIVO:
        if caminho is None:
            raise ValueError("backend 'arquivo' precisa de um caminho de WAV")
        return FonteDeArquivo(caminho=caminho, relogio=relogio)
    if backend is Backend.SINTETICO:
        return FonteSintetica(relogio=relogio, semente=semente, roteiro=roteiro)
    return FonteDeDispositivo(relogio=relogio, ambiente=ambiente, dispositivo=dispositivo)


def sumidouro_do_ambiente(
    *,
    caminho: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
    de_produto: bool = False,
    dispositivo: int | str | None = None,
) -> SumidouroDeAudio:
    """O sumidouro correspondente: arquivo grava WAV, sintético usa memória."""
    backend = backend_escolhido(ambiente, de_produto=de_produto)
    if backend is Backend.ARQUIVO:
        if caminho is None:
            raise ValueError("backend 'arquivo' precisa de um caminho de WAV para o playback")
        return SumidouroDeArquivo(caminho=caminho)
    if backend is Backend.SINTETICO:
        return SumidouroEmMemoria()
    return SumidouroDeDispositivo(ambiente=ambiente, dispositivo=dispositivo)


def dispositivo_pedido(nome: str) -> int | str | None:
    """O campo `entrada`/`saida` da configuração como o PortAudio entende.

    Vazio = o padrão do sistema (`None`); só dígitos = o índice que o `--diagnostico` lista;
    qualquer outra coisa = o nome (o PortAudio aceita um pedaço do nome).
    """
    limpo = nome.strip()
    if not limpo:
        return None
    return int(limpo) if limpo.isdigit() else limpo
