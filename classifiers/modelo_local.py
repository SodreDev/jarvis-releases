"""Cliente do modelo local externo (orquestrador customizado) — SIDECAR.

Gerencia o processo do modelo (binário Rust em modo `--stdio`) como um SIDECAR
quente: spawn LAZY, singleton thread-safe, protocolo de LINHA (JSON), fallback ao
MiniLM, shutdown no `atexit`. Tudo atrás de `config.MODELO_LOCAL_ENABLED` (OFF por
padrão) → com a flag OFF nada é iniciado e `classify()` é BYTE-IDÊNTICO ao de hoje.

O modelo é IP do dono e vive FORA do repo/.exe (ver `.gitignore` + `paths.model_dir`).
A detecção só checa EXISTÊNCIA de arquivos (os.path) — nunca abre nem inspeciona os pesos.

Protocolo do sidecar (1 comando por linha em stdin; 1 linha JSON por resposta em
stdout; logs no stderr): `respond <txt>` · `perceive <txt>` · `train <N>` · `state`
· `ping` · `quit`. Handshake inicial: {"ok":true,"event":"ready",...}.

REALIDADE (fase atual): o `respond` devolve proto-texto (modelo cru p/ nosso domínio).
Esta fase entrega a TUBULAÇÃO fim-a-fim; `classify()` segue no MiniLM até o sidecar
ganhar um comando de embedding/classify + treino no domínio do JARVIS.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path


# ── config (lazy, defensivo) ──────────────────────────────────────────────────
def _cfg(name: str, default):
    try:
        import config as _c
        return getattr(_c, name, default)
    except Exception:
        return default


def _enabled() -> bool:
    return bool(_cfg("MODELO_LOCAL_ENABLED", False))


def _threads() -> int:
    try:
        return max(1, int(_cfg("MODELO_LOCAL_THREADS", 6)))
    except Exception:
        return 6


# ── localização do sidecar (binário + pesos), só existência ───────────────────
_BINARY_NAMES = ("nila_mind.exe", "router.exe", "modelo.exe", "nila_mind")
_WEIGHTS_GLOB = "*.safetensors"


def _resolve_sidecar():
    """Retorna (binary_path, weights_path, cwd) ou None se ausente. Só `os.path`."""
    try:
        from jarvis.config.paths import model_dir
        d = model_dir()
    except Exception:
        d = None
    if d is None:
        return None
    d = Path(d)

    cands = []
    envbin = os.environ.get("JARVIS_MODELO_BIN", "").strip()
    if envbin:
        cands.append(Path(envbin))
    for n in _BINARY_NAMES:
        cands.append(d / n)
        cands.append(d / "target" / "release" / n)
    binp = next((p for p in cands if p.is_file()), None)

    w = os.environ.get("JARVIS_MODELO_WEIGHTS", "").strip()
    weights = Path(w) if (w and Path(w).is_file()) else None
    if weights is None:
        found = sorted(d.glob(_WEIGHTS_GLOB))
        weights = found[0] if found else None

    if binp is None or weights is None:
        return None
    return binp, weights, d


# ── cliente do sidecar (singleton, quente) ────────────────────────────────────
class _SidecarClient:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._dead = False  # falha permanente nesta sessão → não re-spawnar em loop

    def _read_loop(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._q.put(line.rstrip("\n"))
        except Exception:
            pass
        self._q.put(None)  # sentinela de EOF

    def _spawn(self) -> bool:
        info = _resolve_sidecar()
        if info is None:
            self._dead = True
            return False
        binp, weights, cwd = info
        from jarvis.platform import processes as _plat_processes
        flags = _plat_processes().hidden_console_flags()  # Windows: CREATE_NO_WINDOW; Linux: 0
        try:
            self._q = queue.Queue()
            self._proc = subprocess.Popen(
                [str(binp), "--stdio", "--brain", str(weights), "--threads", str(_threads())],
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # logs do sidecar (stderr) descartados
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
        except Exception as e:
            print(f"[modelo_local] spawn falhou: {e}")
            self._dead = True
            return False
        threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True).start()
        # handshake "ready" (cobre o tempo de carregar o .safetensors)
        line = self._readline(timeout=25.0)
        if not line or '"event":"ready"' not in line:
            print(f"[modelo_local] handshake falhou: {line!r}")
            self._kill()
            self._dead = True
            return False
        atexit.register(self.stop)
        return True

    def _readline(self, timeout: float) -> str | None:
        try:
            return self._q.get(timeout=max(0.01, timeout))
        except queue.Empty:
            return None

    def request(self, op: str, arg: str = "", timeout: float = 6.0) -> dict | None:
        """Envia 1 comando e devolve a resposta JSON (dict) ou None (→ fallback)."""
        with self._lock:
            if self._dead:
                return None
            if self._proc is None or self._proc.poll() is not None:
                if not self._spawn():
                    return None
            assert self._proc is not None and self._proc.stdin is not None
            cmd = op if not arg else f"{op} {arg}"
            cmd = cmd.replace("\r", " ").replace("\n", " ")  # 1 request = 1 linha
            try:
                self._proc.stdin.write(cmd + "\n")
                self._proc.stdin.flush()
            except Exception as e:
                print(f"[modelo_local] write falhou: {e}")
                self._kill()
                return None
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ln = self._readline(timeout=deadline - time.monotonic())
                if ln is None:
                    if self._proc.poll() is not None:  # morreu
                        return None
                    continue
                ln = ln.strip()
                if ln.startswith("{"):  # robustez: ignora linhas não-JSON
                    try:
                        return json.loads(ln)
                    except Exception:
                        continue
            return None  # timeout

    def stop(self) -> None:
        with self._lock:
            self._kill()

    def _kill(self) -> None:
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    if p.stdin:
                        p.stdin.write("quit\n")
                        p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=2.0)
                except Exception:
                    p.terminate()
                    try:
                        p.wait(timeout=2.0)
                    except Exception:
                        p.kill()
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


_client = _SidecarClient()


# ── API pública ───────────────────────────────────────────────────────────────
def available() -> bool:
    """True se a flag está ON e o sidecar (binário + pesos) existe — sem spawnar."""
    return _enabled() and _resolve_sidecar() is not None


def respond(text: str, timeout: float = 6.0) -> str | None:
    """Envia texto ao orquestrador local e devolve a resposta (proto-texto hoje).

    Retorna None se a flag estiver OFF / sidecar ausente / erro / timeout — o
    chamador deve então usar o caminho atual (LLM/API). Nunca levanta.
    """
    if not _enabled():
        return None
    r = _client.request("respond", (text or "").strip(), timeout=timeout)
    return r.get("reply", "") if (r and r.get("ok")) else None


def act(query: str, timeout: float = 8.0) -> str | None:
    """Classifica a ação para `query` via respond_act (estado quente clonado, temp=0.5).
    Requer que perceive(corpus) tenha sido chamado antes para aquecer o stream_state.
    Retorna o texto JSON gerado (pode conter {"acao":...}) ou None se OFF/erro.
    """
    if not _enabled():
        return None
    r = _client.request("act", (query or "").strip(), timeout=timeout)
    return r.get("reply", "") if (r and r.get("ok")) else None


def perceive(text: str, timeout: float = 4.0) -> bool:
    """Alimenta o contexto do modelo / aquece o stream_state (sem gerar). True se aceito.
    Para aquecer com o corpus completo use timeout maior (ex: 30.0).
    """
    if not _enabled():
        return False
    r = _client.request("perceive", (text or "").strip(), timeout=timeout)
    return bool(r and r.get("ok"))


def train(n: int = 60) -> dict | None:
    """Roda N passos de consolidação no sidecar (acalma o afeto / 'esquenta' o
    contexto → a respond sai mais limpa). Devolve o dict (com bits_per_byte) ou
    None se OFF/erro. Persiste só no mind_state.bin do modelo (não no .safetensors
    carregado). Timeout escala com N (cada passo é um lote paralelo)."""
    if not _enabled():
        return None
    n = max(1, int(n))
    return _client.request("train", str(n), timeout=max(6.0, n * 0.25))


def state() -> dict | None:
    """Estado/afeto atual do modelo (dict) ou None."""
    if not _enabled():
        return None
    return _client.request("state", timeout=4.0)


def classify(text: str) -> tuple[str, float]:
    """Slot do roteador → (intent, confidence).

    O sidecar AINDA NÃO classifica (devolve proto-texto), então `classify()`
    continua no MiniLM. Quando o sidecar ganhar um comando de embedding/classify
    (fase de treino), ESTE é o ponto único de troca — sempre com fallback.
    """
    from classifiers.embeddings import classify as _minilm
    return _minilm(text)


if __name__ == "__main__":
    # Teste manual da TUBULAÇÃO (ignora a flag de propósito): aponte
    # JARVIS_MODELO_DIR para a pasta do modelo (com target/release/<bin> + *.safetensors).
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # raiz do repo p/ import jarvis.*
    info = _resolve_sidecar()
    if info is None:
        print("sidecar NÃO encontrado. Defina JARVIS_MODELO_DIR para a pasta do modelo")
        print("(esperado: <dir>/target/release/nila_mind.exe + <dir>/*.safetensors)")
        sys.exit(1)
    binp, w, cwd = info
    print(f"sidecar: {binp.name} | pesos: {w.name} | cwd: {cwd}")
    print("ping    ->", _client.request("ping", timeout=25.0))
    print("state   ->", _client.request("state", timeout=10.0))
    print("respond ->", _client.request("respond", "ola, tudo bem?", timeout=15.0))
    _client.stop()
    print("ok — pipe Python <-> sidecar fim-a-fim funcionando.")
