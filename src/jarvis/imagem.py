"""Uma imagem que vai ao motor junto do contexto — a tela da aba (ADR-0032, emenda da tela).

A imagem nunca entra no texto do resultado de uma ferramenta (o modelo leria base64 como texto, e
o limite de 6000 caracteres a cortaria): ela viaja à parte, como **anexo** do resultado, e o
cérebro a entrega ao motor que declara `aceita_imagem`. Vale só para o turno: não vai para a
conversa, para o livro de memória nem para a trilha.

Sem biblioteca de imagem: a largura e a altura saem do cabeçalho do PNG (IHDR) e do JPEG (SOF),
que é o que a captura da extensão produz.
"""

from __future__ import annotations

import base64
import binascii
import struct
from dataclasses import dataclass
from typing import Final

TIPOS: Final = frozenset({"image/jpeg", "image/png"})
LIMITE_DE_BYTES: Final = 5 * 1024 * 1024
"""O que a API aceita por imagem; a captura de uma tela em JPEG fica muito abaixo disso."""
_SOF: Final = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


CHAVE_DOS_ANEXOS: Final = "__anexos__"
"""Onde o corpo de uma tool devolve imagens: o executor as tira dos dados e as põe nos anexos do
resultado — nunca no texto que o modelo lê nem na auditoria."""


class ImagemInvalida(ValueError):
    """O que veio não é um PNG ou JPEG legível dentro do limite."""


@dataclass(frozen=True, slots=True)
class Imagem:
    id: str
    """O id do artefato (`tela:<instantâneo>`): é o mesmo instantâneo da inspeção e dos scripts."""
    tipo: str
    dados: bytes
    largura: int
    altura: int

    def em_base64(self) -> str:
        return base64.b64encode(self.dados).decode("ascii")


def dimensoes(dados: bytes) -> tuple[str, int, int]:
    """`(tipo, largura, altura)` de um PNG ou JPEG; `ImagemInvalida` para o resto."""
    if dados.startswith(b"\x89PNG\r\n\x1a\n") and dados[12:16] == b"IHDR" and len(dados) >= 24:
        largura, altura = struct.unpack(">II", dados[16:24])
        return "image/png", largura, altura
    if dados.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 <= len(dados):
            if dados[i] != 0xFF:
                break
            marcador = dados[i + 1]
            if marcador == 0xFF:
                i += 1
                continue
            if marcador == 0x01 or 0xD0 <= marcador <= 0xD8:
                i += 2
                continue
            tamanho = struct.unpack(">H", dados[i + 2 : i + 4])[0]
            if marcador in _SOF:
                altura, largura = struct.unpack(">HH", dados[i + 5 : i + 9])
                return "image/jpeg", largura, altura
            i += 2 + tamanho
    raise ImagemInvalida("não é um PNG nem um JPEG legível")


def da_url_de_dados(url: object, identificador: str) -> Imagem:
    """A captura da extensão (`data:image/jpeg;base64,…`) → `Imagem`, conferida pelos bytes: o
    tipo e o tamanho que valem são os do arquivo, não os que a URL diz."""
    if not isinstance(url, str) or not url.startswith("data:image/"):
        raise ImagemInvalida("a captura não veio como imagem")
    cabecalho, _, corpo = url.partition(",")
    if ";base64" not in cabecalho:
        raise ImagemInvalida("a captura não veio em base64")
    if len(corpo) > LIMITE_DE_BYTES * 4 // 3 + 4:
        raise ImagemInvalida("a captura passa do tamanho que o motor aceita")
    try:
        dados = base64.b64decode(corpo, validate=True)
    except (binascii.Error, ValueError):
        raise ImagemInvalida("a captura não é base64 válido") from None
    tipo, largura, altura = dimensoes(dados)
    if not (0 < largura <= 10_000 and 0 < altura <= 10_000):
        raise ImagemInvalida("a captura tem dimensões fora do razoável")
    return Imagem(identificador, tipo, dados, largura, altura)
