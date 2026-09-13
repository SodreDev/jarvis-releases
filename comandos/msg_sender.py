# comandos/msg_sender.py — J.A.R.V.I.S.
# Envio de mensagens para WhatsApp, Discord e Instagram
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import re
import threading
import time
import unicodedata

from config import PATHS

_CONTATOS_FILE = PATHS["contatos"]


# ─────────────────────────────────────────────────────────────────────────────
# ROUTER CHROMIUM — tenta usar jarvis.messaging.router primeiro quando
# MESSAGING_SEND_METHOD = "browser" (default). Falha silenciosa = fallback
# para o fluxo legado (pyautogui).
# ─────────────────────────────────────────────────────────────────────────────

def _send_method() -> str:
    try:
        import config as _cfg
        m = str(getattr(_cfg, "MESSAGING_SEND_METHOD", "browser") or "browser")
        m = m.lower().strip()
        return m if m in ("browser", "pyautogui", "auto") else "browser"
    except Exception:
        return "browser"


def _try_browser_send(platform: str, dest: str, mensagem: str,
                      *, profile: str = "user") -> str | None:
    """Tenta enviar via Chromium humano. Retorna a string final pronta para o
    LLM, ou None se browser está desabilitado/indisponível/falhou e o caller
    deve seguir com o fluxo legado."""
    method = _send_method()
    if method == "pyautogui":
        return None
    try:
        from jarvis.messaging.router import get_router
        router = get_router()
        res = router.send(platform, dest, mensagem, profile_hint=profile)  # type: ignore[arg-type]
        if res and getattr(res, "ok", False):
            preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
            plat_pt = {
                "whatsapp": "WhatsApp", "instagram": "Instagram",
                "discord": "Discord", "telegram": "Telegram", "gmail": "Gmail",
            }.get(platform, platform)
            return f"Mensagem '{preview}' enviada para '{dest}' no {plat_pt}, senhor."
        # browser falhou
        if method == "browser":
            # NÃO faz fallback — usuário pediu browser
            err = (res.error if res else "erro desconhecido") or "erro desconhecido"
            plat_pt = {
                "whatsapp": "WhatsApp", "instagram": "Instagram",
                "discord": "Discord",
            }.get(platform, platform)
            return f"Falha ao enviar no {plat_pt} via Chromium: {err}"
        # auto: deixa o caller tentar pyautogui
        return None
    except Exception as e:
        if method == "browser":
            return f"Falha no roteador Chromium ({platform}): {e}"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# AGENDA DE CONTATOS
# ─────────────────────────────────────────────────────────────────────────────

