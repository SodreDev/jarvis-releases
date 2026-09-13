# -*- coding: utf-8 -*-
"""
tools/make_release.py
─────────────────────
Pipeline de release reproduzível e auditável.

Etapas (ordenadas, abortando em qualquer falha):

    1.  scan_secrets        — varre o working tree por padrões de credenciais
                              e ABORTA se algo for detectado em arquivo
                              versionável (não-gitignorado).
    2.  bump_version        — atualiza o arquivo VERSION para a nova versão.
    3.  build_exe           — roda PyInstaller dentro do .venv.
    4.  build_installer     — roda Inno Setup (iscc.exe) para gerar
                              JARVIS_Setup_v{X.Y.Z}.exe.
    5.  build_payload       — cria update_payload_v{X.Y.Z}.zip contendo
                              APENAS arquivos .py + config seguros.
    6.  write_checksums     — gera SHA256SUMS.txt.
    7.  write_release_notes — gera release_notes_v{X.Y.Z}.md (manual ou
                              template).
    8.  git_tag             — cria tag local vX.Y.Z (não faz push).
    9.  resumo              — imprime comandos finais (git push + gh release).

Uso:
    .venv\\Scripts\\python.exe tools\\make_release.py 2.0.1
    .venv\\Scripts\\python.exe tools\\make_release.py 2.0.1 --skip-build
    .venv\\Scripts\\python.exe tools\\make_release.py 2.0.1 --scan-only

NUNCA roda `git push` ou `gh release create` automaticamente — você confirma
manualmente para evitar vazamentos. Caminhos são detectados via __file__ (sem
hard-coded paths).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "installer"
DIST_DIR = ROOT / "dist" / "JARVIS"
OUTPUT_DIR = INSTALLER_DIR / "output"
TOOLS_DIR = ROOT / "tools"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

# ─── Etapa 1: scan de segredos ─────────────────────────────────────────────
SECRET_PATTERNS = [
    # OpenAI / Anthropic / Groq
    (r"sk-[A-Za-z0-9]{20,}",            "OpenAI/Anthropic API key"),
    (r"gsk_[A-Za-z0-9]{20,}",           "Groq API key"),
    # Google / Gemini
    (r"AIza[A-Za-z0-9_\-]{30,}",        "Google/Gemini API key"),
    # Slack
    (r"xox[bpars]-[A-Za-z0-9\-]{10,}",  "Slack token"),
    # GitHub
    (r"ghp_[A-Za-z0-9]{30,}",           "GitHub PAT (classic)"),
    (r"github_pat_[A-Za-z0-9_]{40,}",   "GitHub fine-grained PAT"),
    (r"gho_[A-Za-z0-9]{30,}",           "GitHub OAuth token"),
    # AWS
    (r"AKIA[0-9A-Z]{16}",               "AWS Access Key"),
    # ElevenLabs (sk_xxx 32 hex)
    (r"sk_[a-f0-9]{32,}",               "ElevenLabs API key"),
    # Discord bot token (3 parts)
    (r"[A-Za-z0-9_\-]{24}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}", "Discord token"),
    # JWT genérico
    (r"eyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "JWT"),
    # Chave RSA / OpenSSH
    (r"-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", "Private key"),
    # Senha hardcoded em string longa
    (r"(?i)password\s*[:=]\s*['\"][^'\"\s]{6,}['\"]", "Hardcoded password"),
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{20,}['\"]", "Hardcoded API key"),
]

# Pastas que NUNCA são escaneadas (são gitignoradas)
SKIP_DIRS = {
    ".git", ".venv", "venv", "build", "dist", "__pycache__", "node_modules",
    "credentials", "data", "temp", "logs", "memories", ".idea", ".vscode",
    "VozIa", "kokoro_cache",  # VozIa pode ter binários grandes
    "vscode_extension",  # tem node_modules com centenas de milhares de arquivos
    "modelo_local", "modelo_router",  # modelo SIDECAR — IP do dono, nunca empacotar
}

# Extensões a escanear
SCAN_EXT = {".py", ".json", ".toml", ".yaml", ".yml", ".txt", ".md",
            ".cfg", ".ini", ".spec", ".iss", ".html", ".js", ".ts",
            ".env.example"}

# Permite valores placeholder conhecidos (não são segredos reais)
ALLOWLIST_LITERALS = {
    "your_api_key_here", "your-api-key-here", "xxxxxxxxxxxxxxxxxxxx",
    "REPLACE_ME", "<your-token>", "ghp_xxxxxxxxxxxxxxxxxxxx",
    "sk-xxxxxxxxxxxxxxxxxxxx", "AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
}


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    if path.suffix.lower() not in SCAN_EXT and path.name != ".env.example":
        return True
    # Próprio scanner contém os patterns como string — pula
    if path.resolve() == Path(__file__).resolve():
        return True
    return False


def scan_secrets(root: Path) -> list[dict]:
    """Retorna lista de findings. Vazia = limpo."""
    findings: list[dict] = []
    compiled = [(re.compile(pat), label) for pat, label in SECRET_PATTERNS]

    for dirpath, dirnames, filenames in os.walk(root):
        # Poda diretórios do SKIP_DIRS in-place para não descer neles
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root)
            if _should_skip(rel):
                continue
            print(".", end="", flush=True)
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for cpat, label in compiled:
                for m in cpat.finditer(text):
                    snippet = m.group(0)
                    if any(a in snippet for a in ALLOWLIST_LITERALS):
                        continue
                    if snippet.lower() in ALLOWLIST_LITERALS:
                        continue
                    line_no = text[: m.start()].count("\n") + 1
                    findings.append({
                        "file": str(rel).replace("\\", "/"),
                        "line": line_no,
                        "kind": label,
                        "match": snippet[:60] + ("…" if len(snippet) > 60 else ""),
                    })
    return findings


# ─── Etapa 2: bump version ─────────────────────────────────────────────────
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$")


def bump_version(new_version: str) -> str:
    if not SEMVER_RE.match(new_version):
        raise ValueError(f"Versão inválida: {new_version} (use X.Y.Z)")
    vfile = ROOT / "VERSION"
    old = vfile.read_text(encoding="utf-8").strip() if vfile.is_file() else "0.0.0"
    vfile.write_text(new_version + "\n", encoding="utf-8")
    print(f"  VERSION: {old}  →  {new_version}")
    return old


# ─── Etapa 3: build exe ────────────────────────────────────────────────────
def build_exe() -> Path:
    if not VENV_PY.is_file():
        raise RuntimeError(
            f".venv não encontrado em {VENV_PY}. "
            "Crie com: python -m venv .venv ; .venv\\Scripts\\pip install -r requirements.txt"
        )
    # Limpa build anterior
    for d in (ROOT / "build" / "JARVIS", DIST_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    cmd = [str(VENV_PY), "-m", "PyInstaller", "JARVIS.spec", "--noconfirm"]
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError("PyInstaller falhou — veja build_log.txt")
    exe = DIST_DIR / "JARVIS.exe"
    if not exe.is_file():
        raise RuntimeError(f"Esperado {exe} mas não foi gerado.")
    print(f"  [OK] {exe}")
    return exe


# ─── Etapa 4: build installer ──────────────────────────────────────────────
def build_installer(version: str) -> Path | None:
    iscc = _find_iscc()
    if not iscc:
        print("  [WARN] iscc.exe não encontrado — pulando installer. "
              "Instale Inno Setup 6 (https://jrsoftware.org/isdl.php) e re-rode.")
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [iscc, f"/DAppVer={version}", str(INSTALLER_DIR / "jarvis.iss")]
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError("iscc falhou")
    setup = OUTPUT_DIR / f"JARVIS_Setup_v{version}.exe"
    if not setup.is_file():
        raise RuntimeError(f"Esperado {setup} mas não foi gerado.")
    print(f"  [OK] {setup}")
    return setup


def _find_iscc() -> str | None:
    # 1. env override
    env_path = os.environ.get("INNO_SETUP_PATH")
    if env_path and Path(env_path).is_file():
        return env_path
    # 2. PATH
    found = shutil.which("iscc")
    if found:
        return found
    # 3. caminhos comuns (incluindo install per-user via winget)
    local_app = os.environ.get("LOCALAPPDATA", "")
    guesses = [
        r"C:\Program Files (x86)\Inno Setup 6\iscc.exe",
        r"C:\Program Files\Inno Setup 6\iscc.exe",
    ]
    if local_app:
        guesses.append(str(Path(local_app) / "Programs" / "Inno Setup 6" / "iscc.exe"))
    for guess in guesses:
        if Path(guess).is_file():
            return guess
    return None


# ─── Etapa 5: build payload zip (apenas .py + assets seguros) ─────────────
PAYLOAD_INCLUDE_DIRS = [
    "comandos", "core", "classifiers", "documents", "dashboard",
    "updater", "jarvis", "entity", "security", "VozIa",
    "gesture_interface", "ui", "config", "ide",
]
PAYLOAD_INCLUDE_FILES = [
    "main.py", "config.py", "launcher.py", "version.py", "VERSION",
    "modelos.py", "requirements.txt",
]
PAYLOAD_EXCLUDE_PARTS = {
    "__pycache__", "kokoro_cache", "gesture_data", "browser_profiles",
    "people_memory", ".cache", "image_cache", "ocr_cache",
    "modelo_local", "modelo_router",  # modelo SIDECAR — IP do dono, nunca no payload
}
PAYLOAD_EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log", ".bak", ".tmp", ".vcf",
                          ".env", ".jsonl", ".safetensors"}


def _should_pack(rel: Path) -> bool:
    if any(p in PAYLOAD_EXCLUDE_PARTS for p in rel.parts):
        return False
    if rel.suffix.lower() in PAYLOAD_EXCLUDE_SUFFIX:
        return False
    # Bloqueia credentials/* exceto template
    if rel.parts and rel.parts[0] == "credentials":
        return rel.name in {".env.example", "README.md"}
    return True


def build_payload(version: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = OUTPUT_DIR / f"update_payload_v{version}.zip"
    if payload.exists():
        payload.unlink()
    count = 0
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Arquivos da raiz
        for f in PAYLOAD_INCLUDE_FILES:
            p = ROOT / f
            if p.is_file():
                zf.write(p, arcname=f)
                count += 1
        # Pastas
        for d in PAYLOAD_INCLUDE_DIRS:
            base = ROOT / d
            if not base.is_dir():
                continue
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(ROOT)
                if not _should_pack(rel):
                    continue
                zf.write(f, arcname=str(rel).replace("\\", "/"))
                count += 1
    print(f"  [OK] {payload} ({count} arquivos)")
    return payload


# ─── Etapa 6: SHA256SUMS.txt ───────────────────────────────────────────────
def write_checksums(paths: list[Path]) -> Path:
    out = OUTPUT_DIR / "SHA256SUMS.txt"
    lines = []
    for p in paths:
        if not p or not p.is_file():
            continue
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {p.name}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [OK] {out}")
    return out


# ─── Etapa 7: release notes ────────────────────────────────────────────────
NOTES_TEMPLATE = """# JARVIS {version}

