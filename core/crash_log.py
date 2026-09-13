"""Configuração do log de crash nativo (faulthandler).

Captura segfaults/abort de C-extensions (sounddevice, pywebview/CEF, etc.) que
escapam ao sys.excepthook do Python, mantendo o arquivo sob controle de tamanho.

Motivo: o crash_native.log era aberto em modo append e nunca rotacionado; a
cada ciclo de crash→restart do app o faulthandler acrescentava o dump de todas
as threads, chegando a ~514 MB. Aqui o arquivo é rotacionado na abertura quando
passa de max_bytes (mantendo só 1 cópia antiga). NÃO há dump periódico: o
faulthandler segue armado só para crash fatal (enable, all_threads).
"""
from __future__ import annotations

import datetime
import faulthandler
import os

DEFAULT_MAX_BYTES = 5_000_000


def _rotate_if_needed(path: str, max_bytes: int) -> None:
    """Se o log passar de max_bytes, move para <path>.1 (só 1 cópia antiga)."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            backup = path + ".1"
            try:
                if os.path.exists(backup):
                    os.remove(backup)
            except OSError:
                pass
            os.replace(path, backup)
    except OSError:
        pass


def setup_native_crash_log(path: str, max_bytes: int = DEFAULT_MAX_BYTES):
    """Arma o faulthandler gravando em ``path``, com rotação na abertura.

    - Cria o diretório se preciso.
    - Se o arquivo atual já passou de ``max_bytes``, rotaciona para ``path.1``
      (mantendo só 1 cópia antiga); o atual recomeça vazio.
    - Abre o arquivo e liga ``faulthandler.enable`` (all_threads) para crash
      fatal. NÃO agenda dump periódico (sem dump_traceback_later/repeat).

    Retorna o objeto de arquivo aberto (deve ser mantido vivo pelo chamador para
    o GC não fechar o descritor). Comportamento idêntico no Windows e no Linux.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

    _rotate_if_needed(path, max_bytes)

    fp = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    fp.write(f"\n=== faulthandler armado em {datetime.datetime.now()} ===\n")
    faulthandler.enable(file=fp, all_threads=True)
    return fp
