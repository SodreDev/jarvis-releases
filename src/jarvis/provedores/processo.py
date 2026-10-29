"""Uma CLI de modelo como motor: um processo por pedido, numa pasta vazia, morto no cancelamento.

As regras são as da CLI do Claude (ADR-0018, ADR-0025), valendo para o Codex e o OpenCode
(ADR-0056):

- **pasta vazia** como diretório de trabalho: o processo não enxerga o projeto do dono;
- **sem segredo no `argv`** (`proibir_segredo_em_argv`): `argv` é visível a outros processos;
- **o ambiente do filho sem as chaves que o Jarvis conhece**: o login da CLI é dela (arquivo ou
  chaveiro próprio), e um modelo que tentasse ler o ambiente não acharia a chave da Groq;
- **parar de gerar, não só de ler**: no cancelamento e no prazo o processo é morto e esperado; o
  `finally` faz o mesmo quando quem consome desiste.
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import threading
import time
from collections.abc import Collection, Generator, Mapping, Sequence
from pathlib import Path
from typing import Final

from jarvis.provedores.interface import ProvedorIndisponivel
from jarvis.s2.motor import INTERVALO_DE_CONSULTA_S
from jarvis.voz.chaves import VARIAVEIS, proibir_segredo_em_argv, redigir_do_ambiente
from jarvis.voz.interface import Cancelado

ESPERA_DO_PROCESSO_S: Final = 1.0
CAUDA_DO_ERRO: Final = 400


class ProcessoCancelado(Exception):
    """Quem pediu cancelou: o processo já foi morto."""


class ProcessoSemPrazo(Exception):
    """O prazo nosso acabou: o processo já foi morto."""


class ProcessoFalhou(RuntimeError):
    """O processo saiu com código diferente de zero. A mensagem traz o fim do `stderr`, redigido."""


_FIM: Final = object()


def ambiente_sem_chaves(
    ambiente: Mapping[str, str] | None, *, manter: Collection[str] = ()
) -> dict[str, str]:
    """O ambiente do filho: o do Jarvis menos as chaves que o Jarvis conhece."""
    base = dict(os.environ if ambiente is None else ambiente)
    for variavel in VARIAVEIS:
        if variavel not in manter:
            base.pop(variavel, None)
    return base


def encerrar(processo: subprocess.Popen[str]) -> None:
    if processo.poll() is not None:
        return
    with contextlib.suppress(OSError):
        processo.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        processo.wait(timeout=ESPERA_DO_PROCESSO_S)


def linhas_do_processo(
    argv: Sequence[str],
    *,
    entrada: str,
    pasta: Path,
    ambiente: Mapping[str, str],
    cancelado: Cancelado,
    prazo_s: float,
    redigir_com: Mapping[str, str] | None = None,
) -> Generator[str, None, None]:
    """As linhas do `stdout`, na ordem. `ProcessoCancelado`, `ProcessoSemPrazo`, `ProcessoFalhou`
    (código ≠ 0) ou `ProvedorIndisponivel` (o comando não existe). `redigir_com` é o ambiente
    **do Jarvis** (com as chaves), para o `stderr` sair sem elas; `None` = o do processo."""
    proibir_segredo_em_argv(argv, ambiente=ambiente)
    if cancelado():
        raise ProcessoCancelado
    try:
        processo = subprocess.Popen(  # noqa: S603 — argv explícito, sem shell
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=pasta,
            env=dict(ambiente),
        )
    except FileNotFoundError:
        raise ProvedorIndisponivel(f"`{argv[0]}` não está instalado nesta máquina") from None
    fila: queue.Queue[object] = queue.Queue()
    erro: list[str] = []

    def escrever_e_ler() -> None:
        assert processo.stdin is not None and processo.stdout is not None
        with contextlib.suppress(OSError, ValueError):
            processo.stdin.write(entrada)
            processo.stdin.close()
        with contextlib.suppress(OSError, ValueError):
            for linha in processo.stdout:
                fila.put(linha.rstrip("\r\n"))
        fila.put(_FIM)

    def ler_erro() -> None:
        assert processo.stderr is not None
        with contextlib.suppress(OSError, ValueError):
            for linha in processo.stderr:
                erro.append(linha)
                del erro[:-20]

    threading.Thread(target=escrever_e_ler, name="jarvis-cli", daemon=True).start()
    threading.Thread(target=ler_erro, name="jarvis-cli-erro", daemon=True).start()
    limite = time.monotonic() + prazo_s
    try:
        while True:
            if cancelado():
                raise ProcessoCancelado
            if time.monotonic() > limite:
                raise ProcessoSemPrazo
            try:
                item = fila.get(timeout=INTERVALO_DE_CONSULTA_S)
            except queue.Empty:
                continue
            if item is _FIM:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    processo.wait(timeout=ESPERA_DO_PROCESSO_S)
                if processo.returncode not in (0, None):
                    cauda = redigir_do_ambiente(
                        "".join(erro).strip()[-CAUDA_DO_ERRO:], ambiente=redigir_com
                    )
                    raise ProcessoFalhou(
                        f"`{Path(argv[0]).name}` saiu com código {processo.returncode}: "
                        f"{cauda or 'sem mensagem'}"
                    )
                return
            yield str(item)
    finally:
        encerrar(processo)


__all__ = [
    "ProcessoCancelado",
    "ProcessoFalhou",
    "ProcessoSemPrazo",
    "ambiente_sem_chaves",
    "encerrar",
    "linhas_do_processo",
]
