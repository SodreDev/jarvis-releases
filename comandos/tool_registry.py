# comandos/tool_registry.py — Catálogo de tools para LLM tool-calling
# -*- coding: utf-8 -*-
"""
Registry central de tools que o LLM (LM Studio ou Groq) pode chamar via
function-calling. Cada tool tem:

    - name        : identificador único usado pelo LLM
    - description : descrição em PT explicando QUANDO usar a tool
    - parameters  : JSON Schema (OpenAI tools format)
    - handler     : função que recebe (app, **kwargs) e retorna str

A função `to_openai_tools()` retorna a lista no formato aceito por
chat.completions.create(tools=[...]).

A função `dispatch(name, args, app)` executa a tool e devolve o resultado
para a LLM continuar a conversa.

Design notes:
- Handlers nunca falam diretamente (não chamam `_falar`). Eles retornam o
  resultado em texto para o LLM compor a fala final com personalidade.
- Em caso de erro, devolvem string começando com "ERRO:" para o LLM tratar.
- O `app` é o JarvisApp; tools usam app._sp (Spotify), app._exibir_resposta etc.
"""

from __future__ import annotations

import json as _json
import traceback as _tb
import webbrowser as _wb
from typing import Any, Callable
from urllib.parse import quote_plus as _qp

from jarvis.platform import open_path as _open_path


# ─────────────────────────────────────────────────────────────────────────
# Tool definition
# ─────────────────────────────────────────────────────────────────────────

def _strictify(params: dict) -> dict:
    """Converte um JSON Schema de parâmetros para o formato `strict` aceito por
    OpenAI/Claude: `additionalProperties:false` e TODOS os campos em `required`
    (recursivo — também em objetos e arrays aninhados). Campos OPCIONAIS viram
    nullable (type aceita "null"); o modelo pode "omiti-los" passando null — o
    `dispatch` descarta None no topo e os handlers/renderers ignoram None
    aninhado. Best-effort e não-destrutivo (faz cópia)."""
    import copy as _copy
    p = _copy.deepcopy(params or {})
    if not isinstance(p, dict):
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    return _strictify_node(p)


def _strictify_node(node: dict) -> dict:
    """Aplica regras strict a um nó de schema, recursivamente."""
    if not isinstance(node, dict):
        return node
    props = node.get("properties")
    if isinstance(props, dict):
        node.setdefault("type", "object")
        req_orig = set(node.get("required") or [])
        for name, spec in props.items():
            if not isinstance(spec, dict):
                continue
            _strictify_node(spec)  # recursa antes de mexer no type
            if name not in req_orig:
                t = spec.get("type")
                if isinstance(t, str) and t != "null":
                    spec["type"] = [t, "null"]
                elif isinstance(t, list) and "null" not in t:
                    spec["type"] = t + ["null"]
                if isinstance(spec.get("enum"), list) and None not in spec["enum"]:
                    spec["enum"] = spec["enum"] + [None]
        node["required"] = list(props.keys())
        node["additionalProperties"] = False
    items = node.get("items")
    if isinstance(items, dict):
        _strictify_node(items)
    return node


class Tool:
    __slots__ = ("name", "description", "parameters", "handler")

    def __init__(self, name: str, description: str,
                 parameters: dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_openai_schema(self, strict: bool = False, compact: bool = False) -> dict:
        _desc = _compact_desc(self.description) if compact else self.description
        _params = _compact_params(self.parameters) if compact else self.parameters
        fn = {
            "name": self.name,
            "description": _desc,
            "parameters": _params,
        }
        # strict=True: força args schema-válidos (Claude/OpenAI strict). Requer
        # que TODOS os campos estejam em `required` + additionalProperties:false.
        # `_strictify` torna campos OPCIONAIS nullable, e o `dispatch` descarta
        # None → o handler usa seu default. Assim tools com args opcionais não
        # quebram. (Toggle AGENT_STRICT_TOOLS, OFF por padrão.)
        if strict:
            fn["parameters"] = _strictify(_params)
            fn["strict"] = True
        return {"type": "function", "function": fn}


_TOOLS: dict[str, Tool] = {}


def register(name: str, description: str, parameters: dict):
    def deco(fn):
        _TOOLS[name] = Tool(name, description, parameters, fn)
        return fn
    return deco


def _compact_desc(desc: str, maxlen: int = 240) -> str:
    """Description compacta: 1ª-2ª frase/linha (onde fica 'o que é + use quando')."""
    import re as _re
    d = (desc or "").strip()
    parts = _re.split(r"(?<=[.!?])\s+|\n", d)
    d = " ".join(p.strip() for p in parts[:2] if p.strip())
    if len(d) > maxlen:
        d = d[:maxlen].rsplit(" ", 1)[0] + "…"
    return d.strip()


def _compact_params(params):
    """Trunca as 'description' aninhadas a ~60 chars (mantém type/enum/required/
    estrutura). É onde mora o grosso dos tokens dos schemas verbosos (MCP-Zero)."""
    def _walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "description" and isinstance(v, str) and len(v) > 60:
                    out[k] = v[:60].rsplit(" ", 1)[0] + "…"
                else:
                    out[k] = _walk(v)
            return out
        if isinstance(node, list):
            return [_walk(x) for x in node]
        return node
    try:
        return _walk(params)
    except Exception:
        return params


def to_openai_tools(strict: bool = False, names: "set[str] | list[str] | None" = None,
                    compact: bool = False) -> list[dict]:
    """Lista de tools no formato OpenAI. `names` filtra um subconjunto; `strict`
    ativa schema estrito; `compact` enxuga descrições (corta ~50-60% dos tokens)."""
    if names is not None:
        nameset = set(names)
        items = [t for t in _TOOLS.values() if t.name in nameset]
    else:
        items = list(_TOOLS.values())
    return [t.to_openai_schema(strict=strict, compact=compact) for t in items]


def list_tools() -> list[str]:
    return list(_TOOLS.keys())


# ─────────────────────────────────────────────────────────────────────────
# Camadas (namespaces) das tools — usado pela seleção em camadas do
# _pensar_e_agir (roadmap/13). Apenas organiza; não altera o dispatch.
# ─────────────────────────────────────────────────────────────────────────
TOOL_LAYERS: dict[str, str] = {
    # sistema / PC
    "controle_sistema": "sistema", "controle_audio_sistema": "sistema",
    "controle_ambiente": "sistema", "controle_modos": "sistema",
    "controle_proativo": "sistema", "controle_presenca": "sistema",
    "comando_terminal": "sistema", "listar_drives": "sistema",
    "procurar_pasta": "sistema", "criar_timer": "sistema",
    "criar_alarme": "sistema", "clima": "sistema", "display_text": "sistema",
    # mídia
    "tocar_musica": "midia", "controle_spotify": "midia",
    "reproduzir_youtube": "midia", "controle_voz_tts": "midia",
    # web / apps
    "abrir_site": "web", "abrir_app": "web", "pesquisa_web": "web",
    "pesquisa_rapida": "web", "controle_navegador": "web", "traduzir": "web",
    # mensageria
    "enviar_mensagem": "mensageria", "abrir_dm_discord": "mensageria",
    "ler_notificacoes": "mensageria", "gerenciar_contatos": "mensageria",
    # visão
    "analisar_tela": "visao", "controle_visao": "visao",
    # jogos
    "abrir_jogo": "jogos", "instalar_jogo": "jogos", "listar_jogos": "jogos",
    # memória / imagem / documentos / jarvis
    "notas_memoria": "memoria", "gerar_imagem": "imagem",
    "memoria_buscar": "memoria", "memoria_salvar_fato": "memoria",
    "memoria_esquecer": "memoria", "compactar_conversa": "memoria",
    "resumir_decisoes": "memoria", "aprender_sobre": "memoria",
    "criar_apresentacao": "documentos", "criar_relatorio": "documentos",
    "exportar_pdf": "documentos", "criar_planilha": "documentos",
    "dossie": "documentos", "criar_documento_word": "documentos",
    "encerrar_jarvis": "jarvis",
}


def layer_of(name: str) -> str:
    return TOOL_LAYERS.get(name, "geral")


def tools_in_layers(layers) -> list[str]:
    """Nomes de tools que pertencem a qualquer uma das `layers`."""
    s = set(layers)
    return [n for n in _TOOLS if layer_of(n) in s]


def dispatch(name: str, args: dict, app) -> str:
    """Executa a tool e retorna o resultado em texto.
    Nunca levanta — em erro, devolve 'ERRO: ...'."""
    tool = _TOOLS.get(name)
    if tool is None:
        return f"ERRO: tool '{name}' não existe."
    # Descarta args None (ex.: campos opcionais "omitidos" via null no modo
    # strict) → o handler usa seu valor default em vez de receber None.
    kwargs = {k: v for k, v in args.items() if v is not None} if isinstance(args, dict) else {}
    try:
        result = tool.handler(app, **kwargs)
        out = "" if result is None else str(result)
    except TypeError as e:
        out = f"ERRO: argumentos inválidos para '{name}': {e}"
    except Exception as e:
        print(f"[TOOL] Falha em {name}: {_tb.format_exc()}")
        out = f"ERRO: falha em '{name}': {type(e).__name__}: {e}"
    # Callback opcional (memória/telemetria) — nunca quebra o dispatch.
    _cb = getattr(app, "_on_tool_dispatched", None)
    if _cb is not None:
        try:
            _cb(name, kwargs, out)
        except Exception:
            pass
    return out


# ─────────────────────────────────────────────────────────────────────────
# TOOL HANDLERS
# ─────────────────────────────────────────────────────────────────────────

# ── 1. abrir_app — apps locais (NUNCA web) ───────────────────────────────

@register(
    name="abrir_app",
    description=(
        "Abre um PROGRAMA DESKTOP instalado no Windows. "
        "Use APENAS para apps que rodam fora do navegador: Spotify, Discord, "
        "VSCode, Steam, Chrome (só o navegador), Notepad, Calculadora, OBS, "
        "Photoshop, Word, Excel.\n"
        "⚠ NÃO USE para sites/serviços web. Se o nome é de um SITE "
        "(YouTube, Gmail, Reddit, Twitter, Instagram, GitHub, Netflix, "
        "Wikipedia, Google, etc), use 'abrir_site' — SEMPRE.\n"
        "Exemplos certos: 'abre o spotify', 'abre o vscode'.\n"
        "Exemplos ERRADOS (use abrir_site): 'abre o youtube', 'abre o gmail', "
        "'abre o reddit'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "nome": {
                "type": "string",
                "description": "Nome do app desktop (ex: 'spotify', 'discord', 'vscode').",
            }
        },
        "required": ["nome"],
    },
)
def _t_abrir_app(app, nome: str = "") -> str:
    from comandos import janela_ctrl
    # ── Guarda: nomes que são SITES, não apps desktop ─────────────────────
    # Se o LLM erradamente chamou abrir_app com um site conhecido,
    # redireciona automaticamente para abrir_site (navegador padrão).
    _SITES_BLOQUEADOS = {
        "youtube", "yt", "gmail", "reddit", "twitter", "x", "instagram",
        "insta", "facebook", "fb", "github", "netflix", "amazon",
        "wikipedia", "wiki", "chatgpt", "chat gpt", "maps", "google maps",
        "drive", "google drive", "twitch", "linkedin", "tiktok", "tik tok",
        "whatsapp web", "google", "bing", "duckduckgo",
    }
    nome_norm = (nome or "").strip().lower()
    if nome_norm in _SITES_BLOQUEADOS:
        try:
            return _t_abrir_site(app, nome_norm)
        except Exception:
            pass
    return janela_ctrl.abrir_app(nome)


# ── 2. abrir_site — sempre navegador ────────────────────────────────────

