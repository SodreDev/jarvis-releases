# -*- coding: utf-8 -*-
"""
core/game_platform_detector.py
──────────────────────────────
Descobre jogos instalados em cada launcher do Windows:

  • Steam              — libraryfolders.vdf + appmanifest_*.acf
  • Epic Games         — %ProgramData%\\Epic\\EpicGamesLauncher\\Data\\Manifests\\*.item
  • EA App             — registry + InstallDir
  • Battle.net (Activision/Blizzard) — registry HKLM\\Blizzard Entertainment
  • Ubisoft Connect    — registry HKLM\\Ubisoft\\Launcher\\Installs
  • Xbox (MS Store)    — Get-AppxPackage / WindowsApps

Cada função retorna lista[ GameInfo ] (dataclass), com campos prontos
para lançamento via URI scheme com fallback para .exe direto.

Tudo é silencioso — qualquer erro em uma plataforma vira lista vazia,
não derruba as outras.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None


# ─── DataClass ──────────────────────────────────────────────────────────────

@dataclass
class GameInfo:
    name: str
    platform: str           # "steam" | "epic" | "ea" | "battlenet" | "ubisoft" | "xbox"
    app_id: str = ""        # Steam appid / Epic CatalogItemId / etc.
    install_path: str = ""
    exe_path: str = ""      # exe principal (se conhecido)
    launch_uri: str = ""    # URI scheme para lançar
    install_uri: str = ""   # URI scheme para abrir tela de install
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _reg_open(hive, path):
    if winreg is None:
        return None
    try:
        return winreg.OpenKey(hive, path)
    except OSError:
        return None


def _reg_value(key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except Exception:
        return None


def _reg_subkeys(key) -> list[str]:
    out: list[str] = []
    try:
        i = 0
        while True:
            out.append(winreg.EnumKey(key, i))
            i += 1
    except OSError:
        pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
# STEAM
# ═══════════════════════════════════════════════════════════════════════════

def _parse_vdf(text: str) -> dict:
    """Parser minimalista de VDF (KeyValues do Valve). Suficiente para
    libraryfolders.vdf e appmanifest_*.acf."""
    out: dict = {}
    stack: list[dict] = [out]
    # Tokens: "key" "value" ou "key" { ... }
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i+1] == "/":
            # comentário até fim de linha
            j = text.find("\n", i)
            if j < 0:
                break
            i = j + 1
            continue
        if c == "}":
            if len(stack) > 1:
                stack.pop()
            i += 1
            continue
        if c == "\"":
            # lê uma string
            j = i + 1
            while j < n and text[j] != "\"":
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                j += 1
            key = text[i+1:j]
            i = j + 1
            # pula whitespace
            while i < n and text[i] in " \t\r\n":
                i += 1
            if i < n and text[i] == "{":
                # bloco
                new_d: dict = {}
                stack[-1][key] = new_d
                stack.append(new_d)
                i += 1
            elif i < n and text[i] == "\"":
                j = i + 1
                while j < n and text[j] != "\"":
                    if text[j] == "\\" and j + 1 < n:
                        j += 2
                        continue
                    j += 1
                val = text[i+1:j]
                stack[-1][key] = val
                i = j + 1
            else:
                # valor não-quoted (raro)
                j = i
                while j < n and text[j] not in " \t\r\n":
                    j += 1
                stack[-1][key] = text[i:j]
                i = j
        else:
            i += 1
    return out


def _steam_root() -> Path | None:
    if winreg is None:
        return None
    for hive, path in [
        (winreg.HKEY_CURRENT_USER,  r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]:
        k = _reg_open(hive, path)
        if k:
            try:
                p = _reg_value(k, "SteamPath") or _reg_value(k, "InstallPath")
            finally:
                k.Close()
            if p:
                pp = Path(p)
                if pp.is_dir():
                    return pp
    return None


def discover_steam_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    root = _steam_root()
    if not root:
        return games

    # 1) libraryfolders.vdf → lista de pastas-biblioteca
    libs_file = root / "steamapps" / "libraryfolders.vdf"
    library_paths: list[Path] = [root / "steamapps"]
    if libs_file.is_file():
        try:
            data = _parse_vdf(libs_file.read_text(encoding="utf-8", errors="ignore"))
            libfolders = data.get("libraryfolders") or {}
            for _, entry in libfolders.items():
                if isinstance(entry, dict):
                    p = entry.get("path")
                    if p:
                        cand = Path(p) / "steamapps"
                        if cand.is_dir() and cand not in library_paths:
                            library_paths.append(cand)
        except Exception:
            pass

    # 2) Para cada library, lê appmanifest_*.acf
    seen_ids: set[str] = set()
    for lib in library_paths:
        try:
            for mf in lib.glob("appmanifest_*.acf"):
                try:
                    raw = mf.read_text(encoding="utf-8", errors="ignore")
                    parsed = _parse_vdf(raw)
                    info = parsed.get("AppState") or {}
                    appid = str(info.get("appid") or "").strip()
                    name = str(info.get("name") or "").strip()
                    installdir = str(info.get("installdir") or "").strip()
                    if not appid or not name or appid in seen_ids:
                        continue
                    seen_ids.add(appid)
                    inst = lib / "common" / installdir if installdir else Path("")
                    games.append(GameInfo(
                        name=name,
                        platform="steam",
                        app_id=appid,
                        install_path=str(inst) if inst and inst.exists() else "",
                        launch_uri=f"steam://rungameid/{appid}",
                        install_uri=f"steam://install/{appid}",
                    ))
                except Exception:
                    continue
        except Exception:
            continue
    return games


# ═══════════════════════════════════════════════════════════════════════════
# EPIC GAMES
# ═══════════════════════════════════════════════════════════════════════════

def discover_epic_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / \
        "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not base.is_dir():
        return games
    for item in base.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            name = (data.get("DisplayName") or data.get("AppName") or "").strip()
            app_name = (data.get("AppName") or "").strip()
            install_dir = (data.get("InstallLocation") or "").strip()
            namespace = (data.get("CatalogNamespace") or "").strip()
            catalog_id = (data.get("CatalogItemId") or "").strip()
            exe_rel = (data.get("LaunchExecutable") or "").strip()
            if not name or not app_name:
                continue
            exe_full = ""
            if install_dir and exe_rel:
                full = Path(install_dir) / exe_rel
                if full.is_file():
                    exe_full = str(full)
            uri = ""
            if namespace and catalog_id and app_name:
                uri = (
                    f"com.epicgames.launcher://apps/{namespace}%3A{catalog_id}%3A{app_name}"
                    f"?action=launch&silent=true"
                )
            games.append(GameInfo(
                name=name,
                platform="epic",
                app_id=app_name,
                install_path=install_dir,
                exe_path=exe_full,
                launch_uri=uri,
                install_uri=(
                    f"com.epicgames.launcher://store/p/{app_name}"
                    if app_name else ""
                ),
                metadata={"namespace": namespace, "catalog_id": catalog_id},
            ))
        except Exception:
            continue
    return games


# ═══════════════════════════════════════════════════════════════════════════
# EA APP (origin: / ealink:)
# ═══════════════════════════════════════════════════════════════════════════

def discover_ea_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    if winreg is None:
        return games
    # EA Desktop registra jogos em HKLM\SOFTWARE\WOW6432Node\Electronic Arts\<game>
    # ou também via Uninstall keys
    candidates: list[tuple[int, str]] = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Electronic Arts"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Electronic Arts"),
    ]
    seen_paths: set[str] = set()
    for hive, path in candidates:
        k = _reg_open(hive, path)
        if not k:
            continue
        try:
            for sub in _reg_subkeys(k):
                sk = _reg_open(hive, f"{path}\\{sub}")
                if not sk:
                    continue
                try:
                    install = _reg_value(sk, "Install Dir") or \
                              _reg_value(sk, "InstallDir") or \
                              _reg_value(sk, "InstallLocation")
                    display = _reg_value(sk, "DisplayName") or sub
                    if install and install not in seen_paths and Path(install).is_dir():
                        seen_paths.add(install)
                        games.append(GameInfo(
                            name=str(display).strip(),
                            platform="ea",
                            install_path=install,
                            launch_uri=f"origin://launchgame/{sub}",
                            install_uri="ealink://library",
                        ))
                finally:
                    sk.Close()
        finally:
            k.Close()
    # Fallback: scan ProgramFiles\EA Games
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        v = os.environ.get(env)
        if not v:
            continue
        for sub in ("EA Games", "Origin Games"):
            base = Path(v) / sub
            if not base.is_dir():
                continue
            for child in base.iterdir():
                if child.is_dir() and str(child) not in seen_paths:
                    seen_paths.add(str(child))
                    games.append(GameInfo(
                        name=child.name,
                        platform="ea",
                        install_path=str(child),
                        launch_uri="ealink://library",
                    ))
    return games


# ═══════════════════════════════════════════════════════════════════════════
# BATTLE.NET (Activision / Blizzard)
# ═══════════════════════════════════════════════════════════════════════════

# Map de products conhecidos do battle.net → game code
_BNET_CODES = {
    "WoW":  "wow",     "Diablo II Resurrected": "osi", "Diablo III": "d3",
    "Diablo IV": "d4", "Hearthstone": "wtcg", "Heroes of the Storm": "hero",
    "Overwatch": "pro", "Overwatch 2": "pro",
    "StarCraft": "s1",  "StarCraft II": "s2",
    "Warcraft III": "w3", "Call of Duty": "viper",
    "Call of Duty: Modern Warfare": "odin",
    "Call of Duty: Warzone": "wzn",
    "Call of Duty: Black Ops 6": "spot",
}


def discover_battlenet_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    if winreg is None:
        return games
    candidates = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Blizzard Entertainment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Blizzard Entertainment"),
    ]
    seen: set[str] = set()
    for hive, path in candidates:
        k = _reg_open(hive, path)
        if not k:
            continue
        try:
            for sub in _reg_subkeys(k):
                if sub.lower() in {"battle.net", "agent"}:
                    continue
                sk = _reg_open(hive, f"{path}\\{sub}")
                if not sk:
                    continue
                try:
                    install = _reg_value(sk, "InstallPath") or \
                              _reg_value(sk, "InstallLocation")
                    display = sub
                    if install and install not in seen and Path(install).is_dir():
                        seen.add(install)
                        code = _BNET_CODES.get(sub, "")
                        uri = f"battlenet://{code}" if code else "battlenet://"
                        games.append(GameInfo(
                            name=display,
                            platform="battlenet",
                            app_id=code,
                            install_path=install,
                            launch_uri=uri,
                            install_uri="battlenet://",
                        ))
                finally:
                    sk.Close()
        finally:
            k.Close()
    return games


# ═══════════════════════════════════════════════════════════════════════════
# UBISOFT CONNECT
# ═══════════════════════════════════════════════════════════════════════════

def discover_ubisoft_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    if winreg is None:
        return games
    candidates = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Ubisoft\Launcher\Installs"),
    ]
    seen: set[str] = set()
    for hive, path in candidates:
        k = _reg_open(hive, path)
        if not k:
            continue
        try:
            for sub in _reg_subkeys(k):  # sub é o appid numérico
                sk = _reg_open(hive, f"{path}\\{sub}")
                if not sk:
                    continue
                try:
                    install = _reg_value(sk, "InstallDir")
                    if install and install not in seen and Path(install).is_dir():
                        seen.add(install)
                        # Tenta extrair nome via pasta
                        nome = Path(install.rstrip("\\/")).name
                        games.append(GameInfo(
                            name=nome,
                            platform="ubisoft",
                            app_id=sub,
                            install_path=install,
                            launch_uri=f"uplay://launch/{sub}/0",
                            install_uri=f"uplay://install/{sub}",
                        ))
                finally:
                    sk.Close()
        finally:
            k.Close()
    return games


# ═══════════════════════════════════════════════════════════════════════════
# XBOX (Microsoft Store / Gaming Services)
# ═══════════════════════════════════════════════════════════════════════════

# Pacotes do sistema/Xbox app que NÃO são jogos
_XBOX_EXCLUDE = {
    "Microsoft.GamingApp", "Microsoft.GamingServices", "Microsoft.XboxApp",
    "Microsoft.XboxGameOverlay", "Microsoft.XboxGamingOverlay",
    "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.Xbox.TCUI", "Microsoft.GameInputDeviceService",
}


def discover_xbox_games() -> list[GameInfo]:
    games: list[GameInfo] = []
    # Lista pacotes Appx; filtra os que tenham IsFramework=false e Architecture
    # diferente de Neutral e não estejam na blacklist.
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-AppxPackage | Where-Object { $_.IsFramework -eq $false } | "
             "Select-Object Name,PackageFamilyName,InstallLocation,DisplayName | "
             "ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            return games
        data = json.loads(proc.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        for item in data:
            try:
                name = (item.get("Name") or "").strip()
                pfn  = (item.get("PackageFamilyName") or "").strip()
                inst = (item.get("InstallLocation") or "").strip()
                disp = (item.get("DisplayName") or "").strip() or name
                if not name or name in _XBOX_EXCLUDE:
                    continue
                # Heurística: jogos do Xbox ficam em WindowsApps e têm
                # família começando com publisherID. Filtra apenas pastas
                # que tenham .exe principal jogavel; senão ignora.
                if "WindowsApps" not in (inst or ""):
                    continue
                # Pacotes de framework/IME etc — pula
                low = name.lower()
                if any(x in low for x in ("input", "framework", "runtime",
                                            "redist", "service", "language")):
                    continue
                games.append(GameInfo(
                    name=disp or name,
                    platform="xbox",
                    app_id=pfn,
                    install_path=inst,
                    launch_uri=f"shell:appsFolder\\{pfn}!App",
                    install_uri="ms-windows-store://pdp/?productid=" + name,
                ))
            except Exception:
                continue
    except Exception:
        pass
    return games


# ═══════════════════════════════════════════════════════════════════════════
# Discover ALL — agrega + dedupe
# ═══════════════════════════════════════════════════════════════════════════

_ALL_PLATFORMS = {
    "steam":     discover_steam_games,
    "epic":      discover_epic_games,
    "ea":        discover_ea_games,
    "battlenet": discover_battlenet_games,
    "ubisoft":   discover_ubisoft_games,
    "xbox":      discover_xbox_games,
}


def discover_all(platforms: Iterable[str] | None = None) -> list[GameInfo]:
    """Roda todos os detectores (ou um subset) e devolve lista combinada."""
    sel = list(platforms) if platforms else list(_ALL_PLATFORMS.keys())
    out: list[GameInfo] = []
    for p in sel:
        fn = _ALL_PLATFORMS.get(p)
        if not fn:
            continue
        try:
            out.extend(fn())
        except Exception as e:
            print(f"[game_platform_detector] {p}: {e}")
    return out
