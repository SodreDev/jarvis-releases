# VozIa/tts_normalizer.py
# -*- coding: utf-8 -*-
"""
Pré-processador de texto para TTS.
Normaliza símbolos, siglas e abreviações para pronúncia natural em PT-BR.
Idempotente — pode ser chamado múltiplas vezes com segurança.
"""

import re

# ── Siglas com pronúncia fonética definida ────────────────────────────────────
# Ordenadas por comprimento decrescente para que siglas mais longas sejam
# substituídas antes das mais curtas (ex: HTTPS antes de HTTP, VRAM antes de RAM).
_SIGLAS: list[tuple[str, str]] = sorted([
    # Hardware / memória
    ("VRAM",  "vê-rã"),
    ("RAM",   "rã"),
    ("GPU",   "gépi-iú"),
    ("CPU",   "cê-pê-u"),
    ("SSD",   "ésse-ésse-dê"),
    ("HDMI",  "agá-dê-ême-i"),
    ("HDD",   "agá-dê-dê"),
    ("HD",    "agá-dê"),
    ("USB",   "u-ésse-bê"),
    # Armazenamento / frequência
    ("TB",    "tera"),
    ("GB",    "giga"),
    ("MB",    "mega"),
    ("KB",    "kilo"),
    ("GHz",   "gigahertz"),
    ("MHz",   "megahertz"),
    ("Hz",    "hertz"),
    # Velocidade
    ("km/h",  "quilômetros por hora"),
    ("m/s",   "metros por segundo"),
    # Rede / web
    ("HTTPS", "agá-tê-tê-pê-ésse"),
    ("HTTP",  "agá-tê-tê-pê"),
    ("HTML",  "agá-tê-ême-éle"),
    ("CSS",   "cê-ésse-ésse"),
    ("JSON",  "jéison"),
    ("XML",   "xê-ême-éle"),
    ("SQL",   "ésse-quê-éle"),
    ("API",   "a-pê-i"),
    ("URL",   "u-érre-éle"),
    # Wi-Fi (tem hífen — precisa de tratamento especial)
    ("Wi-Fi", "uái-fáí"),
    ("WiFi",  "uái-fáí"),
    # IA / software
    ("LLM",   "le-éle-êmeé"),
    ("OCR",   "ô-cê-érre"),
    ("PDF",   "pê-dê-éfe"),
    ("DOCX",  "documento Word"),
    ("PPTX",  "PowerPoint"),
    ("XLSX",  "planilha Excel"),
    ("PPT",   "PowerPoint"),
    ("XLS",   "planilha Excel"),
    ("DOC",   "documento Word"),
    ("IoT",   "i-ô-tê"),
    ("AI",    "a-i"),
    # Geral / TI
    ("FPS",   "éfe-pê-ésse"),
    ("RPG",   "érre-pê-gê"),
    ("CEO",   "cê-í-ô"),
    ("CTO",   "cê-tê-ô"),
    ("CFO",   "cê-éfe-ô"),
    ("DIY",   "dê-i-ípsilon"),
    ("OS",    "ô-ésse"),
    ("PC",    "pê-cê"),
    ("TV",    "tê-vê"),
    ("OK",    "okey"),
    ("ID",    "i-dê"),
], key=lambda kv: -len(kv[0]))

# ── Abreviações textuais ──────────────────────────────────────────────────────
_ABREV: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\be\.g\.\s*',  re.I), 'por exemplo, '),
    (re.compile(r'\bi\.e\.\s*',  re.I), 'isto é, '),
    (re.compile(r'\bvs?\.\s*',   re.I), 'versus '),
    (re.compile(r'\betc\.\s*',   re.I), 'et cetera '),
    (re.compile(r'\bobs\.\s*',   re.I), 'observação: '),
    (re.compile(r'\baprox\.\s*', re.I), 'aproximadamente '),
    (re.compile(r'\bex\.\s*',    re.I), 'por exemplo, '),
]

# ── Moeda BRL ─────────────────────────────────────────────────────────────────
# Captura: R$ 1.500,00 / R$ 150 / R$ 0,50
_RE_BRL = re.compile(
    r'R\$\s*'
    r'(?P<inteiro>\d{1,3}(?:[.,]\d{3})*)'
    r'(?:[.,](?P<cent>\d{2}))?'
)

# ── Porcentagem ───────────────────────────────────────────────────────────────
_RE_PCT = re.compile(r'(\d+(?:[,.]\d+)?)\s*%')

# ── Temperatura ───────────────────────────────────────────────────────────────
_RE_CELSIUS      = re.compile(r'(\d+(?:[.,]\d+)?)\s*°\s*[Cc]')
_RE_FAHRENHEIT   = re.compile(r'(\d+(?:[.,]\d+)?)\s*°\s*[Ff]')
_RE_GRAU_GENERICO = re.compile(r'(\d+(?:[.,]\d+)?)\s*°(?!\s*[CcFf])')

# ── URLs ──────────────────────────────────────────────────────────────────────
_RE_URL = re.compile(r'https?://\S+|www\.\S+', re.I)

# ── Markdown ──────────────────────────────────────────────────────────────────
_RE_MD = re.compile(r'[*_`#~>\[\]()]')