@register(
    name="abrir_site",
    description=(
        "Abre um SITE/SERVIÇO WEB no navegador. Use sempre que o pedido envolver "
        "qualquer serviço que rode no navegador, mesmo se o usuário só disser "
        "o nome curto. "
        "USE PARA: YouTube, Google, Gmail, Reddit, Twitter/X, Instagram, "
        "Facebook, GitHub, StackOverflow, Netflix, Amazon, Mercado Livre, "
        "Wikipedia, ChatGPT, Wolfram, Maps, sites de notícia, blog, qualquer URL "
        "ou termo de busca livre.\n"
        "Aceita URL completa OU nome curto (ex: 'youtube' → youtube.com) "
        "OU termo de busca (vai abrir DuckDuckGo).\n"
        "⚠ EM DÚVIDA entre app e site, escolha SEMPRE esta tool."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url_ou_query": {
                "type": "string",
                "description": (
                    "URL completa, nome curto do site (ex: 'youtube'), "
                    "ou termo de busca livre."
                ),
            }
        },
        "required": ["url_ou_query"],
    },
)
def _t_abrir_site(app, url_ou_query: str = "") -> str:
    import re as _re

    def _falar_host(h: str) -> str:
        # Remove www. e a TLD final (.com, .com.br, .org, etc.) para fala mais natural
        h = h.replace("www.", "").split("/")[0]
        return _re.sub(r"\.[a-z]{2,}(\.[a-z]{2})?$", "", h, flags=_re.I) or h

    def _abrir(url: str) -> bool:
        """Abre `url` no NAVEGADOR PADRÃO do Windows via Popen direto no exe
        (funciona com navegador fechado, qualquer thread). Fallbacks:
        os.startfile, webbrowser. Para controle programático da página
        (clicar, pesquisar, ler), use a tool 'controle_navegador'."""
        try:
            from comandos import browser_ctrl as _bc
            return _bc.abrir_url_padrao(url)
        except Exception as _e:
            print(f"[abrir_site] abrir_url_padrao falhou: {_e}")
        try:
            _wb.open(url, new=2)
            return True
        except Exception:
            return False

    q = (url_ou_query or "").strip()
    if not q:
        return "ERRO: nenhuma URL ou termo informado."
    # URL direta?
    if q.startswith(("http://", "https://")):
        _abrir(q)
        try:
            from urllib.parse import urlparse
            host = urlparse(q).hostname or q
        except Exception:
            host = q
        return f"Abri {_falar_host(host)}."
    # Mapa de sites populares — nome curto → domínio
    _COMMON_SITES = {
        "youtube": "youtube.com", "yt": "youtube.com",
        "google": "google.com",
        "gmail": "mail.google.com",
        "reddit": "reddit.com",
        "twitter": "twitter.com", "x": "x.com",
        "instagram": "instagram.com", "insta": "instagram.com",
        "facebook": "facebook.com", "fb": "facebook.com",
        "whatsapp web": "web.whatsapp.com", "whatsapp": "web.whatsapp.com",
        "github": "github.com",
        "stackoverflow": "stackoverflow.com",
        "netflix": "netflix.com",
        "amazon": "amazon.com.br",
        "mercado livre": "mercadolivre.com.br", "mercadolivre": "mercadolivre.com.br",
        "wikipedia": "pt.wikipedia.org", "wiki": "pt.wikipedia.org",
        "chatgpt": "chat.openai.com", "chat gpt": "chat.openai.com",
        "maps": "maps.google.com", "google maps": "maps.google.com",
        "drive": "drive.google.com", "google drive": "drive.google.com",
        "discord web": "discord.com/app",
    }
    qlow = q.lower().strip()
    if qlow in _COMMON_SITES:
        url = "https://" + _COMMON_SITES[qlow]
        _abrir(url)
        return f"Abri {qlow}."
    # Heurística: parte antes da primeira "/" tem ponto e sem espaço → URL com path
    _host_part = q.split("/")[0].split("?")[0]
    if "." in _host_part and " " not in q:
        url = q if q.startswith("www.") else f"https://{q}"
        if not url.startswith("http"):
            url = "https://" + url
        _abrir(url)
        return f"Abri {_falar_host(q)}."
    # Termo de busca → DuckDuckGo (\!ducky redireciona para o 1º resultado)
    duck = f"https://duckduckgo.com/?q=%5C{_qp(q)}&kl=br-pt"
    _abrir(duck)
    return f"Pesquisei '{q}' e abri o primeiro resultado."

# ── 3. abrir_dm_discord — DM específica ─────────────────────────────────

@register(
    name="abrir_dm_discord",
    description=(
        "Abre uma conversa privada (DM) específica no Discord com um usuário. "
        "Use quando o pedido for tipo 'abre a DM do João no Discord' ou "
        "'fala com Maria no Discord'. NÃO confundir com 'abrir_app': abrir_app "
        "abre só o Discord; esta tool navega até a conversa específica."
    ),
    parameters={
        "type": "object",
        "properties": {
            "usuario": {
                "type": "string",
                "description": "Nome do usuário/contato dentro do Discord.",
            }
        },
        "required": ["usuario"],
    },
)
def _t_abrir_dm_discord(app, usuario: str = "") -> str:
    from comandos import janela_ctrl
    import time as _time
    user = (usuario or "").strip()
    if not user:
        return "ERRO: nome do usuário não informado."

    # 1º: garantir que o Discord está ABERTO e em PRIMEIRO PLANO antes de
    # enviar teclas — caso contrário o pyautogui digita na janela ativa
    # (ex.: navegador), o que aconteceu com o usuário assistindo Crunchyroll.
    try:
        import pygetwindow as gw
        janelas = [w for w in gw.getAllWindows() if "discord" in (w.title or "").lower()]
    except Exception:
        janelas = []

    if not janelas:
        # Discord não está aberto — abre e espera carregar
        try:
            janela_ctrl.abrir_app("discord")
        except Exception as e:
            return f"ERRO: Discord não está aberto e não consegui abrir ({e})."
        # espera até a janela aparecer (Electron demora)
        for _ in range(20):  # ~10s
            _time.sleep(0.5)
            try:
                janelas = [w for w in gw.getAllWindows() if "discord" in (w.title or "").lower()]
                if janelas:
                    break
            except Exception:
                pass
        if not janelas:
            return f"Abri o Discord, senhor. Aguarde carregar e peça de novo para abrir a DM com {user}."

    # 2º: focar a janela — tenta win32 (mais confiável no Win11) e faz
    # fallback para pygetwindow. Não aborta mais se getActiveWindow() não
    # confirmar imediatamente (Focus Stealing Prevention do Win11 atrasa).
    win = janelas[0]
    try:
        # Preferência: win32gui força o foreground sem depender de política
        import win32gui as _w32g, win32con as _w32c
        hwnd = win._hWnd
        if _w32g.IsIconic(hwnd):            # minimizado?
            _w32g.ShowWindow(hwnd, _w32c.SW_RESTORE)
        _w32g.SetForegroundWindow(hwnd)
        _time.sleep(0.35)
    except Exception:
        # Fallback: pygetwindow puro
        try:
            if getattr(win, "isMinimized", False):
                win.restore()
            win.activate()
            _time.sleep(0.4)
        except Exception as _fe:
            return f"ERRO ao focar janela do Discord: {_fe}"

    # 3º: agora sim, executa o atalho Ctrl+K + nome
    try:
        return janela_ctrl.navegar_app("discord", "dm", user)
    except Exception as e:
        return f"ERRO ao navegar até DM com {user}: {e}"

# ── 4. clima ────────────────────────────────────────────────────────────

@register(
    name="clima",
    description=(
        "Consulta o clima atual de uma cidade. Se o usuário não disser cidade, "
        "deixe o parâmetro vazio que o sistema usa a cidade configurada."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cidade": {
                "type": "string",
                "description": "Nome da cidade (opcional). Vazio = cidade do usuário.",
            }
        },
    },
)
def _t_clima(app, cidade: str = "") -> str:
    from comandos import system_ctrl as sc
    if not cidade:
        try:
            from core.win_locale import get_user_city
            cidade = get_user_city(getattr(app, "_user_city", None))
        except Exception:
            cidade = "São Paulo"
    dados = sc.get_clima(cidade)
    return sc.formatar_clima(dados)


# ── 5. tocar_musica (Spotify) ───────────────────────────────────────────

@register(
    name="tocar_musica",
    description=(
        "Toca uma música, artista, álbum ou playlist no Spotify. Use quando o "
        "usuário disser 'toca X', 'coloca música do Y', 'põe a playlist Z'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Música, artista, álbum ou playlist a tocar.",
            },
            "tipo": {
                "type": "string",
                "enum": ["musica", "artista", "album", "playlist"],
                "description": "Tipo da busca. Default: musica.",
            },
        },
        "required": ["query"],
    },
)
def _t_tocar_musica(app, query: str = "", tipo: str = "musica") -> str:
    from comandos import spotify_ctrl as sp_ctl
    sp = getattr(app, "_sp", None)
    if not sp:
        return "ERRO: Spotify não conectado."
    fn_map = {
        "musica":   sp_ctl.tocar_musica,
        "artista":  sp_ctl.tocar_artista,
        "album":    sp_ctl.tocar_album,
        "playlist": sp_ctl.tocar_playlist,
    }
    fn = fn_map.get(tipo, sp_ctl.tocar_musica)
    return fn(sp, query)


# ── 6. controle_spotify (pausar/retomar/skip/volume) ────────────────────

@register(
    name="controle_spotify",
    description=(
        "Controla o Spotify: pausar, retomar, próxima, anterior, ajustar volume. "
        "NÃO use para iniciar uma música — use 'tocar_musica'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["pausar", "retomar", "proxima", "anterior",
                         "volume", "mais_alto", "mais_baixo", "tocando"],
            },
            "valor": {
                "type": "integer",
                "description": "Para 'volume': 0-100. Outros: ignorado.",
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_spotify(app, acao: str = "", valor: int = 0) -> str:
    from comandos import spotify_ctrl as sp_ctl
    sp = getattr(app, "_sp", None)
    if not sp:
        return "ERRO: Spotify não conectado."
    if acao == "pausar":      return sp_ctl.pausar(sp)
    if acao == "retomar":     return sp_ctl.retomar(sp)
    if acao == "proxima":     return sp_ctl.proxima(sp)
    if acao == "anterior":    return sp_ctl.anterior(sp)
    if acao == "tocando":     return sp_ctl.tocando_agora(sp)
    if acao == "volume":      return sp_ctl.ajustar_volume(sp, int(valor))
    if acao == "mais_alto":   return sp_ctl.volume_relativo(sp, +10)
    if acao == "mais_baixo":  return sp_ctl.volume_relativo(sp, -10)
    return f"ERRO: ação Spotify '{acao}' desconhecida."


# ── 7. criar_alarme / criar_timer ───────────────────────────────────────

@register(
    name="criar_timer",
    description=(
        "Cria um TIMER de contagem regressiva (em segundos). Use para 'me lembra "
        "em 5 minutos', 'timer de 30 segundos', 'avisa daqui 1 hora'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "segundos": {"type": "integer", "description": "Duração em segundos."},
            "descricao": {"type": "string", "description": "O que avisar quando disparar."},
        },
        "required": ["segundos"],
    },
)
def _t_criar_timer(app, segundos: int = 0, descricao: str = "") -> str:
    from comandos import system_ctrl as sc
    secs = int(segundos)
    if secs <= 0:
        return "ERRO: duração inválida."
    label = descricao or "Timer"
    def _cb(msg):
        try:
            app.root.after(0, app._exibir_resposta, msg)
        except Exception:
            pass
    _, msg = sc.iniciar_timer(secs, label, _cb)
    return msg


@register(
    name="criar_alarme",
    description=(
        "Cria um ALARME para um horário específico do dia. Use para 'me acorda "
        "às 7 da manhã', 'alarme para 15:30', 'lembrete amanhã às 9h'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "horario": {
                "type": "string",
                "description": "Horário no formato 'HH:MM' (24h) ou 'HH:MM dia/mes'.",
            },
            "descricao": {"type": "string"},
        },
        "required": ["horario"],
    },
)
def _t_criar_alarme(app, horario: str = "", descricao: str = "") -> str:
    from comandos import alarme_ctrl
    try:
        # alarme_ctrl espera string parseável
        return alarme_ctrl.criar_alarme(horario, descricao or "Alarme",
                                        callback=lambda m: app.root.after(0, app._exibir_resposta, m))
    except Exception as e:
        return f"ERRO: {e}"


# ── 8. pesquisa_web (DuckDuckGo) ────────────────────────────────────────

@register(
    name="pesquisa_web",
    description=(
        "Pesquisa na web via DuckDuckGo e retorna um resumo. Use para perguntas "
        "factuais, atuais, ou sempre que precisar de info que não está na sua "
        "base. O resultado é texto longo — o sistema vai abrir em editor "
        "automaticamente. NÃO confunda com 'abrir_site' (que só abre URL)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Termo de busca."},
        },
        "required": ["query"],
    },
)
def _t_pesquisa_web(app, query: str = "") -> str:
    if not query.strip():
        return "ERRO: busca vazia."
    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            return "ERRO: pacote de busca não instalado."
    out_lines = [f"[LONGO]Pesquisa: {query}", ""]
    hrefs: list[str] = []
    try:
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(query, region="br-pt", max_results=5), 1):
                titulo = r.get("title", "")
                trecho = r.get("body", "")
                href = r.get("href", "")
                out_lines.append(f"{i}. {titulo}")
                if trecho:
                    out_lines.append(f"   {trecho}")
                if href:
                    out_lines.append(f"   {href}")
                    hrefs.append(href)
                out_lines.append("")
    except Exception as e:
        return f"ERRO: pesquisa falhou: {e}"
    # Busca o CORPO das 1-2 primeiras páginas — o DDG só dá um TRECHO curto (daí
    # "fica pouco conteúdo mesmo pesquisando"). Time-boxed + SSRF-safe, best-effort.
    try:
        from comandos import url_fetch_ctrl as _uf
        for href in hrefs[:2]:
            corpo = _uf.fetch_url_texto(href, timeout=4.0, max_chars=3500)
            if corpo:
                out_lines.append(f"--- conteúdo de {href} ---")
                out_lines.append(corpo)
                out_lines.append("")
    except Exception:
        pass
    full = "\n".join(out_lines)
    # Acumula no DOSSIÊ ativo (texto COMPLETO, sem cap) p/ gerar um doc rico depois.
    try:
        from jarvis.memory import dossie as _dos
        if _dos.ativo():
            _dos.anexar(f"pesquisa: {query}", full)
    except Exception:
        pass
    return full


# ── 8b. aprender_sobre — pesquisa E MEMORIZA (tool agregadora) ────────────

