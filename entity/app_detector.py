# entity/app_detector.py — J.A.R.V.I.S.
# Cache de aplicativos instalados — elimina a 7-strategy cascade no cold path.
# Escaneia Program Files, Program Files (x86), %LOCALAPPDATA%, Start Menu e
# todas as bibliotecas Steam (descobertas via libraryfolders.vdf).
# Gera config/apps_cache.json com {nome_normalizado: caminho_completo}.
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import re
import json
import unicodedata
import threading

_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_DIR, "config", "apps_cache.json")


def _get_steam_common_dirs() -> list[str]:
    """Retorna todos os caminhos steamapps/common de bibliotecas Steam instaladas.

    Lê C:\\Program Files (x86)\\Steam\\steamapps\\libraryfolders.vdf para
    descobrir bibliotecas adicionais em outras unidades/pastas.
    """
    steam_root = r"C:\Program Files (x86)\Steam"
    vdf_path = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    paths: list[str] = []

    # Sempre inclui a biblioteca padrão do Steam
    default_common = os.path.join(steam_root, "steamapps", "common")
    if os.path.isdir(default_common):
        paths.append(default_common)

    if not os.path.isfile(vdf_path):
        return paths

    try:
        with open(vdf_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Extrai valores de "path" do VDF — formato: "path"\t\t"C:\\..."
        for m in re.finditer(r'"path"\s+"([^"]+)"', content):
            lib_path = m.group(1).replace("\\\\", "\\")
            common = os.path.join(lib_path, "steamapps", "common")
            if os.path.isdir(common) and common not in paths:
                paths.append(common)
    except Exception as e:
        print(f"[APP DETECTOR] Erro ao ler libraryfolders.vdf: {e}")

    return paths


# Pastas de varredura padrão
_SCAN_DIRS: list[str] = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), ""),
    os.path.join(os.environ.get("APPDATA", ""), ""),
]

# Pastas de atalhos do Menu Iniciar (usuário + sistema)
_START_MENU_DIRS: list[str] = [
    os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs",
    ),
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
]

# Exes de sistema / instaladores que devem ser ignorados
_SKIP_EXE_RE = re.compile(
    r"(unin?stall|setup|update[rd]?|helper|crash|report|telemetry"
    r"|diagnostic|tracker|service|daemon|host|runtime|installer"
    r"|redistributable|vcredist|dotnet|framework|driver|msiexec"
    r"|regasm|regsvr32|shutdown|reboot|svchost|rundll)",
    re.I,
)

# Profundidade máxima de varredura nos diretórios
_MAX_DEPTH = 3
# Tamanho mínimo de exe para ser considerado app real (bytes)
_MIN_EXE_SIZE = 200_000  # 200 KB


