# -*- coding: utf-8 -*-
"""updater/check_update.py
────────────────────
Verifica e aplica atualizações via **GitHub Releases**.

O repositório NinjaZinS2/jarvis-releases é público — nenhum token é
necessario para checar ou baixar atualizações.

O token PAT (se fornecido) é opcional e só enviado quando presente; serve
unicamente para repos privados ou para evitar rate-limiting da API do GitHub
em ambientes com muitas instâncias.

O token é lido de (em ordem de prioridade):
    1. variável de ambiente JARVIS_UPDATE_TOKEN
    2. credentials/.env (chave JARVIS_UPDATE_TOKEN)
    3. credentials/jarvis_prefs.json → updater.token

O repo-alvo vem de:
    1. env JARVIS_UPDATE_REPO  (formato "owner/nome")
    2. credentials/jarvis_prefs.json → updater.repo
    3. fallback: "NinjaZinS2/jarvis-releases"

Auto-detecção de caminho: TUDO é relativo ao executável/arquivo, NUNCA
hard-coded — segue o mesmo padrão de version.py e config.py.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib import error as urlerr
from urllib import request as urlreq

try:
    from version import get_version, version_tuple
except ImportError:  # rodando dentro do pacote em testes
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from version import get_version, version_tuple  # type: ignore

API_BASE = "https://api.github.com"
USER_AGENT = "JARVIS-Updater/1.0"
DEFAULT_REPO = "NinjaZinS2/jarvis-releases"  # ajuste depois de criar o repo
TIMEOUT = 15
DOWNLOAD_TIMEOUT = 300


class UpdateError(RuntimeError):
    """Erro recuperável do updater (rede, auth, arquivo)."""


# ─── Detecção de caminho ────────────────────────────────────────────────────
def _base_dir() -> Path:
    """Diretório base do projeto (mesma lógica de version.py)."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        live = (exe_dir / ".." / "..").resolve()
        if (live / "main.py").is_file():
            return live
        return exe_dir
    return Path(__file__).resolve().parent.parent


def _creds_dir() -> Path:
    d = _base_dir() / "credentials"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Configuração ───────────────────────────────────────────────────────────
def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _read_prefs() -> dict[str, Any]:
    p = _creds_dir() / "jarvis_prefs.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_token() -> str | None:
    tok = os.environ.get("JARVIS_UPDATE_TOKEN")
    if tok:
        return tok.strip()
    env = _read_env_file(_creds_dir() / ".env")
    tok = env.get("JARVIS_UPDATE_TOKEN")
    if tok:
        return tok
    prefs = _read_prefs()
    return (prefs.get("updater") or {}).get("token") or None


def _get_repo() -> str:
    repo = os.environ.get("JARVIS_UPDATE_REPO")
    if repo:
        return repo.strip()
    prefs = _read_prefs()
    return (prefs.get("updater") or {}).get("repo") or DEFAULT_REPO


# ─── HTTP ───────────────────────────────────────────────────────────────────
def _http_get(url: str, accept: str = "application/vnd.github+json",
              token: str | None = None, timeout: int = TIMEOUT) -> bytes:
    req = urlreq.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", accept)
    if token:
        req.add_header("Authorization", f"token {token}")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
    ctx = ssl.create_default_context()
    try:
        with urlreq.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except urlerr.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise UpdateError(
            f"HTTP {e.code} em {url}: {e.reason}. {body}"
        ) from None
    except urlerr.URLError as e:
        raise UpdateError(f"Rede: {e.reason}") from None


def _http_download(url: str, dest: Path, token: str | None,
                   timeout: int = DOWNLOAD_TIMEOUT) -> Path:
    req = urlreq.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    # Para asset de release privado o Accept precisa ser octet-stream
    req.add_header("Accept", "application/octet-stream")
    if token:
        req.add_header("Authorization", f"token {token}")
    ctx = ssl.create_default_context()
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urlreq.urlopen(req, timeout=timeout, context=ctx) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except urlerr.HTTPError as e:
        raise UpdateError(f"HTTP {e.code} ao baixar asset: {e.reason}") from None
    except urlerr.URLError as e:
        raise UpdateError(f"Rede no download: {e.reason}") from None
    tmp.replace(dest)
    return dest