@register(
    name="aprender_sobre",
    description=(
        "PESQUISA um assunto e MEMORIZA o que aprendeu nas camadas Aprendizados e "
        "Pesquisas (conhecimento que fica salvo para depois). Use quando o Senhor "
        "pedir para APRENDER, ESTUDAR, se ESPECIALIZAR num tema, ou GUARDAR "
        "conhecimento sobre algo.\n"
        "NÃO use para RESPONDER algo que talvez já saiba — para consultar o que já "
        "aprendeu, use 'memoria_buscar'. NÃO confunda com 'pesquisa_web' (que só "
        "busca e mostra, SEM memorizar)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "assunto": {"type": "string", "description": "Tema a aprender/estudar."},
            "profundidade": {
                "type": "string", "enum": ["basico", "aprofundado"],
                "description": "'basico' = visão geral (1 busca); 'aprofundado' = especialização (várias buscas). Default 'basico'.",
            },
        },
        "required": ["assunto"],
    },
)
def _t_aprender_sobre(app, assunto: str = "", profundidade: str = "basico") -> str:
    if not (assunto or "").strip():
        return "ERRO: diga o assunto a aprender."
    try:
        from jarvis.memory import aggregator as _agg
        res = _agg.aprender_sobre(assunto, profundidade=profundidade, app=app)
    except Exception as e:
        return f"ERRO: falha ao aprender: {e}"
    if not res.get("ok"):
        return f"Não consegui aprender sobre '{assunto}', Senhor: {res.get('erro', '')}"
    return res.get("resumo") or f"Aprendi sobre '{assunto}', Senhor."


# ── 8c. dossie — arquivo provisório que acumula pesquisa p/ gerar doc rico ──

@register(
    name="dossie",
    description=(
        "DOSSIÊ PROVISÓRIO: rascunho onde você ACUMULA o conteúdo das pesquisas para "
        "depois gerar um documento RICO e detalhado a partir de TODO o material — e "
        "zera no fim. Fluxo p/ relatório/artigo/resumo denso:\n"
        "  1) dossie acao='iniciar' assunto='<tema>'\n"
        "  2) chame pesquisa_web (e/ou aprender_sobre) VÁRIAS vezes — elas anexam o "
        "que acharem no dossiê AUTOMATICAMENTE;\n"
        "  3) criar_relatorio com fonte_dossie='<tema>' usa TODO o conteúdo acumulado;\n"
        "  4) dossie acao='limpar' (zera o provisório).\n"
        "acao='ler' mostra o que já foi acumulado."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {"type": "string", "enum": ["iniciar", "anexar", "ler", "limpar"]},
            "assunto": {"type": "string", "description": "tema do dossiê (em 'iniciar')."},
            "fonte": {"type": "string", "description": "rótulo da fonte (em 'anexar')."},
            "texto": {"type": "string", "description": "conteúdo a anexar (em 'anexar')."},
        },
        "required": ["acao"],
    },
)
def _t_dossie(app, acao="", assunto="", fonte="", texto=""):
    try:
        from jarvis.memory import dossie as _dos
    except Exception as e:
        return f"ERRO: dossiê indisponível: {e}"
    acao = (acao or "").strip().lower()
    if acao == "iniciar":
        if not (assunto or "").strip():
            return "ERRO: diga o assunto do dossiê."
        _dos.iniciar(assunto)
        return (f"Dossiê de '{assunto}' iniciado, Senhor. Pesquise à vontade que vou "
                f"acumulando; depois é só criar_relatorio com fonte_dossie='{assunto}'.")
    if acao == "anexar":
        r = _dos.anexar(fonte or "nota", texto, assunto or None)
        return "Anexado ao dossiê." if r.get("ok") else f"ERRO: {r.get('erro')}"
    if acao == "ler":
        c = _dos.ler(assunto or None)
        return ("[LONGO]" + c) if c else "Dossiê vazio (nada acumulado ainda)."
    if acao == "limpar":
        _dos.limpar(assunto or None)
        return "Dossiê zerado, Senhor."
    return "ERRO: ação inválida (use iniciar/anexar/ler/limpar)."


# ── 9. traduzir ─────────────────────────────────────────────────────────

@register(
    name="traduzir",
    description="Traduz um texto para outro idioma.",
    parameters={
        "type": "object",
        "properties": {
            "texto": {"type": "string"},
            "para":  {"type": "string",
                      "description": "Idioma de destino (ex: 'inglês', 'espanhol')."},
        },
        "required": ["texto", "para"],
    },
)
def _t_traduzir(app, texto: str = "", para: str = "") -> str:
    from comandos import traducao_ctrl
    try:
        return traducao_ctrl.traduzir(texto, para)
    except Exception as e:
        return f"ERRO: {e}"


# ── 10. controle_sistema (volume, brilho, lock, screenshot) ─────────────

@register(
    name="controle_sistema",
    description=(
        "Controla o sistema operacional: volume mestre, screenshot, bloquear "
        "tela, sleep, desligar/reiniciar PC. NÃO use para volume do Spotify "
        "(use 'controle_spotify'). NÃO use para 'modo de jogo' / 'game mode' / "
        "'modo desenvolvedor' (use 'controle_modos')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["volume", "screenshot", "lock", "sleep",
                         "desligar", "reiniciar", "cancelar_desligamento",
                         "minimizar_tudo", "maximizar_janela", "fechar_janela"],
            },
            "valor": {"type": "integer",
                      "description": "Para 'volume': 0-100. Outros: ignorado."},
        },
        "required": ["acao"],
    },
)
def _t_controle_sistema(app, acao: str = "", valor: int = 0) -> str:
    from comandos import system_ctrl as sc
    from comandos import janela_ctrl as jc
    if acao == "volume":         return sc.set_volume(int(valor))
    if acao == "screenshot":
        path, msg = sc.tirar_screenshot()
        return msg
    if acao == "lock":           return sc.bloquear_tela()
    if acao == "sleep":          return sc.modo_sleep()
    if acao in ("desligar", "reiniciar"):
        # Ações DESTRUTIVAS: usa o sistema de _pending_confirm_acao já existente
        # em _processar_texto para solicitar confirmação antes de executar.
        app._pending_confirm_acao = ("controle_sistema_exec", acao, 0)
        app._follow_up = True
        verbo = "desligar" if acao == "desligar" else "reiniciar"
        return f"Senhor, confirma que deseja {verbo} o computador?"
    if acao == "cancelar_desligamento": return sc.cancelar_desligamento()
    if acao == "minimizar_tudo": return jc.minimizar_tudo()
    if acao == "maximizar_janela": return jc.maximizar_janela()
    if acao == "fechar_janela":  return jc.fechar_janela_ativa()
    return f"ERRO: ação '{acao}' desconhecida."


# ── 10a. controle_modos (game_mode, dev_mode) ───────────────────────────

@register(
    name="controle_modos",
    description=(
        "Ativa ou desativa MODOS especiais do JARVIS. Use SEMPRE para qualquer "
        "pedido relacionado a 'modo de jogo' / 'game mode' / 'modo gamer' / "
        "'modo desenvolvedor' / 'dev mode'. NÃO confundir com controle_sistema "
        "(que é para desligar PC, volume, etc). "
        "Modo Jogo: descarrega modelos locais para liberar VRAM para games. "
        "Modo Dev: ativa integração com VSCode/Copilot."
    ),
    parameters={
        "type": "object",
        "properties": {
            "modo": {
                "type": "string",
                "enum": ["game", "dev"],
                "description": "Qual modo controlar: 'game' (modo de jogo) ou 'dev' (desenvolvedor).",
            },
            "estado": {
                "type": "string",
                "enum": ["ativar", "desativar", "status"],
                "description": "Ação: ativar, desativar, ou consultar status.",
            },
        },
        "required": ["modo", "estado"],
    },
)
def _t_controle_modos(app, modo: str = "", estado: str = "") -> str:
    import threading as _th
    modo = (modo or "").strip().lower()
    estado = (estado or "").strip().lower()
    if modo == "game":
        if estado == "ativar":
            _th.Thread(target=app._ativar_game_mode, daemon=True).start()
            return "Modo Jogo ativado, Senhor. Descarregando modelos locais."
        if estado == "desativar":
            _th.Thread(target=app._desativar_game_mode, daemon=True).start()
            return "Modo Jogo desativado, Senhor. Recarregando modelos."
        if estado == "status":
            from core import game_mode_manager as _gm
            return _gm.status(app)
    if modo == "dev":
        if estado == "ativar":
            _th.Thread(target=app._ativar_dev_mode, daemon=True).start()
            return "Modo Desenvolvedor ativado, Senhor."
        if estado == "desativar":
            _th.Thread(target=app._desativar_dev_mode, daemon=True).start()
            return "Modo Desenvolvedor desativado, Senhor."
        if estado == "status":
            try:
                from core.dev_mode import status as _dev_status
                return _dev_status(app)
            except Exception:
                return "Modo Dev: status indisponível."
    return f"ERRO: combinação modo='{modo}' estado='{estado}' inválida."


# ── 10b. analisar_tela (vision) ──────────────────────────────────────────

@register(
    name="analisar_tela",
    description=(
        "Captura a tela do Senhor e ANALISA visualmente com modelo de visão "
        "(Qwen3-VL local). Use SEMPRE que o pedido envolver: 'olha minha tela', "
        "'o que estou assistindo/vendo', 'o que está aberto', 'descreve o que "
        "tem na tela', 'lê o que está escrito aí', 'qual o erro que apareceu', "
        "'o que esse aplicativo mostra', 'analisa essa imagem'.\n"
        "NÃO confundir com abrir_app/abrir_site \u2014 esta tool LÊ a tela atual; "
        "as outras ABREM coisas. NÃO use para screenshot simples (use "
        "controle_sistema com acao='screenshot' se o Senhor só quer salvar a "
        "imagem sem análise).\n"
        "O parâmetro 'pergunta' é o que o Senhor quer saber sobre a tela "
        "(repassado ao modelo de visão). Se o pedido for genérico, deixe vazio."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pergunta": {
                "type": "string",
                "description": (
                    "O que o Senhor quer saber sobre a tela. Ex.: 'o que estou "
                    "assistindo', 'qual erro aparece', 'que site é esse'. "
                    "Vazio = descrição geral."
                ),
            }
        },
    },
)
def _t_analisar_tela(app, pergunta: str = "") -> str:
    import threading as _th
    try:
        # Dispara análise em thread (streaming exibe sozinho); retorna feedback
        # curto para o LLM compor a fala. O resultado real aparece via streaming.
        _th.Thread(
            target=app._analisar_tela,
            args=(pergunta or "",),
            daemon=True,
        ).start()
        return "Analisando a tela, Senhor."
    except Exception as e:
        return f"ERRO ao iniciar análise visual: {e}"


# ── 10c. controle_visao (descarregar/manter modelo de visão Qwen-VL) ─────

@register(
    name="controle_visao",
    description=(
        "Gerencia o modelo de visão (Qwen3-VL) na VRAM. Use quando o Senhor "
        "pedir para 'descarregar/desligar/liberar a visão', 'tirar o modelo "
        "de visão da memória', 'libera VRAM da visão', ou 'manter a visão "
        "carregada'. NÃO use para analisar a tela (use 'analisar_tela')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["descarregar", "manter"],
                "description": (
                    "'descarregar' libera a VRAM do modelo de visão. "
                    "'manter' confirma que deve ficar carregado."
                ),
            }
        },
        "required": ["acao"],
    },
)
def _t_controle_visao(app, acao: str = "") -> str:
    import threading as _th
    a = (acao or "").strip().lower()
    if a == "descarregar":
        # Cancela timer de auto-unload se existir
        try:
            t = getattr(app, "_vision_unload_timer", None)
            if t is not None:
                t.cancel()
        except Exception:
            pass
        _th.Thread(target=app._descarregar_qwen, daemon=True).start()
        return "Descarregando modelo de visão, senhor."
    if a == "manter":
        # Renova janela de 5min — usuário disse explicitamente que quer manter
        try:
            app._agendar_unload_visao()
        except Exception:
            pass
        return "Modelo de visão permanece carregado, senhor."
    return f"ERRO: ação '{acao}' desconhecida (use 'descarregar' ou 'manter')."


# ── 10d. encerrar_jarvis (sair / reiniciar o próprio JARVIS) ─────────────

@register(
    name="encerrar_jarvis",
    description=(
        "Encerra ou reinicia o próprio JARVIS. Use APENAS quando o Senhor pedir: "
        "'encerre você mesmo', 'sai do programa', 'fecha o Jarvis', "
        "'desliga você', 'até mais Jarvis', 'reinicia você', 'restart'. "
        "NÃO use para 'para de me ouvir' / 'silencio' / 'para de escutar' "
        "(use controle_ambiente para isso). "
        "NÃO use para desligar/reiniciar o computador (use controle_sistema)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["encerrar", "reiniciar"],
                "description": (
                    "'encerrar' fecha o JARVIS. 'reiniciar' reinicia o processo."
                ),
            }
        },
        "required": ["acao"],
    },
)
def _t_encerrar_jarvis(app, acao: str = "") -> str:
    import threading as _th
    import os as _os
    a = (acao or "").strip().lower()
    # Default tolerante: se o LLM esqueceu o param ou mandou algo vazio,
    # assume "encerrar" — o nome da tool já implica fechamento.
    if a in ("", "fechar", "sair", "encerrar", "desligar", "tchau", "ate mais", "até mais"):
        a = "encerrar"
    elif a in ("reiniciar", "restart", "reboot"):
        a = "reiniciar"
    if a == "reiniciar":
        _th.Thread(target=app._reiniciar_jarvis, daemon=True).start()
        return "Reiniciando, senhor. Até já."
    if a == "encerrar":
        def _bye():
            import time as _t
            _t.sleep(2.0)  # deixa TTS falar antes
            try:
                if getattr(app, "_window", None):
                    app._window.destroy()
            except Exception:
                pass
            _os._exit(0)
        _th.Thread(target=_bye, daemon=True).start()
        return "Encerrando, senhor. Até a próxima."
    return f"ERRO: ação '{acao}' desconhecida (use 'encerrar' ou 'reiniciar')."