def _normalize(name: str) -> str:
    """Converte para lowercase sem acentos separadores."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_str.lower())


def _scan_dir(base: str, depth: int = 0) -> dict[str, str]:
    """Varre recursivamente até _MAX_DEPTH buscando .exe com tamanho > _MIN_EXE_SIZE."""
    results: dict[str, str] = {}
    if depth > _MAX_DEPTH or not os.path.isdir(base):
        return results
    try:
        entries = os.scandir(base)
    except PermissionError:
        return results

    for entry in entries:
        try:
            if entry.is_file(follow_symlinks=False):
                if entry.name.lower().endswith(".exe"):
                    if _SKIP_EXE_RE.search(entry.name):
                        continue
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        continue
                    if size < _MIN_EXE_SIZE:
                        continue
                    stem = os.path.splitext(entry.name)[0]
                    key = _normalize(stem)
                    if key and key not in results:
                        results[key] = entry.path
            elif entry.is_dir(follow_symlinks=False):
                results.update(_scan_dir(entry.path, depth + 1))
        except (OSError, PermissionError):
            continue

    return results


def _scan_start_menu() -> dict[str, str]:
    """Escaneia .lnk do Menu Iniciar e resolve para o executável alvo quando possível."""
    results: dict[str, str] = {}
    for base in _START_MENU_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for fname in files:
                if fname.lower().endswith(".lnk"):
                    stem = os.path.splitext(fname)[0]
                    key = _normalize(stem)
                    if key:
                        lnk_path = os.path.join(root, fname)
                        # Tenta resolver o alvo do atalho via shell32
                        target = _resolve_lnk(lnk_path)
                        if target and target.lower().endswith(".exe") and os.path.isfile(target):
                            if key not in results:
                                results[key] = target
    return results


def _resolve_lnk(lnk_path: str) -> str:
    """Resolve o caminho alvo de um arquivo .lnk via COM (Windows)."""
    try:
        import win32com.client  # type: ignore
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(lnk_path)
        return shortcut.Targetpath
    except Exception:
        # pywin32 não disponível — devolve vazio
        return ""


def scan_installed_apps(save: bool = True) -> dict[str, str]:
    """
    Escaneia os diretórios de instalação e o Menu Iniciar.
    Retorna dict {nome_normalizado: caminho_completo_exe}.
    Se save=True (padrão) salva em config/apps_cache.json.
    """
    print("[APP DETECTOR] Iniciando varredura de aplicativos instalados...")
    cache: dict[str, str] = {}

    # 1. Menu Iniciar (mais confiável — .lnk já aponta para exe correto)
    cache.update(_scan_start_menu())

    # 2. Diretórios de Programas + bibliotecas Steam
    all_scan_dirs = list(_SCAN_DIRS) + _get_steam_common_dirs()
    for scan_dir in all_scan_dirs:
        if os.path.isdir(scan_dir):
            found = _scan_dir(scan_dir)
            # Não sobrescreve entradas do Menu Iniciar (mais confiáveis)
            for k, v in found.items():
                if k not in cache:
                    cache[k] = v

    print(f"[APP DETECTOR] Varredura concluída — {len(cache)} apps encontrados.")

    if save:
        try:
            os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
            with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
            print(f"[APP DETECTOR] Cache salvo em {_CACHE_PATH}")
        except Exception as e:
            print(f"[APP DETECTOR] Erro ao salvar cache: {e}")

    return cache


def load_cache() -> dict[str, str]:
    """Carrega o cache do disco. Retorna dict vazio se não existir."""
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[APP DETECTOR] Erro ao carregar cache: {e}")
    return {}


# ── Singleton do cache em memória ─────────────────────────────────────────────
_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def _ensure_loaded() -> None:
    """Garante que o cache está em memória (load do disco ou varredura)."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    with _cache_lock:
        if _cache_loaded:
            return
        disk = load_cache()
        if disk:
            _cache = disk
            print(f"[APP DETECTOR] Cache carregado do disco — {len(_cache)} apps.")
        else:
            # Primeira execução: varre em background para não bloquear inicialização
            threading.Thread(target=_background_scan, daemon=True).start()
        _cache_loaded = True


def _background_scan() -> None:
    global _cache
    new = scan_installed_apps(save=True)
    with _cache_lock:
        _cache = new


def find_app(name: str) -> str | None:
    """
    Busca o caminho do executável pelo nome normalizado.
    Retorna o caminho completo do .exe ou None se não encontrado no cache.

    Exemplos:
        find_app("spotify")  → "C:\\Users\\...\\Spotify.exe"
        find_app("chrome")   → "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    """
    _ensure_loaded()
    key = _normalize(name)
    with _cache_lock:
        return _cache.get(key)


def refresh_cache() -> str:
    """
    Re-escaneia todos os diretórios e atualiza o cache.
    Chamado via comando de voz "atualiza apps" / "reinicia cache de apps".
    Retorna mensagem de status para o usuário.
    """
    global _cache, _cache_loaded
    _cache_loaded = False
    new = scan_installed_apps(save=True)
    with _cache_lock:
        _cache = new
        _cache_loaded = True
    return f"Cache de aplicativos atualizado — {len(new)} apps registrados, senhor."