## Mudanças

- (preencha aqui antes de publicar o release)

## Assets

| Arquivo | Descrição |
|--------|-----------|
| `JARVIS_Setup_v{version}.exe` | Instalador completo (Windows, Inno Setup) |
| `update_payload_v{version}.zip` | Payload incremental (somente .py — para updater) |
| `SHA256SUMS.txt` | Checksums dos arquivos acima |

## Como instalar

1. Baixe e execute `JARVIS_Setup_v{version}.exe`.
2. Edite `credentials\\.env` com suas chaves de API (template em `.env.example`).
3. Inicie pelo atalho do menu Iniciar.

## Como atualizar (instalação existente)

```powershell
.venv\\Scripts\\python.exe -m updater.check_update --apply
```

## Auto-detecção de caminho

O JARVIS funciona em qualquer pasta — não há caminhos hard-coded.
"""


def write_release_notes(version: str) -> Path:
    out = OUTPUT_DIR / f"release_notes_v{version}.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # NÃO sobrescreve notas já escritas à mão (evita voltar ao placeholder).
    if out.is_file() and "(preencha aqui" not in out.read_text(encoding="utf-8", errors="ignore"):
        print(f"  [OK] {out} já preenchido — mantendo (não sobrescreve).")
        return out
    out.write_text(NOTES_TEMPLATE.format(version=version), encoding="utf-8")
    print(f"  [OK] {out} (edite manualmente antes de publicar)")
    return out


# ─── Etapa 8: git tag ──────────────────────────────────────────────────────
def git_tag(version: str) -> bool:
    tag = f"v{version}"
    try:
        # Confere se já existe
        r = subprocess.run(
            ["git", "tag", "-l", tag], cwd=ROOT, capture_output=True, text=True
        )
        if r.stdout.strip():
            print(f"  [WARN] tag {tag} já existe — pulando.")
            return False
        r = subprocess.run(
            ["git", "tag", "-a", tag, "-m", f"JARVIS {version}"],
            cwd=ROOT, capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"  [OK] tag local criada: {tag}")
            return True
        print(f"  [WARN] git tag retornou {r.returncode}: {r.stderr.strip()}")
        return False
    except FileNotFoundError:
        print("  [WARN] git não está no PATH — pulando tag.")
        return False


# ─── CLI ───────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Pipeline de release do JARVIS")
    p.add_argument("version", help="Nova versão (ex: 2.0.1)")
    p.add_argument("--scan-only", action="store_true",
                   help="Apenas roda o scan de segredos e sai")
    p.add_argument("--skip-build", action="store_true",
                   help="Pula PyInstaller (usa dist/JARVIS existente)")
    p.add_argument("--skip-installer", action="store_true",
                   help="Pula Inno Setup")
    p.add_argument("--skip-tag", action="store_true",
                   help="Não cria tag git")
    p.add_argument("--force-secrets", action="store_true",
                   help="Continua mesmo com segredos detectados (USE COM CUIDADO)")
    args = p.parse_args(argv)

    print(f"\n========== JARVIS Release Pipeline → v{args.version} ==========\n")

    # 1. SCAN DE SEGREDOS
    print("[1/8] Scan de segredos…")
    findings = scan_secrets(ROOT)
    if findings:
        print(f"\n  !! {len(findings)} possível(eis) segredo(s) detectado(s):\n")
        for f in findings[:20]:
            print(f"     {f['file']}:{f['line']}  ({f['kind']})  {f['match']}")
        if len(findings) > 20:
            print(f"     … e mais {len(findings) - 20}")
        if not args.force_secrets:
            print("\n  ABORTANDO. Revise os arquivos acima.")
            print("  Se forem falso-positivos, adicione ao ALLOWLIST_LITERALS")
            print("  em tools/make_release.py, ou use --force-secrets.")
            return 2
        print("\n  --force-secrets ativo — continuando mesmo com findings.")
    else:
        print("  [OK] Nenhum segredo detectado em arquivos versionáveis.")

    if args.scan_only:
        return 0

    # 2. BUMP VERSION
    print("\n[2/8] Bump VERSION…")
    bump_version(args.version)

    # 3. BUILD EXE
    if args.skip_build:
        print("\n[3/8] Build .exe… (PULADO)")
    else:
        print("\n[3/8] Build .exe (PyInstaller no .venv)…")
        build_exe()

    # 4. INSTALLER
    setup_exe = None
    if args.skip_installer:
        print("\n[4/8] Inno Setup… (PULADO)")
    else:
        print("\n[4/8] Inno Setup installer…")
        setup_exe = build_installer(args.version)

    # 5. PAYLOAD
    print("\n[5/8] Payload zip…")
    payload = build_payload(args.version)

    # 6. CHECKSUMS
    print("\n[6/8] SHA256SUMS…")
    assets = [a for a in (setup_exe, payload) if a]
    write_checksums(assets)

    # 7. RELEASE NOTES
    print("\n[7/8] Release notes…")
    write_release_notes(args.version)

    # 8. GIT TAG
    if args.skip_tag:
        print("\n[8/8] git tag… (PULADO)")
    else:
        print("\n[8/8] git tag…")
        git_tag(args.version)

    # ── Resumo ────────────────────────────────────────────────────────
    print("\n========== Próximos passos ==========\n")
    print(f"  Edite:   installer\\output\\release_notes_v{args.version}.md")
    print(f"  Confira: installer\\output\\SHA256SUMS.txt\n")
    print(f"  git push origin v{args.version}\n")
    print( "  Publicar no GitHub Releases (manual ou via gh CLI):")
    print(f"    gh release create v{args.version} \\")
    print(f"        installer\\output\\JARVIS_Setup_v{args.version}.exe \\")
    print(f"        installer\\output\\update_payload_v{args.version}.zip \\")
    print( "        installer\\output\\SHA256SUMS.txt \\")
    print(f"        --notes-file installer\\output\\release_notes_v{args.version}.md \\")
    print( "        --repo NinjaZinS2/jarvis-releases")
    print( "        # adicione --prerelease se for RC")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