# ── 10e. controle_navegador (Playwright sobre o navegador instalado) ─────

@register(
    name="controle_navegador",
    description=(
        "Controla o navegador do Senhor (Chrome, Edge, Brave, Opera, Vivaldi, "
        "Arc, Yandex — usa o que estiver instalado, sem baixar nada). Permite "
        "abrir URLs, ler o conteúdo da página atual, listar links, clicar em "
        "elementos por texto, preencher campos e navegar (voltar/avançar/"
        "recarregar). Mantém uma sessão persistente com perfil próprio do JARVIS "
        "(logins ficam salvos entre execuções).\n"
        "USE EM SEQUÊNCIA com abrir_site para fluxos complexos: ex. abrir um "
        "site e DEPOIS clicar em um item específico, ou buscar e clicar no "
        "primeiro resultado de uma SPA (Crunchyroll, YouTube, Netflix, etc.).\n"
        "AÇÕES:\n"
        "• 'pesquisar' — digita na barra de busca da página atual e pressiona "
        "Enter (parâmetro 'texto'). USE para pesquisar dentro do YouTube, Google, "
        "Netflix, Crunchyroll etc. quando o usuário diz 'pesquise X', 'busque Y', "
        "'procure Z na página'. É um atalho para preencher_campo + pressionar_enter.\n"
        "• 'abrir_url' — navega para uma URL (parâmetro 'url'). Aceita também "
        "'navegador' opcional ('brave', 'chrome', 'edge', 'opera', 'vivaldi', "
        "'arc') na PRIMEIRA chamada da sessão.\n"
        "• 'ler_pagina' — extrai o texto principal da página atual.\n"
        "• 'listar_links' — top 15 links da página atual.\n"
        "• 'clicar_texto' — clica no primeiro elemento contendo o texto "
        "(parâmetro 'texto'). Use para clicar em vídeos, episódios, botões.\n"
        "• 'buscar_e_clicar' — variante mais agressiva de clicar_texto, tenta "
        "vários seletores (parâmetro 'query').\n"
        "• 'preencher_campo' — preenche input por label/placeholder/seletor "
        "(parâmetros 'campo' e 'valor'). Útil para search bars.\n"
        "• 'pressionar_enter' — submete form ou ativa o campo focado.\n"
        "• 'voltar', 'avancar', 'recarregar' — navegação.\n"
        "• 'fechar_sessao' — encerra o navegador do JARVIS.\n"
        "• 'status' — info da sessão atual + navegadores disponíveis."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": [
                    "pesquisar",
                    "abrir_url", "ler_pagina", "listar_links",
                    "clicar_texto", "buscar_e_clicar",
                    "preencher_campo", "pressionar_enter",
                    "voltar", "avancar", "recarregar",
                    "fechar_sessao", "status",
                ],
            },
            "url": {"type": "string", "description": "URL para abrir_url."},
            "texto": {"type": "string", "description": "Texto para clicar_texto."},
            "query": {"type": "string", "description": "Texto para buscar_e_clicar."},
            "campo": {"type": "string", "description": "Label/placeholder/CSS para preencher_campo."},
            "valor": {"type": "string", "description": "Valor para preencher_campo."},
            "navegador": {
                "type": "string",
                "description": (
                    "Opcional na primeira chamada: 'brave', 'chrome', 'edge', "
                    "'opera', 'vivaldi', 'arc', 'yandex'. Se omitido, usa o "
                    "primeiro detectado pela ordem de prioridade."
                ),
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_navegador(
    app,
    acao: str = "",
    url: str = "",
    texto: str = "",
    query: str = "",
    campo: str = "",
    valor: str = "",
    navegador: str = "",
) -> str:
    from comandos import browser_ctrl as bc
    a = (acao or "").strip().lower()
    try:
        if a == "pesquisar":     return bc.pesquisar(texto or query or valor)
        if a == "abrir_url":      return bc.abrir_url(url, navegador or None)
        if a == "ler_pagina":     return bc.ler_pagina()
        if a == "listar_links":   return bc.listar_links()
        if a == "clicar_texto":   return bc.clicar_texto(texto)
        if a == "buscar_e_clicar":return bc.buscar_e_clicar(query or texto)
        if a == "preencher_campo":return bc.preencher_campo(campo, valor)
        if a == "pressionar_enter":return bc.pressionar_enter()
        if a == "voltar":         return bc.voltar()
        if a == "avancar":        return bc.avancar()
        if a == "recarregar":     return bc.recarregar()
        if a == "fechar_sessao":  return bc.fechar_sessao()
        if a == "status":         return bc.status()
        return f"ERRO: ação '{acao}' desconhecida."
    except Exception as e:
        return f"ERRO controle_navegador: {e}"


# ── 10f. reproduzir_youtube (busca + autoplay via controle_navegador) ────

@register(
    name="reproduzir_youtube",
    description=(
        "Busca um vídeo no YouTube e abre/toca o primeiro resultado automaticamente. "
        "Use quando o Senhor pedir para ASSISTIR, VER ou ABRIR um vídeo no YouTube: "
        "'toca X no youtube', 'reproduz Y', 'abre um vídeo sobre Z', "
        "'quero ver vídeo de W', 'abre vídeo recente sobre T'. "
        "Para apenas abrir o YouTube (sem buscar vídeo) use 'abrir_site'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca (título do vídeo, artista+música, etc.)",
            },
        },
        "required": ["query"],
    },
)
def _t_reproduzir_youtube(app, query: str = "") -> str:
    from comandos import browser_ctrl as bc
    if not query:
        return "ERRO: query vazia."
    return bc.reproduzir_youtube(query)


# ── 11. notas_memoria ───────────────────────────────────────────────────

@register(
    name="notas_memoria",
    description=(
        "Salva ou consulta lembretes/notas pessoais ('me lembra que', 'salva "
        "que', 'o que eu salvei sobre X')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao":     {"type": "string", "enum": ["salvar", "consultar", "listar"]},
            "conteudo": {"type": "string"},
        },
        "required": ["acao"],
    },
)
def _t_notas_memoria(app, acao: str = "", conteudo: str = "") -> str:
    from comandos import memoria_ctrl
    try:
        if acao == "salvar":
            return memoria_ctrl.salvar(conteudo)
        if acao == "consultar":
            return memoria_ctrl.consultar(conteudo)
        if acao == "listar":
            return memoria_ctrl.listar()
        return f"ERRO: ação '{acao}' inválida."
    except Exception as e:
        return f"ERRO: {e}"


# ── 12. ler_notificacoes ────────────────────────────────────────────────

@register(
    name="ler_notificacoes",
    description=(
        "Lê as notificações pendentes (WhatsApp, Discord, Instagram). Use "
        "quando o usuário pedir 'lê minhas mensagens', 'tenho notificações?', "
        "'o que chegou no whatsapp'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app_filtro": {
                "type": "string",
                "enum": ["whatsapp", "discord", "instagram", "todos"],
            },
        },
    },
)
def _t_ler_notificacoes(app, app_filtro: str = "todos") -> str:
    try:
        from comandos.notif_history import ultimas, formatar_ultimas
        af = None if app_filtro == "todos" else app_filtro
        msgs = ultimas(app=af, limite=10)
        if not msgs:
            return "Nenhuma notificação pendente, Senhor."
        return "[LONGO]" + formatar_ultimas(msgs)
    except Exception as e:
        return f"ERRO: {e}"


# ── 13. comando_terminal (whitelist) ────────────────────────────────────

@register(
    name="comando_terminal",
    description=(
        "Executa um comando de terminal SEGURO (whitelist). Use para inspeção "
        "de repositório, status de testes, versões. Permitidos: git status/log/"
        "diff/branch/remote/show, dir, ls, pwd, where, which, echo, type, cat, "
        "pytest, python -m pytest, npm test, npm run test, node --version, "
        "python --version. Operadores de shell (&&, |, >, etc.) são bloqueados."
    ),
    parameters={
        "type": "object",
        "properties": {
            "comando": {
                "type": "string",
                "description": "Comando completo a executar (um único comando, sem operadores).",
            },
        },
        "required": ["comando"],
    },
)
def _t_comando_terminal(app, comando: str = "") -> str:
    from comandos import terminal_ctrl
    return "[LONGO]" + terminal_ctrl.executar(comando)


# ── 14. gerenciar_contatos ──────────────────────────────────────────────

@register(
    name="gerenciar_contatos",
    description=(
        "Gerencia a agenda de contatos (contatos.json). Ações: 'adicionar' "
        "(requer nome+telefone), 'remover' (requer nome), 'buscar' (requer "
        "query — nome ou número), 'listar' (mostra os primeiros), 'importar_vcf' "
        "(requer caminho do .vcf). Use quando o Senhor pedir para salvar/"
        "remover/procurar contato. Para ENVIAR mensagem use enviar_mensagem."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["adicionar", "remover", "buscar", "listar", "importar_vcf"],
            },
            "nome": {"type": "string"},
            "telefone": {"type": "string"},
            "query": {"type": "string"},
            "caminho": {"type": "string", "description": "Caminho do arquivo .vcf para importar_vcf."},
        },
        "required": ["acao"],
    },
)
def _t_gerenciar_contatos(
    app,
    acao: str = "",
    nome: str = "",
    telefone: str = "",
    query: str = "",
    caminho: str = "",
) -> str:
    from comandos import contato_ctrl as cc
    a = (acao or "").strip().lower()
    try:
        if a == "adicionar":   return cc.adicionar(nome, telefone)
        if a == "remover":     return cc.remover(nome)
        if a == "buscar":      return cc.buscar(query or nome)
        if a == "listar":      return cc.listar()
        if a == "importar_vcf":return cc.importar_vcf(caminho)
        return f"ERRO: ação '{acao}' desconhecida."
    except Exception as e:
        return f"ERRO gerenciar_contatos: {e}"


# ── 15. controle_ambiente (modo escuta passiva) ─────────────────────────

