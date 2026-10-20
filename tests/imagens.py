"""Imagens de verdade, pequenas, para os testes da tela da aba (ADR-0032)."""

from __future__ import annotations

import base64
import struct
import zlib


def png(largura: int, altura: int, cor: bytes = b"\xff\x00\x00") -> bytes:
    """Um PNG RGB de uma cor só (vermelho, por padrão): decodificável por qualquer leitor."""
    cru = (b"\x00" + cor * largura) * altura

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        crc = zlib.crc32(tipo + dados) & 0xFFFFFFFF
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", crc)

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", cabecalho)
        + bloco(b"IDAT", zlib.compress(cru))
        + bloco(b"IEND", b"")
    )


def jpeg_de_cabecalho(largura: int, altura: int) -> bytes:
    """Só o começo de um JPEG (SOI, APP0, SOF0): é o que basta para ler o tamanho."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, altura, largura) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0


def url_de_dados(dados: bytes, tipo: str = "image/png") -> str:
    """Como a extensão entrega a captura (`captureVisibleTab`/`captureTab`)."""
    return f"data:{tipo};base64," + base64.b64encode(dados).decode()
