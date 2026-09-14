"""Registro de backends por capacidade, com resolução lazy e cache thread-safe.

REGISTRY mapeia Cap -> {chave de plataforma -> cadeia de caminhos "módulo:Classe"}.
Chaves possíveis: kind exato ("linux-wayland"), família ("linux-*") e curinga
("*"). A resolução usa a PRIMEIRA chave presente (não mistura cadeias), tenta
cada caminho em ordem e cacheia o primeiro que passa; se nenhum passa, cacheia
um Unavailable e não retenta.
"""
from __future__ import annotations

import importlib
import threading
from typing import Dict, List, Optional, Tuple

from .capabilities import Cap
from .common.unavailable import Unavailable

# Entradas ("módulo:Classe") por capacidade → chave de plataforma.
REGISTRY: Dict[Cap, Dict[str, Tuple[str, ...]]] = {
    Cap.PATHS: {
        "win32": ("jarvis.platform.windows.paths:WindowsPaths",),
        "linux-*": ("jarvis.platform.linux.paths:XdgPaths",),
    },
    Cap.WEBVIEW_ENGINE: {
        "win32": ("jarvis.platform.windows.webview_engine:EdgeChromiumEngine",),
        "linux-*": ("jarvis.platform.linux.webview_engine:QtWebEngine",),
    },
    Cap.PROCESSES: {
        "win32": ("jarvis.platform.windows.processes:WindowsProcesses",),
        "linux-*": ("jarvis.platform.linux.processes:PosixProcesses",),
    },
    Cap.OPEN_PATH: {
        "win32": ("jarvis.platform.windows.open_path:StartfileOpenPath",),
        "linux-*": (
            "jarvis.platform.linux.open_path:XdgOpen",
            "jarvis.platform.linux.open_path:GioOpen",
        ),
    },
    # F2-05: só Linux com sessão gráfica; win32 sem notifier nesta fase (D-F2-5).
    Cap.NOTIFIER: {
        "linux-wayland": (
            "jarvis.platform.linux.notifier:DbusNotifier",
            "jarvis.platform.linux.notifier:NotifySendNotifier",
        ),
        "linux-x11": (
            "jarvis.platform.linux.notifier:DbusNotifier",
            "jarvis.platform.linux.notifier:NotifySendNotifier",
        ),
    },
}

_CACHE: Dict[Cap, object] = {}
_LOCK = threading.RLock()
_MISSING = object()


def _candidate_keys(kind: str) -> List[str]:
    """Ordem de chaves: kind exato → família-* → curinga."""
    keys = [kind]
    if "-" in kind:
        keys.append(kind.split("-", 1)[0] + "-*")
    keys.append("*")
    return keys


def _chain_for(cap: Cap, kind: str) -> Tuple[str, ...]:
    table = REGISTRY.get(cap, {})
    for key in _candidate_keys(kind):
        if key in table:
            return table[key]
    return ()


def _default_ctx(ctx):
    if ctx is not None:
        return ctx
    from .detect import detect
    return detect()


def _build(cap: Cap, ctx) -> object:
    tried: List[Tuple[str, str]] = []
    for path in _chain_for(cap, ctx.kind):
        module_name, _, cls_name = path.partition(":")
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, cls_name)
        except Exception as e:  # import falhou → registra e segue
            tried.append((path, f"import: {type(e).__name__}: {e}"))
            continue
        try:
            probe = cls.probe(ctx)
        except Exception as e:
            tried.append((path, f"probe: {type(e).__name__}: {e}"))
            continue
        if not probe.ok:
            tried.append((path, probe.reason or "probe: ok=False"))
            continue
        try:
            return cls(ctx)
        except Exception as e:
            tried.append((path, f"init: {type(e).__name__}: {e}"))
            continue
    return Unavailable(cap, tried)


def resolve(cap: Cap, ctx=None) -> object:
    """Resolve (com cache) o backend da capacidade. Nunca levanta aqui."""
    ctx = _default_ctx(ctx)
    cached = _CACHE.get(cap, _MISSING)
    if cached is not _MISSING:
        return cached
    with _LOCK:
        cached = _CACHE.get(cap, _MISSING)
        if cached is not _MISSING:
            return cached
        instance = _build(cap, ctx)
        _CACHE[cap] = instance
        return instance


def has(cap: Cap, ctx=None) -> bool:
    """True se existe backend real (não Unavailable). Não levanta."""
    return not isinstance(resolve(cap, ctx), Unavailable)


def refresh(cap: Cap) -> None:
    """Esquece o resultado cacheado daquela capacidade (será re-resolvida)."""
    with _LOCK:
        _CACHE.pop(cap, None)


def _clear_all() -> None:
    """Limpa todo o cache (uso interno/testes)."""
    with _LOCK:
        _CACHE.clear()


def report(ctx=None) -> dict:
    """Relatório do estado da resolução para diagnóstico."""
    ctx = _default_ctx(ctx)
    from .features import effective_features

    caps: Dict[str, dict] = {}
    for cap in Cap:
        chain = list(_chain_for(cap, ctx.kind))
        inst = resolve(cap, ctx)
        if isinstance(inst, Unavailable):
            caps[cap.value] = {"backend": None, "chain": chain, "tried": list(inst._tried)}
        else:
            caps[cap.value] = {
                "backend": getattr(inst, "name", type(inst).__name__),
                "chain": chain,
                "tried": [],
            }

    features = effective_features(
        ctx, has=lambda c: has(c, ctx), get=lambda c: resolve(c, ctx)
    )
    return {
        "kind": ctx.kind,
        "source": ctx.source,
        "desktops": list(ctx.desktops),
        "capabilities": caps,
        "features": sorted(features),
    }