# ─── API pública ────────────────────────────────────────────────────────────
def check_for_update(repo: str | None = None,
                     token: str | None = None,
                     current_version: str | None = None) -> dict[str, Any]:
    """Consulta o release mais recente. Retorna dict com:

        {
          "has_update": bool,
          "current": "1.0.0",
          "latest":  "1.1.0",
          "name":    "JARVIS 1.1.0",
          "notes":   "...",
          "html_url": "...",
          "published_at": "...",
          "asset": {
              "name": "update_payload_v1.1.0.zip",
              "url":  "https://api.github.com/.../assets/123",
              "size": 1234567,
              "kind": "payload" | "installer"
          } | None,
          "installer": { ... } | None,
          "repo": "owner/name",
          "private_repo": bool,
        }

    Lança UpdateError em caso de erro de rede / auth.
    """
    repo = repo or _get_repo()
    # Token é completamente opcional para repos públicos.
    # Só usa token se explicitamente fornecido ou configurado pelo usuário.
    if token is None:
        token = _get_token()  # retorna None se não configurado — OK para repo público
    cur = current_version or get_version()

    url = f"{API_BASE}/repos/{repo}/releases/latest"
    raw = _http_get(url, token=token)
    rel = json.loads(raw.decode("utf-8"))

    latest = (rel.get("tag_name") or "").lstrip("v") or "0.0.0"
    has = version_tuple(latest) > version_tuple(cur)

    payload_asset = None
    installer_asset = None
    for a in rel.get("assets") or []:
        name = (a.get("name") or "").lower()
        item = {
            "name": a.get("name"),
            "url": a.get("url"),  # URL da API (funciona para repo privado com token)
            "browser_url": a.get("browser_download_url"),
            "size": a.get("size"),
        }
        if name.startswith("update_payload") and name.endswith(".zip"):
            item["kind"] = "payload"
            payload_asset = item
        elif name.endswith(".exe") and "setup" in name:
            item["kind"] = "installer"
            installer_asset = item

    return {
        "has_update": has,
        "current": cur,
        "latest": latest,
        "name": rel.get("name") or f"v{latest}",
        "notes": rel.get("body") or "",
        "html_url": rel.get("html_url"),
        "published_at": rel.get("published_at"),
        "asset": payload_asset,
        "installer": installer_asset,
        "repo": repo,
        "private_repo": bool(token),
    }


def download_asset(asset: dict[str, Any], dest_dir: Path | None = None,
                   token: str | None = None) -> Path:
    """Baixa um asset (payload ou installer) e retorna o Path do arquivo."""
    if not asset or not asset.get("url"):
        raise UpdateError("Asset inválido.")
    token = token if token is not None else _get_token()
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "jarvis_update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / asset["name"]
    return _http_download(asset["url"], dest, token=token)


def apply_update(info: dict[str, Any], *, prefer: str = "payload") -> dict[str, Any]:
    """Aplica a atualização.

    - prefer="payload": extrai o ZIP de payload sobre o diretório do projeto
      (apenas arquivos .py / config — NUNCA toca em credentials/, data/, temp/).
    - prefer="installer": baixa o setup.exe e o lança (instalador interativo).

    Retorna dict { 'mode', 'path', 'restart_required' }.
    """
    if not info.get("has_update"):
        return {"mode": "noop", "path": None, "restart_required": False}

    token = _get_token()
    if prefer == "installer" and info.get("installer"):
        path = download_asset(info["installer"], token=token)
        return {"mode": "installer", "path": str(path), "restart_required": True}

    asset = info.get("asset")
    if not asset:
        # Sem payload nem fallback: avisa
        raise UpdateError(
            "Release não contém asset 'update_payload_v*.zip'. "
            "Use prefer='installer' se houver setup.exe disponível."
        )
    zip_path = download_asset(asset, token=token)
    extracted = _extract_safe(zip_path, _base_dir())
    return {
        "mode": "payload",
        "path": str(zip_path),
        "files": extracted,
        "restart_required": True,
    }


# ─── Extração segura ────────────────────────────────────────────────────────
# Pastas protegidas: NUNCA sobrescritas pelo payload (dados do usuário).
PROTECTED = {"credentials", "data", "temp", "logs", "build", "dist",
             ".venv", ".git", "__pycache__", "memories"}


def _is_safe_path(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _extract_safe(zip_path: Path, project_root: Path) -> list[str]:
    """Extrai zip preservando pastas protegidas. Retorna lista de arquivos
    aplicados. Protege contra path traversal."""
    written: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            rel = Path(member.filename)
            # bloqueia caminhos absolutos ou traversal
            if rel.is_absolute() or any(p == ".." for p in rel.parts):
                continue
            # bloqueia pastas protegidas
            top = rel.parts[0] if rel.parts else ""
            if top in PROTECTED:
                continue
            target = project_root / rel
            if not _is_safe_path(target, project_root):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(str(rel).replace("\\", "/"))
    return written


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── CLI ────────────────────────────────────────────────────────────────────
def _cli(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description="JARVIS Updater")
    p.add_argument("--check", action="store_true", help="Apenas checa")
    p.add_argument("--apply", action="store_true", help="Baixa e aplica payload")
    p.add_argument("--installer", action="store_true",
                   help="Baixa o setup.exe ao invés de payload")
    p.add_argument("--repo", help="owner/repo (override)")
    p.add_argument("--token", help="GitHub PAT (override)")
    p.add_argument("--json", action="store_true", help="Saída JSON")
    args = p.parse_args(argv)

    try:
        info = check_for_update(repo=args.repo, token=args.token)
    except UpdateError as e:
        print(f"[updater] erro: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"Versão atual:    {info['current']}")
        print(f"Última do repo:  {info['latest']}  ({info['repo']})")
        print(f"Atualização?     {'SIM' if info['has_update'] else 'não'}")
        if info["has_update"]:
            print(f"Notas:\n{info['notes'][:500]}")

    if args.apply or args.installer:
        if not info["has_update"]:
            print("Nada para aplicar.")
            return 0
        result = apply_update(info, prefer="installer" if args.installer else "payload")
        print(f"[updater] modo: {result['mode']}  →  {result.get('path')}")
        if result.get("restart_required"):
            print("[updater] reinicie o JARVIS para concluir.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
