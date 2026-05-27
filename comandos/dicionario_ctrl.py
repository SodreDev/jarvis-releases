# comandos/dicionario_ctrl.py — J.A.R.V.I.S.
# Definição de palavras (Free Dictionary API para EN, LLM para PT)
# -*- coding: utf-8 -*-

from __future__ import annotations
import urllib.request, urllib.parse, json, re

_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"


def definir_en(palavra: str) -> str | None:
    """
    Busca definição de palavra em inglês via Free Dictionary API.
    Retorna string formatada ou None se a palavra não for encontrada / erro.
    """
    palavra = palavra.strip()
    try:
        url = _DICT_API.format(urllib.parse.quote(palavra.lower()))
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None   # palavra não encontrada → cai para LLM
        return None
    except Exception:
        return None

    if not data or not isinstance(data, list):
        return None

    entry    = data[0]
    phonetic = entry.get("phonetic", "")
    meanings = entry.get("meanings", [])

    linhas = [f"📚 {palavra.capitalize()}{f'  [{phonetic}]' if phonetic else ''}:"]
    for m in meanings[:2]:
        part = m.get("partOfSpeech", "")
        defs = m.get("definitions", [])[:2]
        if part:
            linhas.append(f"  {part}:")
        for d in defs:
            linhas.append(f"    • {d.get('definition', '')}")
            if d.get("example"):
                linhas.append(f"      Ex: \"{d['example']}\"")
    return "\n".join(linhas)


def montar_prompt_definicao(palavra: str, idioma: str = "português") -> str:
    """Monta prompt para o LLM definir uma palavra."""
    return (
        f"Defina a palavra ou expressão '{palavra}' em {idioma}. "
        f"Inclua: classe gramatical, definição clara, sinônimos e um exemplo de uso. "
        f"Seja conciso mas completo. Responda em português."
    )
