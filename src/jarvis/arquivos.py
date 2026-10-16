"""Troca atômica de arquivo pequeno, e leitura que tolera arquivo ocupado.

Os contratos fora do barramento (microfone do F1-13, degradação do F1-14, o que a `ui` mostra)
são arquivinhos na pasta de sessão trocados por `Path.replace`. Isso parece trivial e não é, por
dois motivos que o **P11** cobra:

1. **No Windows, `os.replace` falha se o destino está aberto por outro processo**
   (`ERROR_SHARING_VIOLATION`): o CPython abre arquivo sem `FILE_SHARE_DELETE`, então um leitor
   no instante errado faria o **escritor** levantar `PermissionError` — e o escritor aqui é o
   laço de 20 ms do `audio-io`. Então a escrita **tenta de novo** algumas vezes e, no limite,
   desiste em silêncio: o próximo tick reescreve. Derrubar o áudio porque alguém estava lendo o
   indicador seria o pior negócio possível.
2. **"Não deu para ler agora" não é a mesma coisa que "não existe".** Arquivo ausente é
   informação ("a `ui` não pediu nada ainda"); erro de leitura é ruído de um instante. Se o
   ruído virasse resposta, um leitor azarado no Windows **desligaria o microfone** por um tick.
   Por isso `ler_texto` devolve `None` só para ausente e levanta `LeituraOcupada` no resto, e
   quem chama decide — em geral mantendo o valor anterior.

O temporário leva o **pid** no nome: `degradacao.json` tem dois escritores (o `s2` e o
`agentd`), e dois processos escrevendo no mesmo `.tmp` intercalariam bytes antes do `replace`.

E **bytes inteiros não bastam quando são dois escritores**: quem lê, decide e escreve precisa
de `tranca_exclusiva` em volta do par, senão a atualização de um se perde por cima da do outro
(ler, ler, escrever, escrever). A troca atômica garante que ninguém vê arquivo pela metade; não
garante que ninguém sobrescreve o que o outro acabou de acrescentar.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

if sys.platform == "win32":  # pragma: no cover — ver `tranca_exclusiva`
    import msvcrt
else:
    import fcntl

TENTATIVAS: Final = 5
ESPERA_S: Final = 0.005
"""5 tentativas de 5 ms: 25 ms de teimosia, pouco mais que um quadro de áudio."""
TENTATIVAS_DA_TRANCA: Final = 200
ESPERA_DA_TRANCA_S: Final = 0.005
"""1 s de espera pela trava, no máximo: nada neste projeto fica pendurado esperando arquivo."""
SUFIXO_DA_TRANCA: Final = ".lock"


class LeituraOcupada(OSError):
    """O arquivo existe e não deu para ler **agora**. Não é ausência e não é corrupção."""


def escrever_atomico(
    caminho: Path, texto: str, *, tentativas: int = TENTATIVAS, espera_s: float = ESPERA_S
) -> bool:
    """Grava inteiro ou não grava. Devolve se conseguiu — e **nunca** levanta por disputa.

    O temporário fica no mesmo diretório (senão `replace` atravessaria sistema de arquivos) e
    leva o pid no nome (senão dois escritores intercalariam bytes nele).
    """
    temporario = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")
    try:
        temporario.write_text(texto, encoding="utf-8")
    except OSError:
        return False
    for tentativa in range(tentativas):
        try:
            temporario.replace(caminho)
        except OSError:
            if tentativa == tentativas - 1:
                temporario.unlink(missing_ok=True)
                return False
            time.sleep(espera_s)
        else:
            return True
    return False  # pragma: no cover — o laço acima sempre devolve


def ler_texto(caminho: Path) -> str | None:
    """Conteúdo do arquivo; `None` se não existe; `LeituraOcupada` se não deu agora."""
    try:
        return caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as erro:
        raise LeituraOcupada(f"{caminho} existe e não deu para ler agora") from erro


def _travar(descritor: int) -> bool:
    """Trava exclusiva, sem bloquear. `False` quando outro processo está dentro."""
    try:
        if sys.platform == "win32":  # pragma: no cover — nunca executado nesta máquina
            msvcrt.locking(descritor, msvcrt.LK_NBLCK, 1)  # type: ignore[unreachable]
        else:
            fcntl.flock(descritor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _destravar(descritor: int) -> None:
    try:
        if sys.platform == "win32":  # pragma: no cover — nunca executado nesta máquina
            msvcrt.locking(descritor, msvcrt.LK_UNLCK, 1)  # type: ignore[unreachable]
        else:
            fcntl.flock(descritor, fcntl.LOCK_UN)
    except OSError:  # pragma: no cover — descritor já fechado pelo sistema
        pass


@contextmanager
def tranca_exclusiva(
    caminho: Path,
    *,
    tentativas: int = TENTATIVAS_DA_TRANCA,
    espera_s: float = ESPERA_DA_TRANCA_S,
) -> Iterator[bool]:
    """Serializa o par **ler → decidir → escrever** de um arquivo de estado entre processos.

    A trava **não** pode ser no próprio arquivo: ele é trocado por `replace`, que cria um inode
    novo, então dois processos travariam objetos diferentes e os dois entrariam. Por isso a
    trava é um arquivo ao lado (`<nome>.lock`), que ninguém substitui — só é aberto e travado.
    É por descritor nos dois sistemas: `flock` no POSIX, `msvcrt.locking` no Windows (escrito e
    revisado, nunca executado — não há máquina Windows nesta sessão).

    Devolve se a trava foi obtida. Passado o limite de espera, **segue sem ela** e devolve
    `False`: travar o Jarvis porque um processo morreu segurando a trava seria pior que a
    corrida que a trava evita, e quem chama ainda relê o disco antes de escrever.
    """
    alvo = caminho.with_name(caminho.name + SUFIXO_DA_TRANCA)
    try:
        descritor = os.open(alvo, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    except OSError:  # pragma: no cover — pasta só de leitura: a escrita falharia de todo jeito
        yield False
        return
    try:
        for _ in range(tentativas):
            if _travar(descritor):
                try:
                    yield True
                finally:
                    _destravar(descritor)
                return
            time.sleep(espera_s)
        yield False
    finally:
        os.close(descritor)
