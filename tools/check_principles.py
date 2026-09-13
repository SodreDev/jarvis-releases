#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_principles.py — guarda-corpos dos PRINCÍPIOS do JARVIS (rodar antes de release).

Verifica de forma DETERMINÍSTICA, sem rede e sem LLM, três invariantes do projeto
(ver planning/roadmap/PRINCIPIOS.md):

  1. TOGGLES EXPERIMENTAIS OFF POR PADRÃO — features novas (memória, sub-agentes,
     raciocínio, etc.) nascem desligadas no SOURCE de config.py. Faz parse ESTÁTICO
     (não importa o módulo) para checar o default do código, não o estado de runtime
     com prefs do usuário aplicadas.
  2. py_compile — todo módulo-fonte compila (pega erro de sintaxe ao escalar).
  3. SEM SEGREDOS HARDCODED — nenhum *_TOKEN/_API_KEY/_SECRET/_PASSWORD atribuído a
     literal não-vazio em arquivos versionáveis (devem vir de env/credentials).

Uso:  .venv\\Scripts\\python.exe tools\\check_principles.py
Saída: exit 0 = OK; exit 1 = violação dura. WARNs não falham o build.
"""
from __future__ import annotations

import re
import sys
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.py"

# ── 1. Toggles que DEVEM ter um default específico no source ──────────────────
# bool experimentais → False (feature nova nunca nasce ligada).
# safety → True (anti-eco e redação de PII são proteções, ligadas de propósito).
EXPECTED_BOOL = {
    # experimentais (roadmap 13-16) — OFF por padrão
    "AGENT_INCLUDE_HISTORY": False,
    "AGENT_PARALLEL_TOOLS": False,
    "AGENT_STRICT_TOOLS": False,
    "DECK_V2_ENABLED": False,
    "REPORT_V2_ENABLED": False,
    "MEMORY_ENABLED": False,
    "MEMORY_REFLECTION_ENABLED": False,
    "MEMORY_TRIAGE_ENABLED": False,
    "MEMORY_TRIAGE_LLM_FALLBACK": False,
    "MEMORY_PRIVATE_MODE": False,
    "MEMORY_COMPACTION_ENABLED": False,
    "AGENT_SUBAGENTS": False,
    "AGENT_REASONING": False,
    "MODELO_LOCAL_ENABLED": False,
    "SKILL_MEMORY_ENABLED": False,
    "AGENT_CASE_BLOCKS": False,
    "SKILL_MEMORY_HINT": False,
    "AGENT_TOOL_HISTORY_WRITEBACK": False,
    "MEMORY_COMPACT_IN_LOOP": False,
    "AGENT_TOOLS_COMPACT": False,
    "NILA_ORCHESTRATOR_ENABLED": False,
    # safety — ON por padrão (proteções)
    "WAKE_ANTI_ECHO": True,
    "MEMORY_PII_REDACT": True,
}
# Defaults conservadores não-bool — WARN se mudarem (mudança deliberada de tuning,
# não um on/off; ao calibrar a Fase 2 e trocar p/ "layered", atualize esta tabela).
EXPECTED_STR_WARN = {
    "AGENT_TOOL_SELECT_MODE": "keyword",
    "AGENT_BRAIN_MODE": "fast",
}

# ── 2. py_compile — diretórios-fonte (exclui dist/build/venv/cache) ───────────
SRC_DIRS = [
    "jarvis", "comandos", "classifiers", "documents", "tools", "core",
    "security", "updater", "entity", "dashboard", "plugins", "gesture_interface",
]
TOP_FILES = ["main.py", "config.py", "launcher.py", "version.py"]
EXCLUDE_PARTS = {"__pycache__", "dist", "dist_new", "build", ".venv", ".git", "temp"}

# ── 3. Segredos hardcoded ─────────────────────────────────────────────────────
SECRET_KEY = re.compile(r"\b\w*(?:API_KEY|_TOKEN|_SECRET|_PASSWORD|PASSWORD)\b\s*=\s*([\"'])(.*?)\1")
# Só alerta se o literal PARECE um segredo real (token-like): ≥16 chars, sem espaços.
# Evita falso-positivo em placeholders/fixtures (ex: "with spaces inside", "gsk_abc123").
TOKENISH = re.compile(r"^[A-Za-z0-9_\-\.]{16,}$")
SECRET_SCAN_GLOBS = ["config.py", "credentials/*.py", "jarvis/config/*.py", "core/*.py"]

failures: list[str] = []
warnings: list[str] = []


def _literal_default(name: str) -> str | None:
    """Lê o literal atribuído a `name` no topo de config.py (parse estático)."""
    if not CONFIG.exists():
        return None
    pat = re.compile(rf"^{re.escape(name)}\s*=\s*([^\s#]+)", re.M)
    m = pat.search(CONFIG.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None


def check_toggles() -> None:
    for name, expected in EXPECTED_BOOL.items():
        val = _literal_default(name)
        if val is None:
            warnings.append(f"toggle ausente em config.py: {name} (esperado {expected})")
            continue
        if val != str(expected):
            failures.append(
                f"PRINCÍPIO 2 (Default OFF): {name} = {val} no source (esperado {expected})"
            )
    for name, expected in EXPECTED_STR_WARN.items():
        val = _literal_default(name)
        if val is not None and val.strip("\"'") != expected:
            warnings.append(
                f"default conservador mudou: {name} = {val} (era \"{expected}\"). "
                f"Se foi proposital (ex: calibrou a Fase 2), atualize check_principles.py."
            )


def _iter_py() -> list[Path]:
    out: list[Path] = []
    for f in TOP_FILES:
        p = ROOT / f
        if p.exists():
            out.append(p)
    for d in SRC_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if EXCLUDE_PARTS & set(p.parts):
                continue
            out.append(p)
    return out


def check_compile() -> None:
    for p in _iter_py():
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append(f"py_compile FALHOU: {p.relative_to(ROOT)} :: {e.msg.strip()[:160]}")


def check_secrets() -> None:
    seen: set[Path] = set()
    for g in SECRET_SCAN_GLOBS:
        for p in ROOT.glob(g):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if "os.environ" in line or "getenv" in line or "getattr" in line:
                    continue
                m = SECRET_KEY.search(line)
                if m and TOKENISH.match(m.group(2).strip()):  # parece token real
                    warnings.append(
                        f"possível segredo hardcoded: {p.relative_to(ROOT)}:{i} → {line.strip()[:80]}"
                    )


def main() -> int:
    print(f"[check_principles] raiz: {ROOT}")
    check_toggles()
    check_compile()
    check_secrets()

    if warnings:
        print(f"\n⚠️  {len(warnings)} aviso(s):")
        for w in warnings:
            print(f"   - {w}")
    if failures:
        print(f"\n❌ {len(failures)} violação(ões) dura(s):")
        for f in failures:
            print(f"   - {f}")
        print("\nRESULTADO: FAIL")
        return 1
    print(f"\n✓ toggles OK · py_compile OK ({len(_iter_py())} arquivos) · sem segredo hardcoded")
    print("RESULTADO: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
