# comandos/youtube_ctrl.py — Extrai legendas/transcrição de vídeos do YouTube
# -*- coding: utf-8 -*-
"""
Usa youtube-transcript-api para baixar legendas (manuais ou auto-geradas).
Retorna texto limpo pronto para sumarização pela IA.
"""

import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# ── Regex para extrair video_id de vários formatos de URL ────────────────────
_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|embed/|v/|shorts/))"
    r"([A-Za-z0-9_-]{11})"
)


def extrair_video_id(url: str) -> str | None:
    """Extrai o video_id de 11 caracteres de uma URL do YouTube."""
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def obter_transcricao(video_id: str) -> str:
    """Baixa a transcrição do vídeo.
    Prioridade: pt → pt-BR → en → qualquer idioma auto-gerado.
    Retorna string com o texto completo ou levanta exceção."""
    ytt_api = YouTubeTranscriptApi()
    transcript_list = ytt_api.list_transcripts(video_id)

    # Tenta idiomas na ordem de preferência
    for lang in ("pt", "pt-BR", "en"):
        try:
            tr = transcript_list.find_transcript([lang])
            snippets = tr.fetch()
            return " ".join(s.text for s in snippets)
        except NoTranscriptFound:
            continue

    # Fallback: qualquer transcrição gerada automaticamente
    for tr in transcript_list:
        if tr.is_generated:
            snippets = tr.fetch()
            return " ".join(s.text for s in snippets)

    # Último recurso: qualquer transcrição disponível
    for tr in transcript_list:
        snippets = tr.fetch()
        return " ".join(s.text for s in snippets)

    raise NoTranscriptFound(video_id, ["pt", "en"], None)


def obter_transcricao_de_url(url: str) -> tuple[str, str]:
    """Recebe URL completa, retorna (video_id, transcricao_texto).
    Levanta ValueError se URL inválida ou exceções da API se não houver legenda."""
    vid = extrair_video_id(url)
    if not vid:
        raise ValueError(f"URL do YouTube inválida: {url}")
    texto = obter_transcricao(vid)
    return vid, texto
