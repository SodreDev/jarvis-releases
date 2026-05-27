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


# ─────────────────────────────────────────────────────────────────────────
# Tool definition
# ─────────────────────────────────────────────────────────────────────────

class Tool:
    __slots__ = ("name", "description", "parameters", "handler")

    def __init__(self, name: str, description: str,
                 parameters: dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_TOOLS: dict[str, Tool] = {}


def register(name: str, description: str, parameters: dict):
    def deco(fn):
        _TOOLS[name] = Tool(name, description, parameters, fn)
        return fn
    return deco


def to_openai_tools() -> list[dict]:
    return [t.to_openai_schema() for t in _TOOLS.values()]


def list_tools() -> list[str]:
    return list(_TOOLS.keys())


def dispatch(name: str, args: dict, app) -> str:
    """Executa a tool e retorna o resultado em texto.
    Nunca levanta — em erro, devolve 'ERRO: ...'."""
    tool = _TOOLS.get(name)
    if tool is None:
        return f"ERRO: tool '{name}' não existe."
    try:
        kwargs = args if isinstance(args, dict) else {}
        result = tool.handler(app, **kwargs)
        if result is None:
            return ""
        return str(result)
    except TypeError as e:
        return f"ERRO: argumentos inválidos para '{name}': {e}"
    except Exception as e:
        print(f"[TOOL] Falha em {name}: {_tb.format_exc()}")
        return f"ERRO: falha em '{name}': {type(e).__name__}: {e}"


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
                out_lines.append("")
        return "\n".join(out_lines)
    except Exception as e:
        return f"ERRO: pesquisa falhou: {e}"


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
    from urllib.parse import quote_plus
    if not query:
        return "ERRO: query vazia."
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    r1 = bc.abrir_url(url)
    if r1.startswith("ERRO"):
        return r1
    # Aguarda DOM e clica primeiro #video-title
    try:
        page = bc._page()
        page.wait_for_selector("a#video-title", timeout=10000)
        page.locator("a#video-title").first.click()
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        return f"Reproduzindo: {query}, Senhor."
    except Exception as e:
        return f"Abri o YouTube com a busca, mas não consegui clicar no vídeo: {e}"


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
        from config import GROQ_MODELO_CHAT
        resp = groq.chat.completions.create(
            model=GROQ_MODELO_CHAT,
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
                os.startfile(caminho)
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
