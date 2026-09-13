# security/sanitizer.py — J.A.R.V.I.S.
# Sanitização de entrada e detecção de prompt injection.
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import html

# ── Origens externas (não disparam comandos de sistema) ───────────────────────
_EXTERNAL_ORIGINS: frozenset[str] = frozenset({
    "whatsapp", "instagram", "discord", "telegram", "email", "sms", "chat_externo",
})

# ── Padrões de prompt injection ───────────────────────────────────────────────
# Cobrem variantes em PT-BR e EN; testados case-insensitive.
_INJECTION_PATTERNS: list[re.Pattern] = [
    # Inglês
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"disregard\s+(your\s+)?previous\s+instructions?", re.I),
    re.compile(r"forget\s+(your\s+)?instructions?", re.I),
    re.compile(r"system\s+override", re.I),
    re.compile(r"execute\s+command\b", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(?:an?\s+)?(?:new|different|evil|jailbreak)", re.I),
    re.compile(r"act\s+as\s+(if\s+you\s+(?:are|were)|a\s+)", re.I),
    re.compile(r"pretend\s+(you\s+)?(are|to\s+be)\b", re.I),
    re.compile(r"new\s+(system\s+)?prompt\s*:", re.I),
    re.compile(r"bypass\s+(safety|security|filter)", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"DAN\s+mode", re.I),
    # Português
    re.compile(r"ignore\s+(as\s+)?instru[çc][õo]es\s+anteriores?", re.I),
    re.compile(r"esqueça?\s+(as\s+)?instru[çc][õo]es?", re.I),
    re.compile(r"(aja|age|atue)\s+como\s+(se\s+)?(?:você\s+(?:fosse|é)|um\s+)", re.I),
    re.compile(r"voc[êe]\s+(é|é\s+agora|é\s+um\s+novo)\s+", re.I),
    re.compile(r"novo\s+modo\s*:", re.I),
    re.compile(r"desative\s+(os?\s+)?filtros?", re.I),
    re.compile(r"desabilite\s+(os?\s+)?filtros?", re.I),
    re.compile(r"finja\s+(que\s+)?(voc[êe]\s+[eé]|ser)\b", re.I),
    re.compile(r"simule\s+(que\s+)?voc[êe]\s+[eé]", re.I),
    re.compile(r"n[ãa]o\s+h[áa]\s+restri[çc][õo]es?", re.I),
    re.compile(r"sem\s+restri[çc][õo]es?", re.I),
    re.compile(r"prompt\s+(do\s+)?sistema\s*:", re.I),
    re.compile(r"override\s+(?:de\s+)?sistema", re.I),
    # Marcadores típicos de tentativa de injeção via texto colado
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"\[SYSTEM\]", re.I),
    re.compile(r"\bINSTRUCTIONS?\s*:", re.I),
]

# ── Comprimento máximo permitido para texto externo ───────────────────────────
_MAX_EXTERNAL_LEN = 2000


def _classify_origin(origem: str) -> str:
    """Retorna "external" se a origem for uma fonte externa, "internal" caso contrário."""
    return "external" if origem.lower() in _EXTERNAL_ORIGINS else "internal"


