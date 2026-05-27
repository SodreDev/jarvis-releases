# core/env_writer.py
# -*- coding: utf-8 -*-
"""
Leitura e escrita de arquivos `.env` preservando ordem, comentários e linhas
em branco. Usado pela UI de configuração para editar credentials/.env sem
destruir a estrutura editada à mão pelo usuário.

API pública:
    parse_env(path)        -> dict[str, str]    (apenas chaves=valor)
    read_raw(path)         -> list[str]         (linhas brutas)
    write_env(path, items) -> None              (preserva tudo, atualiza/adiciona)
    mask(value, keep=4)    -> str               (mascara para exibição segura)

Formato suportado:
    # comentário
    CHAVE=valor             ← sem aspas
    CHAVE="valor com espaço" ← aspas duplas
    CHAVE='outro'           ← aspas simples
    CHAVE=                  ← vazio
    (linha em branco)

Não suporta:
    expansão de variáveis (${VAR}), multi-line, export.
    O usuário não precisa disso aqui.
"""
from __future__ import annotations
import os
import re
from typing import Dict, List, Tuple

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _strip_quotes(value: str) -> str:
    """Remove aspas externas se houver (mantém o valor literal interno)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _needs_quotes(value: str) -> bool:
    """Retorna True se o valor precisa ser envolvido por aspas duplas."""
    if value == "":
        return False
    # Espaços, # (comentário inline), aspas dentro, ou caractere especial bash
    return bool(re.search(r"[\s#\"'$`\\]", value))


def _format_value(value: str) -> str:
    """Formata um valor para escrita no arquivo .env."""
    if _needs_quotes(value):
        # Escapa aspas duplas internas
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def parse_env(path: str) -> Dict[str, str]:
    """Lê o arquivo .env e retorna {chave: valor}. Ignora ausência do arquivo."""
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = _LINE_RE.match(line)
                if not m:
                    continue
                key, raw_value = m.group(1), m.group(2)
                # Remove comentário inline se valor não estiver em aspas
                if raw_value and raw_value[0] not in ('"', "'"):
                    hash_idx = raw_value.find(" #")
                    if hash_idx >= 0:
                        raw_value = raw_value[:hash_idx].rstrip()
                out[key] = _strip_quotes(raw_value)
    except Exception:
        pass
    return out


def read_raw(path: str) -> List[str]:
    """Retorna o conteúdo bruto do arquivo (lista de linhas, sem \\n final)."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return []


def write_env(path: str, items: Dict[str, str]) -> None:
    """
    Atualiza o arquivo .env preservando ordem, comentários e linhas em branco.
    Chaves novas (não existentes no arquivo) são adicionadas ao final.
    Chaves passadas com valor None são ignoradas (não removidas).
    """
    if items is None:
        return
    # Sanitiza: descarta None e converte para str
    sane: Dict[str, str] = {k: ("" if v is None else str(v)) for k, v in items.items()}

    existing = read_raw(path)
    seen_keys: set = set()
    out_lines: List[str] = []

    for line in existing:
        m = _LINE_RE.match(line)
        if m is None:
            out_lines.append(line)
            continue
        key = m.group(1)
        if key in sane:
            new_val = _format_value(sane[key])
            out_lines.append(f"{key}={new_val}")
            seen_keys.add(key)
        else:
            out_lines.append(line)

    # Chaves novas → append no final
    novos = [k for k in sane if k not in seen_keys]
    if novos:
        if out_lines and out_lines[-1].strip() != "":
            out_lines.append("")
        out_lines.append("# Adicionado pela UI")
        for k in novos:
            out_lines.append(f"{k}={_format_value(sane[k])}")

    # Garante diretório
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    except Exception:
        pass

    # Escreve atomicamente (tmp + replace)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out_lines))
        if out_lines and out_lines[-1] != "":
            f.write("\n")
    os.replace(tmp, path)


def mask(value: str, keep: int = 4) -> str:
    """
    Mascara um valor para exibição segura.
        ""              -> ""
        "abc"           -> "•••"
        "sk_long_key"   -> "•••• _key" (mantém últimos `keep` chars)
    """
    if not value:
        return ""
    n = len(value)
    if n <= keep:
        return "•" * n
    return "•" * 4 + value[-keep:]


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    sample = """# Header
# linha 2 de comentário

GROQ_API_KEY=gsk_abc123
GEMINI_API_KEY="with spaces inside"

# Outro bloco
ELEVENLABS_API_KEY=
"""
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write(sample)
        path = f.name

    print("PARSE:", parse_env(path))
    write_env(path, {
        "GROQ_API_KEY": "gsk_NEW",
        "ELEVENLABS_API_KEY": "sk_xyz_with space",
        "DISCORD_BOT_TOKEN": "nova_chave",
    })
    print("--- após write ---")
    print(open(path, encoding="utf-8").read())
    print("--- mask ---")
    print(mask("sk_long_secret_key_1234"))
    os.unlink(path)
