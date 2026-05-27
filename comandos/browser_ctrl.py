"""Controle de navegador via Playwright usando o navegador JÁ INSTALADO do usuário.

NÃO baixa Chromium próprio do Playwright — detecta Chrome/Edge/Brave/Opera/
Vivaldi/Arc instalados no Windows e usa o executável deles diretamente.

Mantém um perfil isolado do JARVIS em `%LOCALAPPDATA%\\JARVIS\\browser_profile\\
<browser>` (logins persistem entre sessões; não conflita com o navegador pessoal).
"""

from __future__ import annotations

import concurrent.futures as _cf
import os
import sys
import threading
from typing import Optional

# ── Thread-safety: Playwright sync API exige uma única thread dona ────────────────
# O wake loop cria várias threads e cada uma chama funções do browser_ctrl.
# Sinão, Playwright lança "cannot switch to a different thread".
# Solução: executor de 1 worker — todas as opções correm na mesma thread.
_EXEC: _cf.ThreadPoolExecutor = _cf.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="jarvis-browser"
)


def _run_browser(fn, *args, **kwargs):
    """Executa fn na thread dedicada do browser. Propaga exceções ao caller."""
    current = threading.current_thread().name
    if current.startswith("jarvis-browser"):
        return fn(*args, **kwargs)  # já está na thread certa
    return _EXEC.submit(fn, *args, **kwargs).result(timeout=35)

# ── Detecção de navegadores instalados (Windows) ───────────────────────────

# Lista priorizada: nome amigável, channel-key, lista de paths candidatos.
# Pesquisar em Program Files, Program Files (x86) e LocalAppData.
_PROG = os.environ.get("ProgramFiles", r"C:\Program Files")
_PROG86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
_LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))

