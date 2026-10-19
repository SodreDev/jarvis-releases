"""O quadro do Native Messaging: tamanho de 32 bits na ordem nativa + JSON em UTF-8.

É o mesmo quadro no `stdio` do navegador e no socket do Jarvis. Quadro grande demais ou truncado
é erro — e depois de um erro o fluxo não se ressincroniza, então quem lê **fecha** a conexão.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Final, Protocol

CABECALHO: Final = struct.Struct("=I")


class Leitor(Protocol):
    def read(self, quantos: int, /) -> bytes: ...


class Escritor(Protocol):
    def write(self, dados: bytes, /) -> object: ...

    def flush(self) -> object: ...


class QuadroInvalido(ValueError):
    """Tamanho acima do limite, corte no meio do quadro ou JSON que não é um objeto."""


def _ler_exato(fluxo: Leitor, quantos: int) -> bytes:
    pedacos: list[bytes] = []
    falta = quantos
    while falta:
        parte = fluxo.read(falta)
        if not parte:
            break
        pedacos.append(parte)
        falta -= len(parte)
    return b"".join(pedacos)


def ler_quadro(fluxo: Leitor, limite: int) -> dict[str, Any] | None:
    """O próximo objeto do fluxo, ou `None` no fim limpo (nenhum byte do quadro seguinte)."""
    cabecalho = _ler_exato(fluxo, CABECALHO.size)
    if not cabecalho:
        return None
    if len(cabecalho) < CABECALHO.size:
        raise QuadroInvalido("quadro truncado no cabeçalho")
    (tamanho,) = CABECALHO.unpack(cabecalho)
    if tamanho > limite:
        raise QuadroInvalido(f"quadro de {tamanho} bytes passa do limite de {limite}")
    corpo = _ler_exato(fluxo, tamanho)
    if len(corpo) < tamanho:
        raise QuadroInvalido("quadro truncado no corpo")
    try:
        objeto = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise QuadroInvalido(f"quadro que não é JSON em UTF-8: {erro}") from None
    if not isinstance(objeto, dict):
        raise QuadroInvalido("o quadro tem de ser um objeto JSON")
    return objeto


def codificar(objeto: dict[str, Any], limite: int) -> bytes:
    corpo = json.dumps(objeto, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(corpo) > limite:
        raise QuadroInvalido(f"mensagem de {len(corpo)} bytes passa do limite de {limite}")
    return CABECALHO.pack(len(corpo)) + corpo


def escrever_quadro(fluxo: Escritor, objeto: dict[str, Any], limite: int) -> None:
    fluxo.write(codificar(objeto, limite))
    fluxo.flush()