def _sem_acento(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower()


def _carregar() -> dict:
    if not os.path.isfile(_CONTATOS_FILE):
        return {}
    with open(_CONTATOS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # Remove chaves de ajuda/comentário que começam com "_"
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _salvar_db(db: dict):
    # Preserva chave de ajuda se existir no arquivo original
    original: dict = {}
    if os.path.isfile(_CONTATOS_FILE):
        with open(_CONTATOS_FILE, encoding="utf-8") as f:
            original = json.load(f)
    ajuda = {k: v for k, v in original.items() if k.startswith("_")}
    with open(_CONTATOS_FILE, "w", encoding="utf-8") as f:
        json.dump({**ajuda, **db}, f, ensure_ascii=False, indent=2)


def buscar_contatos(nome: str) -> list[dict]:
    """
    Busca contatos cujo nome contenha `nome` (case/acento insensível).
    Retorna lista de {"nome": str, "phone": str, "score": float} ordenada
    por similaridade decrescente. Apenas matches com score >= 0.55.

    Estratégia:
      - Strip de stop-words PT ("a", "o", "para", "minha", "meu", "pra"...).
      - Suporta aliases via campo "_apelidos" (se contato for dict).
      - Ranking por difflib.SequenceMatcher + bônus para exact / startswith
        / token-set match.
      - Limita a 5 candidatos no retorno; auto-pick fica a cargo do caller
        (score >= 0.85 e único isolado).
    """
    from difflib import SequenceMatcher

    _STOP_WORDS_PT = {
        "a", "o", "as", "os", "um", "uma", "uns", "umas",
        "para", "pra", "pro", "pros", "pras",
        "meu", "minha", "meus", "minhas",
        "seu", "sua", "seus", "suas",
        "do", "da", "dos", "das", "de",
        "contato", "numero", "número", "telefone", "fone",
        "jarvis",
    }

    raw = nome.strip()
    if not raw:
        return []
    # Strip stop-words mantendo apenas tokens significativos.
    tokens = [t for t in _sem_acento(raw).split() if t and t not in _STOP_WORDS_PT]
    if not tokens:
        # Tudo era stop-word → usa o input original limpo.
        tokens = _sem_acento(raw).split() or [_sem_acento(raw)]
    key = " ".join(tokens)
    key_tokens = set(tokens)

    db = _carregar()
    candidatos: list[tuple[float, dict]] = []

    for n, v in db.items():
        # Suporte a contato com aliases: { "phone": "+55...", "apelidos": [...] }
        if isinstance(v, dict):
            phone = v.get("phone", "")
            aliases = [str(a) for a in v.get("apelidos", []) if a]
        else:
            phone = str(v)
            aliases = []

        nomes_para_comparar = [n] + aliases
        best_score = 0.0
        for cand_nome in nomes_para_comparar:
            cand_norm = _sem_acento(cand_nome)
            cand_tokens = set(cand_norm.split())

            # Score base: similaridade de sequência
            ratio = SequenceMatcher(None, key, cand_norm).ratio()

            # Bônus
            if cand_norm == key:
                ratio = 1.0
            elif cand_norm.startswith(key) or key.startswith(cand_norm):
                ratio = max(ratio, 0.92)
            elif key in cand_norm or cand_norm in key:
                ratio = max(ratio, 0.85)
            # Bônus por interseção de tokens (ex: "mae" ∩ {"mae","da","casa"})
            if key_tokens & cand_tokens:
                inter = len(key_tokens & cand_tokens)
                union = len(key_tokens | cand_tokens)
                jaccard = inter / union if union else 0.0
                ratio = max(ratio, 0.6 + 0.3 * jaccard)

            best_score = max(best_score, ratio)

        if best_score >= 0.55:
            candidatos.append((best_score, {"nome": n, "phone": phone, "score": round(best_score, 3)}))

    # Ordena por score decrescente, depois nome
    candidatos.sort(key=lambda x: (-x[0], x[1]["nome"]))
    return [c[1] for c in candidatos[:5]]


def salvar_contato(nome: str, phone: str, country_code: str = "55") -> str:
    """
    Salva ou atualiza um contato na agenda local.
    Normaliza o telefone adicionando o código de país se necessário.
    """
    phone_clean = re.sub(r"\D", "", phone)
    if not phone_clean.startswith(country_code):
        phone_clean = country_code + phone_clean
    db = _carregar()
    db[nome.strip().title()] = f"+{phone_clean}"
    _salvar_db(db)
    return f"+{phone_clean}"


def listar_contatos() -> list[dict]:
    """Retorna todos os contatos da agenda."""
    return [{"nome": n, "phone": p} for n, p in _carregar().items()]


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMAÇÃO NÃO-INVASIVA — foco temporário + PostMessage sem roubo de foco
# ─────────────────────────────────────────────────────────────────────────────

from contextlib import contextmanager


@contextmanager
def _foco_temporario(hwnd_destino: int):
    """
    Contexto que foca *hwnd_destino* para automação e, ao sair,
    restaura a janela original E a posição do cursor.
    Reduz a janela de interrupção para o mínimo possível.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    # Captura estado atual
    hwnd_original = user32.GetForegroundWindow()
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    ox, oy = pt.x, pt.y

    try:
        user32.ShowWindow(hwnd_destino, 9)   # SW_RESTORE
        user32.SetForegroundWindow(hwnd_destino)
        time.sleep(0.25)
        yield hwnd_destino
    finally:
        if hwnd_original:
            try:
                user32.SetForegroundWindow(hwnd_original)
            except Exception:
                pass
        try:
            ctypes.windll.user32.SetCursorPos(ox, oy)
        except Exception:
            pass


def _find_chrome_renderer(parent_hwnd: int) -> int | None:
    """
    Localiza o Chrome_RenderWidgetHostHWND filho dentro de uma janela
    Electron (Discord, WhatsApp Desktop).
    Esse handle recebe mensagens Win32 mesmo sem foco no primeiro plano.
    """
    try:
        import ctypes, ctypes.wintypes
        user32 = ctypes.windll.user32
        _ENUM = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        found: list[int] = []

        def _cb(hwnd: int, _) -> bool:
            buf = ctypes.create_unicode_buffer(128)
            ctypes.windll.user32.GetClassNameW(hwnd, buf, 128)
            if "Chrome_RenderWidgetHostHWND" in buf.value:
                found.append(hwnd)
            return True

        user32.EnumChildWindows(parent_hwnd, _ENUM(_cb), 0)
        # O último renderer listado é geralmente o conteúdo visível principal
        return found[-1] if found else None
    except Exception:
        return None


def _enviar_sem_foco(hwnd: int, mensagem: str) -> bool:
    """
    Envia *mensagem* para a janela Electron *hwnd* via PostMessage,
    **sem** roubar o foco do usuário.

    Estratégia:
      1. Salva o clipboard atual.
      2. Copia *mensagem* para o clipboard (não precisa de foco).
      3. PostMessage WM_PASTE para o renderer Chrome.
      4. PostMessage WM_KEYDOWN/WM_KEYUP VK_RETURN para enviar.
      5. Restaura o clipboard original.

    Retorna True se o renderer foi encontrado e os posts foram feitos.
    Não garante que o app recebeu — use como tentativa antes do fallback.
    """
    renderer = _find_chrome_renderer(hwnd)
    if renderer is None:
        return False
    try:
        import pyperclip
        import ctypes, ctypes.wintypes

        # Salva clipboard para restaurar depois
        try:
            clip_original = pyperclip.paste()
        except Exception:
            clip_original = None

        pyperclip.copy(mensagem)
        time.sleep(0.08)

        WM_PASTE   = 0x0302
        WM_KEYDOWN = 0x0100
        WM_KEYUP   = 0x0101
        VK_RETURN  = 0x0D
        # lParam para Enter: scan code 0x1C, extended=0
        lp_down = (0x1C << 16) | 1
        lp_up   = (0x1C << 16) | 0xC0000001

        user32 = ctypes.windll.user32
        user32.PostMessageW(renderer, WM_PASTE, 0, 0)
        time.sleep(0.15)
        user32.PostMessageW(renderer, WM_KEYDOWN, VK_RETURN, lp_down)
        time.sleep(0.05)
        user32.PostMessageW(renderer, WM_KEYUP, VK_RETURN, lp_up)
        time.sleep(0.1)

        # Restaura clipboard original
        if clip_original is not None:
            try:
                pyperclip.copy(clip_original)
            except Exception:
                pass
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP  (via app desktop — URI scheme whatsapp://)
# ─────────────────────────────────────────────────────────────────────────────

def _focar_janela_whatsapp(timeout: float = 8.0) -> bool:
    """
    Tenta encontrar e trazer a janela do WhatsApp para o primeiro plano.
    Retorna True se conseguiu focar, False se não encontrou.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    enumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    target_hwnd = None

    def _enum_cb(hwnd, _):
        nonlocal target_hwnd
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if "whatsapp" in title:
            target_hwnd = hwnd
            return False  # para de enumerar
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        target_hwnd = None
        user32.EnumWindows(enumProc(_enum_cb), 0)
        if target_hwnd:
            # Traz para frente
            user32.ShowWindow(target_hwnd, 9)   # SW_RESTORE
            user32.SetForegroundWindow(target_hwnd)
            time.sleep(0.3)
            return True
        time.sleep(0.5)
    return False


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Retorna (left, top, right, bottom) da janela, ou None se não encontrou."""
    try:
        import ctypes
        import ctypes.wintypes
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    return None


def _hwnd_whatsapp() -> int | None:
    """Retorna o HWND da janela do WhatsApp, ou None se não encontrou."""
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32
    found = []
    _ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if "whatsapp" in buf.value.lower():
            found.append(hwnd)
            return False
        return True
    user32.EnumWindows(_ENUM(_cb), 0)
    return found[0] if found else None


def enviar_whatsapp(phone: str, mensagem: str, country_code: str = "55") -> str:
    """
    Envia mensagem pelo app desktop do WhatsApp.
    Usa URI scheme para abrir a conversa e preencher o texto,
    depois usa _foco_temporario para pressionar Enter e restaura
    o foco do usuário imediatamente.
    """
    try:
        import urllib.parse
        import pyautogui

        phone_clean = re.sub(r"\D", "", phone)
        if not phone_clean.startswith(country_code):
            phone_clean = country_code + phone_clean

        texto_encoded = urllib.parse.quote(mensagem)
        uri = f"whatsapp://send?phone={phone_clean}&text={texto_encoded}"

        # Abre conversa (sem forçar foco ainda)
        os.startfile(uri)

        # Aguarda WhatsApp abrir e a conversa carregar
        hwnd = _hwnd_whatsapp()
        deadline = time.time() + 10.0
        while hwnd is None and time.time() < deadline:
            time.sleep(0.4)
            hwnd = _hwnd_whatsapp()
        if hwnd is None:
            return "Falha ao enviar WhatsApp: janela não encontrada."

        time.sleep(3.0)   # carrega conversa + preenche texto pelo URI
        hwnd = _hwnd_whatsapp() or hwnd

        # ── Breve roubo de foco apenas para clicar e pressionar Enter ──────
        with _foco_temporario(hwnd):
            rect = _get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                pyautogui.click((left + right) // 2,
                                int(top + (bottom - top) * 0.93))
                time.sleep(0.25)
            pyautogui.press("enter")
            time.sleep(0.4)
            pyautogui.press("enter")   # fallback se primeiro só focou
            time.sleep(0.2)
        # foco restaurado aqui

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada para +{phone_clean} no WhatsApp, senhor."
    except ImportError as e:
        return f"Falha ao enviar WhatsApp: biblioteca ausente ({e}). Instale pyautogui."
    except Exception as e:
        return f"Falha ao enviar WhatsApp: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD  (via app desktop — URI scheme + pyautogui, sem bot, sem token)
# ─────────────────────────────────────────────────────────────────────────────

def _focar_janela_discord(timeout: float = 8.0) -> int | None:
    """
    Tenta encontrar e trazer a janela do Discord para o primeiro plano.
    Retorna o HWND se conseguiu focar, None se não encontrou.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    _ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _buscar_hwnd() -> int | None:
        found = []
        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            # Título do Discord desktop contém "discord" mas NÃO "discord - Electron"
            # (que é o helper de renderer). Aceita qualquer janela com "discord".
            if "discord" in title and "discord helper" not in title:
                found.append(hwnd)
                return False
            return True
        user32.EnumWindows(_ENUM(_cb), 0)
        return found[0] if found else None

    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _buscar_hwnd()
        if hwnd:
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.4)
            return hwnd
        time.sleep(0.5)
    return None


def enviar_discord_usuario(guild_id: str, channel_id: str, mensagem: str) -> str:
    """
    Envia mensagem pelo Discord no canal/DM especificado por ID.
    Usa URI scheme + foco temporário + pyautogui (sem bot, sem token de usuário).
    """
    # ── URI scheme + foco temporário ─────────────────────────────────────────
    try:
        import pyautogui
        import pyperclip

        uri = f"discord://discord.com/channels/{guild_id}/{channel_id}"
        os.startfile(uri)

        hwnd = _focar_janela_discord(timeout=8.0)
        if hwnd is None:
            return ("Falha ao enviar no Discord: janela não encontrada. "
                    "Verifique se o Discord está instalado e aberto.")

        time.sleep(2.0)   # canal carrega após a URI

        with _foco_temporario(hwnd):
            rect = _get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                pyautogui.click((left + right) // 2,
                                int(top + (bottom - top) * 0.95))
            time.sleep(0.25)
            pyperclip.copy(mensagem)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.18)
            pyautogui.press("enter")
            time.sleep(0.35)
            pyautogui.press("enter")   # fallback emoji/sugestão
            time.sleep(0.15)
        # foco restaurado aqui

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada no Discord, senhor."
    except ImportError as e:
        return f"Falha ao enviar no Discord: biblioteca ausente ({e}). Instale pyautogui e pyperclip."
    except Exception as e:
        return f"Falha ao enviar no Discord: {e}"