_CANDIDATOS: list[tuple[str, list[str]]] = [
    ("brave", [
        rf"{_PROG}\BraveSoftware\Brave-Browser\Application\brave.exe",
        rf"{_PROG86}\BraveSoftware\Brave-Browser\Application\brave.exe",
        rf"{_LOCAL}\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]),
    ("chrome", [
        rf"{_PROG}\Google\Chrome\Application\chrome.exe",
        rf"{_PROG86}\Google\Chrome\Application\chrome.exe",
        rf"{_LOCAL}\Google\Chrome\Application\chrome.exe",
    ]),
    ("edge", [
        rf"{_PROG}\Microsoft\Edge\Application\msedge.exe",
        rf"{_PROG86}\Microsoft\Edge\Application\msedge.exe",
    ]),
    ("opera", [
        rf"{_LOCAL}\Programs\Opera\opera.exe",
        rf"{_PROG}\Opera\opera.exe",
        rf"{_PROG86}\Opera\opera.exe",
    ]),
    ("opera_gx", [
        rf"{_LOCAL}\Programs\Opera GX\opera.exe",
    ]),
    ("vivaldi", [
        rf"{_LOCAL}\Vivaldi\Application\vivaldi.exe",
        rf"{_PROG}\Vivaldi\Application\vivaldi.exe",
        rf"{_PROG86}\Vivaldi\Application\vivaldi.exe",
    ]),
    ("arc", [
        rf"{_LOCAL}\Microsoft\Arc\Application\Arc.exe",
        rf"{_LOCAL}\Arc\Application\Arc.exe",
    ]),
    ("yandex", [
        rf"{_LOCAL}\Yandex\YandexBrowser\Application\browser.exe",
    ]),
]


def listar_navegadores_instalados() -> list[tuple[str, str]]:
    """Retorna [(nome, exe_path), ...] dos navegadores Chromium-based detectados.

    Procura em paths conhecidos + Registro do Windows (StartMenuInternet),
    que pega instalações em locais não-padrão (Scoop, Chocolatey, etc.).
    """
    achados: list[tuple[str, str]] = []
    nomes_vistos: set[str] = set()
    for nome, paths in _CANDIDATOS:
        for p in paths:
            if os.path.isfile(p):
                achados.append((nome, p))
                nomes_vistos.add(nome)
                break
    # Fallback: Registro do Windows — HKLM/HKCU\Software\Clients\StartMenuInternet
    try:
        import winreg  # type: ignore
        _REG_MAP = {
            "brave": ["brave"],
            "chrome": ["chrome", "google chrome"],
            "edge": ["edge", "microsoft edge"],
            "opera": ["opera"],
            "opera_gx": ["opera gx"],
            "vivaldi": ["vivaldi"],
            "firefox": ["firefox", "mozilla firefox"],
            "yandex": ["yandex"],
        }
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                root = winreg.OpenKey(hive, r"SOFTWARE\Clients\StartMenuInternet")
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i); i += 1
                    except OSError:
                        break
                    sub_low = sub.lower()
                    matched_key = None
                    for k, aliases in _REG_MAP.items():
                        if any(a in sub_low for a in aliases) and k not in nomes_vistos:
                            matched_key = k
                            break
                    if not matched_key:
                        continue
                    try:
                        cmd_key = winreg.OpenKey(root, sub + r"\shell\open\command")
                        cmd, _ = winreg.QueryValueEx(cmd_key, None)
                        cmd = (cmd or "").strip().strip('"')
                        if cmd and os.path.isfile(cmd):
                            achados.append((matched_key, cmd))
                            nomes_vistos.add(matched_key)
                    except OSError:
                        pass
            finally:
                winreg.CloseKey(root)
    except Exception:
        pass
    return achados


def detectar_navegador_padrao_windows() -> Optional[tuple[str, str]]:
    """Lê o registro do Windows para descobrir qual navegador o usuário
    definiu como PADRÃO para http(s). Retorna (chave_normalizada, exe_path)
    ou None se não conseguir resolver.

    Procura em:
      HKCU\\Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\http\\UserChoice
    """
    try:
        import winreg  # type: ignore
    except Exception:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        progid, _ = winreg.QueryValueEx(key, "ProgId")
        winreg.CloseKey(key)
    except OSError:
        return None
    if not progid:
        return None
    # Resolve ProgId → exe
    # Ex: "ChromeHTML", "BraveHTML", "MSEdgeHTM", "FirefoxURL-308046B0AF4A39CB",
    #     "OperaStable", "VivaldiHTM", "YandexHTML"
    progid_low = progid.lower()
    _MAP = [
        ("brave",    ["bravehtml", "brave"]),
        ("chrome",   ["chromehtml", "chrome"]),
        ("edge",     ["msedgehtm", "msedge", "edgehtm"]),
        ("firefox",  ["firefoxurl", "firefoxhtml", "firefox"]),
        ("opera",    ["operastable", "opera"]),
        ("opera_gx", ["operagxstable"]),
        ("vivaldi",  ["vivaldihtm", "vivaldi"]),
        ("yandex",   ["yandexhtml", "yandex"]),
        ("arc",      ["archtm", "arc"]),
    ]
    matched = None
    for key_norm, aliases in _MAP:
        if any(a in progid_low for a in aliases):
            matched = key_norm
            break
    if not matched:
        return None
    # Tenta achar o exe pela detecção normal
    for nome, exe in listar_navegadores_instalados():
        if nome == matched:
            return matched, exe
    # Fallback: pega o command direto do ProgId
    try:
        cmd_key = winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            rf"{progid}\shell\open\command",
        )
        cmd, _ = winreg.QueryValueEx(cmd_key, None)
        winreg.CloseKey(cmd_key)
        cmd = (cmd or "").strip()
        # Extrai o exe path (primeiro token entre aspas, ou primeiro até espaço)
        if cmd.startswith('"'):
            exe_path = cmd.split('"', 2)[1]
        else:
            exe_path = cmd.split(" ", 1)[0]
        if exe_path and os.path.isfile(exe_path):
            return matched, exe_path
    except OSError:
        pass
    return None


