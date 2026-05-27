# comandos/traducao_ctrl.py — J.A.R.V.I.S.
# Tradução usando Gemini/Groq (LLM-based, sem API extra)
# -*- coding: utf-8 -*-

from __future__ import annotations

_IDIOMAS = {
    "ingles": "inglês",
    "inglês": "inglês",
    "english": "inglês",
    "espanhol": "espanhol",
    "spanish": "espanhol",
    "frances": "francês",
    "francês": "francês",
    "french": "francês",
    "alemao": "alemão",
    "alemão": "alemão",
    "german": "alemão",
    "italiano": "italiano",
    "italian": "italiano",
    "japones": "japonês",
    "japonês": "japonês",
    "japanese": "japonês",
    "coreano": "coreano",
    "korean": "coreano",
    "chines": "chinês",
    "chinês": "chinês",
    "chinese": "chinês",
    "russo": "russo",
    "russian": "russo",
    "portugues": "português",
    "português": "português",
    "arabe": "árabe",
    "árabe": "árabe",
    "arabic": "árabe",
}


def normalizar_idioma(idioma: str) -> str:
    """Normaliza nome do idioma para português."""
    return _IDIOMAS.get(idioma.strip().lower(), idioma.strip())


def montar_prompt_traducao(texto: str, idioma_destino: str) -> str:
    """Monta prompt para a IA traduzir o texto."""
    idioma = normalizar_idioma(idioma_destino)
    return (
        f"Traduza o seguinte texto para {idioma}. "
        f"Retorne APENAS a tradução, sem explicações ou notas.\n\n"
        f"Texto: {texto}"
    )


def formatar_traducao(texto_original: str, traducao: str, idioma: str) -> str:
    """Formata a resposta final da tradução."""
    idioma = normalizar_idioma(idioma)
    return (
        f"🌐 Tradução para {idioma}:\n"
        f"  Original: {texto_original}\n"
        f"  Tradução: {traducao}"
    )