def enviar_discord_por_nome(nome: str, mensagem: str) -> str:
    """
    Envia mensagem no Discord pelo nome da pessoa/canal/servidor.
    Estratégia preferida (MESSAGING_SEND_METHOD=browser): Chromium humano via
    jarvis.messaging.router. Fallback: Ctrl+K Quick Switcher + pyautogui.
    """
    # 1) Chromium humano (Playwright)
    routed = _try_browser_send("discord", nome, mensagem)
    if routed is not None:
        return routed
    # 2) Fallback desktop (Ctrl+K)
    try:
        import pyautogui
        import pyperclip

        # Garante que o Discord está aberto (pode abrir em background)
        hwnd = _focar_janela_discord(timeout=3.0)
        if hwnd is None:
            try:
                os.startfile("discord://")
            except Exception:
                import subprocess
                subprocess.Popen(["discord.exe"])
            hwnd = _focar_janela_discord(timeout=12.0)
        if hwnd is None:
            return "Discord não encontrado. Abra o Discord primeiro, senhor."

        with _foco_temporario(hwnd):
            # Ctrl+K → Quick Switcher
            pyautogui.hotkey("ctrl", "k")
            time.sleep(0.6)

            # Digita o nome
            pyautogui.hotkey("ctrl", "a")
            pyperclip.copy(nome)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1.1)

            # Seleciona primeiro resultado → navega
            pyautogui.press("enter")
            time.sleep(1.8)

            # Clica no input (Discord pode ter re-renderizado)
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            rect = _get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                pyautogui.click((left + right) // 2,
                                int(top + (bottom - top) * 0.95))
            time.sleep(0.3)

            # Cola e envia
            pyperclip.copy(mensagem)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.25)
        # foco restaurado aqui

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada para '{nome}' no Discord, senhor."
    except ImportError as e:
        return f"Falha ao enviar no Discord: biblioteca ausente ({e}). Instale pyautogui e pyperclip."
    except Exception as e:
        return f"Falha ao enviar no Discord: {e}"


