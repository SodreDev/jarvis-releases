# comandos/janela_ctrl.py — J.A.R.V.I.S.
# Gerenciamento de janelas, abertura de apps e navegação in-app no Windows
# -*- coding: utf-8 -*-

from __future__ import annotations
import subprocess
import os
import ctypes
import glob
import re
import shutil
import time
import unicodedata
import winreg

# ═══════════════════════════════════════════════════════════════════════════════
# GERENCIAMENTO DE JANELAS
# ═══════════════════════════════════════════════════════════════════════════════


def minimizar_tudo() -> str:
    """Minimiza todas as janelas (Win+D)."""
    try:
        import pyautogui
        pyautogui.hotkey("win", "d")
        return "Todas as janelas minimizadas, senhor."
    except Exception as e:
        return f"Erro ao minimizar: {e}"


def alternar_janela(nome_app: str) -> str:
    """Traz uma janela para frente pelo nome do app (usa pygetwindow)."""
    try:
        import pygetwindow as gw
        janelas = gw.getWindowsWithTitle(nome_app)
        if not janelas:
            todas = gw.getAllWindows()
            nome_lower = nome_app.lower()
            janelas = [w for w in todas if nome_lower in w.title.lower()]

        if not janelas:
            return f"Nenhuma janela encontrada para '{nome_app}', senhor."

        win = janelas[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        return f"Janela '{win.title}' ativada, senhor."
    except ImportError:
        return _alt_tab_fallback(nome_app)
    except Exception as e:
        return f"Erro ao alternar janela: {e}"


def _alt_tab_fallback(nome_app: str) -> str:
    try:
        import pyautogui
        pyautogui.hotkey("alt", "tab")
        return f"Alt+Tab executado. Procurando '{nome_app}'..."
    except Exception:
        return f"Não consegui alternar para '{nome_app}'."


def fechar_janela_ativa() -> str:
    try:
        import pyautogui
        pyautogui.hotkey("alt", "F4")
        return "Janela fechada, senhor."
    except Exception as e:
        return f"Erro: {e}"


def maximizar_janela() -> str:
    try:
        import pyautogui
        pyautogui.hotkey("win", "up")
        return "Janela maximizada, senhor."
    except Exception as e:
        return f"Erro: {e}"


def minimizar_janela() -> str:
    try:
        import pyautogui
        pyautogui.hotkey("win", "down")
        return "Janela minimizada, senhor."
    except Exception as e:
        return f"Erro: {e}"


def snap_esquerda() -> str:
    try:
        import pyautogui
        pyautogui.hotkey("win", "left")
        return "Janela à esquerda, senhor."
    except Exception as e:
        return f"Erro: {e}"


def snap_direita() -> str:
    try:
        import pyautogui
        pyautogui.hotkey("win", "right")
        return "Janela à direita, senhor."
    except Exception as e:
        return f"Erro: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# ABRIR APLICATIVO — BUSCA EXAUSTIVA
# ═══════════════════════════════════════════════════════════════════════════════

# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalizar(s: str) -> str:
    """Remove acentos e converte para minúsculas."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower().strip()


# ── 1. Aliases manuais — nome falado → comando ou exe ────────────────────────

_ALIAS: dict[str, str] = {
    # Navegadores
    "chrome": "chrome", "google chrome": "chrome", "google": "chrome",
    "firefox": "firefox", "mozilla": "firefox",
    "edge": "msedge", "microsoft edge": "msedge",
    "brave": "brave", "opera": "opera", "vivaldi": "vivaldi",
    # Sistema Windows (sempre disponíveis)
    "notepad": "notepad", "bloco de notas": "notepad",
    "calculadora": "calc", "calculator": "calc",
    "explorador": "explorer", "explorador de arquivos": "explorer",
    "file explorer": "explorer", "explorer": "explorer",
    "terminal": "wt", "windows terminal": "wt",
    "cmd": "cmd", "prompt": "cmd", "prompt de comando": "cmd",
    "powershell": "powershell",
    "gerenciador de tarefas": "taskmgr", "task manager": "taskmgr",
    "painel de controle": "control", "control panel": "control",
    "paint": "mspaint", "wordpad": "wordpad",
    "informacoes do sistema": "msinfo32", "system info": "msinfo32",
    "limpeza de disco": "cleanmgr", "disk cleanup": "cleanmgr",
    "desfragmentador": "dfrgui", "defrag": "dfrgui",
    "gerenciamento de disco": "diskmgmt.msc",
    "editor de registro": "regedit", "regedit": "regedit",
    "servicos": "services.msc", "services": "services.msc",
    "visualizador de eventos": "eventvwr.msc",
    "conexao de area de trabalho remota": "mstsc",
    "area de trabalho remota": "mstsc", "remote desktop": "mstsc",
    "ferramenta de recorte": "snippingtool",
    "recorte e anotacao": "ms-screenclip:",
    "snipping tool": "snippingtool",
    "gravador de passos": "psr",
    "mapa de caracteres": "charmap",
    # Office
    "word": "winword", "excel": "excel",
    "powerpoint": "powerpnt", "outlook": "outlook",
    "onenote": "onenote", "access": "msaccess",
    # Dev
    "vscode": "code", "visual studio code": "code", "vs code": "code",
    "visual studio": "devenv",
    "android studio": "studio64",
    "intellij": "idea64",
    "pycharm": "pycharm64",
    "sublime": "subl", "sublime text": "subl",
    "git bash": "git-bash",
    # Mídia
    "vlc": "vlc", "media player": "wmplayer",
    "windows media player": "wmplayer",
    "fotos": "ms-photos:", "photos": "ms-photos:",
    "musica groove": "mswindowsmusic:",
    # Comunicação
    "discord": "discord", "telegram": "telegram",
    "whatsapp": "whatsapp", "slack": "slack",
    "zoom": "zoom", "teams": "ms-teams:",
    "microsoft teams": "ms-teams:", "skype": "skype",
    # Jogos / Entretenimento
    "steam": "steam",
    "epic games": "com.epicgames.launcher:",
    "minecraft": "minecraft:",
    # Produtividade
    "notion": "notion", "obsidian": "obsidian",
    "todoist": "todoist",
    # Utilitários
    "obs": "obs64", "obs studio": "obs64",
    "spotify": "spotify",
    "blender": "blender",
    "gimp": "gimp",
    "audacity": "audacity",
    "filezilla": "filezilla",
    "putty": "putty",
    "winscp": "winscp",
    "7zip": "7zFM", "7-zip": "7zFM",
    "winrar": "winrar",
}

# ── URI schemes do Windows ───────────────────────────────────────────────────

_URI_SCHEMES: dict[str, str] = {
    "configuracoes": "ms-settings:",
    "configurações": "ms-settings:",
    "settings": "ms-settings:",
    "tela": "ms-settings:display",
    "display": "ms-settings:display",
    "rede": "ms-settings:network",
    "wifi": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth",
    "som": "ms-settings:sound",
    "notificacoes": "ms-settings:notifications",
    "apps": "ms-settings:appsfeatures",
    "aplicativos": "ms-settings:appsfeatures",
    "atualizacoes": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate",
    "armazenamento": "ms-settings:storagesense",
    "privacidade": "ms-settings:privacy",
    "personalizacao": "ms-settings:personalization",
    "plano de fundo": "ms-settings:personalization-background",
    "hora e idioma": "ms-settings:dateandtime",
    "data e hora": "ms-settings:dateandtime",
    "impressoras": "ms-settings:printers",
    "mouse": "ms-settings:mousetouchpad",
    "teclado": "ms-settings:typing",
    "energia": "ms-settings:powersleep",
    "bateria": "ms-settings:batterysaver",
    "camera": "ms-settings:privacy-webcam",
    "microfone": "ms-settings:privacy-microphone",
}

# ── Pastas comuns / especiais ────────────────────────────────────────────────

_PASTAS_ESPECIAIS: dict[str, str] = {
    "documentos": "Documents", "documents": "Documents",
    "downloads": "Downloads",
    "area de trabalho": "Desktop", "desktop": "Desktop",
    "imagens": "Pictures", "pictures": "Pictures",
    "videos": "Videos", "musicas": "Music", "music": "Music",
}

# ═══════════════════════════════════════════════════════════════════════════════
# ESTRATÉGIAS DE BUSCA (do mais rápido ao mais pesado)
# ═══════════════════════════════════════════════════════════════════════════════


def _try_uri_scheme(nome_n: str) -> str | None:
    """Tenta abrir via URI scheme do Windows (ms-settings:, ms-photos:, etc.)."""
    uri = _URI_SCHEMES.get(nome_n)
    if uri:
        os.startfile(uri)
        return uri
    return None


def _try_alias_shutil(nome_n: str) -> str | None:
    """Tenta alias → shutil.which para encontrar no PATH."""
    cmd = _ALIAS.get(nome_n)
    if not cmd:
        return None
    # Se o alias já é um URI scheme, abre direto
    if cmd.endswith(":"):
        os.startfile(cmd)
        return cmd
    # Se é um .msc (snap-in do Windows), abre com mmc
    if cmd.endswith(".msc"):
        subprocess.Popen(["mmc", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cmd
    exe = shutil.which(cmd)
    if exe:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return exe
    return None


def _try_shutil_direct(nome_n: str) -> str | None:
    """Tenta shutil.which com o nome exato (caso já esteja no PATH)."""
    exe = shutil.which(nome_n)
    if exe:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return exe
    # Tenta com .exe
    exe = shutil.which(nome_n + ".exe")
    if exe:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return exe
    return None


def _try_registry_app_paths(nome_n: str) -> str | None:
    """Busca no registro: HKLM/HKCU → SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths."""
    variantes = [nome_n, nome_n + ".exe"]
    # Adiciona alias se houver
    alias_cmd = _ALIAS.get(nome_n)
    if alias_cmd and not alias_cmd.endswith(":") and not alias_cmd.endswith(".msc"):
        variantes.extend([alias_cmd, alias_cmd + ".exe"])

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for var in variantes:
            try:
                key = winreg.OpenKey(
                    hive,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{var}",
                )
                val, _ = winreg.QueryValueEx(key, None)  # (Default)
                winreg.CloseKey(key)
                if val and os.path.isfile(val):
                    subprocess.Popen(
                        [val], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    return val
            except OSError:
                continue
    return None


def _try_start_menu_lnk(nome_n: str) -> str | None:
    """Varre atalhos (.lnk) do Menu Iniciar para encontrar o app."""
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
    except ImportError:
        # Sem pywin32 → não consegue resolver .lnk, pula
        return None

    pastas_menu = [
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]

    shell = Dispatch("WScript.Shell")
    melhor: str | None = None
    melhor_args: str = ""
    melhor_score = 999

    for pasta in pastas_menu:
        if not os.path.isdir(pasta):
            continue
        for lnk_path in glob.iglob(os.path.join(pasta, "**", "*.lnk"), recursive=True):
            try:
                sc = shell.CreateShortCut(lnk_path)
                target = sc.TargetPath
                args = sc.Arguments or ""
            except Exception:
                continue
            if not target:
                continue

            lnk_name = _normalizar(os.path.splitext(os.path.basename(lnk_path))[0])
            target_name = _normalizar(
                os.path.splitext(os.path.basename(target))[0]
            )

            # Match exato no nome do atalho → score 0
            if nome_n == lnk_name or nome_n == target_name:
                melhor = target
                melhor_args = args
                melhor_score = 0
                break
            # Match parcial no nome do atalho → score 1
            if melhor_score > 1 and (nome_n in lnk_name or nome_n in target_name):
                melhor = target
                melhor_args = args
                melhor_score = 1

        if melhor_score == 0:
            break

    if melhor and os.path.isfile(melhor):
        cmd_list = [melhor] + (melhor_args.split() if melhor_args else [])
        subprocess.Popen(cmd_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return melhor
    return None


def _try_program_files_scan(nome_n: str) -> str | None:
    """Varre Program Files, Program Files (x86) e AppData\\Local buscando .exe com nome similar."""
    raizes = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        p = os.environ.get(var)
        if p and os.path.isdir(p):
            raizes.append(p)
    appdata_local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "")
    if os.path.isdir(appdata_local):
        raizes.append(appdata_local)

    # Também verifica pastas no Desktop do usuário
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop):
        raizes.append(desktop)

    melhor: str | None = None
    melhor_score = 999

    for raiz in raizes:
        try:
            entries = os.listdir(raiz)
        except OSError:
            continue
        for entry in entries:
            pasta_app = os.path.join(raiz, entry)
            if not os.path.isdir(pasta_app):
                continue
            entry_n = _normalizar(entry)
            if nome_n not in entry_n and entry_n not in nome_n:
                continue

            # Busca .exe nessa pasta (até 2 níveis)
            for dp, _, fns in os.walk(pasta_app):
                depth = dp.replace(pasta_app, "").count(os.sep)
                if depth > 2:
                    continue
                for fn in fns:
                    if not fn.lower().endswith(".exe"):
                        continue
                    fn_n = _normalizar(os.path.splitext(fn)[0])
                    full = os.path.join(dp, fn)
                    # Ignora uninstallers e updaters
                    if any(x in fn_n for x in ("uninst", "update", "setup", "crash", "helper")):
                        continue

                    if fn_n == nome_n:
                        melhor = full
                        melhor_score = 0
                    elif melhor_score > 1 and nome_n in fn_n:
                        melhor = full
                        melhor_score = 1
                    elif melhor_score > 2 and fn_n in nome_n:
                        melhor = full
                        melhor_score = 2

                if melhor_score == 0:
                    break
            if melhor_score == 0:
                break

    if melhor:
        subprocess.Popen([melhor], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return melhor
    return None


def _try_windows_search(nome_original: str) -> str:
    """Último recurso: abre o Menu Iniciar, digita o nome e pressiona Enter."""
    import pyautogui
    pyautogui.hotkey("win")
    time.sleep(0.6)
    pyautogui.typewrite(nome_original, interval=0.03)
    time.sleep(1.2)
    pyautogui.press("enter")
    return f"(busca Windows) {nome_original}"


# ── Apps Electron (Squirrel-based: Discord, Slack, Teams, etc.) ──────────────

# app_nome normalizado → (pasta em LOCALAPPDATA, exe name)
_ELECTRON_APPS: dict[str, tuple[str, str]] = {
    "discord": ("Discord", "Discord.exe"),
    "slack": ("slack", "slack.exe"),
    "signal": ("Signal", "Signal.exe"),
    "notion": ("Notion", "Notion.exe"),
    "figma": ("Figma", "Figma.exe"),
    "gitkraken": ("gitkraken", "gitkraken.exe"),
    "postman": ("Postman", "Postman.exe"),
}


def _try_electron_app(nome_n: str) -> str | None:
    """Tenta abrir apps Electron via Update.exe --processStart AppName.exe."""
    info = _ELECTRON_APPS.get(nome_n)
    if not info:
        return None
    pasta, exe_name = info
    local_app = os.environ.get("LOCALAPPDATA", "")
    update_exe = os.path.join(local_app, pasta, "Update.exe")
    if os.path.isfile(update_exe):
        subprocess.Popen(
            [update_exe, "--processStart", exe_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return update_exe
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL: abrir_app
# ═══════════════════════════════════════════════════════════════════════════════


def abrir_app(nome: str) -> str:
    """
    Abre um aplicativo pelo nome usando todas as estratégias disponíveis:
    1. URI scheme (ms-settings, ms-photos, etc.)
    2. Alias manual → shutil.which (PATH)
    3. shutil.which direto (para apps no PATH sem alias)
    4. Registro do Windows (App Paths)
    5. Atalhos do Menu Iniciar (.lnk)
    6. Varredura de Program Files / AppData
    7. Busca no Menu Iniciar do Windows (último recurso)
    """
    nome_limpo = nome.strip().rstrip(".!?,; ")
    nome_n = _normalizar(nome_limpo)
    # Normaliza underscores para espaços (LM às vezes usa bloco_de_notas em vez de "bloco de notas")
    nome_n = nome_n.replace("_", " ").strip()
    # Strip prefixos comuns: "pasta", "a pasta", "meu/minha"
    nome_n = re.sub(r'^(?:a\s+)?(?:pasta\s+(?:d[eoa]\s+)?)', '', nome_n).strip()
    nome_n = re.sub(r'^(?:meu|minha|o\s+meu|a\s+minha)\s+', '', nome_n).strip()
    print(f"[APP] Tentando abrir: '{nome_n}'")

    # ── Defesa: nome é um SITE? Redireciona pro navegador. ─────────────
    # Cobre o caso da rota classificador (que pode chamar abrir_app
    # direto), além do guard que já existe em tool_registry._t_abrir_app.
    _SITES_REDIRECT = {
        "youtube": "https://www.youtube.com",
        "yt": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://twitter.com",
        "x": "https://x.com",
        "instagram": "https://www.instagram.com",
        "insta": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "fb": "https://www.facebook.com",
        "github": "https://github.com",
        "netflix": "https://www.netflix.com",
        "wikipedia": "https://pt.wikipedia.org",
        "wiki": "https://pt.wikipedia.org",
        "chatgpt": "https://chat.openai.com",
        "chat gpt": "https://chat.openai.com",
        "twitch": "https://www.twitch.tv",
        "tiktok": "https://www.tiktok.com",
        "tik tok": "https://www.tiktok.com",
        "linkedin": "https://www.linkedin.com",
        "amazon": "https://www.amazon.com.br",
        "mercado livre": "https://www.mercadolivre.com.br",
        "google": "https://www.google.com",
        "bing": "https://www.bing.com",
        "duckduckgo": "https://duckduckgo.com",
    }
    if nome_n in _SITES_REDIRECT:
        try:
            from comandos import browser_ctrl as _bc
            if _bc.abrir_url_padrao(_SITES_REDIRECT[nome_n]):
                return f"Abrindo {nome_n}, senhor."
        except Exception as _re:
            print(f"[APP] redirect site falhou: {_re}")

    # ── Navegador? Trata aqui antes do fluxo normal ─────────────────────
    # Termo genérico ("navegador", "browser", "internet") → abre o
    # navegador PADRÃO do Windows via os.startfile (respeita UserChoice).
    # Nome específico ("brave", "chrome", "edge") → localiza o exe e
    # lança com --remote-debugging-port=9222 (assim, se depois o usuário
    # pedir pra controlar a página, controle_navegador conecta via CDP).
    _GENERIC = {"navegador", "browser", "internet"}
    _BROWSER_SPECIFIC = {
        "chrome", "google chrome", "brave", "brave browser",
        "edge", "microsoft edge", "opera", "opera gx", "vivaldi",
        "arc", "yandex", "firefox", "mozilla firefox",
    }
    if nome_n in _GENERIC:
        try:
            from comandos import browser_ctrl as _bc
            if _bc.abrir_url_padrao(""):
                return f"Abrindo navegador padrão, senhor."
        except Exception as _ge:
            print(f"[APP] abrir_url_padrao falhou: {_ge}")
    if nome_n in _BROWSER_SPECIFIC:
        try:
            from comandos import browser_ctrl as _bc
            _MAPA = {
                "google chrome": "chrome",
                "brave browser": "brave",
                "microsoft edge": "edge",
                "opera gx": "opera_gx",
                "mozilla firefox": "firefox",
            }
            chave = _MAPA.get(nome_n, nome_n)
            instalados = dict(_bc.listar_navegadores_instalados())
            exe = instalados.get(chave)
            if exe and os.path.isfile(exe):
                # Lança com CDP port (só faz sentido p/ Chromium-based).
                args = [exe]
                if chave != "firefox":  # firefox não tem flag CDP
                    import config as _cfg
                    cdp = int(getattr(_cfg, "BROWSER_CDP_PORT", 9222))
                    args.append(f"--remote-debugging-port={cdp}")
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Abrindo {nome_limpo}, senhor."
            # Não encontrei o navegador específico pedido
            disponiveis = ", ".join(n for n in instalados.keys()) or "nenhum"
            return f"{nome_limpo} não está instalado, senhor. Disponíveis: {disponiveis}."
        except Exception as _be:
            print(f"[APP] handler de navegador específico falhou: {_be} — fluxo normal.")

    # ── Cache rápido de apps instalados ──────────────────────────────────
    try:
        from entity.app_detector import find_app as _cache_find
        _cached_path = _cache_find(nome_n)
        if _cached_path and os.path.isfile(_cached_path):
            print(f"[APP] Cache hit: '{nome_n}' → {_cached_path}")
            # Apps Electron usam Update.exe como launcher — precisam de
            # --processStart <App.exe> para abrir o app de verdade.
            if os.path.basename(_cached_path).lower() == "update.exe":
                _el_info = _ELECTRON_APPS.get(nome_n)
                if _el_info:
                    _, _exe_name = _el_info
                    subprocess.Popen(
                        [_cached_path, "--processStart", _exe_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    return f"Abrindo {nome_limpo}, senhor."
                # Update.exe sem mapeamento → tenta encontrar o .exe real na mesma pasta
                _app_dir = os.path.dirname(_cached_path)
                _app_dir_parent = os.path.dirname(_app_dir)
                for _root, _dirs, _files in os.walk(_app_dir_parent):
                    for _f in _files:
                        if _f.lower().endswith(".exe") and _f.lower() != "update.exe":
                            _real = os.path.join(_root, _f)
                            if os.path.isfile(_real):
                                subprocess.Popen(
                                    [_cached_path, "--processStart", _f],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                )
                                return f"Abrindo {nome_limpo}, senhor."
            else:
                subprocess.Popen([_cached_path])
            return f"Abrindo {nome_limpo}, senhor."
    except Exception as _ce:
        print(f"[APP] Cache lookup falhou: {_ce}")

    # ── Pasta especial? ──────────────────────────────────────────────────
    pasta_nome = _PASTAS_ESPECIAIS.get(nome_n)
    if pasta_nome:
        caminho = os.path.join(os.path.expanduser("~"), pasta_nome)
        if os.path.isdir(caminho):
            os.startfile(caminho)
            return f"Abrindo pasta {pasta_nome}, senhor."

    # ── Estratégias em ordem de prioridade ───────────────────────────────
    estrategias = [
        ("URI scheme", lambda: _try_uri_scheme(nome_n)),
        ("alias/PATH", lambda: _try_alias_shutil(nome_n)),
        ("PATH direto", lambda: _try_shutil_direct(nome_n)),
        ("Registro (App Paths)", lambda: _try_registry_app_paths(nome_n)),
        ("Electron (Update.exe)", lambda: _try_electron_app(nome_n)),
        ("Menu Iniciar (.lnk)", lambda: _try_start_menu_lnk(nome_n)),
        ("Program Files scan", lambda: _try_program_files_scan(nome_n)),
    ]

    for label, fn in estrategias:
        try:
            result = fn()
            if result:
                print(f"[APP] Encontrado via {label}: {result}")
                return f"Abrindo {nome_limpo}, senhor."
        except Exception as e:
            print(f"[APP] {label} falhou: {e}")
            continue

    # ── Fallback final: busca no Windows ─────────────────────────────────
    # NUNCA retornar mensagem de sucesso falsa. Se nada foi encontrado,
    # avisar honestamente. _try_windows_search abre a busca do Menu Iniciar
    # mas NÃO é garantia de que algo vai abrir — por isso a mensagem é honesta.
    print(f"[APP] Nenhuma estratégia direta funcionou para '{nome_n}'.")
    try:
        _try_windows_search(nome_limpo)
        return f"Não encontrei {nome_limpo} instalado, senhor. Abri a busca do Windows."
    except Exception as e:
        return f"Não consegui abrir {nome_limpo}, senhor: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# NAVEGAÇÃO IN-APP — atalhos de teclado por aplicativo
# ═══════════════════════════════════════════════════════════════════════════════

# Mapeamento: app → { ação → sequência de teclas/passos }
# Cada entrada pode ser:
#   - tuple de teclas para hotkey  ex: ("ctrl", "k")
#   - list de steps sequenciais    ex: [("hotkey", "ctrl", "k"), ("wait", 0.3), ("type", "geral"), ("press", "enter")]
_APP_ATALHOS: dict[str, dict[str, list | tuple]] = {
    "discord": {
        # Navegação (Ctrl+K = Quick Switcher — busca canais, servidores, DMs)
        "buscar": ("ctrl", "k"),
        "buscar canal": ("ctrl", "k"),
        "buscar servidor": ("ctrl", "k"),
        "ir para": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "canal": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "servidor": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "dm": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "conversa": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "mensagem direta": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        "chat": [("hotkey", "ctrl", "k"), ("wait", 0.8), ("type", "{arg}"), ("wait", 1.2), ("press", "enter")],
        # Comunicação
        "mutar": ("ctrl", "shift", "m"),
        "desmutar": ("ctrl", "shift", "m"),
        "ensurdecer": ("ctrl", "shift", "d"),
        "desensurdecer": ("ctrl", "shift", "d"),
        # Geral
        "configuracoes": ("ctrl", ","),
        "fechar": ("escape",),
        "marcar como lido": ("ctrl", "shift", "e"),
    },
    "chrome": {
        "nova aba": ("ctrl", "t"),
        "fechar aba": ("ctrl", "w"),
        "reabrir aba": ("ctrl", "shift", "t"),
        "proxima aba": ("ctrl", "tab"),
        "aba anterior": ("ctrl", "shift", "tab"),
        "barra de endereco": ("ctrl", "l"),
        "pesquisar": ("ctrl", "l"),
        "ir para": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "{arg}"), ("press", "enter")],
        "historico": ("ctrl", "h"),
        "downloads": ("ctrl", "j"),
        "favoritos": ("ctrl", "shift", "o"),
        "nova janela": ("ctrl", "n"),
        "janela anonima": ("ctrl", "shift", "n"),
        "atualizar": ("f5",),
        "zoom in": ("ctrl", "+"),
        "zoom out": ("ctrl", "-"),
        "tela cheia": ("f11",),
        "ferramentas do desenvolvedor": ("f12",),
        "configuracoes": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "chrome://settings"), ("press", "enter")],
    },
    "edge": {
        "nova aba": ("ctrl", "t"),
        "fechar aba": ("ctrl", "w"),
        "pesquisar": ("ctrl", "l"),
        "ir para": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "{arg}"), ("press", "enter")],
        "historico": ("ctrl", "h"),
        "downloads": ("ctrl", "j"),
        "favoritos": ("ctrl", "shift", "o"),
        "copilot": ("ctrl", "shift", "."),
    },
    "firefox": {
        "nova aba": ("ctrl", "t"),
        "fechar aba": ("ctrl", "w"),
        "pesquisar": ("ctrl", "l"),
        "ir para": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "{arg}"), ("press", "enter")],
        "historico": ("ctrl", "h"),
        "downloads": ("ctrl", "j"),
    },
    "vscode": {
        "command palette": ("ctrl", "shift", "p"),
        "paleta de comandos": ("ctrl", "shift", "p"),
        "buscar arquivo": ("ctrl", "p"),
        "abrir arquivo": ("ctrl", "p"),
        "abrir": [("hotkey", "ctrl", "p"), ("wait", 0.3), ("type", "{arg}"), ("wait", 0.5), ("press", "enter")],
        "ir para": [("hotkey", "ctrl", "p"), ("wait", 0.3), ("type", "{arg}"), ("wait", 0.5), ("press", "enter")],
        "terminal": ("ctrl", "`"),
        "buscar texto": ("ctrl", "shift", "f"),
        "fechar aba": ("ctrl", "w"),
        "nova aba": ("ctrl", "n"),
        "configuracoes": ("ctrl", ","),
        "extensoes": ("ctrl", "shift", "x"),
        "explorer": ("ctrl", "shift", "e"),
        "sidebar": ("ctrl", "b"),
    },
    "spotify": {
        "buscar": ("ctrl", "l"),
        "pesquisar": ("ctrl", "l"),
        "ir para": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "{arg}"), ("press", "enter")],
    },
    "explorer": {
        "nova janela": ("ctrl", "n"),
        "barra de endereco": ("ctrl", "l"),
        "ir para": [("hotkey", "ctrl", "l"), ("wait", 0.3), ("type", "{arg}"), ("press", "enter")],
        "buscar": ("ctrl", "e"),
        "pesquisar": ("ctrl", "e"),
        "nova pasta": ("ctrl", "shift", "n"),
    },
    "notepad": {
        "novo": ("ctrl", "n"),
        "abrir": ("ctrl", "o"),
        "salvar": ("ctrl", "s"),
        "salvar como": ("ctrl", "shift", "s"),
        "buscar": ("ctrl", "h"),
        "substituir": ("ctrl", "h"),
    },
    "obs": {
        "iniciar gravacao": [("hotkey", "ctrl", "shift", "r")],
        "parar gravacao": [("hotkey", "ctrl", "shift", "r")],
        "iniciar stream": [("hotkey", "ctrl", "shift", "s")],
        "parar stream": [("hotkey", "ctrl", "shift", "s")],
    },
}

# Aliases de nome de app → chave em _APP_ATALHOS
_APP_ALIASES: dict[str, str] = {
    "google chrome": "chrome", "google": "chrome",
    "microsoft edge": "edge",
    "visual studio code": "vscode", "vs code": "vscode", "code": "vscode",
    "obs studio": "obs",
    "explorador de arquivos": "explorer", "explorador": "explorer",
    "bloco de notas": "notepad",
}


def _executar_step(step, arg: str = ""):
    """Executa um passo de automação (hotkey, type, press, wait)."""
    import pyautogui
    if isinstance(step, tuple) and len(step) >= 2 and step[0] == "hotkey":
        pyautogui.hotkey(*step[1:])
    elif isinstance(step, tuple) and len(step) == 2 and step[0] == "wait":
        time.sleep(step[1])
    elif isinstance(step, tuple) and len(step) == 2 and step[0] == "type":
        texto = step[1].replace("{arg}", arg)
        # typewrite só funciona com ASCII; para Unicode usa pyperclip + ctrl+v
        try:
            texto.encode("ascii")
            pyautogui.typewrite(texto, interval=0.02)
        except UnicodeEncodeError:
            import pyperclip
            pyperclip.copy(texto)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
    elif isinstance(step, tuple) and len(step) == 2 and step[0] == "press":
        pyautogui.press(step[1])
    else:
        # Tupla simples de teclas → hotkey
        pyautogui.hotkey(*step)


def navegar_app(app_nome: str, acao: str, argumento: str = "") -> str:
    """
    Executa uma ação de navegação dentro de um app via atalhos de teclado.
    Ex: navegar_app("discord", "canal", "geral")
    """
    app_n = _normalizar(app_nome)
    acao_n = _normalizar(acao)

    # Resolve aliases
    app_key = _APP_ALIASES.get(app_n, app_n)

    atalhos = _APP_ATALHOS.get(app_key)
    if not atalhos:
        return (f"Não tenho atalhos mapeados para '{app_nome}', senhor. "
                f"Posso abrir o aplicativo se desejar.")

    # Busca a ação (exata, depois parcial)
    sequencia = atalhos.get(acao_n)
    if not sequencia:
        for k, v in atalhos.items():
            if acao_n in k or k in acao_n:
                sequencia = v
                break

    if not sequencia:
        acoes_disp = ", ".join(sorted(atalhos.keys()))
        return (f"Não conheço a ação '{acao}' no {app_nome}, senhor. "
                f"Ações disponíveis: {acoes_disp}")

    try:
        import pyautogui

        # Primeiro, traz a janela do app para frente
        _focar_janela(app_key)
        time.sleep(0.3)

        if isinstance(sequencia, list):
            # Sequência de passos
            for step in sequencia:
                _executar_step(step, argumento)
        else:
            # Hotkey simples
            pyautogui.hotkey(*sequencia)

        desc_acao = acao_n
        if argumento:
            desc_acao += f" '{argumento}'"
        return f"Ação '{desc_acao}' executada no {app_nome}, senhor."

    except Exception as e:
        return f"Erro ao executar ação no {app_nome}: {e}"


def _focar_janela(app_key: str):
    """Tenta trazer a janela do app para frente."""
    try:
        import pygetwindow as gw
        # Mapeamento de app_key → possíveis títulos de janela
        title_hints = {
            "discord": "Discord",
            "chrome": "Google Chrome",
            "edge": "Edge",
            "firefox": "Firefox",
            "vscode": "Visual Studio Code",
            "spotify": "Spotify",
            "explorer": "Explorador de Arquivos",
            "notepad": "Bloco de Notas",
            "obs": "OBS",
        }
        hint = title_hints.get(app_key, app_key)
        janelas = [w for w in gw.getAllWindows() if hint.lower() in w.title.lower()]
        if janelas:
            win = janelas[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            return True
    except Exception:
        pass
    return False



# ═══════════════════════════════════════════════════════════════════════════════
# NAVEGAÇÃO VISUAL (screenshot → VL model → pyautogui)
# ═══════════════════════════════════════════════════════════════════════════════

_NAV_SYSTEM = (
    "Você é um assistente de automação de PC. "
    "Analise a screenshot e execute EXATAMENTE o que foi pedido.\n"
    "Responda SOMENTE com JSON puro, sem markdown, sem ```.\n\n"
    "Formato de resposta (APENAS um destes):\n"
    '{"acao": "click", "x": 123, "y": 456, "descricao": "botão X"}\n'
    '{"acao": "click_duplo", "x": 123, "y": 456, "descricao": "ícone Y"}\n'
    '{"acao": "click_direito", "x": 123, "y": 456, "descricao": "menu Z"}\n'
    '{"acao": "tipo", "texto": "algum texto", "descricao": "campo de busca"}\n'
    '{"acao": "tecla", "teclas": ["ctrl", "k"], "descricao": "atalho de busca"}\n'
    '{"acao": "scroll", "direcao": "baixo", "quantidade": 3, "descricao": "rolar lista"}\n'
    '{"acao": "nao_encontrado", "descricao": "motivo pelo qual não encontrou"}\n\n'
    "REGRAS:\n"
    "- Coordenadas x,y são pixels ABSOLUTOS na screenshot.\n"
    "- Se o elemento pedido não está visível, diga nao_encontrado.\n"
    "- NUNCA invente coordenadas. Só retorne se REALMENTE vê o elemento.\n"
    "- Se precisar rolar para encontrar, use scroll.\n"
    "- Responda APENAS o JSON, nada mais."
)


def _capturar_screenshot_b64(max_w: int = 1280) -> tuple:
    """Captura screenshot, retorna (base64_str, largura_real, altura_real, escala)."""
    import base64, io
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except ImportError:
        import pyautogui
        img = pyautogui.screenshot()

    real_w, real_h = img.size
    if real_w > max_w:
        escala = real_w / max_w
        img = img.resize((max_w, int(real_h / escala)))
    else:
        escala = 1.0

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return b64, real_w, real_h, escala


def _chamar_vl(lm_client, model: str, image_b64: str, prompt: str,
               max_tokens: int = 256) -> str:
    """Chama o modelo VL do LM Studio com imagem + prompt."""
    msgs = [
        {"role": "system", "content": _NAV_SYSTEM},
        {"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]},
    ]
    resp = lm_client.chat.completions.create(
        model=model, messages=msgs,
        max_tokens=max_tokens, temperature=0.1,
    )
    return (resp.choices[0].message.content or "").strip()


def _parse_acao_json(texto: str) -> dict | None:
    """Extrai o JSON de ação da resposta do VL (tolerante a lixo ao redor)."""
    import json as _json
    # Tenta parse direto
    texto = texto.strip()
    # Remove possível markdown code fence
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return _json.loads(texto)
    except _json.JSONDecodeError:
        # Tenta encontrar JSON dentro do texto
        import re as _re
        m = _re.search(r"\{.*\}", texto, _re.S)
        if m:
            try:
                return _json.loads(m.group())
            except _json.JSONDecodeError:
                pass
    return None


def _executar_acao_visual(acao: dict, escala: float = 1.0) -> str:
    """Executa a ação retornada pelo VL model."""
    import pyautogui
    tipo = acao.get("acao", "")
    desc = acao.get("descricao", "")

    if tipo == "nao_encontrado":
        return f"Não encontrei na tela: {desc}"

    if tipo in ("click", "click_duplo", "click_direito"):
        x = int(acao.get("x", 0) * escala)
        y = int(acao.get("y", 0) * escala)
        if x <= 0 or y <= 0:
            return f"Coordenadas inválidas para '{desc}'."
        if tipo == "click":
            pyautogui.click(x, y)
        elif tipo == "click_duplo":
            pyautogui.doubleClick(x, y)
        elif tipo == "click_direito":
            pyautogui.rightClick(x, y)
        return f"Cliquei em '{desc}' ({x}, {y})."

    if tipo == "tipo":
        texto = acao.get("texto", "")
        if texto:
            try:
                texto.encode("ascii")
                pyautogui.typewrite(texto, interval=0.02)
            except UnicodeEncodeError:
                import pyperclip
                pyperclip.copy(texto)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.1)
            return f"Digitei '{texto}' em '{desc}'."
        return "Nenhum texto para digitar."

    if tipo == "tecla":
        teclas = acao.get("teclas", [])
        if teclas:
            pyautogui.hotkey(*teclas)
            return f"Pressionei {'+'.join(teclas)} ({desc})."
        return "Nenhuma tecla especificada."

    if tipo == "scroll":
        direcao = acao.get("direcao", "baixo")
        qtd = int(acao.get("quantidade", 3))
        clicks = -qtd if direcao in ("baixo", "down") else qtd
        pyautogui.scroll(clicks)
        return f"Scroll {direcao} ({qtd}x) — {desc}."

    return f"Ação desconhecida: {tipo}"


def navegar_visual(lm_client, model: str, instrucao: str,
                   app_nome: str = "", max_steps: int = 2,
                   status_callback=None) -> str:
    """
    Navegação visual: tira screenshot, pede ao VL model onde clicar, executa.
    Repete até max_steps vezes (para ações em 2 passos, ex: abrir busca → clicar resultado).

    Args:
        lm_client: cliente OpenAI apontando para LM Studio
        model: nome do modelo VL (ex: LMSTUDIO_MODEL)
        instrucao: o que o usuário quer fazer (ex: "ir no canal geral do discord")
        app_nome: nome do app (para contexto, opcional)
        max_steps: máximo de screenshots/ações (1 ou 2)
        status_callback: fn(msg) para atualizar status na UI (opcional)

    Returns:
        Descrição do que foi feito.
    """
    resultados = []

    for step in range(max_steps):
        if status_callback:
            status_callback(f"👁  Analisando tela (passo {step + 1}/{max_steps})...")

        # 1. Captura screenshot
        b64, real_w, real_h, escala = _capturar_screenshot_b64(max_w=1280)

        # 2. Monta prompt
        if step == 0:
            prompt = (
                f"O usuário quer: '{instrucao}'.\n"
                f"{'App alvo: ' + app_nome + '. ' if app_nome else ''}"
                f"A screenshot tem {real_w}x{real_h} pixels (redimensionada para visualização).\n"
                f"Diga EXATAMENTE onde clicar ou o que fazer para alcançar o objetivo.\n"
                f"Responda SOMENTE com JSON."
            )
        else:
            prompt = (
                f"Passo anterior: {resultados[-1]}\n"
                f"Objetivo original: '{instrucao}'.\n"
                f"A tela agora mudou. O que devo fazer agora para completar a ação?\n"
                f"Se o objetivo já foi alcançado, responda: "
                '{"acao": "nao_encontrado", "descricao": "objetivo ja alcancado"}\n'
                f"Responda SOMENTE com JSON."
            )

        # 3. Chama VL model
        try:
            resposta_raw = _chamar_vl(lm_client, model, b64, prompt, max_tokens=200)
            print(f"[NAV_VISUAL] step={step} resposta={resposta_raw[:200]}")
        except Exception as e:
            return f"Erro ao analisar tela: {e}"

        # 4. Parse da resposta
        acao = _parse_acao_json(resposta_raw)
        if not acao:
            return f"Não consegui interpretar a resposta do modelo: {resposta_raw[:150]}"

        # 5. Verifica se é "não encontrado" ou "já alcançado"
        if acao.get("acao") == "nao_encontrado":
            desc = acao.get("descricao", "")
            if "alcancado" in desc.lower() or "concluido" in desc.lower():
                if resultados:
                    return " → ".join(resultados) + " ✓"
            return f"Não encontrei na tela: {desc}"

        # 6. Executa a ação
        resultado = _executar_acao_visual(acao, escala)
        resultados.append(resultado)
        print(f"[NAV_VISUAL] step={step} executado: {resultado}")

        # Se só tem 1 step, ou é o último, retorna
        if step >= max_steps - 1:
            break

        # Aguarda a UI reagir antes do próximo screenshot
        time.sleep(1.5)

    return " → ".join(resultados) if resultados else "Nenhuma ação executada."


def abrir_e_navegar(app_nome: str, acao: str = "", argumento: str = "",
                    lm_client=None, lm_model: str = "",
                    status_callback=None) -> str:
    """
    Abre um app (se não estiver aberto) e opcionalmente navega nele.
    Tenta atalhos de teclado primeiro. Se não houver atalho mapeado E
    lm_client estiver disponível, usa navegação visual (screenshot → VL → click).

    Ex: abrir_e_navegar("discord", "canal", "geral")
    Ex: abrir_e_navegar("discord", "canal", "geral", lm_client=lm, lm_model="qwen3-vl")
    """
    app_n = _normalizar(app_nome)
    app_key = _APP_ALIASES.get(app_n, app_n)

    # Verifica se o app já está aberto
    ja_aberto = _focar_janela(app_key)

    if not ja_aberto:
        resultado = abrir_app(app_nome)
        if "não consegui" in resultado.lower():
            return resultado
        # Apps Electron (Discord, Slack) demoram mais para carregar
        _HEAVY_APPS = {"discord", "slack", "teams", "notion", "figma", "postman"}
        wait_s = 6.0 if app_key in _HEAVY_APPS else 3.0
        if status_callback:
            status_callback(f"⏳  Aguardando {app_nome} carregar...")
        time.sleep(wait_s)
        # Tenta focar até conseguir (max 3 tentativas)
        for _ in range(3):
            if _focar_janela(app_key):
                break
            time.sleep(1.5)
        time.sleep(0.5)

    if not acao:
        return f"{'Alternando para' if ja_aberto else 'Abrindo'} {app_nome}, senhor."

    # ── Tenta atalhos de teclado mapeados ────────────────────────────────
    acao_n = _normalizar(acao)
    atalhos = _APP_ATALHOS.get(app_key)

    # Verifica se tem atalho exato ou parcial
    sequencia = None
    if atalhos:
        sequencia = atalhos.get(acao_n)
        if not sequencia:
            for k, v in atalhos.items():
                if acao_n in k or k in acao_n:
                    sequencia = v
                    break

    if sequencia:
        # Tem atalho → executa via teclado
        try:
            import pyautogui
            if isinstance(sequencia, list):
                for step in sequencia:
                    _executar_step(step, argumento)
            else:
                pyautogui.hotkey(*sequencia)

            desc = acao_n
            if argumento:
                desc += f" '{argumento}'"
            return f"Ação '{desc}' executada no {app_nome}, senhor."
        except Exception as e:
            # Se o atalho falhar, tenta visão como fallback
            print(f"[NAV] Atalho falhou ({e}), tentando visão...")

    # ── Sem atalho mapeado (ou falhou) → tenta navegação visual ──────────
    if lm_client and lm_model:
        instrucao = f"{acao}"
        if argumento:
            instrucao += f" {argumento}"
        instrucao += f" no {app_nome}"

        if status_callback:
            status_callback(f"👁  Navegando visualmente no {app_nome}...")

        return navegar_visual(
            lm_client, lm_model, instrucao,
            app_nome=app_nome, max_steps=2,
            status_callback=status_callback,
        )

    # ── Sem atalho e sem VL → reporta ───────────────────────────────────
    if atalhos:
        acoes_disp = ", ".join(sorted(atalhos.keys()))
        return (f"Não conheço a ação '{acao}' no {app_nome}, senhor. "
                f"Ações disponíveis: {acoes_disp}")
    return (f"Não tenho atalhos mapeados para '{app_nome}', senhor. "
            f"Tentei abrir o aplicativo — verifique se está visível.")
