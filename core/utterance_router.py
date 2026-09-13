"""
Utterance Router — classifica a quem se dirige uma fala captada pelo mic.

Cascata de baixo custo (CPU desprezível):

    1. Regex de wake word        → "jarvis_command"     conf=0.99
    2. Heurística de vocativo /
       2ª pessoa direta          → "jarvis_question_implicit" / "conversation_2p"
    3. Sinais conversacionais
       (perguntas curtas, riso,
       "né?", "tá ligado")        → "conversation_2p"   conf=0.6-0.8
    4. Default                   → "ambient_noise"      conf=0.5

Targets:
    "jarvis_command"            → comando explícito (já capturado pelo wake)
    "jarvis_question_implicit"  → fala potencialmente dirigida ao JARVIS sem
                                  wake word — proactive engine pode responder
    "conversation_2p"           → conversa entre humanos — apenas observar
    "ambient_noise"             → barulho/leitura/TV — descartar
"""
from __future__ import annotations

import re

# ── Padrões de baixo custo ──────────────────────────────────────────────

_WAKE_RE = re.compile(
    r"\b(jarvis|j[áa]rvis|jarves|jarvi[sz])\b",
    re.IGNORECASE,
)

# Pronomes / formas de tratamento que indicam fala dirigida AO assistente
# (em PT-BR: "você", "tu", "me", "pra mim", "cara", "mano" são humanos;
# já "senhor" + pergunta direta tende a ser ao JARVIS quando vc fala sozinho)
_DIRECT_QUESTION_RE = re.compile(
    r"\b(que horas|quanto (é|custa|tá)|qual (é|o|a)|onde fica|"
    r"como (faço|funciona|abro|fecho)|cadê|preciso|quero saber|"
    r"você sabe|me (mostra|fala|diz|ajuda|lembra)|tá ouvindo)\b",
    re.IGNORECASE,
)

# Marcas conversacionais tipicamente entre humanos
_CONV_MARKERS_RE = re.compile(
    r"\b(né|tá ligado|cara|mano|tipo assim|kkk+|haha+|sério\?|"
    r"jura\?|nossa|caralho|porra|meu deus|ai meu|bicho)\b",
    re.IGNORECASE,
)

# Frases curtas / fillers — provável ruído
_NOISE_RE = re.compile(
    r"^\s*(ah|oh|hum+|é|tá|ok|sim|não|aham|uhum|né)\s*[\.\!\?]?\s*$",
    re.IGNORECASE,
)
# Conteúdo dominado por URLs/domínios — vem de call/mídia, não é comando
_URL_HEAVY_RE = re.compile(
    r"(https?://|www\.)[^\s]+|\b[\w-]+\.(com|net|org|br|io|dev|gov)(\.[a-z]{2})?\b",
    re.IGNORECASE,
)

def classify_target(text: str) -> tuple[str, float]:
    """
    Retorna (target, confidence).

    target ∈ {jarvis_command, jarvis_question_implicit,
              conversation_2p, ambient_noise, unknown}
    """
    t = (text or "").strip()
    if not t:
        return ("ambient_noise", 1.0)

    if _NOISE_RE.match(t):
        return ("ambient_noise", 0.85)

    # Texto dominado por URL/domínio (ex: amigo falando de site numa call)
    # → trata como ruído de fundo, nunca como comando
    url_matches = _URL_HEAVY_RE.findall(t)
    word_count = len(t.split())
    if url_matches and word_count <= 6:
        return ("ambient_noise", 0.90)

    if _WAKE_RE.search(t):
        return ("jarvis_command", 0.99)

    has_question = "?" in t or _DIRECT_QUESTION_RE.search(t) is not None
    has_conv = _CONV_MARKERS_RE.search(t) is not None

    if has_conv and has_question:
        # Pergunta dentro de conversa → provavelmente entre humanos
        return ("conversation_2p", 0.75)

    if has_conv:
        return ("conversation_2p", 0.80)

    if has_question:
        # Pergunta sem marcas conversacionais — pode ser dirigida ao JARVIS
        return ("jarvis_question_implicit", 0.60)

    # Frase curta neutra → ruído
    if len(t.split()) <= 3:
        return ("ambient_noise", 0.65)

    return ("conversation_2p", 0.55)