@register(
    name="controle_ambiente",
    description=(
        "Liga/desliga o MODO AMBIENTE — JARVIS escuta passivamente ao mic e "
        "acompanha o contexto. Use quando o Senhor pedir: "
        "'modo ambiente', 'fica escutando', 'presta atenção no que falo', "
        "'observa a conversa', 'ativa áudio ambiente', 'desativa áudio ambiente', "
        "'desliga o modo ambiente', 'para de escutar', 'para de me ouvir', "
        "'não preciso que me escute', 'silêncio modo ambiente'. "
        "NÃO confundir com modo proativo (controle_proativo). "
        "NÃO confundir com encerrar_jarvis (que fecha o programa)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["ativar", "desativar", "status", "limpar_buffer"],
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_ambiente(app, acao: str = "") -> str:
    from core import ambient_listener as al
    a = (acao or "").strip().lower()
    if a == "ativar":        return al.enable()
    if a == "desativar":     return al.disable()
    if a == "status":
        return ("Modo ambiente ATIVO." if al.is_enabled()
                else "Modo ambiente desligado, Senhor.")
    if a == "limpar_buffer":
        n = al.clear_buffer()
        return f"Buffer ambiente limpo, Senhor ({n} entradas removidas)."
    return f"ERRO: ação '{acao}' inválida."


# ── 16. controle_proativo ───────────────────────────────────────────────

@register(
    name="controle_proativo",
    description=(
        "Liga/desliga o MODO PROATIVO — JARVIS pode falar de vez em quando "
        "sem ser chamado (saudação ao voltar, oferecer ajuda quando detecta "
        "pergunta). Use 'silenciar' para calar por X minutos. Use 'fica quieto' "
        "ou 'modo silencioso' para silenciar por 30 min."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["ativar", "desativar", "silenciar", "status"],
            },
            "minutos": {
                "type": "number",
                "description": "Para 'silenciar': por quantos minutos ficar mudo (default 30).",
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_proativo(app, acao: str = "", minutos: float = 30) -> str:
    from core import proactive_engine as pe
    a = (acao or "").strip().lower()
    if a == "ativar":     return pe.enable()
    if a == "desativar":  return pe.disable()
    if a == "silenciar":  return pe.silence_for(float(minutos) * 60.0)
    if a == "status":
        return ("Modo proativo ATIVO." if pe._ENABLED
                else "Modo proativo desligado, Senhor.")
    return f"ERRO: ação '{acao}' inválida."


# ── 17. controle_presenca (camera) ──────────────────────────────────────

@register(
    name="controle_presenca",
    description=(
        "Liga/desliga o detector de PRESENÇA via webcam (sabe se o Senhor está "
        "no PC ou ausente). Coexiste com a interface gestual sem competir pela "
        "câmera. Use 'status' para saber estado atual: present/away/looking_away."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["ativar", "desativar", "status"],
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_presenca(app, acao: str = "") -> str:
    from core import presence_detector as pd
    a = (acao or "").strip().lower()
    if a == "ativar":    return pd.start()
    if a == "desativar": return pd.stop()
    if a == "status":
        if not pd.is_running():
            return "Detector de presença desligado, Senhor."
        return f"Estado de presença: {pd.get_state()}, Senhor."
    return f"ERRO: ação '{acao}' inválida."


# ── 19. controle_audio_sistema ──────────────────────────────────────────

@register(
    name="controle_audio_sistema",
    description=(
        "Controla a escuta do áudio do sistema (loopback) — tudo que toca no PC: "
        "vídeos, músicas, chamadas. Quando ligado, o JARVIS entende o que está sendo "
        "assistido e pode reagir ou dar contexto quando chamado. "
        "Use quando o Senhor pedir 'ouve o que tá tocando', 'para de ouvir o pc', "
        "'escuta o vídeo que estou vendo', 'status do áudio'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["ativar", "desativar", "status"],
            },
        },
        "required": ["acao"],
    },
)
def _t_controle_audio_sistema(app, acao: str = "") -> str:
    from core import system_audio_listener as _sal
    import config as _cfg
    a = (acao or "").strip().lower()
    if a == "ativar":
        if not _sal.DEPS_OK:
            return "pyaudiowpatch não instalado — impossível capturar loopback."
        result = _sal.start(transcribe_cb=app._quick_transcribe)
        _cfg.SYSTEM_AUDIO_ENABLED = True
        return result
    if a == "desativar":
        _cfg.SYSTEM_AUDIO_ENABLED = False
        return _sal.stop()
    if a == "status":
        if _sal.is_running():
            return "Estou ouvindo o áudio do sistema, Senhor."
        return "Áudio do sistema desligado, Senhor."
    return f"ERRO: ação '{acao}' inválida."


# ── 18. controle_voz_tts ────────────────────────────────────────────────

@register(
    name="controle_voz_tts",
    description=(
        "Troca o motor de TTS (Text-to-Speech) usado pela voz do JARVIS. "
        "Use quando o Senhor pedir 'usa a voz do edge', 'usa a voz do gemini', "
        "'troca a voz', 'qual voz tá usando'. "
        "edge = Edge TTS (Microsoft, gratuito, rápido). "
        "gemini = Gemini TTS (Google, premium, requer API key)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "provedor": {
                "type": "string",
                "enum": ["edge", "gemini", "status"],
            },
        },
        "required": ["provedor"],
    },
)
def _t_controle_voz_tts(app, provedor: str = "") -> str:
    import config as _cfg
    p = (provedor or "").strip().lower()
    if p == "status":
        return f"Voz atual: {_cfg.TTS_PROVIDER}, Senhor."
    if p == "edge":
        _cfg.TTS_PROVIDER = "edge"
        return "Voz trocada para Edge TTS, Senhor."
    if p == "gemini":
        try:
            from VozIa import gemini_tts as _g
            if not _g.disponivel():
                return ("Gemini TTS indisponível, Senhor — verifique "
                        "GEMINI_TTS_API_KEY e a biblioteca google-genai.")
        except Exception as e:
            return f"Gemini TTS indisponível: {e}"
        _cfg.TTS_PROVIDER = "gemini"
        return "Voz trocada para Gemini TTS, Senhor."
    return f"ERRO: provedor '{provedor}' inválido."


# ── 20. pesquisa_rapida ─────────────────────────────────────────────────

@register(
    name="pesquisa_rapida",
    description=(
        "Pesquisa na internet (DuckDuckGo) e resume a resposta com IA. "
        "Use para perguntas sobre fatos atuais, cotações, notícias, eventos recentes, "
        "curiosidades, análises, previsões, ou qualquer pergunta que exija "
        "informação externa ou atualizada. "
        "Use SEMPRE que o Senhor fizer uma pergunta sobre um tema externo, "
        "evento, lugar, pessoa, esporte, política, ciência, cultura, tecnologia. "
        "NÃO use para comandos de controle do PC (abrir apps, Spotify, alarmes etc)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pergunta": {
                "type": "string",
                "description": "A pergunta completa a ser pesquisada, com contexto se necessário.",
            },
        },
        "required": ["pergunta"],
    },
)
def _t_pesquisa_rapida(app, pergunta: str = "") -> str:
    """Pesquisa na web via DuckDuckGo e resume com Groq 70B."""
    if not pergunta.strip():
        return "ERRO: pergunta vazia."
    groq = getattr(app, "_groq", None)
    if not groq:
        return "ERRO: Groq indisponível."

    # ── 1. Busca real na web via DuckDuckGo ─────────────────────────────
    web_context = ""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(pergunta, region="br-pt", max_results=4))
        if results:
            linhas = []
            for i, r in enumerate(results, 1):
                titulo = r.get("title", "")
                corpo  = r.get("body", "")
                url    = r.get("href", "")
                linhas.append(f"{i}. {titulo}: {corpo} (Fonte: {url})")
            web_context = (
                "\n══ RESULTADOS DA WEB ══\n"
                + "\n".join(linhas)
                + "\n═══════════════════════\n"
            )
            print(f"[pesquisa_rapida] {len(results)} resultados DuckDuckGo para '{pergunta[:50]}'")
    except Exception as e_ddg:
        print(f"[pesquisa_rapida] DuckDuckGo falhou: {e_ddg}")

    # ── 2. Injeta contexto ambiente ──────────────────────────────────────
    ctx = ""
    try:
        from core import ambient_listener as _al
        if _al.is_enabled():
            ctx = _al.context_text(n=8, max_chars=600)
    except Exception:
        pass

    system = (
        "Você é JARVIS, mordomo digital britânico do Senhor, com PERSONA e "
        "OPINIÃO próprias. Responda a pergunta de forma direta, com posição. "
        "Quando houver dados da web, USE-OS como fonte principal e cite as fontes. "
        "Para fatos (datas, cotações, eventos): seja preciso ou diga que não "
        "tem o dado. Para opiniões, palpites, análises, previsões: ARRISQUE "
        "uma posição fundamentada ('acho que', 'minha leitura é', 'aposto em'). "
        "PROIBIDO começar com disclaimers. "
        "Formato: 2-4 frases. Português brasileiro. Sem markdown, sem listas, "
        "sem emojis, sem saudação. Trate como 'Senhor'. Tom britânico seco."
    )
    user_msg = pergunta
    if ctx:
        user_msg = f"Contexto recente:\n{ctx}\n\nPergunta: {pergunta}"
    if web_context:
        user_msg += f"\n\nDados atualizados da internet:{web_context}"

    try:
        # Usa o Groq REAL (grátis, modelo válido) p/ o resumo — evita mandar um
        # id Groq cru ao cliente OpenRouter (erro 400) e poupa créditos.
        _cli = getattr(app, "_groq_real", None) or groq
        _mdl = getattr(app, "_groq_real_model", None)
        if not _mdl:
            from config import GROQ_MODELO_CHAT as _mdl
        resp = _cli.chat.completions.create(
            model=_mdl,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        answer = (resp.choices[0].message.content or "").strip()
        answer = answer.replace("**", "").replace("*", "").replace("`", "")
        import re as _re_d
        _DISCLAIMER_PATS = [
            r"^pe[çc]o\s+desculpas?,?\s+(mas\s+)?n[ãa]o\s+posso\s+(fornecer|dar|opinar|emitir|expressar)[^.]*\.\s*",
            r"^desculpe,?\s+(mas\s+)?n[ãa]o\s+posso\s+(fornecer|dar|opinar|emitir|expressar)[^.]*\.\s*",
            r"^como\s+(uma?\s+)?(ia|intelig[êe]ncia\s+artificial|assistente)[^.]*\bn[ãa]o\s+(tenho|posso)[^.]*\.\s*",
            r"^n[ãa]o\s+posso\s+(fornecer|dar|opinar|emitir|expressar)\s+(uma?\s+)?(opini[ãa]o|resposta)[^.]*\.\s*",
            r"^infelizmente,?\s+(eu\s+)?n[ãa]o\s+posso\s+opinar[^.]*\.\s*",
            r"^essa?\s+[ée]\s+uma?\s+(quest[ãa]o|pergunta)\s+(muito\s+)?subjetiva[^.]*\.\s*",
        ]
        for _pat in _DISCLAIMER_PATS:
            answer = _re_d.sub(_pat, "", answer, count=1, flags=_re_d.I | _re_d.S).lstrip()
        if not answer or len(answer) < 20:
            answer = ("Sem dado conclusivo, Senhor — mas se for pra arriscar, "
                      "minha leitura é que depende de fatores que ainda não temos.")
        print(f"[pesquisa_rapida] '{pergunta[:60]}' → '{answer[:80]}'")
        return answer or "ERRO: resposta vazia."
    except Exception as e:
        print(f"[pesquisa_rapida] Groq falhou: {e}")
        return f"ERRO: {e}"


# ── 21. enviar_mensagem ─────────────────────────────────────────────────

@register(
    name="enviar_mensagem",
    description=(
        "Envia uma mensagem para um contato via WhatsApp ou Discord. "
        "Use quando o Senhor pedir: 'manda uma mensagem pra X', 'envia pro X', "
        "'fala pro X que...', 'diga pro X que...', 'avisa o X', 'manda oi pra mãe', "
        "'envia um WhatsApp para X dizendo Y'. "
        "O app padrão é WhatsApp. Use Discord apenas quando o Senhor especificar. "
        "Parâmetros: destinatario = nome ou número; mensagem = texto a enviar."
    ),
    parameters={
        "type": "object",
        "properties": {
            "destinatario": {
                "type": "string",
                "description": "Nome do contato ou número de telefone (ex: 'mãe', 'João', '11999999999').",
            },
            "mensagem": {
                "type": "string",
                "description": "Texto completo da mensagem a enviar.",
            },
            "app": {
                "type": "string",
                "enum": ["whatsapp", "discord"],
                "description": "App de envio. Default: whatsapp.",
            },
        },
        "required": ["destinatario", "mensagem"],
    },
)
def _t_enviar_mensagem(app, destinatario: str = "", mensagem: str = "",
                       app_envio: str = "whatsapp", **_kw) -> str:
    # Aceita `app` vindo do LLM e `app_envio` por compatibilidade
    _app_choice = (_kw.get("app") or app_envio or "whatsapp").lower()
    if not destinatario or not mensagem:
        return "ERRO: preciso do destinatario e da mensagem."
    if _app_choice == "discord":
        from comandos.msg_sender import enviar_discord_por_nome
        return enviar_discord_por_nome(destinatario, mensagem)
    # WhatsApp (default)
    from comandos.msg_sender import enviar_whatsapp_por_nome
    return enviar_whatsapp_por_nome(destinatario, mensagem)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def parse_tool_call(tc) -> tuple[str, dict]:
    """Extrai (name, args) de um ToolCall do OpenAI SDK."""
    name = tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name", "")
    raw  = tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", "{}")
    try:
        args = _json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        args = {}
    return name, args


# ── 22. gerar_imagem ─────────────────────────────────────────────────────
@register(
    name="gerar_imagem",
    description=(
        "Gera uma imagem usando Pollinations.ai (IA generativa, gratuito). "
        "Use quando o Senhor pedir: 'gere uma imagem de X', 'crie uma ilustração de X', "
        "'desenhe X', 'gera uma foto de X', 'crie uma arte de X', 'ilustra X', "
        "'gera uma imagem de X estilo Y'. "
        "Salva a imagem localmente e abre automaticamente no visualizador do sistema. "
        "NÃO use para pesquisas ou comandos de controle do PC."
    ),
    parameters={
        "type": "object",
        "properties": {
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição detalhada do que gerar. "
                    "Pode incluir estilo: 'realista', 'anime', '3d', 'rápido'. "
                    "Exemplos: 'um castelo medieval à noite com lua cheia', "
                    "'retrato realista de um cientista futurista', 'logo cyberpunk'."
                ),
            },
        },
        "required": ["descricao"],
    },
)
def _t_gerar_imagem(app, descricao: str = "") -> str:
    """Gera imagem via Pollinations.ai, salva e abre automaticamente."""
    if not descricao.strip():
        return "ERRO: descrição da imagem não pode ser vazia."
    try:
        import os
        import threading
        from comandos.image_gen_ctrl import gerar_imagem

        groq = getattr(app, "_groq", None)

        def _gen():
            try:
                caminho = gerar_imagem(descricao, groq_client=groq)
                # Abre no visualizador padrão do SO
                _open_path(caminho)
                # Notifica via JARVIS UI se disponível
                _exibir = getattr(app, "_exibir_resposta", None)
                root    = getattr(app, "root", None)
                if _exibir and root:
                    nome = os.path.basename(caminho)
                    root.after(0, _exibir,
                        f"Imagem gerada com sucesso, Senhor — '{nome}' aberta no visualizador.")
            except Exception as e:
                print(f"[gerar_imagem] Erro: {e}")
                _exibir = getattr(app, "_exibir_resposta", None)
                root    = getattr(app, "root", None)
                if _exibir and root:
                    root.after(0, _exibir, f"Não consegui gerar a imagem, Senhor: {e}")

        threading.Thread(target=_gen, daemon=True).start()
        return "Gerando imagem, Senhor. Aguarde alguns instantes enquanto processo via Pollinations.ai…"
    except Exception as e:
        return f"ERRO: {e}"

# ─────────────────────────────────────────────────────────────────────────
# display_text — viewer HTML para textos longos (substitui Notepad)
# ─────────────────────────────────────────────────────────────────────────

