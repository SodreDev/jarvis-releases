# -*- coding: utf-8 -*-
"""
plugins.loader — Descoberta e carregamento de plugins do JARVIS.

Plugin layout:
    plugins/<nome>/
        manifest.json
        <entry>.py

manifest.json:
    {
      "name": "weather",
      "version": "0.1.0",
      "entry": "main",            # módulo Python (sem .py)
      "description": "...",
      "permissions": ["network"],  # informativo
      "tools": [
        {"name": "weather.current", "fn": "current_weather"}
      ]
    }
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugins_dir() -> str:
    d = os.path.join(_base(), "plugins")
    os.makedirs(d, exist_ok=True)
    return d


def discover() -> List[Dict[str, Any]]:
    """Lista manifestos válidos encontrados em plugins/."""
    found: List[Dict[str, Any]] = []
    root = plugins_dir()
    for name in sorted(os.listdir(root)):
        pdir = os.path.join(root, name)
        manifest_p = os.path.join(pdir, "manifest.json")
        if not os.path.isdir(pdir) or not os.path.exists(manifest_p):
            continue
        try:
            with open(manifest_p, "r", encoding="utf-8") as fh:
                m = json.load(fh)
            m["_dir"] = pdir
            m["_slug"] = name
            found.append(m)
        except Exception:
            continue
    return found


def _load_module(plugin: Dict[str, Any]):
    entry = plugin.get("entry", "main")
    path = os.path.join(plugin["_dir"], f"{entry}.py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Plugin '{plugin.get('name')}' sem {entry}.py")
    mod_name = f"jarvis_plugin_{plugin['_slug']}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Falha ao montar spec para {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_loaded: Dict[str, Dict[str, Any]] = {}


def load_all(*, register_cb: Optional[Callable[[str, Callable], None]] = None) -> List[Dict[str, Any]]:
    """Carrega todos os plugins. `register_cb(tool_name, fn)` é chamado para
    cada tool exportada (use para integrar com tool_registry)."""
    out = []
    for p in discover():
        try:
            mod = _load_module(p)
            tools = []
            for tool in p.get("tools", []) or []:
                fn_name = tool.get("fn")
                if not fn_name:
                    continue
                fn = getattr(mod, fn_name, None)
                if not callable(fn):
                    continue
                tools.append({"name": tool.get("name", fn_name), "fn": fn,
                              "description": tool.get("description", "")})
                if register_cb:
                    try: register_cb(tool.get("name", fn_name), fn)
                    except Exception: pass
            _loaded[p["_slug"]] = {"manifest": p, "module": mod, "tools": tools}
            out.append({"name": p.get("name"), "slug": p["_slug"], "tools": [t["name"] for t in tools]})
        except Exception as e:
            out.append({"name": p.get("name"), "slug": p.get("_slug"), "error": str(e)})
    return out


def loaded() -> Dict[str, Dict[str, Any]]:
    return dict(_loaded)


def call(tool_name: str, *args, **kwargs):
    """Invoca uma tool de plugin pelo nome."""
    for info in _loaded.values():
        for t in info["tools"]:
            if t["name"] == tool_name:
                return t["fn"](*args, **kwargs)
    raise KeyError(f"Tool não encontrada: {tool_name}")


__all__ = ["discover", "load_all", "loaded", "call", "plugins_dir"]