def is_injection_attempt(text: str) -> bool:
    """
    Retorna True se o texto contém padrões de prompt injection.
    Deve ser chamado mesmo para entradas internas (ex: texto colado pelo usuário).
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def sanitize_external(text: str) -> str:
    """
    Limpa texto oriundo de fontes externas (WhatsApp, email, etc.):
    - Remove tags HTML
    - Decodifica entidades HTML
    - Remove caracteres de controle
    - Trunca em _MAX_EXTERNAL_LEN
    """
    # Decodifica entidades HTML (ex: &amp; → &)
    text = html.unescape(text)
    # Remove tags HTML
    text = re.sub(r"<[^>]{0,200}>", "", text)
    # Remove caracteres de controle exceto newline/tab
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Trunca
    if len(text) > _MAX_EXTERNAL_LEN:
        text = text[:_MAX_EXTERNAL_LEN] + " [...]"
    return text.strip()


def sanitize_input(text: str, origem: str) -> tuple[str, str]:
    """
    Ponto de entrada principal do sanitizer.

    Retorna (texto_processado, source_tag) onde source_tag = "internal" | "external".

    O chamador deve:
    - Se source_tag == "external": passar apenas para chat (nunca executar comandos)
    - Se is_injection_attempt() já verificado antes: bloquear totalmente
    """
    source_tag = _classify_origin(origem)

    if source_tag == "external":
        text = sanitize_external(text)

    return text, source_tag


# ─────────────────────────────────────────────────────────────────────────────
# safe_path / safe_shell / safe_url
# ─────────────────────────────────────────────────────────────────────────────
import os as _os
import sys as _sys
import shlex as _shlex
from urllib.parse import urlparse as _urlparse


class UnsafeInput(Exception):
    """Levantado quando uma entrada é classificada como insegura."""


def _resolve_base() -> str:
    if getattr(_sys, "frozen", False):
        return _os.path.dirname(_sys.executable)
    return _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def safe_path(
    user_path: str,
    *,
    base: str | None = None,
    must_exist: bool = False,
    allow_outside: bool = False,
) -> str:
    """
    Normaliza um caminho fornecido pelo usuário, bloqueando traversal.

    - Resolve `..` e symlinks.
    - Se `allow_outside=False`, exige que o resultado esteja dentro de `base`.
    - `base` padrão: raiz do projeto (ou exe quando frozen).
    """
    if not isinstance(user_path, str) or not user_path.strip():
        raise UnsafeInput("Caminho vazio.")
    if "\x00" in user_path:
        raise UnsafeInput("Null byte no caminho.")
    base = _os.path.realpath(base or _resolve_base())
    candidate = user_path
    if not _os.path.isabs(candidate):
        candidate = _os.path.join(base, candidate)
    resolved = _os.path.realpath(candidate)
    if not allow_outside:
        try:
            common = _os.path.commonpath([resolved, base])
        except ValueError:
            raise UnsafeInput("Caminho fora da raiz permitida.")
        if common != base:
            raise UnsafeInput(f"Caminho fora da raiz permitida: {resolved}")
    if must_exist and not _os.path.exists(resolved):
        raise UnsafeInput(f"Caminho não existe: {resolved}")
    return resolved


# Tokens proibidos em comandos shell (encadeamento, redireção, expansão).
_SHELL_FORBIDDEN = frozenset({"&", "|", ";", "`", "$", ">", "<", "\n", "\r"})

# Allowlist conservadora de executáveis seguros — extensível por chamadores.
_DEFAULT_SHELL_ALLOWLIST: frozenset[str] = frozenset({
    "python", "python.exe", "py", "py.exe",
    "pip", "pip.exe", "pytest", "pytest.exe",
    "git", "git.exe",
    "node", "node.exe", "npm", "npm.exe", "npx", "npx.exe",
    "code", "code.exe",
})


def safe_shell(
    command: str,
    *,
    allowlist: frozenset[str] | None = None,
    extra: frozenset[str] = frozenset(),
) -> list[str]:
    """
    Valida um comando shell e retorna a lista de argumentos pronta para
    `subprocess.run(..., shell=False)`.

    Recusa: encadeamento (`&&`, `;`), redireção (`>`, `<`), expansão (`$`),
    backticks, newlines. O executável precisa estar na allowlist.
    """
    if not isinstance(command, str) or not command.strip():
        raise UnsafeInput("Comando vazio.")
    if any(c in command for c in _SHELL_FORBIDDEN):
        raise UnsafeInput("Comando contém metacaracteres de shell.")
    try:
        parts = _shlex.split(command, posix=(_os.name != "nt"))
    except ValueError as exc:
        raise UnsafeInput(f"Comando mal formado: {exc}") from exc
    if not parts:
        raise UnsafeInput("Comando vazio após parsing.")
    exe = _os.path.basename(parts[0]).lower()
    allow = (allowlist or _DEFAULT_SHELL_ALLOWLIST) | extra
    if exe not in allow:
        raise UnsafeInput(
            f"Executável '{exe}' não permitido (allowlist={sorted(allow)})."
        )
    return parts


_URL_ALLOWED_SCHEMES = frozenset({"http", "https"})
_URL_BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def safe_url(
    url: str,
    *,
    allow_local: bool = False,
    schemes: frozenset[str] = _URL_ALLOWED_SCHEMES,
) -> str:
    """
    Valida uma URL. Recusa schemes não-http(s), hosts vazios e (por padrão)
    aponta para loopback (SSRF básico).
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeInput("URL vazia.")
    parsed = _urlparse(url.strip())
    if parsed.scheme.lower() not in schemes:
        raise UnsafeInput(f"Scheme não permitido: {parsed.scheme!r}.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeInput("URL sem host.")
    if not allow_local and host in _URL_BLOCKED_HOSTS:
        raise UnsafeInput(f"Host bloqueado (loopback): {host}.")
    return parsed.geturl()


__all__ = [
    "is_injection_attempt",
    "sanitize_external",
    "sanitize_input",
    "safe_path",
    "safe_shell",
    "safe_url",
    "UnsafeInput",
]