@register(
    name="display_text",
    description=(
        "Exibe um texto longo no viewer interno do JARVIS (substitui Notepad). "
        "Use para mostrar listas grandes, código, conteúdo de arquivo, sumários "
        "extensos — qualquer texto com mais de ~15 linhas que o usuário precise "
        "VER em vez de ouvir. NÃO use para respostas curtas conversacionais."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Título curto (ex: 'main.py')."},
            "content": {"type": "string", "description": "Texto completo a exibir."},
            "language": {"type": "string", "description": "Linguagem opcional (python, json, text...)."},
        },
        "required": ["title", "content"],
    },
)
def _t_display_text(app, title: str = "Texto", content: str = "", language: str = "") -> str:
    try:
        ok = app._mostrar_texto_longo(str(title or "Texto"),
                                       str(content or ""),
                                       str(language or ""))
        if ok:
            return f"Texto exibido no viewer: '{title}'."
        return "Viewer indisponível; abri no Notepad como fallback."
    except Exception as e:
        return f"ERRO: {e}"

# ─────────────────────────────────────────────────────────────────────────
# Filesystem awareness — drives, locations aprendidos, busca de pastas
# ─────────────────────────────────────────────────────────────────────────

@register(
    name="listar_drives",
    description=(
        "Lista todas as letras de drive (SSDs/HDs) do computador com espaço "
        "total e livre. Use quando o Senhor pedir 'quais discos eu tenho', "
        "'lista os SSDs', 'mostra os drives', 'quanto espaço sobra no D:', etc."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)
def _t_listar_drives(app) -> str:
    try:
        from core import filesystem_indexer as _fsi
        drives = _fsi.list_drives()
        if not drives:
            return "Não consegui detectar nenhum drive."
        linhas = []
        for d in drives:
            tot = d.get("total_gb") or 0.0
            fre = d.get("free_gb") or 0.0
            fs  = d.get("fstype") or "?"
            mp  = d.get("mountpoint") or d.get("letter") or "?"
            tag = " (removível)" if d.get("removable") else ""
            linhas.append(f"{mp}  [{fs}]  livre {fre:.1f} GB / total {tot:.1f} GB{tag}")
        return "Drives detectados:\n" + "\n".join(linhas)
    except Exception as e:
        return f"ERRO: {e}"


@register(
    name="procurar_pasta",
    description=(
        "Localiza uma pasta ou diretório no PC pelo nome, usando primeiro o "
        "cache de locais aprendidos e depois um quick-scan dos drives. "
        "Use quando o Senhor disser 'onde está a pasta X', 'acha o diretório Y', "
        "'cadê o projeto Z'. Retorna o caminho completo se encontrado. "
        "Resultados positivos são gravados automaticamente para uso futuro."
    ),
    parameters={
        "type": "object",
        "properties": {
            "nome": {"type": "string", "description": "Nome ou parte do nome da pasta."},
        },
        "required": ["nome"],
    },
)
def _t_procurar_pasta(app, nome: str = "") -> str:
    try:
        from core import filesystem_indexer as _fsi
        if not nome:
            return "ERRO: preciso do nome da pasta."
        hit = _fsi.find_path(nome)
        if not hit:
            return f"Não encontrei pasta com '{nome}', Senhor."
        origem = "cache aprendido" if hit["source"] == "learned" else "scan dos drives"
        return f"Encontrei em {hit['path']} (via {origem})."
    except Exception as e:
        return f"ERRO: {e}"

# ─────────────────────────────────────────────────────────────────────────
# Games — descobrir/listar/abrir/instalar via launcher
# ─────────────────────────────────────────────────────────────────────────

@register(
    name="listar_jogos",
    description=(
        "Lista todos os jogos instalados no PC, agrupados por launcher (Steam, "
        "Epic, EA, Battle.net, Ubisoft, Xbox). Use quando o Senhor disser "
        "'quais jogos eu tenho', 'lista meus jogos', 'mostra a biblioteca'. "
        "Opcionalmente filtra por plataforma."
    ),
    parameters={
        "type": "object",
        "properties": {
            "plataforma": {
                "type": "string",
                "description": "Filtrar por: steam, epic, ea, battlenet, ubisoft, xbox.",
            },
            "atualizar": {
                "type": "boolean",
                "description": "Força re-scan ignorando cache (24h).",
            },
        },
        "required": [],
    },
)
def _t_listar_jogos(app, plataforma: str = "", atualizar: bool = False) -> str:
    try:
        from comandos import games_ctrl as _gc
        return _gc.listar_jogos(plataforma or None, force_refresh=bool(atualizar))
    except Exception as e:
        return f"ERRO: {e}"


@register(
    name="abrir_jogo",
    description=(
        "Abre/lança um jogo instalado, escolhendo o launcher correto "
        "automaticamente. Use para 'joga X', 'abre o jogo X', 'inicia X'. "
        "Aceita plataforma opcional para desempate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "nome": {"type": "string", "description": "Nome do jogo."},
            "plataforma": {
                "type": "string",
                "description": "Plataforma opcional: steam, epic, ea, battlenet, ubisoft, xbox.",
            },
        },
        "required": ["nome"],
    },
)
def _t_abrir_jogo(app, nome: str = "", plataforma: str = "") -> str:
    try:
        from comandos import games_ctrl as _gc
        return _gc.abrir_jogo(nome, plataforma or None)
    except Exception as e:
        return f"ERRO: {e}"


@register(
    name="instalar_jogo",
    description=(
        "Abre a tela de instalação de um jogo no launcher informado. Use para "
        "'instala X no steam', 'baixa Y no epic'. Se já estiver instalado, "
        "avisa. Se não souber o jogo, abre a loja do launcher."
    ),
    parameters={
        "type": "object",
        "properties": {
            "nome": {"type": "string", "description": "Nome do jogo."},
            "plataforma": {
                "type": "string",
                "description": "Plataforma: steam, epic, ea, battlenet, ubisoft, xbox.",
            },
        },
        "required": ["nome"],
    },
)
def _t_instalar_jogo(app, nome: str = "", plataforma: str = "") -> str:
    try:
        from comandos import games_ctrl as _gc
        return _gc.instalar_jogo(nome, plataforma or None)
    except Exception as e:
        return f"ERRO: {e}"


# ─────────────────────────────────────────────────────────────────────────
# Documentos — apresentação spec→render (roadmap/13, Fase 2)
# ─────────────────────────────────────────────────────────────────────────

@register(
    name="criar_apresentacao",
    description=(
        "Cria uma APRESENTAÇÃO (.pptx) BONITA e VARIADA a partir de uma spec que "
        "VOCÊ compõe (padrão spec→render). NÃO use um formato único — VARIE o layout "
        "de cada slide; layouts adjacentes devem diferir; misture densos e visuais.\n"
        "Layouts (campo 'layout'):\n"
        "  • capa — abertura (titulo, subtitulo?, eyebrow?, image_prompt?)\n"
        "  • hero — imagem cheia + título sobreposto (titulo, legenda?, image_prompt)\n"
        "  • secao — divisória de seção (titulo, numero?, eyebrow?)\n"
        "  • agenda — índice (titulo, bullets[])\n"
        "  • topicos — título + bullets (titulo, bullets[], image_prompt?)\n"
        "  • texto — corpo de texto médio/grande, explicativo (titulo, corpo)\n"
        "  • duas_colunas / comparativo — duas listas (titulo, esq_titulo, esquerda[], dir_titulo, direita[])\n"
        "  • kpi — 1-4 números grandes (titulo?, items[]={valor,titulo?,legenda?})\n"
        "  • bento — grade de 3-6 cards (titulo, items[]={titulo,legenda?})\n"
        "  • timeline — linha do tempo (titulo, items[]={quando,titulo})\n"
        "  • citacao — citação grande (valor=frase, legenda=autor)\n"
        "  • destaque — 1 número/frase de impacto (valor, legenda?, titulo?)\n"
        "  • imagem — imagem cheia c/ legenda (image_prompt, titulo?, legenda?)\n"
        "  • imagem_lateral — imagem à direita + texto (titulo, bullets[]|legenda, image_prompt)\n"
        "  • fechamento — encerramento (titulo, subtitulo?)\n"
        "  • declaracao — 1 frase de impacto · processo — passos+setas (items{titulo,desc}) · "
        "matriz — 2x2 (items[4]) · tabela — (headers[],rows[[]]) · equipe — pessoas "
        "(items{titulo=nome,legenda=cargo}) · numerado — passos numerados · executivo — "
        "3 colunas (items[3]{titulo,bullets[]}) · galeria — imagens · livre — COMPOSE "
        "(blocks[] no grid 12col: {type,col,span,row,rspan,...})\n"
        "ESCOLHA o layout pelo TIPO de conteúdo: número→destaque/kpi, sequência→processo/"
        "numerado, tabela→tabela, comparação→comparativo, 2 eixos→matriz, criativo→livre.\n"
        "Use a QUANTIDADE de texto que o conteúdo pedir: slides explicativos podem "
        "ter parágrafos (layout 'texto'); slides de visão geral usam bullets. NÃO "
        "resuma a 3 itens se o tema exige mais — prefira 'texto' ou mais bullets. "
        "Só títulos/valores são curtos (título <=72, kpi.valor <=16 como '74%'). "
        "'image_prompt' em INGLÊS, visual SEM texto. Se precisar de dados atuais, "
        "chame 'pesquisa_web' ANTES. Comece com 'capa', use 'secao' p/ dividir, "
        "termine com 'fechamento'; 6-12 slides é ideal."
    ),
    parameters={
        "type": "object",
        "properties": {
            "titulo": {"type": "string", "description": "Título da apresentação."},
            "subtitulo": {"type": "string", "description": "Subtítulo/contexto (opcional)."},
            "tema": {"type": "string", "description": "'stark_dark', 'stark_light', nome de cor (azul, verde…) ou hex #rrggbb."},
            "gerar_imagens": {"type": "boolean", "description": "Gera ilustrações IA p/ slides com image_prompt (default true)."},
            "slides": {
                "type": "array",
                "description": "Lista ordenada de slides; cada um escolhe um 'layout' e preenche os campos dele.",
                "items": {
                    "type": "object",
                    "properties": {
                        "layout": {"type": "string", "description": "capa|hero|secao|agenda|topicos|texto|duas_colunas|comparativo|kpi|bento|timeline|citacao|destaque|imagem|imagem_lateral|fechamento|declaracao|processo|matriz|tabela|equipe|numerado|executivo|galeria|livre"},
                        "titulo": {"type": "string"},
                        "subtitulo": {"type": "string"},
                        "eyebrow": {"type": "string", "description": "rótulo curto acima do título (kicker)"},
                        "numero": {"type": "string"},
                        "corpo": {"type": "string", "description": "parágrafo(s) de texto p/ layout 'texto' (use \\n entre parágrafos)"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "esq_titulo": {"type": "string"},
                        "esquerda": {"type": "array", "items": {"type": "string"}},
                        "dir_titulo": {"type": "string"},
                        "direita": {"type": "array", "items": {"type": "string"}},
                        "valor": {"type": "string"},
                        "legenda": {"type": "string"},
                        "items": {
                            "type": "array",
                            "description": "p/ kpi/bento/timeline/processo/matriz/equipe/executivo: {valor?,titulo?,legenda?,quando?,desc?,bullets?}",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "valor": {"type": "string"},
                                    "titulo": {"type": "string"},
                                    "legenda": {"type": "string"},
                                    "quando": {"type": "string"},
                                    "desc": {"type": "string"},
                                    "bullets": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": [],
                            },
                        },
                        "headers": {"type": "array", "items": {"type": "string"}, "description": "p/ layout 'tabela': cabeçalhos das colunas"},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "p/ layout 'tabela': linhas (cada uma é lista de células)"},
                        "blocks": {
                            "type": "array",
                            "description": "p/ layout 'livre': blocos no grid 12col×6lin. type: titulo|texto|bullets|stat|card|imagem|citacao|divisor",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "col": {"type": "integer"}, "span": {"type": "integer"},
                                    "row": {"type": "integer"}, "rspan": {"type": "integer"},
                                    "texto": {"type": "string"}, "titulo": {"type": "string"},
                                    "valor": {"type": "string"}, "legenda": {"type": "string"},
                                    "autor": {"type": "string"},
                                    "itens": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["type"],
                            },
                        },
                        "image_prompt": {"type": "string"},
                        "icon": {"type": "string"},
                    },
                    "required": ["layout"],
                },
            },
        },
        "required": ["titulo", "slides"],
    },
)
def _t_criar_apresentacao(app, titulo="", subtitulo="", tema="", gerar_imagens=True, slides=None):
    try:
        from documents import deck_builder as _db
    except Exception as e:
        return f"ERRO: módulo de apresentação indisponível: {e}"
    spec = {"titulo": titulo, "subtitulo": subtitulo, "tema": tema, "slides": slides or []}
    try:
        path = _db.gerar_deck(spec, gen_visuals=bool(gerar_imagens))
    except Exception as e:
        return f"ERRO: falha ao gerar apresentação: {e}"
    try:
        _open_path(path)  # abre no app padrão (PowerPoint no Windows)
    except Exception:
        pass
    return f"Apresentação criada com {len(slides or [])} slides e aberta: {path}"


