# url_fetch_ctrl.py — Busca URL e extrai texto limpo para resumo pela IA
# Segurança: bloqueia IPs privados/loopback (SSRF protection)
import re
import ipaddress
import socket

# ── Limites de segurança ─────────────────────────────────────────────────────
_MAX_BYTES   = 500_000   # 500 KB máximo de download
_TIMEOUT_S   = 10        # timeout de conexão e leitura

# Regex para extrair a primeira URL válida do texto do comando
_URL_RE = re.compile(
    r"https?://[^\s\"'>;\])}]+"
    r"|(?:www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s\"'>;\])}]*)",
    re.I,
)

# Prefixos de URL de IPs privados a bloquear (SSRF)
_PRIVATE_PREFIXES = (
    "http://127.", "https://127.",
    "http://10.",  "https://10.",
    "http://192.168.", "https://192.168.",
    "http://172.", "https://172.",
    "http://169.254.", "https://169.254.",  # link-local
    "http://0.", "https://0.",
    "http://localhost", "https://localhost",
)


def _is_private_url(url: str) -> bool:
    """Retorna True se a URL aponta para um IP privado/loopback (bloqueia SSRF)."""
    tl = url.lower()
    if any(tl.startswith(p) for p in _PRIVATE_PREFIXES):
        return True
    try:
        # Resolve hostname e checa se é IP privado
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        if host:
            resolved = socket.gethostbyname(host)
            addr = ipaddress.ip_address(resolved)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return True
    except Exception:
        pass
    return False


def _extrair_texto_html(html: bytes, charset: str = "utf-8") -> str:
    """Extrai texto legível de HTML via BeautifulSoup."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # Remove scripts, estilos e navegação
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Compacta linhas em branco consecutivas
    linhas = [l.strip() for l in text.splitlines()]
    linhas = [l for l in linhas if l]
    return "\n".join(linhas)


def fetch_url_texto(url: str, timeout: float = 4.0, max_chars: int = 3500) -> str:
    """GET direto numa URL → texto LIMPO do corpo (bs4). Time-boxed + SSRF-safe.
    Retorna '' em QUALQUER falha (nunca levanta) — feito p/ usar em loop de pesquisa,
    onde uma URL morta NÃO pode travar o agente."""
    import httpx
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    if _is_private_url(url):
        return ""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "JARVIS/1.0 (fetch)"}) as client:
            resp = client.get(url)
            resp.raise_for_status()
        conteudo = resp.content[:_MAX_BYTES]
        ct = resp.headers.get("content-type", "").lower()
        if "html" in ct or not ct:
            texto = _extrair_texto_html(conteudo)
        elif "text" in ct:
            texto = conteudo.decode("utf-8", errors="replace")
        else:
            return ""
        return (texto or "").strip()[:max_chars]
    except Exception:
        return ""


def fetch_e_resumir(texto_cmd: str, resumir_cb=None) -> str:
    """Faz GET na URL detectada no texto e retorna texto limpo (ou resumo via IA).

    Args:
        texto_cmd: texto do comando do usuário (deve conter a URL)
        resumir_cb: opcional — callable(texto) que chama a IA e retorna resumo str
    """
    import httpx

    # Extrai URL do comando
    m = _URL_RE.search(texto_cmd)
    if not m:
        return "Nenhuma URL encontrada no comando, Senhor."
    url = m.group(0)
    if not url.startswith("http"):
        url = "https://" + url

    # Bloqueia IPs internos (SSRF)
    if _is_private_url(url):
        return "Acesso bloqueado: URLs internas/privadas não são permitidas, Senhor."

    # Faz o GET
    try:
        with httpx.Client(timeout=_TIMEOUT_S, follow_redirects=True,
                          headers={"User-Agent": "JARVIS/1.0 (fetch)"}) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.TimeoutException:
        return f"Tempo esgotado ao acessar {url[:60]}, Senhor."
    except httpx.HTTPStatusError as e:
        return f"Erro HTTP {e.response.status_code} ao acessar {url[:60]}, Senhor."
    except Exception as e:
        return f"Falha ao acessar URL ({type(e).__name__}), Senhor."

    # Verifica tamanho
    conteudo = resp.content
    if len(conteudo) > _MAX_BYTES:
        conteudo = conteudo[:_MAX_BYTES]

    # Extrai texto
    ct = resp.headers.get("content-type", "").lower()
    if "html" in ct or not ct:
        texto = _extrair_texto_html(conteudo)
    elif "text" in ct:
        texto = conteudo.decode("utf-8", errors="replace")
    else:
        return f"Tipo de conteúdo não suportado ({ct}), Senhor."

    if not texto.strip():
        return "A página não retornou conteúdo de texto útil, Senhor."

    # Limita para não explodir contexto da IA
    MAX_CHARS = 8000
    truncado = len(texto) > MAX_CHARS
    texto_ia = texto[:MAX_CHARS]

    # Chama IA para resumir (se callback disponível)
    if resumir_cb:
        prompt = (
            f"O usuário pediu para resumir o conteúdo da URL: {url}\n\n"
            f"CONTEÚDO EXTRAÍDO{'[truncado]' if truncado else ''}:\n{texto_ia}\n\n"
            "Faça um resumo claro e conciso em português do conteúdo acima. "
            "Mantenha os pontos mais importantes. Sem markdown excessivo."
        )
        resumo = resumir_cb(prompt)
        return resumo or "Não foi possível gerar o resumo, Senhor."
    else:
        # Sem IA: retorna amostra do texto + aviso
        amostra = texto[:500]
        return (
            f"Conteúdo de {url[:60]}:\n{amostra}"
            + ("\n[...texto truncado]" if len(texto) > 500 else "")
        )
