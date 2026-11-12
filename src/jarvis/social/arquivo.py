"""Arquivo privado do dono: gravado inteiro ou não gravado, sempre 0600, pasta 0700.

`redes.toml` tem telefones da lista permitida, as memórias fixas têm a rede de contatos dele, e o
log de envios diz com quem ele fala. Nenhum deles pode nascer legível por outro usuário, nem por
um instante: o temporário já nasce 0600 (`os.open` com o modo) e só então vira o arquivo."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

PERMISSAO: Final = 0o600
PERMISSAO_DA_PASTA: Final = 0o700


def escrever_privado(caminho: Path, texto: str) -> None:
    """Troca atômica com 0600. Levanta `OSError` se não deu (quem chama diz ao dono)."""
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=PERMISSAO_DA_PASTA)
    temporario = caminho.with_name(f".{caminho.name}.{os.getpid()}.tmp")
    descritor = os.open(
        temporario,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_CLOEXEC", 0),
        PERMISSAO,
    )
    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        if os.name != "nt":
            temporario.chmod(PERMISSAO)  # umask não afrouxa, mas um arquivo velho poderia
        temporario.replace(caminho)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise


def anexar_privado(caminho: Path, linha: str) -> None:
    """Acrescenta uma linha a um log 0600 (o de envios). Cria com 0600 se não existe."""
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=PERMISSAO_DA_PASTA)
    descritor = os.open(
        caminho,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0),
        PERMISSAO,
    )
    with os.fdopen(descritor, "a", encoding="utf-8") as arquivo:
        arquivo.write(linha.rstrip("\n") + "\n")


def texto_toml(valor: str) -> str:
    """Uma string básica de TOML. JSON escapa aspas, barra e controles com escapes que o TOML
    também aceita; o DEL (U+007F) o JSON deixa cru e o TOML proíbe, então vai escapado."""
    return json.dumps(valor, ensure_ascii=False).replace("\x7f", "\\u007f")


__all__ = ["PERMISSAO", "anexar_privado", "escrever_privado", "texto_toml"]