@register(
    name="criar_relatorio",
    description=(
        "Cria um RELATÓRIO em PDF bonito (HTML/CSS→PDF) a partir de uma spec que VOCÊ "
        "compõe — capa, seções, gráficos, tabelas, KPIs. Ideal p/ relatórios de pesquisa, "
        "documentos formais, dossiês.\n"
        "Blocos (campo 'block' de cada seção):\n"
        "  • capa (titulo, subtitulo?, image_prompt?) · secao (titulo, numero?) — nova página\n"
        "  • texto (titulo?, corpo) · bullets (titulo?, bullets[]) · kpi (items[]={valor,titulo,legenda?})\n"
        "  • grafico (titulo?, grafico={tipo:bar|line|pie, labels[], valores[]}) · tabela (headers[], rows[[]])\n"
        "  • callout (tipo:info|warn|ok|crit, titulo, texto) · citacao (valor, legenda=autor) · imagem (image_prompt, legenda?)\n"
        "  • campos (campos[]={label}) p/ PREENCHIMENTO · questao (enunciado, alternativas[], resposta?) p/ prova/simulado · gabarito (respostas[]) · equacao (latex) p/ MATEMÁTICA (KaTeX, selecionável)\n"
        "formato='prova|simulado|artigo|resumo|redacao|relatorio|argumentacao|contrato' ajusta a "
        "estrutura (blocos/sequência) e o estilo automaticamente.\n"
        "tipo_fonte ('executivo'|'financeiro'|'tecnico'|'generico') ajusta o estilo. "
        "Comece com 'capa'; use 'secao' p/ capítulos; 'grafico' p/ dados, 'kpi' p/ métricas. "
        "Se precisar de dados atuais, chame 'pesquisa_web' ANTES. image_prompt em INGLÊS.\n"
        "fonte_dossie='<tema>': usa TODO o conteúdo acumulado no dossiê (via dossie + "
        "pesquisa_web) p/ compor um relatório RICO automaticamente — nesse caso NÃO "
        "precisa passar 'secoes'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "titulo": {"type": "string"},
            "subtitulo": {"type": "string"},
            "tema": {"type": "string", "description": "tema, nome de cor ou hex"},
            "tipo_fonte": {"type": "string", "description": "executivo|financeiro|tecnico|generico"},
            "page": {"type": "string", "description": "A4|Letter|Legal"},
            "toc": {"type": "boolean", "description": "incluir sumário"},
            "gerar_imagens": {"type": "boolean"},
            "fonte_dossie": {"type": "string", "description": "tema do dossiê a usar como fonte (conteúdo acumulado via pesquisa). Se setado, compõe um relatório rico do material — pode deixar 'secoes' vazio."},
            "formato": {"type": "string", "description": "ajusta a ESTRUTURA e o estilo: simulado|prova|artigo|resumo|redacao|relatorio|argumentacao|contrato. Combina com fonte_dossie."},
            "secoes": {
                "type": "array",
                "description": "Lista ordenada de seções; cada uma escolhe um 'block'.",
                "items": {
                    "type": "object",
                    "properties": {
                        "block": {"type": "string", "description": "capa|secao|texto|bullets|kpi|grafico|tabela|callout|citacao|duas_colunas|imagem|divisor|campos|questao|gabarito|equacao"},
                        "titulo": {"type": "string"}, "subtitulo": {"type": "string"},
                        "eyebrow": {"type": "string"}, "numero": {"type": "string"},
                        "corpo": {"type": "string"}, "tipo": {"type": "string"},
                        "valor": {"type": "string"}, "legenda": {"type": "string"},
                        "esq_titulo": {"type": "string"}, "dir_titulo": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "esquerda": {"type": "array", "items": {"type": "string"}},
                        "direita": {"type": "array", "items": {"type": "string"}},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                        "items": {"type": "array", "items": {"type": "object", "properties": {"valor": {"type": "string"}, "titulo": {"type": "string"}, "legenda": {"type": "string"}}, "required": []}},
                        "grafico": {"type": "object", "properties": {"tipo": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}}, "valores": {"type": "array", "items": {"type": "string"}}}, "required": []},
                        "image_prompt": {"type": "string"},
                        "campos": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "largura": {"type": "string"}}, "required": []}, "description": "campos de preenchimento (block=campos)"},
                        "enunciado": {"type": "string", "description": "enunciado (block=questao)"},
                        "alternativas": {"type": "array", "items": {"type": "string"}, "description": "alternativas a-e (block=questao)"},
                        "resposta": {"type": "string"},
                        "respostas": {"type": "array", "items": {"type": "string"}, "description": "chave do gabarito (block=gabarito)"},
                        "latex": {"type": "string", "description": "expressão LaTeX (block=equacao), ex: x = \\frac{-b}{2a}"},
                    },
                    "required": ["block"],
                },
            },
        },
        "required": ["titulo"],
    },
)
def _t_criar_relatorio(app, titulo="", subtitulo="", tema="", tipo_fonte="generico",
                       page="A4", toc=False, gerar_imagens=True, secoes=None,
                       fonte_dossie="", formato=""):
    try:
        from documents import report_builder as _rb
    except Exception as e:
        return f"ERRO: módulo de relatório indisponível: {e}"
    secoes = secoes or []
    formato = (formato or "").strip().lower()
    _guia = _FORMATO_GUIA.get(formato, "")
    # formato escolhe um SKIN (só se o cérebro não pediu um tipo_fonte específico)
    if formato in _FORMATO_SKIN and (not tipo_fonte or tipo_fonte == "generico"):
        tipo_fonte = _FORMATO_SKIN[formato]
    # Fonte = DOSSIÊ: compõe as seções a partir de TODO o material acumulado (que
    # excede o contexto do orquestrador) via um LLM barato (8b). Só se o material
    # for substancial; senão usa as 'secoes' que o cérebro já passou.
    if fonte_dossie:
        try:
            from jarvis.memory import dossie as _dos
            _k = None if str(fonte_dossie).strip().lower() in ("1", "true", "sim", "ativo") else str(fonte_dossie)
            material = _dos.ler(_k)
            if material and len(material.strip()) > 200:
                geradas = _compose_secoes_from_material(app, titulo or str(fonte_dossie), tema, tipo_fonte, material, guia=_guia)
                if geradas:
                    secoes = geradas
                    toc = True  # doc rico ganha sumário
        except Exception as _ed:
            print(f"[DOSSIE] composição falhou: {_ed}")
    spec = {"titulo": titulo, "subtitulo": subtitulo, "tema": tema,
            "tipo_fonte": tipo_fonte, "page": page, "toc": bool(toc),
            "secoes": secoes}
    try:
        path = _rb.gerar_relatorio(spec, gen_visuals=bool(gerar_imagens))
    except Exception as e:
        return f"ERRO: falha ao gerar relatório: {e}"
    try:
        _open_path(path)
    except Exception:
        pass
    return f"Relatório PDF criado com {len(secoes or [])} seções e aberto: {path}"


# Guias de FORMATO (P1): cada formato injeta uma estrutura-alvo na composição da
# spec + escolhe um skin. É PROMPT-DRIVEN — não há template Python por formato.
_FORMATO_GUIA = {
    "prova": "PROVA: capa, um 'texto' com instruções, vários blocos 'questao' (enunciado + alternativas a-e), e um 'gabarito' no fim. Sóbrio.",
    "simulado": "SIMULADO: como prova — capa, instruções, muitos blocos 'questao' (alternativas a-e) cobrindo o tema, e 'gabarito' no fim.",
    "artigo": "ARTIGO acadêmico: capa, um 'texto' de RESUMO/abstract, seções ('secao'+'texto') de desenvolvimento, e 'citacao' p/ referências. Tom impessoal.",
    "resumo": "RESUMO objetivo: capa enxuta e, por tópico, 'texto' curto + 'bullets' com os pontos-chave. Direto ao ponto.",
    "redacao": "REDAÇÃO dissertativa: um 'texto' com introdução (tese), desenvolvimento e conclusão. Texto CORRIDO, sem bullets/tabelas.",
    "relatorio": "RELATÓRIO: capa, seções com 'texto', e 'kpi'/'tabela'/'grafico' p/ dados quando houver. Formal.",
    "argumentacao": "ARGUMENTAÇÃO: 'callout' com a TESE, seções com argumentos, uma seção de contra-argumentos rebatidos, e conclusão.",
    "contrato": "CONTRATO: título, 'campos' p/ as partes, cláusulas NUMERADAS ('secao' por cláusula + 'texto'), e 'campos' finais p/ data/local/assinaturas. Formal/jurídico.",
}
_FORMATO_SKIN = {
    "prova": "generico", "simulado": "generico", "artigo": "tecnico", "resumo": "generico",
    "redacao": "generico", "relatorio": "executivo", "argumentacao": "tecnico", "contrato": "tecnico",
}


def _compose_secoes_from_material(app, titulo, tema, tipo_fonte, material, guia=""):
    """Compõe a SPEC de seções de um relatório a partir do MATERIAL bruto (dossiê)
    via um LLM BARATO (8b). `guia` injeta a estrutura-alvo do formato. → lista|None."""
    cli = getattr(app, "_groq_real", None) or getattr(app, "_groq", None)
    if cli is None or not (material or "").strip():
        return None
    import json as _json, re as _re
    try:
        import config as _c
        mdl = getattr(_c, "GROQ_MODELO_TOOLS", None) or getattr(_c, "GROQ_MODELO_CHAT", "")
    except Exception:
        mdl = ""
    sysm = (
        "Você compõe a SPEC de um relatório PDF a partir de MATERIAL bruto de pesquisa. "
        "Devolva SÓ um array JSON de seções — NADA fora do JSON. Cada seção tem 'block'. "
        "Blocos válidos: capa{titulo,subtitulo}; secao{titulo,numero}; texto{titulo,corpo}; "
        "bullets{titulo,bullets:[]}; kpi{items:[{valor,titulo,legenda}]}; "
        "tabela{headers:[],rows:[[]]}; callout{tipo:info|warn|ok|crit,titulo,texto}; "
        "citacao{valor,legenda}; campos{campos:[{label}]}; questao{enunciado,alternativas:[],resposta}; "
        "gabarito{respostas:[]}; equacao{latex}. Comece SEMPRE com uma 'capa'. Cubra TODO o "
        "material em 6 a 12 seções bem estruturadas e RICAS (parágrafos densos, bullets, "
        "tabelas quando os dados permitirem). Em português, FIEL ao material (não invente fatos)."
    )
    if guia:
        sysm += "\nFORMATO ALVO — siga ESTA estrutura: " + guia
    usr = (f"Título: {titulo}\nEstilo: {tema or tipo_fonte}\n\nMATERIAL:\n"
           f"{material[:12000]}\n\nSpec (array JSON de seções):")
    try:
        r = cli.chat.completions.create(
            model=mdl, messages=[{"role": "system", "content": sysm},
                                 {"role": "user", "content": usr}],
            max_tokens=3500, temperature=0.3)
        raw = (r.choices[0].message.content or "").strip()
        m = _re.search(r"\[.*\]", raw, _re.S)
        arr = _json.loads(m.group(0) if m else raw)
        if isinstance(arr, list) and arr:
            return arr
    except Exception as e:
        print(f"[DOSSIE] spec-LLM falhou: {e}")
    return None


def _compose_word_secoes_from_material(app, titulo, material, guia=""):
    """Compõe seções de um DOC WORD (heading + paragraphs) do material bruto via 8b."""
    cli = getattr(app, "_groq_real", None) or getattr(app, "_groq", None)
    if cli is None or not (material or "").strip():
        return None
    import json as _json, re as _re
    try:
        import config as _c
        mdl = getattr(_c, "GROQ_MODELO_TOOLS", None) or getattr(_c, "GROQ_MODELO_CHAT", "")
    except Exception:
        mdl = ""
    sysm = ("Você compõe as SEÇÕES de um documento Word a partir de MATERIAL bruto. "
            "Devolva SÓ um array JSON: [{\"heading\":str,\"paragraphs\":[str,...]}]. "
            "6 a 12 seções, parágrafos densos, em português, FIEL ao material (não invente).")
    if guia:
        sysm += "\nFORMATO ALVO: " + guia
    usr = f"Título: {titulo}\n\nMATERIAL:\n{material[:12000]}\n\nSeções (array JSON):"
    try:
        r = cli.chat.completions.create(model=mdl, messages=[
            {"role": "system", "content": sysm}, {"role": "user", "content": usr}],
            max_tokens=3500, temperature=0.3)
        raw = (r.choices[0].message.content or "").strip()
        m = _re.search(r"\[.*\]", raw, _re.S)
        arr = _json.loads(m.group(0) if m else raw)
        if isinstance(arr, list) and arr:
            return arr
    except Exception as e:
        print(f"[DOSSIE-WORD] spec-LLM falhou: {e}")
    return None


@register(
    name="criar_documento_word",
    description=(
        "Cria um documento WORD (.docx) EDITÁVEL a partir de seções (heading + "
        "parágrafos + tabela opcional). Use quando o Senhor for EDITAR depois "
        "(contrato, redação, carta, rascunho) ou pedir explicitamente Word/.docx. Para "
        "PDF bonito (relatório/dossiê), use 'criar_relatorio'. fonte_dossie='<tema>' usa "
        "o conteúdo acumulado; formato ajusta a estrutura."
    ),
    parameters={
        "type": "object",
        "properties": {
            "titulo": {"type": "string"},
            "subtitulo": {"type": "string"},
            "fonte_dossie": {"type": "string", "description": "tema do dossiê acumulado (compõe as seções automaticamente)."},
            "formato": {"type": "string", "description": "simulado|prova|artigo|resumo|redacao|relatorio|argumentacao|contrato"},
            "secoes": {
                "type": "array",
                "description": "Seções em ordem.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                        "table": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    },
                    "required": ["heading"],
                },
            },
        },
        "required": ["titulo"],
    },
)
def _t_criar_documento_word(app, titulo="", subtitulo="", fonte_dossie="", formato="", secoes=None):
    try:
        from documents import docx_engine as _dx
    except Exception as e:
        return f"ERRO: módulo Word indisponível: {e}"
    secoes = secoes or []
    formato = (formato or "").strip().lower()
    if fonte_dossie:
        try:
            from jarvis.memory import dossie as _dos
            _k = None if str(fonte_dossie).strip().lower() in ("1", "true", "sim", "ativo") else str(fonte_dossie)
            material = _dos.ler(_k)
            if material and len(material.strip()) > 200:
                geradas = _compose_word_secoes_from_material(app, titulo or str(fonte_dossie), material, guia=_FORMATO_GUIA.get(formato, ""))
                if geradas:
                    secoes = geradas
        except Exception as _ed:
            print(f"[DOSSIE-WORD] composição falhou: {_ed}")
    if not secoes:
        return "ERRO: nada para o documento (passe 'secoes' ou 'fonte_dossie')."
    try:
        path = _dx.gerar_relatorio(titulo, secoes, subtitulo=subtitulo)
    except Exception as e:
        return f"ERRO: falha ao gerar Word: {e}"
    try:
        _open_path(path)
    except Exception:
        pass
    return f"Documento Word criado com {len(secoes)} seções e aberto: {path}"