def enviar_discord_canal_atual(mensagem: str) -> str:
    """
    Envia mensagem no canal do Discord que estiver aberto *agora*.
    Tenta em ordem: 1) API user token com DISCORD_CHANNEL_ID, 2) PostMessage
    ao renderer Chromium, 3) foco temporário + pyautogui.
    """
    try:
        # ── Encontra o HWND sem forçar foco ──────────────────────────────────
        import ctypes, ctypes.wintypes
        user32 = ctypes.windll.user32
        _ENUM = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        found: list[int] = []

        def _cb(hwnd: int, _) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            t = buf.value.lower()
            if "discord" in t and "discord helper" not in t:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_ENUM(_cb), 0)
        hwnd = found[0] if found else None

        if hwnd is None:
            return "Discord não está aberto, senhor."

        # ── Tentativa 1: PostMessage ao renderer (sem roubar foco) ──────────
        if _enviar_sem_foco(hwnd, mensagem):
            preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
            return f"Mensagem '{preview}' enviada no canal atual do Discord, senhor."

        # ── Fallback: foco temporário + pyautogui ────────────────────────────
        import pyautogui, pyperclip
        with _foco_temporario(hwnd):
            rect = _get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                pyautogui.click((left + right) // 2,
                                int(top + (bottom - top) * 0.95))
            time.sleep(0.25)
            pyperclip.copy(mensagem)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.25)
        # foco restaurado aqui

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada no canal atual do Discord, senhor."
    except ImportError as e:
        return f"Falha ao enviar no Discord: biblioteca ausente ({e}). Instale pyautogui e pyperclip."
    except Exception as e:
        return f"Falha ao enviar no Discord: {e}"