# ── Mapa letra → fonema para spell-out de siglas genéricas ───────────────────
_FONEMAS: dict[str, str] = {
    'A': 'á',  'B': 'bê',    'C': 'cê',     'D': 'dê',      'E': 'ê',
    'F': 'éfe','G': 'gê',    'H': 'agá',    'I': 'í',       'J': 'jota',
    'K': 'cá', 'L': 'éle',   'M': 'ême',    'N': 'êne',     'O': 'ô',
    'P': 'pê', 'Q': 'quê',   'R': 'érre',   'S': 'ésse',    'T': 'tê',
    'U': 'ú',  'V': 'vê',    'W': 'dáblio', 'X': 'xis',     'Y': 'ípsilon',
    'Z': 'zê',
}

# Pré-compila padrões das siglas conhecidas uma única vez
_SIGLAS_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?<![A-Za-z])' + re.escape(sigla) + r'(?![A-Za-z])'), pronunc)
    for sigla, pronunc in _SIGLAS
]

# Padrão para siglas genéricas residuais (2–5 letras maiúsculas)
_RE_SIGLA_GENERICA = re.compile(r'\b[A-Z]{2,5}\b')

# Palavras curtas em PT-BR (e algumas EN comuns) que NÃO devem ser soletradas
# mesmo se aparecerem em CAIXA ALTA. Ex.: "REINICIO EM PROGRESSO" → não soletra "EM".
_PT_PALAVRAS_CAPS = {
    "EM", "DE", "DO", "DA", "DOS", "DAS", "AO", "AOS", "AS", "OS",
    "NA", "NO", "NAS", "NOS", "OU", "SE", "SEU", "SUA", "ELE", "ELA",
    "JA", "JÁ", "TAO", "TÃO", "MAS", "MAIS", "QUE", "POR", "PRA", "PARA",
    "COM", "SEM", "ATE", "ATÉ", "VOCE", "VOCÊ", "EU", "TU", "ME", "TE",
    "É", "VAI", "VEM", "FOI", "SIM", "NAO", "NÃO", "SO", "SÓ",
    "OK", "AH", "OH", "HEY", "HI", "YES", "NO",
    "EX", "ETC",
}


def _brl_to_text(m: re.Match) -> str:
    """Converte match de R$ para texto legível em PT-BR."""
    inteiro = int(m.group('inteiro').replace('.', '').replace(',', ''))
    cent    = int(m.group('cent') or '0')
    if cent and not inteiro:
        return f"{cent} centavos"
    if cent:
        return f"{inteiro} reais e {cent} centavos"
    return f"{inteiro} reais"


def _spell_sigla(m: re.Match) -> str:
    """Soletra sigla genérica letra-a-letra: 'SLA' → 'ésse-éle-á'.
    Pula palavras PT-BR comuns em caixa alta (EM, DE, NA, OU…)."""
    palavra = m.group(0)
    if palavra.upper() in _PT_PALAVRAS_CAPS:
        return palavra.lower()
    return '-'.join(_FONEMAS.get(ch, ch) for ch in palavra)


def normalizar(texto: str) -> str:
    """
    Normaliza texto para síntese TTS em português.
    Deve ser chamado antes de qualquer engine (Edge TTS ou Kokoro).
    """
    if not texto:
        return texto

    # 0. Nome do assistente: J.A.R.V.I.S / J.A.R.V.I.S. / JARVIS → "Jarvis"
    # Importante fazer ANTES de _ABREV — senão "V." casa com a regex de "vs."
    # e sai pronunciado como "J.A.R.versus I.S.". Não consome a pontuação
    # final — preserva o "." de fim de frase para o TTS pausar corretamente.
    texto = re.sub(
        r'\bJ\.?\s*A\.?\s*R\.?\s*V\.?\s*I\.?\s*S\b',
        'Jarvis',
        texto,
        flags=re.IGNORECASE,
    )
    # Limpa "Jarvis.," (ponto+vírgula órfão deixado pelo "." da sigla original)
    texto = re.sub(r'\bJarvis\.([,;:!?])', r'Jarvis\1', texto)

    # 1. Remove formatação Markdown
    texto = _RE_MD.sub('', texto)

    # 2. URLs → "[link]"
    texto = _RE_URL.sub('[link]', texto)

    # 3. Moeda BRL  (R$ 1.500,00 → "1500 reais")
    texto = _RE_BRL.sub(_brl_to_text, texto)

    # 4. Porcentagem  (50% → "50 por cento")
    texto = _RE_PCT.sub(
        lambda m: m.group(1).replace(',', '.') + ' por cento', texto
    )

    # 5. Temperatura
    texto = _RE_CELSIUS.sub(
        lambda m: m.group(1) + ' graus Celsius', texto
    )
    texto = _RE_FAHRENHEIT.sub(
        lambda m: m.group(1) + ' graus Fahrenheit', texto
    )
    texto = _RE_GRAU_GENERICO.sub(
        lambda m: m.group(1) + ' graus', texto
    )

    # 6. Abreviações textuais  (e.g. → "por exemplo")
    for pat, repl in _ABREV:
        texto = pat.sub(repl, texto)

    # 7. Siglas com pronúncia definida (mais longas primeiro)
    for pat, pronunc in _SIGLAS_COMPILED:
        texto = pat.sub(pronunc, texto)

    # 8. Siglas genéricas residuais (2–5 caps)  → spell-out fonético
    texto = _RE_SIGLA_GENERICA.sub(_spell_sigla, texto)

    return texto.strip()