@register(
    name="exportar_pdf",
    description=(
        "Converte um arquivo de documento JÁ EXISTENTE (.docx, .xlsx, .pptx, .odt…) "
        "em PDF, com alta fidelidade (MS Office se instalado, senão LibreOffice). "
        "Use quando o Senhor pedir 'converte X em pdf', 'exporta esse documento em pdf'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "arquivo": {"type": "string", "description": "Caminho do arquivo a converter."},
        },
        "required": ["arquivo"],
    },
)
def _t_exportar_pdf(app, arquivo=""):
    try:
        from documents import pdf_convert as _pc
    except Exception as e:
        return f"ERRO: conversor indisponível: {e}"
    if not arquivo:
        return "ERRO: informe o caminho do arquivo."
    pdf = _pc.to_pdf(arquivo)
    if not pdf:
        return ("ERRO: não consegui converter. Instale o MS Office ou o LibreOffice "
                "(https://libreoffice.org) para conversão de Word/Excel/PowerPoint → PDF.")
    try:
        _open_path(pdf)
    except Exception:
        pass
    return f"PDF gerado e aberto: {pdf}"


@register(
    name="criar_planilha",
    description=(
        "Cria uma PLANILHA Excel (.xlsx) PROFISSIONAL a partir de uma spec que VOCÊ compõe — "
        "cabeçalho colorido, linhas zebra, freeze panes, FORMATOS por coluna (moeda/percent/"
        "data), FORMATAÇÃO CONDICIONAL (escala de cor, data bars, ícones, maior/menor), "
        "GRÁFICOS nativos e um painel de KPIs no topo.\n"
        "Cada 'aba' = {nome, kpis?[{valor,titulo,legenda?}], headers[], rows[[...]], "
        "formatos?[{coluna, formato}], condicional?[{coluna, tipo, valor?}], "
        "grafico?{tipo:bar|line|pie, titulo?, col_valor, col_rotulo?}}. "
        "'coluna' aceita o NOME do header ou o índice. Use formatos p/ moeda/percent/data, "
        "condicional p/ realçar metas, grafico p/ visualizar. Se precisar de dados atuais, "
        "chame 'pesquisa_web' ANTES."
    ),
    parameters={
        "type": "object",
        "properties": {
            "titulo": {"type": "string"},
            "tema": {"type": "string"},
            "abas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                        "kpis": {"type": "array", "items": {"type": "object", "properties": {"valor": {"type": "string"}, "titulo": {"type": "string"}, "legenda": {"type": "string"}}, "required": []}},
                        "formatos": {"type": "array", "items": {"type": "object", "properties": {"coluna": {"type": "string"}, "formato": {"type": "string"}}, "required": ["coluna", "formato"]}},
                        "condicional": {"type": "array", "items": {"type": "object", "properties": {"coluna": {"type": "string"}, "tipo": {"type": "string"}, "valor": {"type": "string"}}, "required": ["coluna", "tipo"]}},
                        "grafico": {"type": "object", "properties": {"tipo": {"type": "string"}, "titulo": {"type": "string"}, "col_valor": {"type": "string"}, "col_rotulo": {"type": "string"}}, "required": []},
                    },
                    "required": ["nome", "headers", "rows"],
                },
            },
        },
        "required": ["titulo", "abas"],
    },
)
def _t_criar_planilha(app, titulo="", tema="", abas=None):
    try:
        from documents import sheet_builder as _sb
    except Exception as e:
        return f"ERRO: módulo de planilha indisponível: {e}"
    try:
        path = _sb.gerar_planilha({"titulo": titulo, "tema": tema, "abas": abas or []})
    except Exception as e:
        return f"ERRO: falha ao gerar planilha: {e}"
    try:
        _open_path(path)
    except Exception:
        pass
    return f"Planilha criada com {len(abas or [])} aba(s) e aberta: {path}"


# ── Memória semântica/vetorial (roadmap/14) ──────────────────────────────────
# Deixam o PRÓPRIO LLM consultar e gravar memória — resolvendo referências a
# coisas ditas/feitas antes ("minha IDE", "o PDF", "de novo") ANTES de executar
# a ação. Só ficam visíveis quando config.MEMORY_ENABLED (ver _filter_tools_for_text).

@register(
    name="memoria_buscar",
    description=(
        "Busca na MEMÓRIA do Senhor: conversas passadas, arquivos/ações que o "
        "JARVIS já fez, fatos e preferências salvos. USE SEMPRE QUE o pedido "
        "fizer referência a algo dito/feito ANTES e você NÃO tiver o dado no "
        "contexto atual: 'minha IDE', 'esse site', 'aquele arquivo', 'o PDF', "
        "'de novo', 'como sempre', 'manda pra ele', 'qual era mesmo...'. Chame "
        "ESTA tool PRIMEIRO para resolver a referência e SÓ DEPOIS a tool de "
        "ação.\n"
        "↳ NÃO confunda com pesquisa_web (fatos gerais do mundo/internet). "
        "Aqui é a memória PESSOAL do Senhor."
    ),
    parameters={
        "type": "object",
        "properties": {
            "consulta": {
                "type": "string",
                "description": "O que buscar, em linguagem natural (ex.: 'qual minha IDE', 'o PDF que gerei').",
            },
        },
        "required": ["consulta"],
    },
)
def _t_memoria_buscar(app, consulta=""):
    try:
        import jarvis.memory as _mem
    except Exception as e:
        return f"ERRO: memória indisponível: {e}"
    if not _mem.enabled():
        return "Memória desativada (ative em Configurações → Cérebro)."
    try:
        store = _mem.get_store()
        out = store.format_for_prompt(store.retrieve(consulta))
        return out or "Nenhuma memória relevante encontrada."
    except Exception as e:
        return f"ERRO: falha ao buscar memória: {e}"


@register(
    name="memoria_salvar_fato",
    description=(
        "Salva um FATO DURÁVEL sobre o Senhor na memória: identidade, "
        "preferência ou dado estável que valha lembrar no futuro. Ex.: "
        "assunto='minha IDE', atributo='fica em', valor='IDE.DevSystemWeb.com'; "
        "ou assunto='tema favorito', atributo='é', valor='escuro'. Use "
        "fixar=true para IDENTIDADE/preferência forte (sempre lembrada).\n"
        "↳ NÃO salve segredos/senhas/tokens, nem conversa trivial/efêmera "
        "(saudação, chit-chat). Para só CONSULTAR, use memoria_buscar."
    ),
    parameters={
        "type": "object",
        "properties": {
            "assunto":  {"type": "string", "description": "Sujeito do fato (ex.: 'minha IDE', 'meu nome')."},
            "atributo": {"type": "string", "description": "Relação (ex.: 'fica em', 'é', 'prefere')."},
            "valor":    {"type": "string", "description": "Valor do fato (ex.: 'IDE.DevSystemWeb.com')."},
            "fixar":    {"type": "boolean", "description": "True = fixa como identidade/preferência (sempre lembrada)."},
        },
        "required": ["assunto", "atributo", "valor"],
    },
)
def _t_memoria_salvar_fato(app, assunto="", atributo="", valor="", fixar=False):
    try:
        import jarvis.memory as _mem
    except Exception as e:
        return f"ERRO: memória indisponível: {e}"
    if not _mem.enabled():
        return "Memória desativada (ative em Configurações → Cérebro)."
    try:
        rid = _mem.get_store().upsert_fact(assunto, atributo, valor, pinned=bool(fixar))
        if rid is None:
            return "ERRO: não consegui salvar (assunto/atributo vazio?)."
        return f"Anotado: {assunto} {atributo} {valor}."
    except Exception as e:
        return f"ERRO: falha ao salvar fato: {e}"


@register(
    name="memoria_esquecer",
    description=(
        "Remove da memória um fato/assunto que o Senhor pediu para esquecer ou "
        "que ficou desatualizado. Informe o 'assunto' exato (ex.: 'minha IDE'). "
        "Use SÓ quando o Senhor pedir explicitamente para esquecer/apagar algo."
    ),
    parameters={
        "type": "object",
        "properties": {
            "assunto": {"type": "string", "description": "Assunto/sujeito a esquecer (ex.: 'minha IDE')."},
        },
        "required": ["assunto"],
    },
)
def _t_memoria_esquecer(app, assunto=""):
    try:
        import jarvis.memory as _mem
    except Exception as e:
        return f"ERRO: memória indisponível: {e}"
    if not _mem.enabled():
        return "Memória desativada (ative em Configurações → Cérebro)."
    try:
        n = _mem.get_store().forget((assunto or "").strip())
        return (f"Esqueci {n} registro(s) sobre '{assunto}'." if n
                else f"Nada encontrado sobre '{assunto}'.")
    except Exception as e:
        return f"ERRO: falha ao esquecer: {e}"


def _mem_llm_call(app, system: str, user: str, max_tokens: int = 220) -> str:
    """Chamada curta a um LLM barato (Groq real preferido) para resumir/compactar."""
    cli = getattr(app, "_groq_real", None) or getattr(app, "_groq", None)
    if cli is None:
        return ""
    mdl = getattr(app, "_groq_real_model", None) or "llama-3.3-70b-versatile"
    r = cli.chat.completions.create(
        model=mdl,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=0.3)
    return (r.choices[0].message.content or "").strip()


def _coletar_conversa(app, n: int = 24) -> str:
    """Reúne os últimos turnos da conversa (chat ou voz) em texto."""
    turns = []
    for m in (getattr(app, "_chat_history", None) or [])[-n:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            who = "Senhor" if m["role"] == "user" else "JARVIS"
            turns.append(f"{who}: {m['content']}")
    if not turns:
        for t in (getattr(app, "_voz_ctx", None) or [])[-8:]:
            turns.append(f"Senhor: {t.get('user', '')}\nJARVIS: {t.get('jarvis', '')}")
    return "\n".join(turns)


@register(
    name="compactar_conversa",
    description=(
        "Resume a CONVERSA recente em forma CURTA para liberar contexto (gastar "
        "menos tokens), preservando decisões, arquivos gerados e caminhos. Use "
        "quando a conversa ficou longa, o Senhor pedir 'resume/compacta o que "
        "falamos', ou para fechar um assunto. O resumo é guardado na memória."
    ),
    parameters={
        "type": "object",
        "properties": {
            "foco": {"type": "string", "description": "Opcional: tema a priorizar no resumo."},
        },
        "required": [],
    },
)
def _t_compactar_conversa(app, foco=""):
    try:
        from jarvis.memory import compaction as _cp
        import jarvis.memory as _mem
    except Exception as e:
        return f"ERRO: compactação indisponível: {e}"
    txt = _coletar_conversa(app)
    if not txt:
        return "Não há conversa recente para compactar, senhor."
    if foco:
        txt = f"[Priorize: {foco}]\n" + txt
    resumo = _cp.summarize_turns(txt, lambda s, u: _mem_llm_call(app, s, u))
    if not resumo:
        return "ERRO: não consegui resumir agora."
    try:
        if _mem.enabled():
            _mem.get_store().add("episodic", "Resumo da conversa: " + resumo,
                                 importance=0.6, source="summary")
    except Exception:
        pass
    return "Resumo: " + resumo


@register(
    name="resumir_decisoes",
    description=(
        "Extrai e registra, em forma curta, as DECISÕES e escolhas tomadas na "
        "conversa (com a razão de cada uma) — para não reocupar contexto "
        "relembrando tudo. Use quando o Senhor pedir 'quais decisões tomamos' ou "
        "para consolidar o que foi decidido. Guarda o resumo na memória."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def _t_resumir_decisoes(app):
    try:
        from jarvis.memory import compaction as _cp
        import jarvis.memory as _mem
    except Exception as e:
        return f"ERRO: compactação indisponível: {e}"
    txt = _coletar_conversa(app)
    if not txt:
        return "Não há conversa recente, senhor."
    sysm = ("Liste em 1-5 linhas curtas APENAS as DECISÕES/escolhas tomadas na "
            "conversa, cada uma com a razão. Preserve nomes/paths/valores verbatim. "
            "Se não houver decisão clara, responda 'Nenhuma decisão registrada.'")
    resumo = _mem_llm_call(app, sysm, f"Conversa:\n{txt}\n\nDecisões:")
    if not resumo:
        return "ERRO: não consegui consolidar agora."
    try:
        if _mem.enabled():
            _mem.get_store().add("semantic", "Decisões: " + resumo,
                                 importance=0.7, source="summary")
    except Exception:
        pass
    return resumo
