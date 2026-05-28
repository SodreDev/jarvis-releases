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
                    # Filtra ferramentas, redistribuíveis, SDKs — só quer "game"
                    app_type = str(info.get("type") or "game").strip().lower()
                    if app_type and app_type not in ("game", ""):
                        continue
                    # Filtra pelo nome: Redistributables, Proton, SteamVR etc.
                    name_low = name.lower()
                    if any(k in name_low for k in (
                        "redistributable", "steamworks shared",
                        "steamvr", "steam linux runtime", "proton",
                        "directx", "vcredist", "dotnet",
                    )):
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
# EA APP (ealink: / EADesktop)
# ═══════════════════════════════════════════════════════════════════════════

# Nomes que NÃO são jogos nas pastas do EA Desktop
_EA_NON_GAMES = {
    "EA Desktop", "EA app", "EA Anti-Cheat", "EAAntiCheat",
    "EADM", "EA Core", "EA Services",
}


def _ea_install_dirs() -> list[Path]:
    """Lê os diretórios-base de instalação do EA Desktop dos arquivos .ini."""
    dirs: list[Path] = []
    ea_pdata = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "EA Desktop"
    ea_local = Path(os.environ.get("LOCALAPPDATA", "")) / "Electronic Arts" / "EA Desktop"

    for ini_dir in [ea_pdata, ea_local]:
        if not ini_dir.is_dir():
            continue
        for ini_file in ini_dir.glob("*.ini"):
            try:
                for line in ini_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    k, _, v = line.partition("=")
                    if "downloadinplacedir" in k.lower() and v.strip():
                        p = Path(v.strip())
                        if p not in dirs:
                            dirs.append(p)
            except Exception:
                continue
    # Garante defaults comuns caso o ini não exista / não tenha a chave
    for default in [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "EA Games",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "EA Games",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Origin Games",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Origin Games",
    ]:
        if default not in dirs:
            dirs.append(default)
    return dirs


def _ea_find_install_path(game_name: str, install_dirs: list[Path]) -> str:
    """Tenta encontrar a pasta de instalação de um jogo EA."""
    name_lower = game_name.lower().replace(" ", "")
    for base in install_dirs:
        if not base.is_dir():
            continue
        # Procura subpasta com nome exato ou similar
        try:
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                child_lower = child.name.lower().replace(" ", "")
                if child_lower == name_lower or name_lower in child_lower or child_lower in name_lower:
                    return str(child)
        except (PermissionError, OSError):
            continue
    return ""


def discover_ea_games() -> list[GameInfo]:
    """Detecta jogos instalados via EA Desktop / EA App.

    Usa o diretório ProgramData\\EA Desktop\\InstallData como fonte de
    verdade dos jogos instalados — que o EA Desktop cria mesmo em installs
    parciais — e depois tenta localizar o caminho físico real via os
    diretórios de instalação configurados nos arquivos .ini.
    """
    games: list[GameInfo] = []

    # ── 1. Fonte primária: ProgramData\EA Desktop\InstallData ──────────────
    ea_installdata = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / \
        "EA Desktop" / "InstallData"

    if ea_installdata.is_dir():
        install_dirs = _ea_install_dirs()
        seen_names: set[str] = set()

        for game_dir in ea_installdata.iterdir():
            try:
                if not game_dir.is_dir():
                    continue
                name = game_dir.name.strip()
                if not name or name in _EA_NON_GAMES or name in seen_names:
                    continue
                seen_names.add(name)
                install_path = _ea_find_install_path(name, install_dirs)
                games.append(GameInfo(
                    name=name,
                    platform="ea",
                    install_path=install_path,
                    launch_uri="ealink://library",
                    install_uri="ealink://library",
                ))
            except Exception:
                continue

    # ── 2. Fallback legado: registro HKLM\Electronic Arts ──────────────────
    if winreg is not None:
        seen_paths: set[str] = {g.install_path for g in games if g.install_path}
        legacy_reg = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Electronic Arts"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Electronic Arts"),
        ]
        for hive, path in legacy_reg:
            k = _reg_open(hive, path)
            if not k:
                continue
            try:
                for sub in _reg_subkeys(k):
                    if sub in {"EA Core", "EA Desktop", "EADM"}:
                        continue
                    sk = _reg_open(hive, f"{path}\\{sub}")
                    if not sk:
                        continue
                    try:
                        install = (
                            _reg_value(sk, "Install Dir")
                            or _reg_value(sk, "InstallDir")
                            or _reg_value(sk, "InstallLocation")
                        )
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
# XBOX (Microsoft Store / Game Pass)
# ═══════════════════════════════════════════════════════════════════════════

