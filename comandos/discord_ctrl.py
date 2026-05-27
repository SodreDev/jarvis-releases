# comandos/discord_ctrl.py — J.A.R.V.I.S.
# Leitura de mensagens e informações do Discord via REST API
# Requer: pip install requests
# BOT TOKEN: Discord Developer Portal → seu bot → "Bot" → "Token"
# ou USER TOKEN (risco de banimento — use com cuidado)
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import json
import datetime
import re
from typing import Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)

# ── Config de servidores/canais ───────────────────────────────────────────────
# Arquivo para mapear nomes amigáveis ↔ IDs numéricos
_SERVERS_FILE  = os.path.join(_ROOT, "discord_servers.json")
_DEFAULT_TOKEN = ""   # Preenchido via config.py → DISCORD_BOT_TOKEN

_BASE_URL = "https://discord.com/api/v10"
_HEADERS: dict[str, str] = {}


def _load_config() -> None:
    """Carrega token do config.py e inicializa headers."""
    global _DEFAULT_TOKEN, _HEADERS
    try:
        from config import DISCORD_BOT_TOKEN  # type: ignore
        _DEFAULT_TOKEN = DISCORD_BOT_TOKEN
    except ImportError:
        pass
    if _DEFAULT_TOKEN:
        _HEADERS = {"Authorization": f"Bot {_DEFAULT_TOKEN}"}