def _resolver_navegador(preferido: Optional[str] = None) -> tuple[str, str]:
    """Retorna (nome, exe_path) do navegador a usar.

    Ordem de prioridade:
      1. `preferido` explícito (param ou config.BROWSER_PREFERRED).
         Se pedido e não instalado → ERRO honesto (não silencia).
      2. Navegador PADRÃO do Windows (registro UserChoice).
      3. Primeiro detectado (Brave > Chrome > Edge > Opera > …).
    """
    instalados = listar_navegadores_instalados()
    if not instalados:
        raise RuntimeError(
            "Nenhum navegador Chromium-based (Chrome/Edge/Brave/Opera/Vivaldi/"
            "Arc/Yandex) foi encontrado no sistema."
        )
    if preferido:
        pref_l = preferido.strip().lower().replace(" ", "_")
        for nome, exe in instalados:
            if nome == pref_l or pref_l in nome:
                return nome, exe
        nomes_disp = ", ".join(n for n, _ in instalados)
        raise RuntimeError(
            f"{preferido} não está instalado. Disponíveis: {nomes_disp}."
        )
    # Sem preferência explícita → tenta navegador padrão do Windows
    padrao = detectar_navegador_padrao_windows()
    if padrao:
        return padrao
    return instalados[0]


def abrir_url_padrao(url: str = "") -> bool:
    """Abre `url` (ou só lança o navegador, se vazio) usando o NAVEGADOR
    PADRÃO do Windows. Robusto: funciona com o navegador fechado, em
    qualquer thread.

    Estratégia (em ordem):
      1. Se há URL e SEM override de navegador → `os.startfile(url)`.
         O shell do Windows resolve a associação UserChoice e abre o
         navegador padrão JÁ ATIVANDO a janela (foco correto, sem
         abrir oculto). É o caminho que melhor lida com "navegador
         fechado" vs "instância já rodando".
      2. Senão, ou se (1) falhar: localiza o exe (override
         BROWSER_PREFERRED → padrão Windows → 1º detectado) e
         `subprocess.Popen([exe, url])` (sem creationflags estranhas,
         pra GUI aparecer normalmente).
      3. Fallback final: `webbrowser.open`.

    Retorna True se conseguiu disparar a abertura.
    """
    import subprocess as _sp
    import os as _os
    import threading as _th
    import time as _t

    # Log de diagnóstico — quando chamado de dentro do JARVIS.exe não
    # temos console, então gravamos num arquivo pra inspeção posterior.
    def _diag(msg: str) -> None:
        try:
            log_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "browser_diag.log")
            log_path = _os.path.abspath(log_path)
            with open(log_path, "a", encoding="utf-8") as f:
                ts = _t.strftime("%Y-%m-%d %H:%M:%S")
                tname = _th.current_thread().name
                f.write(f"[{ts}][{tname}] {msg}\n")
        except Exception:
            pass

    url = (url or "").strip()
    _diag(f"=== abrir_url_padrao(url={url!r}) ===")

    # COM init pra thread atual (necessário pra os.startfile / ShellExecute
    # funcionar fora da thread principal, especialmente dentro do
    # JARVIS.exe que é um windowed PyInstaller exe).
    try:
        import pythoncom  # type: ignore
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        _diag("CoInitializeEx OK")
    except Exception as _ce:
        _diag(f"CoInitializeEx falhou (talvez já init): {_ce}")

    # Verifica se usuário pediu override de navegador específico
    pref = ""
    try:
        import config as _cfg
        pref = (getattr(_cfg, "BROWSER_PREFERRED", "") or "").strip().lower()
    except Exception:
        pass
    _diag(f"BROWSER_PREFERRED={pref!r}")

    # Se URL vazia, usa uma página default — assim NUNCA caímos no caso
    # de "brave.exe sem args + background process intercepta + nada abre".
    url_efetiva = url or "https://www.google.com"

    # ATENÇÃO: NÃO usamos os.startfile aqui. Quando JARVIS roda como exe
    # ele está dentro de um Job Object (vide main.py), e os.startfile
    # delega ao shell, que herda o job. Chromium (Brave/Chrome/Edge)
    # detecta job e altera comportamento — abre o processo mas SEM janela.
    # Solução: SEMPRE lançamos via Popen com CREATE_BREAKAWAY_FROM_JOB
    # (escapa do job → comportamento normal).
    # Fallback final é webbrowser (que também usa Popen em python moderno).

    # (2) Localiza exe e lança via Popen — passando --new-window pra
    # garantir que uma janela visível seja criada (mesmo se há serviços
    # background do Brave/Chrome rodando que interceptariam o launch).
    exe_path = None
    try:
        if pref:
            for k, p in listar_navegadores_instalados():
                if k == pref or pref in k:
                    exe_path = p
                    break
        if not exe_path:
            det = detectar_navegador_padrao_windows()
            if det:
                exe_path = det[1]
        if not exe_path:
            inst = listar_navegadores_instalados()
            if inst:
                exe_path = inst[0][1]
    except Exception as e:
        _diag(f"resolução de exe falhou: {e}")
    _diag(f"exe_path={exe_path!r}")
    if exe_path and _os.path.isfile(exe_path):
        try:
            # --new-window força criação de janela mesmo com background
            # services rodando. É flag Chromium (brave/chrome/edge/opera).
            exe_lower = exe_path.lower()
            is_chromium = any(b in exe_lower for b in (
                "brave", "chrome", "msedge", "edge", "opera", "vivaldi", "arc", "yandex"
            ))
            args = [exe_path]
            if is_chromium:
                args.append("--new-window")
            args.append(url_efetiva)
            _diag(f"Popen args={args!r}")
            # CREATE_BREAKAWAY_FROM_JOB (0x01000000): essencial pra o
            # Chromium escapar do Job Object do JARVIS e abrir janela
            # normalmente. CREATE_NEW_PROCESS_GROUP (0x00000200):
            # desacopla console e sinais.
            CREATE_BREAKAWAY_FROM_JOB = 0x01000000
            flags = CREATE_BREAKAWAY_FROM_JOB
            try:
                flags |= _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                flags |= _sp.DETACHED_PROCESS  # type: ignore[attr-defined]
            except Exception:
                pass
            p = _sp.Popen(args, close_fds=True, creationflags=flags)
            _diag(f"Popen OK pid={p.pid} flags=0x{flags:08x} → return True")
            return True
        except Exception as e:
            _diag(f"Popen FALHOU: {type(e).__name__}: {e}")

    # (3) Último recurso: webbrowser
    try:
        import webbrowser as _wb
        _wb.open(url or "https://www.google.com", new=2)
        _diag("webbrowser.open OK → return True")
        return True
    except Exception as e:
        _diag(f"webbrowser FALHOU: {e}")
    _diag("TODOS os métodos falharam → return False")
    return False


