# core/dev_mode/prompt_guard.py — Validação e sanitização de prompts antes do envio.
#
# Garante que todo prompt enviado ao Copilot Agent:
#   1. Está completo (contém seções obrigatórias)
#   2. Não contém injeção de prompt (tentativas de subversão)
#   3. Não contém padrões maliciosos (shell injection, SQL injection, etc.)
#   4. Respeita limites de tamanho

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Resultado da validação ────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Resultado da validação de um prompt."""
    is_valid: bool
    sanitized_prompt: str
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid


# ── Constantes ────────────────────────────────────────────────────────────────

_MAX_PROMPT_LENGTH: int = 12_000     # ~3000 tokens estimados
_MIN_PROMPT_LENGTH: int = 50

_REQUIRED_SECTIONS: tuple[str, ...] = ("ROLE", "TASK", "WORKFLOW")

# Padrões de injeção de prompt — tentativas de subverter as instruções do modelo
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("prompt override",
     re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I)),
    ("prompt override",
     re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I)),
    ("prompt override",
     re.compile(r"forget\s+(?:all\s+)?(?:your\s+)?(?:previous|prior)\s+(?:instructions?|context)", re.I)),
    ("role hijacking",
     re.compile(r"(?:you\s+are|act\s+as|pretend\s+(?:to\s+)?be)\s+(?:a\s+)?(?:root|admin|hacker|malware)", re.I)),
    ("system prompt leak",
     re.compile(r"(?:show|reveal|print|output|display)\s+(?:your\s+)?(?:system\s+)?prompt", re.I)),
    ("system prompt leak",
     re.compile(r"(?:what\s+(?:are|is)\s+your)\s+(?:system\s+)?(?:instructions?|prompt|rules?)", re.I)),
    ("instruction injection",
     re.compile(r"\[\s*SYSTEM\s*\]", re.I)),
    ("instruction injection",
     re.compile(r"<\s*system\s*>", re.I)),
    ("new session trick",
     re.compile(r"(?:start|begin)\s+(?:a\s+)?new\s+(?:conversation|session|chat)", re.I)),
]

# Padrões de comandos destrutivos — shell, SQL, ou código perigoso
_MALICIOUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("destructive shell",
     re.compile(r"\brm\s+-r[f]?\s+/", re.I)),
    ("destructive shell",
     re.compile(r"\bformat\s+[a-z]:\s*/", re.I)),
    ("destructive shell",
     re.compile(r":>\s*/(?:etc|dev|proc|sys)\b", re.I)),
    ("SQL injection",
     re.compile(r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b", re.I)),
    ("SQL injection",
     re.compile(r"\bDELETE\s+FROM\s+\w+\s*(?:;|$)", re.I)),
    ("credential exfiltration",
     re.compile(r"(?:curl|wget|fetch)\s+https?://.*(?:password|secret|token|key)", re.I)),
    ("data exfiltration",
     re.compile(r"(?:curl|wget|fetch)\s+.*\|\s*(?:bash|sh|cmd)", re.I)),
    ("reverse shell",
     re.compile(r"\b(?:nc|netcat|ncat)\s+-[el]", re.I)),
    ("reverse shell",
     re.compile(r"\bbash\s+-i\s+>(?:&|/dev/tcp)", re.I)),
]


# ── Funções internas ──────────────────────────────────────────────────────────

def _check_completeness(prompt: str) -> list[str]:
    """Verifica se todas as seções obrigatórias estão presentes."""
    warnings: list[str] = []
    for section in _REQUIRED_SECTIONS:
        # Procura a seção como cabeçalho (início de linha ou após separador)
        pattern = re.compile(rf"(?:^|\n){re.escape(section)}\b", re.I)
        if not pattern.search(prompt):
            warnings.append(f"Seção obrigatória ausente: {section}")
    return warnings


def _detect_injection(prompt: str) -> list[str]:
    """Detecta padrões de injeção de prompt."""
    threats: list[str] = []
    for label, pattern in _INJECTION_PATTERNS:
        if pattern.search(prompt):
            threats.append(f"Injeção detectada ({label}): {pattern.pattern[:60]}")
    return threats


def _detect_malicious(prompt: str) -> list[str]:
    """Detecta comandos destrutivos ou maliciosos."""
    threats: list[str] = []
    for label, pattern in _MALICIOUS_PATTERNS:
        if pattern.search(prompt):
            threats.append(f"Padrão malicioso detectado ({label})")
    return threats


def _check_length(prompt: str) -> list[str]:
    """Verifica limites de tamanho do prompt."""
    warnings: list[str] = []
    if len(prompt) < _MIN_PROMPT_LENGTH:
        warnings.append(
            f"Prompt muito curto ({len(prompt)} chars, mínimo {_MIN_PROMPT_LENGTH})"
        )
    if len(prompt) > _MAX_PROMPT_LENGTH:
        warnings.append(
            f"Prompt excede tamanho máximo ({len(prompt)} chars, máximo {_MAX_PROMPT_LENGTH})"
        )
    return warnings


def _sanitize(prompt: str) -> str:
    """Remove padrões perigosos preservando o conteúdo legítimo."""
    cleaned = prompt
    for _label, pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[BLOCKED]", cleaned)
    for _label, pattern in _MALICIOUS_PATTERNS:
        cleaned = pattern.sub("[BLOCKED]", cleaned)
    return cleaned


# ── API pública ───────────────────────────────────────────────────────────────

def validate_prompt(prompt: str) -> ValidationResult:
    """Valida e sanitiza um prompt antes do envio ao Copilot.

    Executa 4 verificações em sequência:
    1. Completude — seções obrigatórias presentes
    2. Tamanho — entre MIN e MAX
    3. Injeção de prompt — tentativas de subversão do modelo
    4. Padrões maliciosos — shell injection, SQL injection, exfiltração

    Returns:
        ValidationResult com is_valid=True se o prompt é seguro e completo,
        ou is_valid=False com warnings detalhando os problemas encontrados.
    """
    if not prompt or not prompt.strip():
        return ValidationResult(
            is_valid=False,
            sanitized_prompt="",
            warnings=["Prompt vazio"],
        )

    all_warnings: list[str] = []

    # 1. Completude
    all_warnings.extend(_check_completeness(prompt))

    # 2. Tamanho
    all_warnings.extend(_check_length(prompt))

    # 3. Injeção — bloqueia imediatamente
    injection_warnings = _detect_injection(prompt)
    if injection_warnings:
        all_warnings.extend(injection_warnings)
        sanitized = _sanitize(prompt)
        return ValidationResult(
            is_valid=False,
            sanitized_prompt=sanitized,
            warnings=all_warnings,
        )

    # 4. Padrões maliciosos — bloqueia imediatamente
    malicious_warnings = _detect_malicious(prompt)
    if malicious_warnings:
        all_warnings.extend(malicious_warnings)
        sanitized = _sanitize(prompt)
        return ValidationResult(
            is_valid=False,
            sanitized_prompt=sanitized,
            warnings=all_warnings,
        )

    # Prompt passou em todas as verificações de segurança
    # Se só tem warnings de completude/tamanho, ainda pode ser inválido
    has_blocking = any(
        w.startswith("Seção obrigatória ausente") or w.startswith("Prompt muito curto")
        for w in all_warnings
    )

    return ValidationResult(
        is_valid=not has_blocking,
        sanitized_prompt=prompt,
        warnings=all_warnings,
    )