def enviar_whatsapp_por_nome(nome_contato: str, mensagem: str) -> str:
    """
    Envia mensagem no WhatsApp para um contato pelo nome de exibição,
    sem precisar do número de telefone.

    Estratégia preferida (MESSAGING_SEND_METHOD=browser): Chromium humano.
    Fallback: WhatsApp Desktop via Ctrl+F + pyautogui.
    """
    # 1) Chromium humano (Playwright)
    routed = _try_browser_send("whatsapp", nome_contato, mensagem)
    if routed is not None:
        return routed
    # 2) Fallback desktop
    try:
        import pyautogui, pyperclip

        # Abre o WhatsApp (URI scheme — mantém sessão existente)
        os.startfile("whatsapp://")

        hwnd = _hwnd_whatsapp()
        deadline = time.time() + 10.0
        while hwnd is None and time.time() < deadline:
            time.sleep(0.5)
            hwnd = _hwnd_whatsapp()
        if hwnd is None:
            return "Falha ao enviar WhatsApp: janela não encontrada (timeout)."

        time.sleep(1.5)   # aguarda app estabilizar

        with _foco_temporario(hwnd):
            # Abre pesquisa de conversas
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.7)

            # Limpa campo e digita o nome
            pyautogui.hotkey("ctrl", "a")
            pyperclip.copy(nome_contato)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1.2)   # aguarda resultados aparecerem

            # Seleciona o primeiro resultado
            pyautogui.press("enter")
            time.sleep(1.0)   # aguarda conversa carregar

            # Fecha pesquisa se ainda estiver aberta
            pyautogui.press("escape")
            time.sleep(0.3)

            # Clica na área de digitação (parte inferior da janela)
            rect = _get_window_rect(hwnd)
            if rect:
                left, top, right, bottom = rect
                pyautogui.click(int((left + right) / 2),
                                int(top + (bottom - top) * 0.93))
                time.sleep(0.3)

            # Cola e envia
            pyperclip.copy(mensagem)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.3)
        # foco restaurado

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada para '{nome_contato}' no WhatsApp, senhor."
    except ImportError as e:
        return f"Falha ao enviar WhatsApp: biblioteca ausente ({e}). Instale pyautogui e pyperclip."
    except Exception as e:
        return f"Falha ao enviar WhatsApp (por nome): {e}"


# ─────────────────────────────────────────────────────────────────────────────
# INSTAGRAM  (via automação de browser — sem instagrapi, sem risco de bloqueio)
# ─────────────────────────────────────────────────────────────────────────────