# ── Sessão Playwright persistente ───────────────────────────────────────────

_LOCK = threading.RLock()
_state: dict = {
    "playwright": None,   # objeto Playwright (sync_api)
    "context": None,      # BrowserContext persistente
    "page": None,         # Página ativa
    "browser_name": None,
    "exe_path": None,
}


def _profile_dir(browser_name: str) -> str:
    """Retorna o diretório de perfil padrão REAL do browser instalado.

    Usa o perfil do usuário (com cookies/logins já salvos) em vez de um
    perfil isolado. O Playwright conecta ao contexto existente do Chrome/Brave/
    Edge/etc sem solicitar novos logins.
    """
    real_profiles: dict[str, str] = {
        "brave":    os.path.join(_LOCAL, "BraveSoftware", "Brave-Browser", "User Data"),
        "chrome":   os.path.join(_LOCAL, "Google", "Chrome", "User Data"),
        "edge":     os.path.join(_LOCAL, "Microsoft", "Edge", "User Data"),
        "opera":    os.path.join(_LOCAL, "Programs", "Opera", "User Data"),
        "opera_gx": os.path.join(_LOCAL, "Programs", "Opera GX", "User Data"),
        "vivaldi":  os.path.join(_LOCAL, "Vivaldi", "User Data"),
        "yandex":   os.path.join(_LOCAL, "Yandex", "YandexBrowser", "User Data"),
    }
    real = real_profiles.get(browser_name)
    if real and os.path.isdir(real):
        return real
    # Fallback: perfil isolado do JARVIS (mantido para compatibilidade)
    base = os.path.join(_LOCAL, "JARVIS", "browser_profile", browser_name)
    os.makedirs(base, exist_ok=True)
    return base