# Pacotes do sistema/Xbox app que NÃO são jogos (lista explícita)
_XBOX_EXCLUDE = {
    "Microsoft.GamingApp", "Microsoft.GamingServices", "Microsoft.XboxApp",
    "Microsoft.XboxGameOverlay", "Microsoft.XboxGamingOverlay",
    "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.Xbox.TCUI", "Microsoft.GameInputDeviceService",
}

# Prefixos de publishers/pacotes que nunca são jogos
_XBOX_NON_GAME_PREFIXES = (
    "Microsoft.", "MicrosoftWindows.", "MicrosoftCorporationII.",
    "Windows.", "MSTeams", "NVIDIACorp.", "RealtekSemiconductorCorp.",
    "AppleInc.", "AdobeSystems.", "Clipchamp.", "SpotifyAB.",
    "AmazonVideo.", "4DF9E0F8.",  # Netflix publisher
    "Facebook.", "5319275A.",     # WhatsApp / Facebook publisher
    "Skype.", "LinkedInCorp.", "OpenAI.", "Anthropic.",
    "Kaspersky.", "aimgr",
)

# Fragmentos no nome do pacote que indicam que NÃO é um jogo base
_XBOX_NON_GAME_KEYWORDS = (
    "dlc", "gamestub", "launchtracker", "gamepasspack", "contentpack",
    "crossgenpack", "betaearlyaccess", "starterpack", "standardlaunch",
    "extension", "codec", "encoder", "decoder", "videoextension",
    "imageextension", "handwriting", "inputmethod", ".ime.",
    "experience", "webexperience", "appinstaller", "storeapp",
    "purchaseapp", "bingsearch", "sechealth", "desktopapp",
    "screensketch", "screenclip", "photos", "paint", "notes",
    "onenote", "office", "teams", "edge", "onedrive",
)


def discover_xbox_games() -> list[GameInfo]:
    """Detecta jogos do Xbox Game Pass / Microsoft Store.

    Usa `gamelaunchhelper.exe` como marcador primário para jogos do Xbox
    Game Pass (todos os títulos GP rodam via esse helper). Para outros
    pacotes da Store que sejam jogos (e.g. Roblox), aplica filtro
    complementar por palavras-chave.
    """
    games: list[GameInfo] = []
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-AppxPackage | Where-Object { $_.IsFramework -eq $false } | "
             "Select-Object Name,PackageFamilyName,InstallLocation | "
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
                if not name or not pfn:
                    continue
                # Deve estar em WindowsApps
                if "WindowsApps" not in inst:
                    continue
                # A pasta deve existir
                inst_path = Path(inst)
                if not inst_path.is_dir():
                    continue
                # Blacklist explícita de pacotes de sistema
                if name in _XBOX_EXCLUDE:
                    continue
                # Prefixos de publishers que nunca são jogos
                if any(name.startswith(p) for p in _XBOX_NON_GAME_PREFIXES):
                    continue

                # ── Verificação primária: AppxManifest.xml ──────────────────
                manifest = inst_path / "AppxManifest.xml"
                is_game = False
                display_name = name.rsplit("_", 1)[0]  # fallback
                if manifest.is_file():
                    try:
                        manifest_text = manifest.read_text(
                            encoding="utf-8", errors="replace"
                        )
                        manifest_low = manifest_text.lower()
                        # gamelaunchhelper.exe é o executável de todos os
                        # jogos do Xbox Game Pass / GDK
                        if "gamelaunchhelper" in manifest_low:
                            is_game = True
                        # Tenta extrair DisplayName do manifest XML
                        m = re.search(
                            r'DisplayName\s*=\s*"([^"]{2,80})"',
                            manifest_text,
                        )
                        if m:
                            candidate = m.group(1).strip()
                            # Ignora se for referência de recurso (ms-resource:...)
                            if not candidate.startswith("ms-resource"):
                                display_name = candidate
                    except Exception:
                        pass

                # ── Verificação secundária: palavras-chave de não-jogos ─────
                if not is_game:
                    name_low = name.lower()
                    if any(k in name_low for k in _XBOX_NON_GAME_KEYWORDS):
                        continue
                    # Sem gamelaunchhelper e sem marcadores de não-jogo →
                    # tenta verificar se há .exe
                    exes = list(inst_path.glob("*.exe"))
                    if not exes:
                        continue

                games.append(GameInfo(
                    name=display_name,
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