def enviar_instagram_pyautogui(destinatario: str, mensagem: str) -> str:
    """
    Envia mensagem direta no Instagram.
    Estratégia preferida (MESSAGING_SEND_METHOD=browser): Chromium humano via
    jarvis.messaging.router. Fallback: automação do navegador padrão + pyautogui.
    Não usa instagrapi — zero sessão de API, zero risco de bloqueio de conta."""
    # 1) Chromium humano (Playwright)
    routed = _try_browser_send("instagram", destinatario.lstrip("@").strip(), mensagem)
    if routed is not None:
        return routed
    # 2) Fallback pyautogui (legado abaixo)
    _LEGACY_DOC = """

    Estratégia:
      1. Abre instagram.com/direct/new/ no browser padrão
         (usuário deve estar logado no Instagram pelo browser)
      2. O compose dialog abre com o campo de busca auto-focado
      3. Cola o @username via clipboard, aguarda resultados
      4. Clica no primeiro resultado da lista
      5. Clica no botão Avançar/Chat para abrir a conversa
      6. Cola e envia a mensagem
    """
    try:
        import pyautogui, pyperclip
        import time as _t, ctypes, ctypes.wintypes, webbrowser as _wb

        dest_clean = destinatario.lstrip("@").strip()

        # ── Abre o compose dialog de nova mensagem no Instagram Web ──────────
        _wb.open("https://www.instagram.com/direct/new/")
        _t.sleep(4.0)   # aguarda browser + SPA carregar

        # ── Localiza janela do browser com Instagram aberto ──────────────────
        user32 = ctypes.windll.user32
        _ENUM = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        found: list[int] = []

        def _cb(hwnd: int, _) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "instagram" in buf.value.lower():
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_ENUM(_cb), 0)
        if not found:
            return (
                "Instagram: navegador com Instagram não encontrado. "
                "Abra instagram.com no seu navegador e faça login, senhor."
            )

        hwnd = found[0]

        with _foco_temporario(hwnd):
            rect = _get_window_rect(hwnd)
            if not rect:
                return "Instagram: não foi possível obter as dimensões da janela."
            left, top, right, bottom = rect
            w = right - left
            h = bottom - top

            # ── O campo de busca do compose dialog é auto-focado. ────────────
            # Clica no centro da janela caso outro elemento tenha roubado o foco.
            pyautogui.click(left + w // 2, top + int(h * 0.30))
            _t.sleep(0.4)

            # ── Limpa campo e cola o username ─────────────────────────────────
            pyautogui.hotkey("ctrl", "a")
            pyperclip.copy(dest_clean)
            pyautogui.hotkey("ctrl", "v")
            _t.sleep(1.8)   # aguarda autocomplete aparecer

            # ── Clica no primeiro resultado da lista de sugestões ─────────────
            # No compose dialog do Instagram Web, os resultados ficam abaixo
            # do campo de busca, que está ~28% do topo da janela.
            result_x = left + int(w * 0.50)
            result_y = top + int(h * 0.40)
            pyautogui.click(result_x, result_y)
            _t.sleep(0.5)

            # ── Clica no botão "Avançar" / "Chat" (canto sup. direito do modal)
            next_x = left + int(w * 0.82)
            next_y = top + int(h * 0.19)
            pyautogui.click(next_x, next_y)
            _t.sleep(2.0)   # aguarda a conversa abrir

            # ── Clica na área de input de texto (parte inferior) ──────────────
            input_x = left + int(w * 0.50)
            input_y = top + int(h * 0.92)
            pyautogui.click(input_x, input_y)
            _t.sleep(0.35)

            # ── Cola e envia ──────────────────────────────────────────────────
            pyperclip.copy(mensagem)
            pyautogui.hotkey("ctrl", "v")
            _t.sleep(0.2)
            pyautogui.press("enter")
            _t.sleep(0.3)
        # foco restaurado

        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        return f"Mensagem '{preview}' enviada para @{dest_clean} no Instagram, senhor."
    except ImportError as e:
        return f"Falha ao enviar Instagram: biblioteca ausente ({e}). Instale pyautogui e pyperclip."
    except Exception as e:
        return f"Falha ao enviar Instagram (automação): {e}"


# ─────────────────────────────────────────────────────────────────────────────
# INSTAGRAM  (via instagrapi — DESATIVADO por padrão, INSTAGRAM_USE_API=True p/ reativar)
# ─────────────────────────────────────────────────────────────────────────────

_IG_SESSION_FILE = PATHS["instagram_session"]

# ── Singleton do client IG ───────────────────────────────────────────────────
_ig_cached: object | None = None      # tipo real: instagrapi.Client
_ig_lock = threading.Lock()


def _ntp_offset() -> float:
    """Retorna a diferença (segundos) entre NTP e relógio local. 0.0 em caso de falha."""
    try:
        import socket, struct
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(3)
        client.sendto(b'\x1b' + 47 * b'\0', ('pool.ntp.org', 123))
        data, _ = client.recvfrom(1024)
        ntp_t = struct.unpack('!12I', data)[10] - 2208988800
        return ntp_t - time.time()
    except Exception:
        return 0.0


def _ig_totp_code(totp_seed: str) -> str | None:
    """Gera código TOTP compensando drift do relógio via NTP."""
    if not totp_seed:
        return None
    import pyotp, datetime
    seed_clean = totp_seed.strip().replace(" ", "")
    totp = pyotp.TOTP(seed_clean)
    offset = _ntp_offset()
    if abs(offset) > 5:
        print(f"[IG] Drift do relogio detectado: {offset:.1f}s — usando hora NTP para TOTP.")
    ntp_now = datetime.datetime.fromtimestamp(time.time() + offset, tz=datetime.timezone.utc)
    return totp.at(ntp_now)


def _ig_cliente(username: str, password: str, totp_seed: str = ""):
    """
    Retorna um Client do instagrapi já autenticado.
    Mantém um **singleton** em memória — só refaz login quando a sessão
    for explicitamente invalidada via ``_ig_invalidar()``.
    """
    global _ig_cached
    from instagrapi import Client

    with _ig_lock:
        # ── Retorna client em cache se existir ───────────────────────────
        if _ig_cached is not None:
            return _ig_cached

        os.makedirs(os.path.dirname(_IG_SESSION_FILE), exist_ok=True)

        # ── Tenta restaurar sessão salva (sem login fresco) ──────────────
        if os.path.isfile(_IG_SESSION_FILE):
            try:
                cl = Client()
                cl.load_settings(_IG_SESSION_FILE)
                cl.login(username, password)        # reutiliza sessão
                cl.get_timeline_feed()               # valida
                _ig_cached = cl
                print("[IG] Sessão existente restaurada com sucesso.")
                return cl
            except Exception as e:
                print(f"[IG] Sessão salva falhou ({e}), tentando login fresco...")

        # ── Login fresco (sessão inexistente ou expirada) ────────────────
        cl = Client()
        code = _ig_totp_code(totp_seed)
        if code:
            cl.login(username, password, verification_code=code)
        else:
            cl.login(username, password)
        cl.dump_settings(_IG_SESSION_FILE)
        _ig_cached = cl
        print("[IG] Login fresco realizado e sessão salva.")
        return cl


def _ig_invalidar():
    """
    Invalida o client em cache.  **NÃO apaga** o arquivo de sessão —
    na próxima chamada ``_ig_cliente()`` tentará restaurá-lo antes de
    fazer um login fresco.
    """
    global _ig_cached
    with _ig_lock:
        _ig_cached = None


def _ig_erro_amigavel(e: Exception) -> str:
    """Converte exceção do instagrapi em mensagem amigável em pt-BR."""
    msg = str(e).lower()
    if "login_required" in msg or "loginrequired" in msg or "not authenticated" in msg:
        return "sessão do Instagram expirou — refazendo login na próxima tentativa"
    if "usernamenotfound" in msg or "user not found" in msg:
        return "usuário não encontrado no Instagram"
    if "rate_limit" in msg or "429" in msg or "feedback_required" in msg:
        return "Instagram bloqueou temporariamente (rate limit) — tente em alguns minutos"
    if "challenge_required" in msg:
        return "Instagram está exigindo verificação de segurança — acesse o app manualmente"
    if "bad_password" in msg or "badpassword" in msg:
        return "senha do Instagram incorreta — verifique a config"
    if "checkpoint_required" in msg:
        return "conta do Instagram requer checkpoint de segurança — acesse o app"
    if "totp" in msg or "two_factor" in msg:
        return "código de autenticação de dois fatores inválido"
    if "network" in msg or "connection" in msg or "timeout" in msg:
        return "falha de rede ao conectar ao Instagram"
    return str(e)


def enviar_instagram(username: str, password: str,
                     destinatario: str, mensagem: str,
                     totp_seed: str = "",
                     apelidos: dict[str, str] | None = None) -> str:
    """
    Envia mensagem direta no Instagram.
    Procura o destinatário **apenas entre conversas existentes** (DMs),
    comparando @username, nome de exibição e apelidos configurados.
    Se encontrar exatamente 1 match, envia direto.
    Se encontrar múltiplos, retorna string especial "MULTIPLOS:..." para
    o main.py montar a lista de seleção.
    Inclui retry automático (1x) em caso de sessão expirada.
    """
    def _tentar_envio(tentativa: int = 1) -> str:
        nonlocal username, password, totp_seed
        try:
            apelidos_local = apelidos or {}
            dest_raw = destinatario.lstrip("@").strip()
            dest_norm = _sem_acento(dest_raw)

            # ── Resolve apelido → @username ──────────────────────────────────
            for apelido, at_user in apelidos_local.items():
                if _sem_acento(apelido.strip()) == dest_norm:
                    dest_raw = at_user.lstrip("@").strip()
                    dest_norm = _sem_acento(dest_raw)
                    print(f"[IG] Apelido '{apelido}' → @{dest_raw}")
                    break

            # ── Busca nas DMs ────────────────────────────────────────────────
            opcoes = buscar_contatos_instagram(
                username, password, dest_raw, totp_seed, max_resultados=5,
            )

            if not opcoes:
                return (f"Senhor, não encontrei nenhum contato parecido com "
                        f"'{destinatario}' nas suas conversas do Instagram.")

            # Match único ou exato → envia direto
            if len(opcoes) == 1 or opcoes[0]["score"] == 0:
                escolhido = opcoes[0]
                cl = _ig_cliente(username, password, totp_seed)
                cl.direct_send(mensagem, [escolhido["user_id"]])
                preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
                return (f"Mensagem '{preview}' enviada para "
                        f"@{escolhido['username']} no Instagram, senhor.")

            # Múltiplos matches → retorna marcador para main.py montar seleção
            import json as _json
            return "MULTIPLOS:" + _json.dumps(
                [{"username": o["username"], "full_name": o["full_name"],
                  "user_id": o["user_id"]} for o in opcoes],
                ensure_ascii=False,
            )

        except Exception as e:
            erro_msg = _ig_erro_amigavel(e)
            is_session_err = any(k in str(e).lower() for k in
                                 ("login_required", "loginrequired", "not authenticated"))
            # Retry único em caso de sessão expirada
            if is_session_err and tentativa == 1:
                print(f"[IG] Sessão inválida — invalidando e tentando de novo...")
                _ig_invalidar()
                time.sleep(2.0)
                return _tentar_envio(tentativa=2)
            # Rate limit: não invalida sessão, só avisa
            if "rate_limit" in str(e).lower() or "429" in str(e):
                return f"Falha ao enviar Instagram: {erro_msg}"
            _ig_invalidar()
            return f"Falha ao enviar Instagram: {erro_msg}"

    return _tentar_envio()


def buscar_contatos_instagram(
    username: str, password: str, busca: str, totp_seed: str = "",
    max_resultados: int = 10,
) -> list[dict]:
    """
    Busca contatos do Instagram nas conversas diretas (DMs).
    Compara ``busca`` contra username, full_name e, opcionalmente, o
    apelido da thread (thread title).

    Retorna lista de dicts ordenada por relevância:
        [{"username": str, "full_name": str, "user_id": str, "score": int}, ...]

    score: 0 = match exato de username, 1 = username contém, 2 = full_name contém,
           3 = match parcial por tokens.
    """
    try:
        cl = _ig_cliente(username, password, totp_seed)

        # ── Busca threads do Direct (API bruta para evitar ValidationError) ──
        raw = cl.private_request("direct_v2/inbox/", params={"limit": "40"})
        threads = raw.get("inbox", {}).get("threads", [])

        busca_norm = _sem_acento(busca.strip().lstrip("@"))
        resultados: list[dict] = []
        vistos: set[str] = set()

        for th in threads:
            users = th.get("users") or []
            thread_title = (th.get("thread_title") or "").strip()
            for u in users:
                uid = str(u.get("pk", ""))
                uname = u.get("username", "")
                full  = u.get("full_name", "")
                if not uname or uid in vistos:
                    continue
                vistos.add(uid)

                uname_norm = _sem_acento(uname)
                full_norm  = _sem_acento(full)
                title_norm = _sem_acento(thread_title)

                score: int | None = None

                # 0 = match exato de username
                if uname_norm == busca_norm:
                    score = 0
                # 1 = username contém busca (ou vice-versa)
                elif busca_norm in uname_norm or uname_norm in busca_norm:
                    score = 1
                # 2 = full_name contém busca
                elif busca_norm in full_norm or full_norm and any(
                    tok in full_norm for tok in busca_norm.split()
                ):
                    score = 2
                # 2.5 = thread_title contém busca
                elif title_norm and busca_norm in title_norm:
                    score = 2
                # 3 = match por tokens individuais da busca no username ou full_name
                else:
                    tokens = [t for t in busca_norm.split() if len(t) >= 2]
                    if tokens and any(
                        tk in uname_norm or tk in full_norm for tk in tokens
                    ):
                        score = 3

                if score is not None:
                    resultados.append({
                        "username":  uname,
                        "full_name": full,
                        "user_id":   uid,
                        "score":     score,
                    })

        # Ordena por score (menor = melhor), depois alfabético
        resultados.sort(key=lambda x: (x["score"], x["username"].lower()))
        return resultados[:max_resultados]

    except Exception as e:
        print(f"[IG] Erro ao buscar contatos: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# FORMATADOR DE LEITURA (converte lista de msgs em texto para TTS)
# ─────────────────────────────────────────────────────────────────────────────

def formatar_leitura(app_key: str, sender: str,
                     msgs: list[dict]) -> str:
    """
    Transforma a lista de mensagens do debounce em texto legível pelo JARVIS.
    `msgs` = [{"type": "text"|"audio"|"media", "content": str, "ts"?: str}, ...]
    """
    textos  = [m["content"] for m in msgs if m["type"] == "text" and m["content"]]
    audios  = sum(1 for m in msgs if m["type"] == "audio")
    medias  = [m["content"] for m in msgs if m["type"] == "media"]
    n       = len(msgs)

    partes  = []
    if textos:
        if len(textos) == 1:
            partes.append(f'"{textos[0]}"')
        else:
            enumeradas = "; ".join(f'mensagem {i+1}: "{t}"'
                                   for i, t in enumerate(textos))
            partes.append(enumeradas)
    if audios:
        sufixo = "mensagem de áudio" if audios == 1 else f"{audios} mensagens de áudio"
        partes.append(sufixo)
    if medias:
        if len(medias) == 1:
            partes.append(medias[0])
        else:
            partes.append(f"{len(medias)} mídias")

    app_nome = {"whatsapp": "WhatsApp", "discord": "Discord",
                "instagram": "Instagram"}.get(app_key, app_key.title())

    conteudo = " e ".join(partes) if partes else f"{n} mensagem(ns)"

    # Horário da primeira e última mensagem (se disponíveis)
    hora_info = ""
    tss = [m.get("ts") for m in msgs if m.get("ts")]
    if tss:
        try:
            from datetime import datetime
            primeiro = datetime.fromisoformat(tss[0]).strftime("%H:%M")
            ultimo   = datetime.fromisoformat(tss[-1]).strftime("%H:%M")
            if primeiro == ultimo:
                hora_info = f", às {primeiro}"
            else:
                hora_info = f", entre {primeiro} e {ultimo}"
        except Exception:
            pass

    return (
        f"Senhor, {sender} enviou {conteudo} "
        f"pelo {app_nome}{hora_info}."
    )
