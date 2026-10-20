"""A tela chega ao motor de verdade? Uma chamada ao `claude -p` com uma imagem (ADR-0032).

Uso — gasta **uma** chamada pequena da conta do dono (rápida, esforço baixo):

    uv run --frozen python -m tools.harness_tela_no_motor

Gera um PNG de uma cor só (nada da tela do dono), manda ao `MotorClaudeCli` pelo mesmo caminho do
produto (`Contexto.imagens` → `--input-format stream-json` com bloco `image` base64) e confere se
a resposta diz a cor. Imprime o que mandou (tamanhos, nunca a imagem) e o que voltou.
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

from jarvis.imagem import Imagem
from jarvis.s2.motor import Contexto, Fim, Mensagem, Modo, Texto
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.voz.interface import nunca_cancelado

COR = b"\x00\xb0\x00"
"""Verde: não é a cor que um modelo diria por padrão para uma imagem que ele não viu."""
LADO = 64


def _png(lado: int, cor: bytes) -> bytes:
    cru = (b"\x00" + cor * lado) * lado

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        crc = zlib.crc32(tipo + dados) & 0xFFFFFFFF
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", crc)

    cabecalho = struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", cabecalho)
        + bloco(b"IDAT", zlib.compress(cru))
        + bloco(b"IEND", b"")
    )


def main() -> int:
    imagem = Imagem("tela:teste", "image/png", _png(LADO, COR), LADO, LADO)
    contexto = Contexto(
        sistema="Você descreve imagens com uma palavra.",
        mensagens=(
            Mensagem("dono", "Qual é a cor desta imagem? Responda só o nome da cor, em português."),
        ),
        imagens=(imagem,),
    )
    with tempfile.TemporaryDirectory(prefix="jarvis-tela-") as pasta:
        motor = MotorClaudeCli(pasta_de_trabalho=Path(pasta))
        comeco = time.monotonic()
        texto, fim = "", None
        for delta in motor.gerar(contexto, Modo.RAPIDO, nunca_cancelado):
            if isinstance(delta, Texto):
                texto += delta.texto
            elif isinstance(delta, Fim):
                fim = delta
    resposta = " ".join(texto.split())
    viu = "verde" in resposta.casefold()
    relatorio = {
        "mandado": {"tipo": imagem.tipo, "lado_px": LADO, "bytes": len(imagem.dados)},
        "argv_tem_stream_json": "--input-format" in motor.argumentos(Modo.RAPIDO, com_imagem=True),
        "resposta": resposta[:200],
        "fim": str(fim.motivo) if fim else "sem fim",
        "detalhe": fim.detalhe[:200] if fim else "",
        "ms": round((time.monotonic() - comeco) * 1000),
        "viu_a_imagem": viu,
    }
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0 if viu else 1


if __name__ == "__main__":
    sys.exit(main())
