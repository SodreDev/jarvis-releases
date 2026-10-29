"""A caixa de scripts isolada (ADR-0050): Python ou JS do Jarvis sem rede, sem os arquivos do
dono, numa pasta temporária, com tempo, CPU, memória e saída limitados. O resultado é **dado**.

A caixa não é um terminal: não roda comando do sistema do dono, não instala, não baixa código,
não abre a rede (a não ser com o sim do dono, e aí só a rede) e não monta a casa do dono. O guarda
de contexto (ADR-0049) barra o script que tenta sair do eixo **antes** de ele chegar aqui; esta
caixa é a cerca que vale mesmo assim — se algo passar, não há o que alcançar.

    Jarvis ──prlimit(CPU, memória, arquivo, processos)── bwrap(--unshare-all, --cap-drop ALL,
        /usr só-leitura, /caixa tmpfs, script por descritor) ── python3 -I / node

Nenhum segredo entra (`--clearenv`; as chaves nunca são lidas). A saída volta cortada e redigida.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

PRAZO_PADRAO_S: Final = 10.0
CPU_PADRAO_S: Final = 10
MEMORIA_PADRAO_BYTES: Final = 256 * 1024 * 1024
ARQUIVO_PADRAO_BYTES: Final = 16 * 1024 * 1024
PROCESSOS_PADRAO: Final = 64
SAIDA_MAXIMA_BYTES: Final = 64 * 1024
PASTA_DA_CAIXA: Final = "/caixa"


class Linguagem(StrEnum):
    PYTHON = "python"
    JS = "js"


@dataclass(frozen=True, slots=True)
class Limites:
    prazo_s: float = PRAZO_PADRAO_S
    cpu_s: int = CPU_PADRAO_S
    memoria_bytes: int = MEMORIA_PADRAO_BYTES
    arquivo_bytes: int = ARQUIVO_PADRAO_BYTES
    processos: int = PROCESSOS_PADRAO
    saida_bytes: int = SAIDA_MAXIMA_BYTES

    def apertados(
        self, *, prazo_s: float | None = None, memoria_bytes: int | None = None
    ) -> Limites:
        """O pedido pode apertar, nunca afrouxar além do teto do código."""
        return Limites(
            prazo_s=min(self.prazo_s, prazo_s) if prazo_s else self.prazo_s,
            cpu_s=self.cpu_s,
            memoria_bytes=min(self.memoria_bytes, memoria_bytes)
            if memoria_bytes
            else self.memoria_bytes,
            arquivo_bytes=self.arquivo_bytes,
            processos=self.processos,
            saida_bytes=self.saida_bytes,
        )


@dataclass(frozen=True, slots=True)
class Resultado:
    saida: str
    erro: str
    codigo_de_saida: int
    estouro_de_tempo: bool = False
    saida_cortada: bool = False
    ms: float = 0.0
    sem_suporte: bool = False


class CaixaIndisponivel(RuntimeError):
    """Nenhum backend de isolamento no sistema (nem bubblewrap nem podman)."""


_BINARIO: Final[dict[Linguagem, str]] = {Linguagem.PYTHON: "python3", Linguagem.JS: "node"}


def _comando(lingua: Linguagem, memoria_bytes: int, caminho: str) -> list[str]:
    """O interpretador dentro da caixa: isolado, sem ler o diretório atual nem o ambiente.

    O Node (V8) reserva muito espaço virtual e morre sob `RLIMIT_AS`; quem limita a memória dele é
    o `--max-old-space-size` (o teto do heap do V8), não o rlimit. O Python é limitado pelo `--as`
    do prlimit (ver `_prlimit`)."""
    if lingua is Linguagem.PYTHON:
        return ["python3", "-I", "-B", caminho]
    teto_mib = max(32, memoria_bytes // (1024 * 1024))
    return ["node", "--disable-proto=throw", f"--max-old-space-size={teto_mib}", caminho]


def _interpretador(linguagem: Linguagem) -> str | None:
    return shutil.which(_BINARIO[linguagem])


def backend_disponivel() -> str | None:
    """`bwrap`, `podman` ou `None` — o que degrada a ferramenta honesto quando falta (ADR-0050)."""
    for binario in ("bwrap", "podman"):
        if shutil.which(binario):
            return binario
    return None


_AUTO: Final = "auto"
"""Valor padrão de `backend`: detecta na hora. `backend=None` força «sem caixa» (para o teste)."""


@dataclass(slots=True)
class CaixaDeScript:
    """Sobe uma caixa nova por execução. Sem estado entre chamadas."""

    limites: Limites = Limites()
    backend: str | None = _AUTO

    def __post_init__(self) -> None:
        if self.backend == _AUTO:
            self.backend = backend_disponivel()

    def disponivel(self) -> bool:
        return self.backend is not None

    def rodar(
        self,
        linguagem: Linguagem | str,
        codigo: str,
        *,
        entrada: str = "",
        rede: bool = False,
        limites: Limites | None = None,
    ) -> Resultado:
        lingua = Linguagem(linguagem)
        limites = limites or self.limites
        if self.backend is None:
            return Resultado("", "não há caixa de isolamento neste sistema", 126, sem_suporte=True)
        interpretador = _interpretador(lingua)
        if interpretador is None:
            return Resultado("", f"{_BINARIO[lingua]} não está instalado", 127, sem_suporte=True)
        if self.backend == "bwrap":
            # O script entra por um descritor (nunca vira arquivo); o stdin leva a entrada do dono.
            return self._rodar_bwrap(lingua, codigo, entrada, rede, limites)
        # podman: o script vai pelo stdin (`python3 -`/`node -`); a entrada não tem canal próprio.
        argv = self._por_podman(lingua, rede, limites)
        return self._executar(argv, escrita=-1, script=None, stdin=codigo, limites=limites)

    # bwrap: o script entra por um descritor (nunca vira arquivo no disco do dono).

    def _rodar_bwrap(
        self, lingua: Linguagem, codigo: str, entrada: str, rede: bool, limites: Limites
    ) -> Resultado:
        leitura, escrita = os.pipe()
        os.set_inheritable(leitura, True)
        try:
            argv = self._por_bwrap(lingua, rede, limites, fd=leitura)
            return self._executar(
                argv, escrita=escrita, script=codigo, stdin=entrada, limites=limites, herdar=leitura
            )
        finally:
            for fd in (leitura, escrita):
                with suppress(OSError):
                    os.close(fd)

    def _por_bwrap(self, lingua: Linguagem, rede: bool, limites: Limites, *, fd: int) -> list[str]:
        rede_args = [] if rede else ["--unshare-net"]
        bwrap = [
            "bwrap",
            "--unshare-user",
            "--unshare-ipc",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-cgroup",
            *rede_args,
            "--cap-drop",
            "ALL",
            "--new-session",
            "--die-with-parent",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/sbin",
            "/sbin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            PASTA_DA_CAIXA,
            "--chdir",
            PASTA_DA_CAIXA,
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "HOME",
            PASTA_DA_CAIXA,
            "--setenv",
            "TMPDIR",
            PASTA_DA_CAIXA,
            "--ro-bind-data",
            str(fd),
            PASTA_DA_CAIXA + "/script",
            "--",
            *_comando(lingua, limites.memoria_bytes, PASTA_DA_CAIXA + "/script"),
        ]
        return [*self._prlimit(lingua, limites), *bwrap]

    def _por_podman(self, lingua: Linguagem, rede: bool, limites: Limites) -> list[str]:
        imagem = (
            "docker.io/library/python:3.12-slim-bookworm"
            if lingua is Linguagem.PYTHON
            else "docker.io/library/node:22-slim"
        )
        extra = (
            []
            if lingua is Linguagem.PYTHON
            else [f"--max-old-space-size={max(32, limites.memoria_bytes // (1024 * 1024))}"]
        )
        comando = "python3" if lingua is Linguagem.PYTHON else "node"
        argv = [
            "podman",
            "run",
            "--rm",
            "--interactive",
            "--network",
            "none" if not rede else "slirp4netns",
            "--read-only",
            "--tmpfs",
            f"{PASTA_DA_CAIXA}:size={limites.arquivo_bytes}",
            "--workdir",
            PASTA_DA_CAIXA,
            "--memory",
            str(limites.memoria_bytes),
            "--pids-limit",
            str(limites.processos),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--env",
            f"HOME={PASTA_DA_CAIXA}",
            imagem,
            comando,
            *extra,
            "-",
        ]
        return argv

    def _prlimit(self, lingua: Linguagem, limites: Limites) -> list[str]:
        if not shutil.which("prlimit"):
            return []
        memoria = [f"--as={limites.memoria_bytes}"] if lingua is Linguagem.PYTHON else []
        # Sem `--nproc`: RLIMIT_NPROC conta os processos de TODO o uid (numa máquina
        # compartilhada, o limite já nasce estourado e o namespace do bwrap nem sobe). Quem limita
        # a contagem é o namespace de PID do bwrap (`--unshare-pid`) e, no podman, `--pids-limit`.
        return [
            "prlimit",
            f"--cpu={limites.cpu_s}",
            *memoria,
            f"--fsize={limites.arquivo_bytes}",
            "--",
        ]

    def _executar(
        self,
        argv: list[str],
        *,
        escrita: int,
        script: str | None,
        stdin: str,
        limites: Limites,
        herdar: int = -1,
    ) -> Resultado:
        """Sobe o processo. Quando o script vai por descritor (`herdar`/`escrita`), escreve-o no
        cano e deixa o fd ser herdado; o `stdin` leva a entrada do dono. Sem descritor (podman), o
        `stdin` leva o próprio script."""
        comeco = time.perf_counter()
        try:
            if script is not None:
                os.write(escrita, script.encode("utf-8"))
                os.close(escrita)
            processo = subprocess.Popen(  # noqa: S603 — argv sem shell, binário resolvido acima
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(herdar,) if herdar >= 0 else (),
                start_new_session=True,
            )
        except (OSError, ValueError) as falha:
            return Resultado("", f"a caixa não subiu: {falha}", 126)
        estouro = False
        try:
            saida, saida_erro = processo.communicate(stdin.encode("utf-8"), timeout=limites.prazo_s)
        except subprocess.TimeoutExpired:
            estouro = True
            _matar_o_grupo(processo.pid)
            saida, saida_erro = processo.communicate()
        ms = (time.perf_counter() - comeco) * 1000.0
        cortada = len(saida) > limites.saida_bytes or len(saida_erro) > limites.saida_bytes
        return Resultado(
            saida=_texto(saida, limites.saida_bytes),
            erro=_texto(saida_erro, limites.saida_bytes),
            codigo_de_saida=processo.returncode if processo.returncode is not None else -1,
            estouro_de_tempo=estouro,
            saida_cortada=cortada,
            ms=ms,
        )


def _matar_o_grupo(pid: int) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)


def _texto(bruto: bytes, limite: int) -> str:
    return bruto[:limite].decode("utf-8", errors="replace")