def _load_servers() -> dict:
    """Carrega mapeamento nome→ID do arquivo JSON."""
    if os.path.exists(_SERVERS_FILE):
        try:
            with open(_SERVERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_servers(data: dict) -> None:
    with open(_SERVERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get(endpoint: str, token: Optional[str] = None) -> dict | list | None:
    """Faz GET na API do Discord. Retorna JSON ou None em caso de erro."""
    try:
        import requests
    except ImportError:
        return None
    _load_config()
    hdrs = {"Authorization": f"Bot {token or _DEFAULT_TOKEN}"}
    if not (token or _DEFAULT_TOKEN):
        return None
    try:
        r = requests.get(f"{_BASE_URL}{endpoint}", headers=hdrs, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _post(endpoint: str, payload: dict, token: Optional[str] = None) -> dict | None:
    """Faz POST na API do Discord. Retorna JSON ou None em caso de erro."""
    try:
        import requests, json as _j
    except ImportError:
        return None
    _load_config()
    if not (token or _DEFAULT_TOKEN):
        return None
    hdrs = {
        "Authorization": f"Bot {token or _DEFAULT_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            f"{_BASE_URL}{endpoint}",
            data=_j.dumps(payload),
            headers=hdrs,
            timeout=10,
        )
        if r.status_code in (200, 201):
            return r.json()
        return None
    except Exception:
        return None


def _find_user_id(username: str) -> Optional[str]:
    """
    Busca o ID de um usuário pelo username/apelido nos servidores do bot.
    Aceita '@nome', 'nome', 'nome#1234' ou ID numérico direto.
    Retorna o user_id ou None se não encontrado.
    """
    username = username.lstrip("@").strip()
    if re.fullmatch(r"\d{15,20}", username):
        return username
    username_lower = username.lower()
    guilds_data = _get("/users/@me/guilds")
    if not guilds_data:
        return None
    for guild in (guilds_data[:15] if isinstance(guilds_data, list) else []):
        gid = guild.get("id")
        if not gid:
            continue
        members = _get(f"/guilds/{gid}/members?limit=200")
        if not isinstance(members, list):
            continue
        for member in members:
            user = member.get("user", {})
            uname = user.get("username", "").lower()
            global_name = (user.get("global_name") or "").lower()
            nick = (member.get("nick") or "").lower()
            uid = user.get("id", "")
            if username_lower in (uname, global_name, nick) or \
               username_lower in uname or username_lower in global_name:
                return uid
    return None


# USER TOKEN API  — envio silencioso com a conta do usuário (sem bot, sem foco)
# ─────────────────────────────────────────────────────────────────────────────

def _user_token() -> str:
    """Retorna DISCORD_USER_TOKEN do config, ou '' se não configurado."""
    try:
        from config import DISCORD_USER_TOKEN  # type: ignore
        return (DISCORD_USER_TOKEN or "").strip()
    except ImportError:
        return ""


def _uget(endpoint: str, token: str) -> dict | list | None:
    """GET na API do Discord com user token (sem prefixo 'Bot')."""
    try:
        import requests
        r = requests.get(
            f"{_BASE_URL}{endpoint}",
            headers={"Authorization": token,
                     "User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _upost(endpoint: str, payload: dict, token: str) -> dict | None:
    """POST na API do Discord com user token (sem prefixo 'Bot')."""
    try:
        import requests
        r = requests.post(
            f"{_BASE_URL}{endpoint}",
            headers={"Authorization": token,
                     "Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0"},
            json=payload,
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _resolver_nome_api(nome: str, token: str) -> str | None:
    """
    Resolve nome de pessoa/canal → channel_id usando a API com user token.

    Ordem de busca:
      1. DMs abertas — compara username e display_name do recipiente
      2. Canais de texto em todos os servidores do usuário
    """
    import unicodedata

    def _n(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        ).lower()

    q = _n(nome)

    # 1. DMs existentes
    dms = _uget("/users/@me/channels", token)
    if isinstance(dms, list):
        for ch in dms:
            if ch.get("type") not in (1, 3):   # 1=DM, 3=Group DM
                continue
            for r in ch.get("recipients", []):
                if q in _n(r.get("username", "")) or q in _n(r.get("global_name") or ""):
                    return ch["id"]

    # 2. Canais de servidores
    guilds = _uget("/users/@me/guilds", token)
    if isinstance(guilds, list):
        for g in guilds:
            channels = _uget(f"/guilds/{g['id']}/channels", token)
            if not isinstance(channels, list):
                continue
            for ch in channels:
                if ch.get("type") in (0, 11, 12) and q in _n(ch.get("name", "")):
                    return ch["id"]

    return None


def enviar_via_user_token(nome_ou_id: str, mensagem: str) -> str:
    """
    Envia mensagem pelo Discord usando o user token configurado em DISCORD_USER_TOKEN.
    Completamente silencioso — sem abrir janela, sem roubar foco, sem mouse/teclado.

    Retorna:
      - Mensagem de sucesso/erro se o token estiver configurado.
      - String vazia "" se DISCORD_USER_TOKEN não estiver configurado
        (sinal para o caller tentar o fallback de desktop automation).
    """
    token = _user_token()
    if not token:
        return ""   # não configurado → caller usa fallback

    channel_id: str | None = None

    dest = nome_ou_id.strip()
    if re.fullmatch(r"\d{15,20}", dest):
        channel_id = dest
    else:
        channel_id = _resolver_nome_api(dest, token)
        if not channel_id:
            return (
                f"Não encontrei '{dest}' nos seus canais e DMs do Discord, senhor. "
                f"Tente o ID numérico do canal ou verifique o nome."
            )

    data = _upost(f"/channels/{channel_id}/messages",
                  {"content": mensagem[:2000]}, token)
    if data and data.get("id"):
        preview = mensagem[:60] + ("..." if len(mensagem) > 60 else "")
        dest_label = dest if dest != channel_id else f"canal {channel_id}"
        return f"Mensagem '{preview}' enviada para '{dest_label}' no Discord, senhor."

    return (
        f"Falha ao enviar para '{dest}' via API do Discord, senhor. "
        f"Verifique se o DISCORD_USER_TOKEN está correto e não expirou."
    )



def _create_dm_channel(user_id: str) -> Optional[str]:
    """Cria ou obtém um canal de DM com o usuário. Retorna o channel_id."""
    data = _post("/users/@me/channels", {"recipient_id": user_id})
    if data and isinstance(data, dict):
        return data.get("id")
    return None


def _resolve_channel_id(nome_ou_id: str) -> Optional[str]:
    """Tenta resolver nome amigável para ID. Se já for ID numérico, retorna direto."""
    if re.fullmatch(r"\d+", nome_ou_id.strip()):
        return nome_ou_id.strip()
    servers = _load_servers()
    # Busca por canais mapeados
    nome_lower = nome_ou_id.lower().strip()
    for k, v in servers.get("channels", {}).items():
        if k.lower() == nome_lower or nome_lower in k.lower():
            return str(v)
    return None


def _resolve_guild_id(nome_ou_id: str) -> Optional[str]:
    """Tenta resolver nome de servidor para ID."""
    if re.fullmatch(r"\d+", nome_ou_id.strip()):
        return nome_ou_id.strip()
    servers = _load_servers()
    nome_lower = nome_ou_id.lower().strip()
    for k, v in servers.get("guilds", {}).items():
        if k.lower() == nome_lower or nome_lower in k.lower():
            return str(v)
    return None


def _fmt_ts(ts_str: str) -> str:
    """Formata timestamp ISO do Discord para leitura."""
    try:
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        dt_local = dt.astimezone(tz=None)
        now = datetime.datetime.now().astimezone()
        delta = now - dt_local
        if delta.seconds < 60 and delta.days == 0:
            return "agora há pouco"
        elif delta.seconds < 3600 and delta.days == 0:
            return f"há {delta.seconds // 60}min"
        elif delta.days == 0:
            return f"às {dt_local.strftime('%H:%M')}"
        elif delta.days == 1:
            return f"ontem às {dt_local.strftime('%H:%M')}"
        else:
            return dt_local.strftime("%d/%m %H:%M")
    except Exception:
        return "data?"


# ── API Pública ──────────────────────────────────────────────────────────────

def ler_canal(canal_id_ou_nome: str, n: int = 20) -> str:
    """
    Lê as últimas `n` mensagens de um canal.
    Aceita ID numérico ou nome mapeado em discord_servers.json.
    """
    _load_config()
    if not _DEFAULT_TOKEN:
        return (
            "Token do Discord não configurado, senhor.\n"
            "Adicione DISCORD_BOT_TOKEN em config.py e convide o bot ao servidor."
        )

    cid = _resolve_channel_id(canal_id_ou_nome) or canal_id_ou_nome.strip()
    data = _get(f"/channels/{cid}/messages?limit={min(n, 50)}")
    if data is None:
        return (
            f"Não foi possível acessar o canal '{canal_id_ou_nome}', senhor.\n"
            "Verifique se o ID está correto e o bot tem permissão de leitura."
        )

    if not data:
        return f"Canal '{canal_id_ou_nome}' está vazio, senhor."

    linhas = []
    for msg in reversed(data[:n]):
        autor  = msg.get("author", {}).get("global_name") or msg.get("author", {}).get("username", "?")
        conteudo = msg.get("content", "").strip()
        ts     = _fmt_ts(msg.get("timestamp", ""))
        # Ignora mensagens de bots/webhooks a menos que tenham conteúdo relevante
        is_bot = msg.get("author", {}).get("bot", False)
        if is_bot and not conteudo:
            continue
        prefixo = "🤖" if is_bot else "👤"
        if conteudo:
            linhas.append(f"[{ts}] {prefixo}{autor}: {conteudo[:200]}")
        # Embeds (resumido)
        for emb in msg.get("embeds", []):
            titulo = emb.get("title", "")
            descr  = emb.get("description", "")[:80]
            if titulo:
                linhas.append(f"[{ts}] 📌{autor} (embed): {titulo} — {descr}")

    if not linhas:
        return "Nenhuma mensagem de texto encontrada no canal, senhor."

    return f"Últimas {len(linhas)} mensagens do canal:\n" + "\n".join(linhas)


def resumir_canal(canal_id_ou_nome: str, n: int = 30) -> str:
    """
    Retorna o texto bruto das mensagens para ser resumido pelo LLM.
    O chamador deve passar esse texto para o modelo.
    """
    _load_config()
    cid = _resolve_channel_id(canal_id_ou_nome) or canal_id_ou_nome.strip()
    data = _get(f"/channels/{cid}/messages?limit={min(n, 50)}")
    if not data:
        return f"Sem acesso ao canal '{canal_id_ou_nome}', senhor."

    linhas = []
    for msg in reversed(data):
        autor    = msg.get("author", {}).get("username", "?")
        conteudo = msg.get("content", "").strip()
        if conteudo:
            linhas.append(f"{autor}: {conteudo[:300]}")

    return "\n".join(linhas) if linhas else "Canal sem mensagens de texto."


def listar_servidores() -> str:
    """Lista os servidores que o bot participa."""
    _load_config()
    data = _get("/users/@me/guilds")
    if not data:
        return "Não foi possível listar servidores, senhor."
    linhas = [f"• {g.get('name', '?')} (ID: {g.get('id', '?')})" for g in data[:20]]
    return f"Servidores do bot ({len(linhas)}):\n" + "\n".join(linhas)


def listar_canais(guild_id_ou_nome: str) -> str:
    """Lista os canais de texto de um servidor."""
    _load_config()
    gid = _resolve_guild_id(guild_id_ou_nome) or guild_id_ou_nome.strip()
    data = _get(f"/guilds/{gid}/channels")
    if not data:
        return f"Não foi possível acessar o servidor '{guild_id_ou_nome}', senhor."
    # Tipo 0 = texto, tipo 2 = voz, tipo 4 = categoria
    canais_texto = [c for c in data if c.get("type") == 0]
    linhas = [f"• #{c['name']} (ID: {c['id']})" for c in canais_texto[:25]]
    return f"Canais de texto ({len(linhas)}):\n" + "\n".join(linhas)


def status_voz(guild_id_ou_nome: str) -> str:
    """Mostra quem está nos canais de voz de um servidor."""
    _load_config()
    gid = _resolve_guild_id(guild_id_ou_nome) or guild_id_ou_nome.strip()
    data = _get(f"/guilds/{gid}/voice-states")
    if data is None:
        return f"Não foi possível verificar canais de voz, senhor."
    if not data:
        return "Nenhum membro nos canais de voz agora, senhor."
    por_canal: dict[str, list[str]] = {}
    for vs in data:
        canal = vs.get("channel_id", "?")
        user  = vs.get("member", {}).get("user", {}).get("global_name") \
             or vs.get("member", {}).get("user", {}).get("username", "?")
        por_canal.setdefault(canal, []).append(user)
    linhas = [f"Canal {cid}: {', '.join(users)}" for cid, users in por_canal.items()]
    return "Status de voz:\n" + "\n".join(linhas)


def info_servidor(guild_id_ou_nome: str) -> str:
    """Retorna informações gerais de um servidor."""
    _load_config()
    gid = _resolve_guild_id(guild_id_ou_nome) or guild_id_ou_nome.strip()
    data = _get(f"/guilds/{gid}?with_counts=true")
    if not data:
        return f"Servidor '{guild_id_ou_nome}' não encontrado, senhor."
    nome       = data.get("name", "?")
    membros    = data.get("approximate_member_count", "?")
    online     = data.get("approximate_presence_count", "?")
    dono       = data.get("owner_id", "?")
    desc       = data.get("description") or "sem descrição"
    return (
        f"Servidor: {nome}\n"
        f"Membros: {membros} ({online} online)\n"
        f"Dono ID: {dono}\n"
        f"Descrição: {desc}"
    )


def adicionar_mapeamento(tipo: str, nome: str, discord_id: str) -> str:
    """
    Adiciona um mapeamento nome→ID.
    tipo: 'guild' ou 'channel'
    """
    servers = _load_servers()
    chave = "guilds" if tipo.lower() in ("guild", "servidor", "server") else "channels"
    servers.setdefault(chave, {})[nome.lower()] = discord_id
    _save_servers(servers)
    tipo_label = "servidor" if chave == "guilds" else "canal"
    return f"Mapeamento adicionado: '{nome}' → {discord_id} ({tipo_label}), senhor."


def listar_mapeamentos() -> str:
    """Lista todos os mapeamentos nome→ID configurados."""
    servers = _load_servers()
    linhas = []
    for nome, id_ in servers.get("guilds", {}).items():
        linhas.append(f"🏠 Servidor '{nome}' → {id_}")
    for nome, id_ in servers.get("channels", {}).items():
        linhas.append(f"💬 Canal '{nome}' → {id_}")
    if not linhas:
        return (
            "Nenhum mapeamento configurado ainda, senhor.\n"
            "Use: 'mapeia servidor NOME ID' ou 'mapeia canal NOME ID'"
        )
    return "Mapeamentos do Discord:\n" + "\n".join(linhas)


def ler_dms(n: int = 10) -> str:
    """Lê as DMs mais recentes do bot (canais DM abertos)."""
    _load_config()
    data = _get("/users/@me/channels")
    if not data:
        return "Sem DMs disponíveis, senhor."
    dms = [c for c in data if c.get("type") == 1][:n]
    if not dms:
        return "Nenhuma DM aberta, senhor."
    linhas = []
    for dm in dms:
        recs = dm.get("recipients", [{}])
        nome = recs[0].get("global_name") or recs[0].get("username", "?") if recs else "?"
        linhas.append(f"• DM com {nome} (ID: {dm['id']})")
    return "DMs abertas:\n" + "\n".join(linhas)


def enviar_mensagem(destinatario: str, mensagem: str) -> str:
    """
    Envia uma mensagem pelo Discord.

    Lógica de resolução do destino:
      - Vazio → usa DISCORD_CHANNEL_ID do config.py
      - ID numérico (15-20 dígitos) → canal ou DM direto
      - Nome mapeado em discord_servers.json → canal mapeado
      - '@nome' ou nome de usuário → busca nos membros dos servidores e envia DM
    O bot precisa ter permissão 'Send Messages' no canal ou 'Create DMs'.
    """
    _load_config()
    if not _DEFAULT_TOKEN:
        return (
            "Token do Discord não configurado, senhor.\n"
            "Adicione DISCORD_BOT_TOKEN em config.py."
        )
    if not mensagem.strip():
        return "Mensagem vazia, senhor."

    dest = destinatario.strip()

    # Sem destinatário → usa canal padrão do config
    if not dest:
        try:
            from config import DISCORD_CHANNEL_ID  # type: ignore
            dest = str(DISCORD_CHANNEL_ID).strip()
        except ImportError:
            pass
        if not dest:
            return (
                "Nenhum destinatário informado e DISCORD_CHANNEL_ID não configurado "
                "em config.py, senhor."
            )

    channel_id: Optional[str] = None

    # ID numérico direto → tenta como canal/DM
    if re.fullmatch(r"\d{15,20}", dest):
        channel_id = dest
    else:
        # Tenta resolver como nome de canal mapeado
        channel_id = _resolve_channel_id(dest)

        if not channel_id:
            # Tenta como usuário → DM
            user_id = _find_user_id(dest)
            if not user_id:
                return (
                    f"Não encontrei '{dest}' como canal ou usuário do Discord, senhor.\n"
                    "Use o ID numérico, o nome mapeado em discord_servers.json, "
                    "ou @username do Discord."
                )
            channel_id = _create_dm_channel(user_id)
            if not channel_id:
                return (
                    f"Não foi possível criar DM com '{dest}', senhor.\n"
                    "Verifique se o bot está no mesmo servidor que o usuário."
                )

    data = _post(f"/channels/{channel_id}/messages", {"content": mensagem[:2000]})
    if data:
        return "Mensagem enviada no Discord com sucesso, senhor."
    return (
        "Falha ao enviar a mensagem no Discord, senhor.\n"
        "Verifique se o bot tem permissão 'Send Messages' no canal."
    )


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD MONITOR — polling de mensagens via screenshot + OCR
# Detecta novas mensagens mesmo com Discord em foco (sem toast do Windows)
# ─────────────────────────────────────────────────────────────────────────────

import threading as _threading
import time as _time_mod
import hashlib as _hashlib


class DiscordMonitor:
    """
    Monitora o canal do Discord aberto por polling de screenshot.
    Detecta novas mensagens mesmo quando o Discord está em foco (sem
    notificações toast do Windows).

    Uso::

        mon = DiscordMonitor(callback=fn, intervalo=3.0, cooldown_min=5.0)
        mon.start()
        # ...
        mon.stop()

    O callback tem assinatura: ``fn(app_key: str, sender: str, msgs: list[dict])``
    """

    # Singleton do reader easyocr (carregado uma vez, reutilizado)
    _ocr_reader: object = None

    def __init__(self, callback, intervalo: float = 3.0, cooldown_min: float = 5.0):
        self._callback = callback
        self._intervalo = intervalo
        self._cooldown_min = cooldown_min
        self._last_hash: str = ""
        self._last_lines: list[str] = []
        self._running = False
        self._thread: _threading.Thread | None = None
        # cooldowns: canal_key -> timestamp do último reply
        self._cooldowns: dict[str, float] = {}

    # ── Controle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._last_hash = ""
        self._last_lines = []
        self._thread = _threading.Thread(
            target=self._loop, daemon=True, name="DiscordMon"
        )
        self._thread.start()
        print("[DISCORD-MON] Monitor iniciado.")

    def stop(self) -> None:
        self._running = False
        print("[DISCORD-MON] Monitor parado.")

    def is_ativo(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    # ── Cooldown helpers ──────────────────────────────────────────────────────

    def em_cooldown(self, canal_key: str = "default") -> bool:
        """Retorna True se o canal ainda está dentro do período de cooldown."""
        ts = self._cooldowns.get(canal_key, 0.0)
        return (_time_mod.time() - ts) < (self._cooldown_min * 60)

    def registrar_reply(self, canal_key: str = "default") -> None:
        """Marca que um auto-reply foi enviado para este canal agora."""
        self._cooldowns[canal_key] = _time_mod.time()

    # ── Internos ──────────────────────────────────────────────────────────────

    def _get_discord_hwnd(self) -> int | None:
        """Retorna o HWND da janela principal do Discord (visível), ou None."""
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
            if "discord" in t and "discord helper" not in t and "discord updater" not in t:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_ENUM(_cb), 0)
        return found[0] if found else None

    def _get_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        import ctypes, ctypes.wintypes
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
        return None

    def _screenshot_chat(
        self, rect: tuple[int, int, int, int]
    ) -> bytes | None:
        """Captura a área de chat do Discord (exclui nav lateral e input)."""
        left, top, right, bottom = rect
        w = right - left
        h = bottom - top
        # Discord layout: sidebar ~15% w esquerda, chat ~70% central, input ~8% baixo
        sx = left + int(w * 0.15)
        sy = top  + int(h * 0.08)
        sw = int(w * 0.70)
        sh = int(h * 0.80)
        try:
            import mss
            with mss.mss() as sct:
                mon = {"left": sx, "top": sy, "width": sw, "height": sh}
                frame = sct.grab(mon)
                import mss.tools
                return mss.tools.to_png(frame.rgb, frame.size)
        except ImportError:
            pass
        try:
            from PIL import ImageGrab
            import io as _io
            im = ImageGrab.grab(bbox=(sx, sy, sx + sw, sy + sh))
            buf = _io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    @staticmethod
    def _hash(data: bytes) -> str:
        return _hashlib.md5(data).hexdigest()

    def _ocr(self, png: bytes) -> list[str]:
        """Extrai linhas de texto da imagem PNG. Tenta easyocr depois pytesseract."""
        # ── easyocr ──────────────────────────────────────────────────────────
        try:
            import easyocr, io, numpy as np
            from PIL import Image
            img = Image.open(io.BytesIO(png)).convert("RGB")
            arr = np.array(img)
            reader = DiscordMonitor._ocr_reader
            if reader is None:
                reader = easyocr.Reader(["pt", "en"], gpu=False, verbose=False)
                DiscordMonitor._ocr_reader = reader
            results = reader.readtext(arr, detail=0, paragraph=True)
            return [r.strip() for r in results if r.strip()]
        except ImportError:
            pass
        # ── pytesseract ───────────────────────────────────────────────────────
        try:
            import pytesseract, io
            from PIL import Image
            img = Image.open(io.BytesIO(png)).convert("L")
            text = pytesseract.image_to_string(img, lang="por+eng")
            return [ln.strip() for ln in text.splitlines() if ln.strip()]
        except Exception:
            pass
        return []

    def _novas_linhas(self, current: list[str]) -> list[str]:
        prev = set(self._last_lines[-30:])
        return [ln for ln in current if ln not in prev]

    def _loop(self) -> None:
        while self._running:
            try:
                hwnd = self._get_discord_hwnd()
                if hwnd:
                    rect = self._get_rect(hwnd)
                    if rect:
                        png = self._screenshot_chat(rect)
                        if png:
                            h = self._hash(png)
                            if h != self._last_hash:
                                self._last_hash = h
                                lines = self._ocr(png)
                                novas = self._novas_linhas(lines)
                                # Só dispara após ter um estado de referência
                                if novas and self._last_lines:
                                    conteudo = "\n".join(novas)
                                    try:
                                        self._callback(
                                            "discord",
                                            "Discord",
                                            [{"type": "text", "content": conteudo}],
                                        )
                                    except Exception as _ce:
                                        print(f"[DISCORD-MON] callback error: {_ce}")
                                if lines:
                                    self._last_lines = lines
            except Exception as _e:
                print(f"[DISCORD-MON] Erro no loop: {_e}")
            _time_mod.sleep(self._intervalo)


# ── Singleton global ──────────────────────────────────────────────────────────

_monitor_instance: DiscordMonitor | None = None
_monitor_lock = _threading.Lock()


def start_monitor(
    callback,
    intervalo: float = 3.0,
    cooldown_min: float = 5.0,
) -> DiscordMonitor:
    """Inicia (ou reinicia) o monitor de mensagens do Discord."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance and _monitor_instance.is_ativo():
            _monitor_instance.stop()
        _monitor_instance = DiscordMonitor(callback, intervalo, cooldown_min)
        _monitor_instance.start()
        return _monitor_instance


def stop_monitor() -> None:
    """Para o monitor de mensagens do Discord."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance:
            _monitor_instance.stop()
            _monitor_instance = None


def get_monitor() -> DiscordMonitor | None:
    """Retorna a instância do monitor ativo, ou None."""
    return _monitor_instance