def _ensure_browser(preferido: Optional[str] = None) -> dict:
    """Lazy-init da sessão Playwright.

    Estratégia em 3 tentativas:
    1. Reconecta ao contexto existente se ainda válido.
    2. Tenta conectar via CDP ao browser JÁ ABERTO na porta configurada.
    3. Lança um novo browser com --remote-debugging-port para que as próximas
       chamadas possam reconectar sem criar uma segunda janela.
    """
    with _LOCK:
        # ── 1. Reconectar contexto existente ──────────────────────────────
        ctx = _state.get("context")
        if ctx is not None:
            try:
                _ = ctx.pages
                return _state
            except Exception:
                _state["context"] = None
                _state["page"] = None
        # Limpa modo nativo para retestar CDP/perfil a cada chamada nova.
        # (Se o usuário abriu o browser com CDP desde a última vez, aproveitamos.)
        _state.pop("native_only", None)

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"Playwright não instalado: {e}. Rode: pip install playwright"
            ) from e

        pw = _state.get("playwright")
        if pw is None:
            pw = sync_playwright().start()
            _state["playwright"] = pw

        import config as _cfg
        cdp_port = int(getattr(_cfg, "BROWSER_CDP_PORT", 9222))
        pref = preferido or (getattr(_cfg, "BROWSER_PREFERRED", "") or "").strip() or None

        # ── 2. Tentar conectar via CDP ao browser já aberto ───────────────
        cdp_url = f"http://localhost:{cdp_port}"
        try:
            browser = pw.chromium.connect_over_cdp(cdp_url, timeout=2000)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()
            _state["context"] = ctx
            _state["page"] = page
            _state["browser_name"] = "existing"
            _state["exe_path"] = None
            print(f"[BROWSER] Conectado ao browser existente via CDP :{cdp_port}.")
            return _state
        except Exception:
            pass  # browser não está aberto com CDP — lança um novo

        # ── 3. Lançar novo browser com user profile real + CDP port ───────
        nome, exe = _resolver_navegador(pref)
        profile = _profile_dir(nome)

        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=profile,
                executable_path=exe,
                headless=False,
                channel=None,
                args=[
                    "--start-maximized",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    f"--remote-debugging-port={cdp_port}",
                ],
                ignore_default_args=[
                    "--enable-automation",
                    "--enable-blink-features=AutomationControlled",
                ],
                viewport=None,
            )
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()
            _state["context"] = ctx
            _state["page"] = page
            _state["browser_name"] = nome
            _state["exe_path"] = exe
            print(f"[BROWSER] Sessão iniciada com {nome} ({exe}) CDP:{cdp_port}.")
            return _state
        except Exception as e3:
            print(f"[BROWSER] launch_persistent_context falhou ({e3}) — tentando perfil temporário.")

        # ── 4. Nativo — browser aberto sem CDP, não conseguimos assumir o perfil ──
        # Quando Brave/Chrome está aberto sem --remote-debugging-port, lançar
        # com o mesmo user-data-dir falha (Single Instance Lock). A solução é
        # passar a URL diretamente para o processo já aberto (o browser redireciona
        # internamente), sem criar uma sessão Playwright que abriria janela zerada.
        # abrir_url() detecta este modo e usa subprocess em vez de page.goto().
        _state["context"] = None
        _state["page"] = None
        _state["browser_name"] = nome + "-native"
        _state["exe_path"] = exe
        _state["native_only"] = True
        print(f"[BROWSER] Modo nativo ativado — URLs abertas via subprocess no {nome} existente.")
        return _state


def _page():
    s = _ensure_browser()
    if s.get("native_only"):
        raise RuntimeError(
            "Navegador em modo nativo (sem Playwright). "
            "Use abrir_url() para abrir URLs; automação Playwright indisponível."
        )
    return s["page"]


def fechar_sessao() -> str:
    with _LOCK:
        try:
            ctx = _state.get("context")
            if ctx is not None:
                ctx.close()
        except Exception:
            pass
        _state["context"] = None
        _state["page"] = None
        return "Sessão de navegador encerrada."


# ── Ações ───────────────────────────────────────────────────────────────────

