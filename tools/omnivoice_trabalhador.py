"""Trabalhador do OmniVoice: o ÚNICO processo que importa a biblioteca e o PyTorch (ADR-0039).

Roda no Python isolado que `tools/instalar_omnivoice.py` cria fora do repositório
(`~/.local/share/jarvis/omnivoice/venv`), sempre com `-I`: nada do ambiente do usuário entra, e
o Jarvis não é importável aqui — por isso este arquivo só usa a biblioteca padrão, o numpy, o
PyTorch e o `omnivoice`. O instalador o copia para a pasta do motor (com o hash no registro da
instalação); quem o executa é `jarvis.voz.omnivoice.MotorTtsOmniVoice`, que nunca importa
nenhuma das duas bibliotecas — é assim que elas ficam fora do processo e do pacote do Jarvis.

**Contrato** (`PROTOCOLO`; o mesmo número mora em `jarvis.voz.omnivoice`): cada mensagem é um
tamanho de 4 bytes (big-endian) e um JSON em UTF-8; quando o JSON traz `"bytes": n`, seguem n
bytes crus — o áudio, em float32 little-endian, na taxa do modelo (24 kHz).

    trabalhador → motor   {"tipo": "ola", "protocolo": 1}                       logo ao subir
                          {"tipo": "pronto", "taxa": 24000, "dispositivo": "cuda", "segundos": 7.3}
                          {"tipo": "erro", "motivo": "sem_gpu" | "carga", "detalhe": "..."}  e sai
    motor → trabalhador   {"op": "voz", "id": 1, "audio": "/.../ref.wav", "texto": "..."}
                          {"op": "sintetizar", "id": 2, "texto": "...", "idioma": "pt"}
                          {"op": "sair"}                                        (ou fim da entrada)
    trabalhador → motor   {"tipo": "voz", "id": 1}
                          {"tipo": "audio", "id": 2, "taxa": 24000, "amostras": k, "bytes": 4k}
                          {"tipo": "erro", "id": n, "motivo": "voz" | "sintese" | "pedido", ...}

Um pedido de cada vez, na ordem em que chegam: quem enfileira e cancela é o motor.

**O stdout é só do protocolo.** Logo ao subir, o descritor 1 passa a apontar para o stderr, e o
canal fica num descritor duplicado: biblioteca que imprimir não corrompe a conversa. E nada do
que o dono vai ouvir — texto falado, áudio de referência — é escrito no stderr nem em arquivo;
o erro leva só o tipo e a mensagem da exceção, cortada.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import struct
import sys
import time
from typing import Any, BinaryIO

PROTOCOLO = 1
IDIOMA_PADRAO = "pt"
LIMITE_DO_PEDIDO = 1_000_000
"""Bytes de JSON por pedido. Um lote de fala tem poucas centenas; o resto é pedido quebrado."""
DISPOSITIVOS = ("cuda", "cpu", "mps")


def escrever(saida: BinaryIO, cabecalho: dict[str, Any], corpo: bytes = b"") -> None:
    if corpo:
        cabecalho = {**cabecalho, "bytes": len(corpo)}
    dados = json.dumps(cabecalho, ensure_ascii=False).encode("utf-8")
    saida.write(struct.pack(">I", len(dados)) + dados + corpo)
    saida.flush()


def _exato(entrada: BinaryIO, tamanho: int) -> bytes | None:
    partes: list[bytes] = []
    falta = tamanho
    while falta:
        pedaco = entrada.read(falta)
        if not pedaco:
            return None
        partes.append(pedaco)
        falta -= len(pedaco)
    return b"".join(partes)


def ler(entrada: BinaryIO) -> dict[str, Any] | None:
    """O próximo pedido, ou `None` no fim da entrada (o Jarvis fechou ou morreu)."""
    prefixo = _exato(entrada, 4)
    if prefixo is None:
        return None
    (tamanho,) = struct.unpack(">I", prefixo)
    if tamanho > LIMITE_DO_PEDIDO:
        raise ValueError(f"pedido de {tamanho} bytes passa do limite de {LIMITE_DO_PEDIDO}")
    dados = _exato(entrada, tamanho)
    if dados is None:
        return None
    pedido = json.loads(dados.decode("utf-8"))
    if not isinstance(pedido, dict):
        raise ValueError("pedido não é um objeto JSON")
    return pedido


def _resumo(erro: BaseException) -> str:
    return f"{type(erro).__name__}: {erro}"[:300]


def _canal_do_protocolo() -> BinaryIO:
    """Guarda o stdout verdadeiro para o protocolo e manda o descritor 1 para o stderr."""
    sys.stdout.flush()
    canal = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return canal


def _mps_disponivel(torch: Any) -> bool:
    mps = getattr(torch.backends, "mps", None)
    return bool(mps is not None and mps.is_available())


def verificar(dispositivo: str, saida: BinaryIO) -> int:
    """Uma linha de JSON: versões e se o dispositivo pedido existe. Não carrega o modelo."""
    from importlib import metadata

    import omnivoice  # noqa: F401 — a pergunta é "importa?"
    import torch

    versoes: dict[str, str] = {}
    for pacote in ("omnivoice", "torch", "torchaudio", "transformers", "numpy"):
        try:
            versoes[pacote] = metadata.version(pacote)
        except metadata.PackageNotFoundError:
            versoes[pacote] = ""
    cuda = bool(torch.cuda.is_available())
    mps = _mps_disponivel(torch)
    relatorio = {
        "protocolo": PROTOCOLO,
        "python": platform.python_version(),
        "versoes": versoes,
        "cuda": cuda,
        "mps": mps,
        "gpu": str(torch.cuda.get_device_name(0)) if cuda else "",
        "dispositivo": dispositivo,
        "dispositivo_ok": {"cuda": cuda, "mps": mps, "cpu": True}[dispositivo],
    }
    saida.write((json.dumps(relatorio, ensure_ascii=False) + "\n").encode("utf-8"))
    saida.flush()
    return 0


def servir(pesos: str, dispositivo: str, entrada: BinaryIO, saida: BinaryIO) -> int:
    escrever(saida, {"tipo": "ola", "protocolo": PROTOCOLO})
    comeco = time.monotonic()
    try:
        import numpy as np
        import torch
        from omnivoice import OmniVoice
    except Exception as erro:  # o venv quebrado chega ao motor como frase, não como silêncio
        escrever(saida, {"tipo": "erro", "motivo": "carga", "detalhe": _resumo(erro)})
        return 4
    if (dispositivo == "cuda" and not torch.cuda.is_available()) or (
        dispositivo == "mps" and not _mps_disponivel(torch)
    ):
        escrever(
            saida,
            {
                "tipo": "erro",
                "motivo": "sem_gpu",
                "detalhe": f"o PyTorch não vê {dispositivo} agora (driver, GPU ocupada ou ausente)",
            },
        )
        return 3
    mapa = {"cuda": "cuda:0", "mps": "mps", "cpu": "cpu"}[dispositivo]
    precisao = torch.float16 if dispositivo == "cuda" else torch.float32
    try:
        modelo = OmniVoice.from_pretrained(pesos, device_map=mapa, dtype=precisao)
    except Exception as erro:
        motivo = "sem_gpu" if "out of memory" in str(erro).lower() else "carga"
        escrever(saida, {"tipo": "erro", "motivo": motivo, "detalhe": _resumo(erro)})
        return 4
    taxa = int(getattr(modelo, "sampling_rate", 0) or 24_000)
    escrever(
        saida,
        {
            "tipo": "pronto",
            "taxa": taxa,
            "dispositivo": dispositivo,
            "segundos": round(time.monotonic() - comeco, 3),
        },
    )

    voz: Any = None
    while True:
        try:
            pedido = ler(entrada)
        except (ValueError, UnicodeDecodeError) as erro:
            # Com o enquadramento quebrado não há como achar o próximo pedido: sai.
            escrever(saida, {"tipo": "erro", "motivo": "pedido", "detalhe": _resumo(erro)})
            return 5
        if pedido is None or pedido.get("op") == "sair":
            return 0
        identificador = pedido.get("id")
        operacao = pedido.get("op")
        if operacao == "voz":
            try:
                voz = modelo.create_voice_clone_prompt(
                    ref_audio=str(pedido["audio"]), ref_text=str(pedido["texto"])
                )
            except Exception as erro:
                voz = None
                escrever(
                    saida,
                    {
                        "tipo": "erro",
                        "id": identificador,
                        "motivo": "voz",
                        "detalhe": _resumo(erro),
                    },
                )
                continue
            escrever(saida, {"tipo": "voz", "id": identificador})
            continue
        if operacao == "sintetizar":
            if voz is None:
                escrever(
                    saida,
                    {
                        "tipo": "erro",
                        "id": identificador,
                        "motivo": "pedido",
                        "detalhe": "sintetizar antes de uma voz pronta",
                    },
                )
                continue
            inicio = time.monotonic()
            try:
                audios = modelo.generate(
                    text=str(pedido["texto"]),
                    language=str(pedido.get("idioma") or IDIOMA_PADRAO),
                    voice_clone_prompt=voz,
                )
                audio = np.asarray(audios[0], dtype="<f4").reshape(-1)
            except Exception as erro:  # memória da GPU, texto que o modelo recusa: o motor decide
                escrever(
                    saida,
                    {
                        "tipo": "erro",
                        "id": identificador,
                        "motivo": "sintese",
                        "detalhe": _resumo(erro),
                    },
                )
                continue
            escrever(
                saida,
                {
                    "tipo": "audio",
                    "id": identificador,
                    "taxa": taxa,
                    "amostras": int(audio.size),
                    "segundos": round(time.monotonic() - inicio, 3),
                },
                audio.tobytes(),
            )
            continue
        escrever(
            saida,
            {
                "tipo": "erro",
                "id": identificador,
                "motivo": "pedido",
                "detalhe": f"operação desconhecida: {operacao!r}",
            },
        )


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Trabalhador do OmniVoice (ADR-0039).")
    analisador.add_argument("--pesos", default="", help="pasta com os pesos da revisão")
    analisador.add_argument("--dispositivo", choices=DISPOSITIVOS, default="cpu")
    analisador.add_argument(
        "--verificar", action="store_true", help="só confere versões e dispositivo (sem modelo)"
    )
    args = analisador.parse_args(argv)
    saida = _canal_do_protocolo()
    if args.verificar:
        return verificar(args.dispositivo, saida)
    if not args.pesos:
        escrever(saida, {"tipo": "erro", "motivo": "carga", "detalhe": "faltou --pesos"})
        return 2
    return servir(args.pesos, args.dispositivo, sys.stdin.buffer, saida)


if __name__ == "__main__":
    sys.exit(main())