def abrir_url(url: str, navegador: Optional[str] = None) -> str:
    if not url:
        return "ERRO: url vazia."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Inicializa sessão (pode entrar em modo nativo se browser já estiver aberto sem CDP)
    _ensure_browser(navegador)
    if _state.get("native_only"):
        # Browser aberto sem CDP: abre URL na instância existente via subprocess.
        # O browser detecta outra instância em execução e abre uma nova aba lá.
        exe = _state.get("exe_path")
        if exe:
            import subprocess as _sp
            _sp.Popen([exe, url], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        else:
            import webbrowser as _wb
            _wb.open(url)
        return f"Aberto: {url}"
    page = _page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return f"Aberto: {page.title() or url}"
    except Exception as e:
        return f"ERRO ao abrir {url}: {e}"


def ler_pagina(max_chars: int = 1500) -> str:
    page = _page()
    try:
        # Extrai texto principal (Readability seria melhor, mas DOM rápido funciona)
        try:
            txt = page.evaluate(
                "() => (document.body && document.body.innerText) || ''"
            )
        except Exception:
            txt = page.content()
        txt = (txt or "").strip()
        if len(txt) > max_chars:
            txt = txt[:max_chars] + "…"
        title = page.title() or ""
        url = page.url
        return f"Página: {title}\nURL: {url}\n\n{txt}"
    except Exception as e:
        return f"ERRO ler_pagina: {e}"


def listar_links(top: int = 15) -> str:
    page = _page()
    try:
        items = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({text: (a.innerText||'').trim().slice(0,80), href: a.href}))
                    .filter(x => x.text && x.href.startsWith('http'))
                    .slice(0, %d)""" % int(top)
        )
        if not items:
            return "Nenhum link encontrado."
        return "\n".join(f"- {it['text']} → {it['href']}" for it in items)
    except Exception as e:
        return f"ERRO listar_links: {e}"


def clicar_texto(texto: str, timeout_ms: int = 8000) -> str:
    """Clica no primeiro elemento (link, botão, qualquer) que contém o texto."""
    if not texto:
        return "ERRO: texto vazio."
    page = _page()
    try:
        # Tenta vários seletores em ordem
        loc = page.get_by_text(texto, exact=False).first
        loc.scroll_into_view_if_needed(timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        return f"Cliquei em: {texto}"
    except Exception as e:
        return f"ERRO clicar_texto '{texto}': {e}"


def buscar_e_clicar(query: str) -> str:
    """Busca o primeiro elemento clicável com o texto e clica.

    Útil para SPAs onde get_by_text precisa achar resultado de busca interno
    (ex.: digitou na search bar e quer clicar no primeiro item da lista).
    """
    if not query:
        return "ERRO: query vazia."
    page = _page()
    try:
        # Tenta achar um link ou cartão com o texto
        sels = [
            f"a:has-text('{query}')",
            f"[role='link']:has-text('{query}')",
            f"[role='button']:has-text('{query}')",
            f"text='{query}'",
        ]
        for sel in sels:
            try:
                loc = page.locator(sel).first
                loc.scroll_into_view_if_needed(timeout=3000)
                loc.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=8000)
                return f"Cliquei em '{query}'."
            except Exception:
                continue
        return f"ERRO: nenhum elemento com texto '{query}' encontrado."
    except Exception as e:
        return f"ERRO buscar_e_clicar: {e}"


def pesquisar(termo: str) -> str:
    """Digita `termo` na barra de busca da página atual e pressiona Enter.
    Funciona em YouTube, Google, Bing, DuckDuckGo, Crunchyroll, Netflix, etc.
    """
    page = _page()
    try:
        # Seletores de barra de busca comuns nas grandes plataformas
        _SEARCH_SELECTORS = [
            'input[name="search_query"]',   # YouTube
            'input[name="q"]',               # Google, DuckDuckGo
            'input[type="search"]',          # genérico HTML5
            'input[role="searchbox"]',
            'input[aria-label*="earch" i]',
            'input[placeholder*="earch" i]',
            'input[placeholder*="usca" i]',  # pt-BR "busca"
            'input[placeholder*="esquis" i]', # pt-BR "pesquisa"
            '#search-input',
            '.search-input',
        ]
        filled = False
        for sel in _SEARCH_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=800):
                    loc.click(timeout=1000)
                    loc.fill(termo, timeout=3000)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            return f"ERRO pesquisar: não encontrei barra de busca na página '{page.title() or page.url}'."
        page.keyboard.press("Enter")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        return f"Pesquisei '{termo}'."
    except Exception as e:
        return f"ERRO pesquisar: {e}"


def preencher_campo(label_ou_seletor: str, valor: str) -> str:
    page = _page()
    try:
        # Tenta primeiro por label/placeholder, depois seletor CSS
        try:
            page.get_by_label(label_ou_seletor).first.fill(valor, timeout=5000)
        except Exception:
            try:
                page.get_by_placeholder(label_ou_seletor).first.fill(valor, timeout=5000)
            except Exception:
                page.locator(label_ou_seletor).first.fill(valor, timeout=5000)
        return f"Preenchi '{label_ou_seletor}' com '{valor}'."
    except Exception as e:
        return f"ERRO preencher_campo: {e}"


def pressionar_enter() -> str:
    page = _page()
    try:
        page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=8000)
        return "Enter pressionado."
    except Exception as e:
        return f"ERRO pressionar_enter: {e}"


def voltar() -> str:
    page = _page()
    try:
        page.go_back(wait_until="domcontentloaded", timeout=8000)
        return f"Voltei para: {page.title() or page.url}"
    except Exception as e:
        return f"ERRO voltar: {e}"


def avancar() -> str:
    page = _page()
    try:
        page.go_forward(wait_until="domcontentloaded", timeout=8000)
        return f"Avancei para: {page.title() or page.url}"
    except Exception as e:
        return f"ERRO avancar: {e}"


def recarregar() -> str:
    page = _page()
    try:
        page.reload(wait_until="domcontentloaded", timeout=10000)
        return "Página recarregada."
    except Exception as e:
        return f"ERRO recarregar: {e}"


def status() -> str:
    s = _state
    if not s.get("context"):
        nav = listar_navegadores_instalados()
        nomes = ", ".join(n for n, _ in nav) or "(nenhum detectado)"
        return f"Sessão fechada. Navegadores disponíveis: {nomes}."
    try:
        page = s["page"]
        return f"Navegador: {s['browser_name']} | Página: {page.title()} | URL: {page.url}"
    except Exception:
        return "Sessão inválida."


# ── Wrappers thread-safe ───────────────────────────────────────────────────────
# Substitui as funções originais por versões que garantem execução na
# thread dedicada do Playwright (evita "cannot switch to a different thread").
_abrir_url_impl       = abrir_url
_ler_pagina_impl      = ler_pagina
_listar_links_impl    = listar_links
_clicar_texto_impl    = clicar_texto
_buscar_e_clicar_impl = buscar_e_clicar
_pesquisar_impl       = pesquisar
_preencher_campo_impl = preencher_campo
_pressionar_enter_impl= pressionar_enter
_voltar_impl          = voltar
_avancar_impl         = avancar
_recarregar_impl      = recarregar
_fechar_sessao_impl   = fechar_sessao
_status_impl          = status


def abrir_url(url: str, navegador=None):          return _run_browser(_abrir_url_impl, url, navegador)
def ler_pagina(max_chars: int = 1500):            return _run_browser(_ler_pagina_impl, max_chars)
def listar_links(top: int = 15):                  return _run_browser(_listar_links_impl, top)
def clicar_texto(texto: str, timeout_ms=8000):   return _run_browser(_clicar_texto_impl, texto, timeout_ms)
def buscar_e_clicar(query: str):                  return _run_browser(_buscar_e_clicar_impl, query)
def pesquisar(termo: str):                        return _run_browser(_pesquisar_impl, termo)
def preencher_campo(label: str, valor: str):      return _run_browser(_preencher_campo_impl, label, valor)
def pressionar_enter():                           return _run_browser(_pressionar_enter_impl)
def voltar():                                     return _run_browser(_voltar_impl)
def avancar():                                    return _run_browser(_avancar_impl)
def recarregar():                                 return _run_browser(_recarregar_impl)
def fechar_sessao():                              return _run_browser(_fechar_sessao_impl)
def status():                                     return _run_browser(_status_impl)
