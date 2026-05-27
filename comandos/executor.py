"""
Módulo de Execução de Comandos Locais — J.A.R.V.I.S.
Processa comandos do usuário e executa ações no sistema operacional.

Usa subprocess.Popen para não travar o aplicativo principal.
Compatível com Windows e macOS.
"""

import os
import platform
import re
import subprocess
import webbrowser


def _abrir_url_navegador_padrao(url: str) -> bool:
    """Abre URL no NAVEGADOR PADRÃO do Windows via Popen direto no exe
    (robusto: funciona com navegador fechado, qualquer thread).
    Fallback: os.startfile, webbrowser."""
    try:
        from comandos import browser_ctrl as _bc
        return _bc.abrir_url_padrao(url)
    except Exception as _e:
        print(f"[executor] abrir_url_padrao falhou: {_e}")
    try:
        if hasattr(os, "startfile"):
            os.startfile(url)  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    try:
        webbrowser.open(url, new=2)
        return True
    except Exception:
        return False

# ==========================================
# MAPEAMENTO DE COMANDOS
# ==========================================

_SITES = {
    # ── Busca / Navegação ─────────────────────────────────────────────────
    ("navegador", "google", "browser", "chrome", "internet", "pesquisa"): (
        "https://www.google.com",
        "Google aberto, senhor.",
    ),
    ("bing",): (
        "https://www.bing.com",
        "Bing aberto, Senhor.",
    ),
    ("duckduckgo", "duck duck go", "duck"): (
        "https://duckduckgo.com",
        "DuckDuckGo aberto, Senhor.",
    ),

    # ── Redes Sociais ─────────────────────────────────────────────────────
    ("youtube",): (
        "https://www.youtube.com",
        "YouTube carregado, Senhor.",
    ),    # YouTube — sub-seções
    (
        "historico youtube", "historico do youtube", "meu historico youtube",
        "historico de pesquisa youtube", "historico de pesquisa do youtube",
        "historico de visualizacoes", "historico de visualizacoes youtube",
        "ver historico youtube", "meu historico de pesquisa",
    ): (
        "https://www.youtube.com/feed/history",
        "Histórico do YouTube aberto, Senhor.",
    ),
    (
        "inscricoes youtube", "inscricoes do youtube", "minhas inscricoes",
        "canais inscritos", "meus canais inscritos",
    ): (
        "https://www.youtube.com/feed/subscriptions",
        "Inscrições do YouTube abertas, Senhor.",
    ),
    (
        "tendencias youtube", "em alta youtube", "videos em alta",
        "trending youtube", "mais vistos youtube",
    ): (
        "https://www.youtube.com/feed/trending",
        "Tendências do YouTube abertas, Senhor.",
    ),
    (
        "assistir mais tarde", "watch later", "videos salvos youtube",
    ): (
        "https://www.youtube.com/playlist?list=WL",
        "Lista 'Assistir Mais Tarde' aberta, Senhor.",
    ),
    (
        "biblioteca youtube", "minhas playlists youtube", "playlist salvas",
    ): (
        "https://www.youtube.com/feed/library",
        "Biblioteca do YouTube aberta, Senhor.",
    ),
    # Google — sub-seções
    (
        "historico google", "historico de pesquisa google", "meu historico de pesquisas",
        "historico do google", "historico de buscas google",
    ): (
        "https://myactivity.google.com/myactivity",
        "Histórico do Google aberto, Senhor.",
    ),
    (
        "conta google", "minha conta google", "google account",
    ): (
        "https://myaccount.google.com",
        "Conta Google aberta, Senhor.",
    ),
    (
        "politica de privacidade google", "privacidade google", "dados google",
    ): (
        "https://policies.google.com/privacy",
        "Política de privacidade do Google aberta, Senhor.",
    ),
    (
        "termos de servico google", "termos google",
    ): (
        "https://policies.google.com/terms",
        "Termos de serviço do Google abertos, Senhor.",
    ),
    # Google Arts & Culture / Notícias
    (
        "google noticias", "noticias google", "google news",
    ): (
        "https://news.google.com",
        "Google Notícias aberto, Senhor.",
    ),
    (
        "google arts", "arts and culture", "google arts and culture",
    ): (
        "https://artsandculture.google.com",
        "Google Arts & Culture aberto, Senhor.",
    ),    ("instagram",): (
        "https://www.instagram.com",
        "Instagram aberto, Senhor.",
    ),
    ("twitter", "x", "x.com"): (
        "https://x.com",
        "X aberto, Senhor.",
    ),
    ("facebook", "face"): (
        "https://www.facebook.com",
        "Facebook aberto, Senhor.",
    ),
    ("tiktok", "tik tok"): (
        "https://www.tiktok.com",
        "TikTok aberto, Senhor.",
    ),
    ("reddit",): (
        "https://www.reddit.com",
        "Reddit aberto, Senhor.",
    ),
    ("linkedin", "linked in"): (
        "https://www.linkedin.com",
        "LinkedIn aberto, Senhor.",
    ),
    ("pinterest",): (
        "https://www.pinterest.com",
        "Pinterest aberto, Senhor.",
    ),
    ("twitch",): (
        "https://www.twitch.tv",
        "Twitch aberto, Senhor.",
    ),

    # ── Comunicação ───────────────────────────────────────────────────────
    ("whatsapp", "whats"): (
        "https://web.whatsapp.com",
        "WhatsApp Web aberto, Senhor.",
    ),
    ("gmail", "email", "correio", "e-mail"): (
        "https://mail.google.com",
        "Gmail aberto, Senhor.",
    ),
    # Discord, Telegram, Slack e Teams agora são abertos nativamente
    # via janela_ctrl.abrir_app() (app desktop, não browser)
    ("outlook",): (
        "https://outlook.live.com",
        "Outlook aberto, Senhor.",
    ),

    # ── Streaming de Vídeo ────────────────────────────────────────────────
    ("netflix",): (
        "https://www.netflix.com",
        "Netflix aberta, Senhor. Boa sessão.",
    ),
    ("disney", "disney plus", "disney+"): (
        "https://www.disneyplus.com",
        "Disney+ aberta, Senhor.",
    ),
    ("prime video", "prime", "amazon prime", "amazon video"): (
        "https://www.primevideo.com",
        "Prime Video aberto, Senhor.",
    ),
    ("hbo", "max", "hbo max", "warner"): (
        "https://www.max.com",
        "Max aberto, Senhor.",
    ),
    ("globoplay", "globo play", "globo"): (
        "https://globoplay.globo.com",
        "Globoplay aberto, Senhor.",
    ),
    ("crunchyroll", "anime", "crunchy"): (
        "https://www.crunchyroll.com",
        "Crunchyroll aberto, Senhor.",
    ),
    ("pluto tv", "pluto", "plutotv"): (
        "https://pluto.tv",
        "Pluto TV aberta, Senhor.",
    ),
    ("apple tv", "apple tv+", "appletv"): (
        "https://tv.apple.com",
        "Apple TV+ aberta, Senhor.",
    ),
    ("paramount", "paramount+"): (
        "https://www.paramountplus.com",
        "Paramount+ aberto, Senhor.",
    ),

    # ── Música ────────────────────────────────────────────────────────────
    ("spotify",): (
        "https://open.spotify.com",
        "Spotify aberto, Senhor.",
    ),
    ("deezer",): (
        "https://www.deezer.com",
        "Deezer aberto, Senhor.",
    ),
    ("soundcloud", "sound cloud"): (
        "https://soundcloud.com",
        "SoundCloud aberto, Senhor.",
    ),
    ("apple music",): (
        "https://music.apple.com",
        "Apple Music aberto, Senhor.",
    ),

    # ── Inteligência Artificial ───────────────────────────────────────────
    ("chatgpt", "chat gpt", "openai", "open ai"): (
        "https://chatgpt.com",
        "ChatGPT aberto, Senhor.",
    ),
    ("gemini", "google gemini", "bard"): (
        "https://gemini.google.com",
        "Gemini aberto, Senhor.",
    ),
    ("claude", "anthropic"): (
        "https://claude.ai",
        "Claude da Anthropic aberto, Senhor.",
    ),
    ("copilot", "microsoft copilot", "bing ia", "bing ai"): (
        "https://copilot.microsoft.com",
        "Microsoft Copilot aberto, Senhor.",
    ),
    ("perplexity",): (
        "https://www.perplexity.ai",
        "Perplexity aberto, Senhor.",
    ),
    ("grok", "grok ai", "grok ia"): (
        "https://grok.com",
        "Grok aberto, Senhor.",
    ),
    ("midjourney",): (
        "https://www.midjourney.com",
        "Midjourney aberto, Senhor.",
    ),
    ("leonardo", "leonardo ai", "leonardoai"): (
        "https://app.leonardo.ai",
        "Leonardo AI aberto, Senhor.",
    ),
    ("runway", "runway ml", "runwayml"): (
        "https://app.runwayml.com",
        "Runway ML aberto, Senhor.",
    ),
    ("elevenlabs", "eleven labs"): (
        "https://elevenlabs.io",
        "ElevenLabs aberto, Senhor.",
    ),
    ("hugging face", "huggingface"): (
        "https://huggingface.co",
        "Hugging Face aberto, Senhor.",
    ),
    ("stable diffusion", "stablediffusion", "stability"): (
        "https://stability.ai",
        "Stability AI aberto, Senhor.",
    ),
    ("sora", "openai sora"): (
        "https://sora.com",
        "Sora aberto, Senhor.",
    ),
    ("poe",): (
        "https://poe.com",
        "Poe aberto, Senhor.",
    ),

    # ── Estudo / Educação ─────────────────────────────────────────────────
    ("wikipedia", "wiki"): (
        "https://pt.wikipedia.org",
        "Wikipedia aberta, Senhor.",
    ),
    ("khan academy", "khanacademy", "khan"): (
        "https://pt.khanacademy.org",
        "Khan Academy aberta, Senhor.",
    ),
    ("coursera",): (
        "https://www.coursera.org",
        "Coursera aberto, Senhor.",
    ),
    ("udemy",): (
        "https://www.udemy.com",
        "Udemy aberta, Senhor.",
    ),
    ("alura",): (
        "https://www.alura.com.br",
        "Alura aberta, Senhor.",
    ),
    ("duolingo",): (
        "https://www.duolingo.com",
        "Duolingo aberto, Senhor.",
    ),
    ("descomplica",): (
        "https://descomplica.com.br",
        "Descomplica aberto, Senhor.",
    ),
    ("quizlet",): (
        "https://quizlet.com",
        "Quizlet aberto, Senhor.",
    ),
    ("enem", "preparação enem", "preparacao enem"): (
        "https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enem",
        "Portal do ENEM aberto, Senhor.",
    ),

    # ── Dev / Tecnologia ─────────────────────────────────────────────────
    ("github",): (
        "https://github.com",
        "GitHub aberto, Senhor.",
    ),
    ("stackoverflow", "stack overflow"): (
        "https://stackoverflow.com",
        "Stack Overflow aberto, Senhor.",
    ),
    ("mdn", "mozilla developer", "mozilla"): (
        "https://developer.mozilla.org",
        "MDN aberto, Senhor.",
    ),
    ("npm",): (
        "https://www.npmjs.com",
        "NPM aberto, Senhor.",
    ),
    ("pypi", "pip"): (
        "https://pypi.org",
        "PyPI aberto, Senhor.",
    ),
    ("vercel",): (
        "https://vercel.com",
        "Vercel aberto, Senhor.",
    ),
    ("netlify",): (
        "https://www.netlify.com",
        "Netlify aberto, Senhor.",
    ),
    ("replit",): (
        "https://replit.com",
        "Replit aberto, Senhor.",
    ),
    ("codepen",): (
        "https://codepen.io",
        "CodePen aberto, Senhor.",
    ),
    ("figma",): (
        "https://www.figma.com",
        "Figma aberto, Senhor.",
    ),
    ("discloud",): (
        "https://discloud.com",
        "Discloud aberto, Senhor.",
    ),

    # ── Produtividade / Ferramentas ───────────────────────────────────────
    ("google drive", "drive", "gdrive"): (
        "https://drive.google.com",
        "Google Drive aberto, Senhor.",
    ),
    ("google docs", "docs"): (
        "https://docs.google.com",
        "Google Docs aberto, Senhor.",
    ),
    ("google sheets", "sheets", "planilhas google"): (
        "https://sheets.google.com",
        "Google Sheets aberto, Senhor.",
    ),
    ("google calendar", "agenda", "calendar"): (
        "https://calendar.google.com",
        "Google Calendar aberto, Senhor.",
    ),
    ("notion",): (
        "https://www.notion.so",
        "Notion aberto, Senhor.",
    ),
    ("trello",): (
        "https://trello.com",
        "Trello aberto, Senhor.",
    ),
    ("canva",): (
        "https://www.canva.com",
        "Canva aberto, Senhor.",
    ),
    ("amazon", "amazon.com"): (
        "https://www.amazon.com.br",
        "Amazon aberta, Senhor.",
    ),
    ("mercado livre", "mercadolivre", "mercado"): (
        "https://www.mercadolivre.com.br",
        "Mercado Livre aberto, Senhor.",
    ),

    # ── Projeto Pessoal / Igreja ──────────────────────────────────────────
    (
        "socialgp", "socialgps",
        "projeto socialgp", "projeto socialgps", "projeto social",
        "projeto da igreja", "plataforma da igreja",
        "social gp", "social gps",
    ): (
        "https://socialgp.discloud.app",
        "SocialGP aberto, Senhor. Plataforma da igreja carregada.",
    ),
    # ── Google Workspace ───────────────────────────────────────────────────
    ("google docs", "docs google", "documento google",
     "novo documento", "criar documento", "gdocs"): (
        "https://docs.new",
        "Google Docs aberto, Senhor. Novo documento criado.",
    ),
    ("google sheets", "sheets google", "planilha google", "gsheets",
     "nova planilha", "criar planilha", "spreadsheet google"): (
        "https://sheets.new",
        "Google Sheets aberta, Senhor. Nova planilha criada.",
    ),
    ("google slides", "slides google", "apresentacao google", "apresentação google",
     "nova apresentacao", "nova apresentação", "powerpoint google", "gslides"): (
        "https://slides.new",
        "Google Slides aberto, Senhor. Nova apresentação criada.",
    ),
    ("google forms", "forms google", "formulario google", "formulário google",
     "novo formulario", "novo formulário", "gforms"): (
        "https://forms.new",
        "Google Forms aberto, Senhor.",
    ),
    ("google meet", "meet", "videochamada google", "video chamada google", "chamada google"): (
        "https://meet.google.com",
        "Google Meet aberto, Senhor.",
    ),
    ("google maps", "maps", "mapa google", "gmaps"): (
        "https://maps.google.com",
        "Google Maps aberto, Senhor.",
    ),
    ("classroom", "google classroom", "sala de aula google",
     "sala de aula virtual", "sala virtual", "google class"): (
        "https://classroom.google.com",
        "Google Classroom aberto, Senhor.",
    ),
    ("google photos", "fotos google", "gphotos"): (
        "https://photos.google.com",
        "Google Fotos aberto, Senhor.",
    ),
    ("google tradutor", "tradutor google", "translate", "google translate",
     "tradução google", "traduzir"): (
        "https://translate.google.com",
        "Google Tradutor aberto, Senhor.",
    ),
    ("youtube studio", "yt studio", "creator studio"): (
        "https://studio.youtube.com",
        "YouTube Studio aberto, Senhor.",
    ),
    ("youtube music", "yt music"): (
        "https://music.youtube.com",
        "YouTube Music aberto, Senhor.",
    ),

    # ── Microsoft Office Online ──────────────────────────────────────────────
    ("office", "office 365", "office365", "microsoft office",
     "office online", "microsoft office online", "microsoft 365"): (
        "https://www.office.com",
        "Microsoft Office 365 aberto, Senhor.",
    ),
    ("word online", "word web", "word na internet", "word online microsoft"): (
        "https://www.office.com/launch/word",
        "Word Online aberto, Senhor.",
    ),
    ("excel online", "excel web", "excel na internet", "excel online microsoft"): (
        "https://www.office.com/launch/excel",
        "Excel Online aberto, Senhor.",
    ),
    ("powerpoint online", "powerpoint web", "power point online",
     "powerpoint na internet", "ppt online"): (
        "https://www.office.com/launch/powerpoint",
        "PowerPoint Online aberto, Senhor.",
    ),
    ("onenote", "onenote online", "one note", "one note online"): (
        "https://www.onenote.com",
        "OneNote aberto, Senhor.",
    ),
    ("onedrive", "one drive", "microsoft onedrive"): (
        "https://onedrive.live.com",
        "OneDrive aberto, Senhor.",
    ),
    ("sharepoint", "share point"): (
        "https://sharepoint.com",
        "SharePoint aberto, Senhor.",
    ),
    ("bing maps", "mapa bing"): (
        "https://www.bing.com/maps",
        "Bing Maps aberto, Senhor.",
    ),

    # ── Canva (subpáginas de criação) ─────────────────────────────────────────
    ("canva apresentacao", "canva apresentação", "apresentacao canva",
     "apresentação canva", "criar apresentacao canva", "slides canva", "canva slides"): (
        "https://www.canva.com/create/presentations/",
        "Criador de apresentações do Canva aberto, Senhor.",
    ),
    ("canva logo", "logo canva", "criar logo canva", "criar logo"): (
        "https://www.canva.com/create/logos/",
        "Criador de logos do Canva aberto, Senhor.",
    ),
    ("canva post", "post canva", "canva instagram", "post instagram canva"): (
        "https://www.canva.com/create/instagram-posts/",
        "Criador de posts do Canva aberto, Senhor.",
    ),
    ("canva video", "video canva", "vídeo canva", "criar video canva"): (
        "https://www.canva.com/create/videos/",
        "Criador de vídeos do Canva aberto, Senhor.",
    ),
    ("canva whiteboard", "lousa canva", "quadro canva", "whiteboard canva"): (
        "https://www.canva.com/create/whiteboards/",
        "Lousa digital do Canva aberta, Senhor.",
    ),
    ("canva curriculo", "canva currículo", "curriculo canva", "currículo canva",
     "criar curriculo canva"): (
        "https://www.canva.com/create/resumes/",
        "Criador de currículos do Canva aberto, Senhor.",
    ),
    ("canva flyer", "flyer canva", "panfleto canva", "criar flyer"): (
        "https://www.canva.com/create/flyers/",
        "Criador de flyers do Canva aberto, Senhor.",
    ),
    ("canva banner", "banner canva", "criar banner"): (
        "https://www.canva.com/create/banners/",
        "Criador de banners do Canva aberto, Senhor.",
    ),
    ("canva thumbnail", "thumbnail canva", "miniatura canva"): (
        "https://www.canva.com/create/youtube-thumbnails/",
        "Criador de thumbnails do Canva aberto, Senhor.",
    ),
    ("canva cartao", "cartao canva", "cartão canva", "canva cartão",
     "cartao de visita canva", "cartão de visita canva"): (
        "https://www.canva.com/create/business-cards/",
        "Criador de cartões do Canva aberto, Senhor.",
    ),}

_APPS = {
    ("bloco de notas", "notepad"): (
        "notepad.exe",
        "TextEdit",
        "Interface de texto aberta, Senhor.",
    ),
    ("calculadora", "calculator", "calc"): (
        "calc.exe",
        "Calculator",
        "Sistemas matemáticos online, Senhor.",
    ),
    ("explorador", "explorer", "arquivos", "pasta"): (
        "explorer.exe",
        "Finder",
        "Explorador de arquivos aberto, Senhor.",
    ),
    ("terminal", "cmd", "powershell", "prompt"): (
        "powershell.exe",
        "Terminal",
        "Terminal aberto, Senhor.",
    ),
    ("word", "word"): (
        "winword.exe",
        "Microsoft Word",
        "Microsoft Word sendo iniciado, Senhor.",
    ),
    ("excel",): (
        "excel.exe",
        "Microsoft Excel",
        "Microsoft Excel sendo iniciado, Senhor.",
    ),
    ("paint",): (
        "mspaint.exe",
        "Paintbrush",
        "Paint aberto, Senhor.",
    ),
    ("vscode", "vs code", "visual studio code"): (
        "code",
        "Visual Studio Code",
        "VS Code sendo iniciado, Senhor.",
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# SUBPÁGINAS DINÂMICAS — pesquisa em sites específicos
# Formato: (regex_compilado, url_template, msg_template, url_encode_query?)
# {q} na URL é substituído pela query (urllib.parse.quote_plus se True)
# {raw} na mensagem é o texto capturado sem encoding
# ══════════════════════════════════════════════════════════════════════════════
_SUBPAGES: list[tuple] = [

    # ── Sub-seções fixas (sem variável — URL direta) ────────────────────────────
    # YouTube histórico
    (re.compile(
        r"hist[oó]rico(?:\s+de\s+(?:pesquisa|busca|visualiz\w+|naveg\w+))?"
        r"(?:\s+(?:do|no|da|de))?\s+youtube",
        re.I),
     "https://www.youtube.com/feed/history",
     "Histórico do YouTube aberto, Senhor.", False),

    (re.compile(
        r"(?:meu\s+)?hist[oó]rico\s+(?:de\s+(?:pesquisa|busca|naveg\w+)\s*)$",
        re.I),
     "https://www.youtube.com/feed/history",
     "Histórico aberto, Senhor.", False),

    # Inscrições YouTube
    (re.compile(
        r"(?:inscri\w+|canais?\s+inscritos?)\s+(?:do|no)\s+youtube",
        re.I),
     "https://www.youtube.com/feed/subscriptions",
     "Inscrições do YouTube abertas, Senhor.", False),

    # Tendências YouTube
    (re.compile(
        r"(?:em\s+alta|tend\w+|trending)\s+(?:do|no)\s+youtube",
        re.I),
     "https://www.youtube.com/feed/trending",
     "Tendências do YouTube abertas, Senhor.", False),

    # Histórico Google
    (re.compile(
        r"hist[oó]rico\s+(?:de\s+(?:pesquisa|busca|naveg\w+)\s+)?(?:do|no)\s+google",
        re.I),
     "https://myactivity.google.com/myactivity",
     "Histórico do Google aberto, Senhor.", False),

    # Política / Termos do Google
    (re.compile(
        r"(?:pol[ií]tica\s+(?:de\s+)?privacidade|privacidade)\s+(?:do\s+)?google",
        re.I),
     "https://policies.google.com/privacy",
     "Política de privacidade do Google aberta, Senhor.", False),

    (re.compile(
        r"termos?\s+(?:de\s+)?(?:uso|servi[çc]o)\s+(?:do\s+)?google",
        re.I),
     "https://policies.google.com/terms",
     "Termos de serviço do Google abertos, Senhor.", False),

    # ── YouTube (pesquisa variável) ────────────────────────────────────────────
    (re.compile(
        r"(?:v[íi]deo|v[íi]deos?|assisti[r]?|ver)\s+(?:de|sobre|do|da|dos|das)?\s+(.+?)"
        r"(?:\s+no\s+youtube)?\s*$", re.I),
     "https://www.youtube.com/results?search_query={q}",
     "Pesquisando '{raw}' no YouTube, Senhor.", True),

    (re.compile(r"canal\s+(?:do|da|de)?\s+(.+?)(?:\s+no\s+youtube)?\s*$", re.I),
     "https://www.youtube.com/results?search_query={q}",
     "Procurando canal '{raw}' no YouTube, Senhor.", True),

    (re.compile(r"pesquisa[r]?\s+(.+?)\s+no\s+youtube\s*$", re.I),
     "https://www.youtube.com/results?search_query={q}",
     "Pesquisando '{raw}' no YouTube, Senhor.", True),

    (re.compile(r"(.+?)\s+no\s+youtube\s*$", re.I),
     "https://www.youtube.com/results?search_query={q}",
     "Pesquisando '{raw}' no YouTube, Senhor.", True),

    # ── Google (busca) ────────────────────────────────────────────────────────
    (re.compile(
        r"(?:pesquisa[r]?|busca[r]?|procura[r]?|googla[r]?|googl[ae])\s+(?:sobre\s+)?(.+?)"
        r"(?:\s+no\s+google)?\s*$", re.I),
     "https://www.google.com/search?q={q}",
     "Pesquisando '{raw}' no Google, Senhor.", True),

    (re.compile(r"(.+?)\s+no\s+google\s*$", re.I),
     "https://www.google.com/search?q={q}",
     "Pesquisando '{raw}' no Google, Senhor.", True),

    # ── Google Maps ───────────────────────────────────────────────────────────
    (re.compile(
        r"(?:rota|dire[çc][aã]o|caminho|como\s+chegar)\s+(?:at[eé]|para|de)?\s+(.+?)\s*$",
        re.I),
     "https://www.google.com/maps/dir//{q}",
     "Traçando rota para '{raw}', Senhor.", True),

    (re.compile(
        r"(?:mapa|localiza[r]?|onde\s+(?:fica|[eé]|est[aá])|busca[r]?\s+no\s+mapa)"
        r"\s+(?:de|do|da)?\s*(.+?)\s*$", re.I),
     "https://www.google.com/maps/search/{q}",
     "Abrindo Google Maps para '{raw}', Senhor.", True),

    # ── Google Tradutor ───────────────────────────────────────────────────────
    (re.compile(
        r"traduz(?:ir|a|e)?\s+(.+?)(?:\s+(?:para|em)\s+\w+)?\s*$", re.I),
     "https://translate.google.com/?text={q}",
     "Traduzindo '{raw}', Senhor.", True),

    # ── Wikipedia ─────────────────────────────────────────────────────────────
    (re.compile(
        r"(?:artigo|p[áa]gina|wiki|defini[çc][aã]o)\s+(?:de|sobre|do|da)?\s+(.+?)"
        r"(?:\s+na?\s+wikipedia)?\s*$", re.I),
     "https://pt.wikipedia.org/wiki/Special:Search/{q}",
     "Pesquisando '{raw}' na Wikipedia, Senhor.", True),

    (re.compile(r"(.+?)\s+na\s+wikipedia\s*$", re.I),
     "https://pt.wikipedia.org/wiki/Special:Search/{q}",
     "Abrindo Wikipedia para '{raw}', Senhor.", True),

    # ── GitHub ────────────────────────────────────────────────────────────────
    (re.compile(
        r"perfil\s+(?:do|da|de)?\s+(.+?)\s+(?:no|do)\s+github\s*$", re.I),
     "https://github.com/{q}",
     "Abrindo perfil '{raw}' no GitHub, Senhor.", False),

    (re.compile(
        r"(?:rep[oó]|reposit[oó]rio)\s+(?:do|da|de)?\s+(.+?)"
        r"(?:\s+(?:no|do)\s+github)?\s*$", re.I),
     "https://github.com/search?q={q}&type=repositories",
     "Procurando repositório '{raw}' no GitHub, Senhor.", True),

    (re.compile(r"(.+?)\s+no\s+github\s*$", re.I),
     "https://github.com/search?q={q}",
     "Pesquisando '{raw}' no GitHub, Senhor.", True),

    # ── Stack Overflow ────────────────────────────────────────────────────────
    (re.compile(
        r"(?:pergunta|d[úu]vida|erro|bug|problema)\s+(?:sobre\s+)?(.+?)"
        r"(?:\s+no\s+stack\s*overflow)?\s*$", re.I),
     "https://stackoverflow.com/search?q={q}",
     "Pesquisando '{raw}' no Stack Overflow, Senhor.", True),

    (re.compile(r"(.+?)\s+no\s+stack\s*overflow\s*$", re.I),
     "https://stackoverflow.com/search?q={q}",
     "Pesquisando '{raw}' no Stack Overflow, Senhor.", True),

    # ── Reddit ────────────────────────────────────────────────────────────────
    (re.compile(
        r"(?:subreddit|comunidade|r/)\s*(?:de|do|da|sobre)?\s+(.+?)"
        r"(?:\s+no\s+reddit)?\s*$", re.I),
     "https://www.reddit.com/r/{q}",
     "Abrindo r/{raw} no Reddit, Senhor.", False),

    (re.compile(r"(.+?)\s+no\s+reddit\s*$", re.I),
     "https://www.reddit.com/search/?q={q}",
     "Pesquisando '{raw}' no Reddit, Senhor.", True),

    # ── Netflix ───────────────────────────────────────────────────────────────
    (re.compile(r"(?:serie|série|filme|show|assistir)\s+(.+?)\s+na\s+netflix\s*$", re.I),
     "https://www.netflix.com/search?q={q}",
     "Pesquisando '{raw}' na Netflix, Senhor.", True),

    (re.compile(r"(.+?)\s+na\s+netflix\s*$", re.I),
     "https://www.netflix.com/search?q={q}",
     "Pesquisando '{raw}' na Netflix, Senhor.", True),

    # ── Spotify ───────────────────────────────────────────────────────────────
    (re.compile(r"(.+?)\s+no\s+spotify\s*$", re.I),
     "https://open.spotify.com/search/{q}",
     "Pesquisando '{raw}' no Spotify, Senhor.", True),

    # ── PyPI ──────────────────────────────────────────────────────────────────
    (re.compile(
        r"(?:pacote|package|biblioteca|lib|m[oó]dulo)\s+(?:python\s+)?(.+?)"
        r"(?:\s+no\s+pypi)?\s*$", re.I),
     "https://pypi.org/search/?q={q}",
     "Pesquisando pacote '{raw}' no PyPI, Senhor.", True),

    (re.compile(r"(.+?)\s+no\s+pypi\s*$", re.I),
     "https://pypi.org/search/?q={q}",
     "Pesquisando '{raw}' no PyPI, Senhor.", True),

    # ── npm ───────────────────────────────────────────────────────────────────
    (re.compile(r"(.+?)\s+no\s+npm\s*$", re.I),
     "https://www.npmjs.com/search?q={q}",
     "Pesquisando '{raw}' no NPM, Senhor.", True),

    # ── Instagram ─────────────────────────────────────────────────────────────
    (re.compile(r"perfil\s+(?:do|da|de)?\s+(.+?)\s+(?:no|do)\s+instagram\s*$", re.I),
     "https://www.instagram.com/{q}/",
     "Abrindo perfil '{raw}' no Instagram, Senhor.", False),

    # ── Twitter/X ─────────────────────────────────────────────────────────────
    (re.compile(r"perfil\s+(?:do|da|de)?\s+(.+?)\s+(?:no|do)\s+(?:twitter|x)\s*$", re.I),
     "https://x.com/{q}",
     "Abrindo perfil '{raw}' no X, Senhor.", False),

    (re.compile(r"(.+?)\s+no\s+(?:twitter|x\.com|x)\s*$", re.I),
     "https://x.com/search?q={q}",
     "Pesquisando '{raw}' no X, Senhor.", True),

    # ── Google Imagens ────────────────────────────────────────────────────────
    (re.compile(
        r"(?:imagem|imagens|foto|fotos|imagem\s+de)\s+(?:de|do|da)?\s*(.+?)"
        r"(?:\s+no\s+google)?\s*$", re.I),
     "https://www.google.com/search?tbm=isch&q={q}",
     "Buscando imagens de '{raw}' no Google, Senhor.", True),

    # ── Canva (busca interna) ─────────────────────────────────────────────────
    (re.compile(r"(?:template|modelo|cria[r]?)\s+(.+?)\s+(?:no\s+)?canva\s*$", re.I),
     "https://www.canva.com/search/templates?q={q}",
     "Pesquisando template '{raw}' no Canva, Senhor.", True),
]

# Mapa de intenção (chave normalizada) → função executora
# Usado pela IA para executar comandos por semântica
_INTENCOES: dict[str, tuple] = {}

# Índice invertido: palavra-chave → (url, msg) — para busca rápida em _buscar_url
_KEYWORDS_SITES: dict[str, tuple[str, str]] = {}


def _registrar_intencoes():
    """Preenche o mapa de intenções e o índice de palavras-chave."""
    for palavras, (url, msg) in _SITES.items():
        for p in palavras:
            _INTENCOES[p] = ("site", url, msg)
            _KEYWORDS_SITES[p.lower()] = (url, msg)
    for palavras, (win, mac, msg) in _APPS.items():
        for p in palavras:
            _INTENCOES[p] = ("app", win, mac, msg)


_registrar_intencoes()

# Chaves disponíveis para o prompt de classificação da IA
INTENCOES_DISPONIVEIS: list[str] = sorted(_INTENCOES.keys())


# ==========================================
# FUNÇÕES PÚBLICAS
# ==========================================

def executar_por_intencao(intencao: str) -> str | None:
    """
    Recebe uma chave de intenção normalizada (ex.: 'youtube', 'calculadora')
    e executa o comando correspondente.

    Retorna a mensagem de confirmação ou None se a intenção não for conhecida.
    """
    dados = _INTENCOES.get(intencao.lower().strip())
    if not dados:
        return None

    if dados[0] == "site":
        _, url, msg = dados
        _abrir_url_navegador_padrao(url)
        return msg

    if dados[0] == "app":
        _, win, mac, msg = dados
        _abrir_app(win=win, mac=mac)
        return msg

    return None


def buscar_subpagina(texto: str) -> tuple[str, str] | None:
    """
    Detecta padrões de subpáginas e pesquisas dinâmicas em sites.
    Suporta dois modos:
      - URL fixa: padrão sem grupo de captura ou sem {q} na URL
      - URL dinâmica: padrão com grupo de captura e {q} na URL
    """
    import urllib.parse
    t = texto.strip()
    for entry in _SUBPAGES:
        pattern, url_tmpl, msg_tmpl, do_quote = entry
        m = pattern.search(t)
        if not m:
            continue
        # Modo URL fixa: sem {q} no template
        if "{q}" not in url_tmpl:
            return url_tmpl, msg_tmpl
        # Modo URL dinâmica: requer grupo de captura
        try:
            raw = m.group(1).strip()
        except IndexError:
            raw = ""
        if not raw or len(raw) < 2:
            continue
        q = urllib.parse.quote_plus(raw) if do_quote else raw.replace(" ", "")
        url = url_tmpl.replace("{q}", q)
        msg = msg_tmpl.replace("{raw}", raw)
        return url, msg
    return None


def abrir_url(url: str) -> str:
    """Abre uma URL no navegador padrão e retorna confirmação."""
    _abrir_url_navegador_padrao(url)
    return f"Site {url} aberto com sucesso, Senhor."


def buscar_site_local(texto: str, exact_only: bool = False) -> tuple[str, str] | None:
    """
    Procura no dicionário interno de sites usando correspondência de palavras-chave.

    Estratégia (por ordem de prioridade):
      1. Correspondência exata da string normalizada
      2. Correspondência como substring (a query contém a keyword ou vice-versa)
         — só executada quando exact_only=False
      3. Correspondência parcial por palavras (todas as palavras da keyword presentes no texto)
         — só executada quando exact_only=False

    Retorna (url, mensagem) ou None se não encontrar.
    Prioriza domínios .com sobre outros quando há empate no score.

    exact_only=True: apenas correspondência exata. Use quando o texto de entrada pode
    ser um nome genérico (ex: "cloud", "projeto") para evitar falsos positivos por substring.
    """
    q = _normalizar(texto)
    if not q:
        return None

    # 1. Exato
    if q in _KEYWORDS_SITES:
        return _KEYWORDS_SITES[q]

    if exact_only:
        return None

    # 2. Substring — ordena por comprimento da keyword (maior = mais específico) e .com primeiro
    # Keywords de 1-2 chars exigem correspondência como palavra completa
    candidatos: list[tuple[int, bool, str, tuple]] = []
    for kw, dados in _KEYWORDS_SITES.items():
        if len(kw) <= 2:
            # Só aceita se for palavra delimitada (ex: " x " ou "x " ou " x")
            padrao = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
            if not re.search(padrao, q):
                continue
        else:
            if kw not in q and q not in kw:
                continue
        pref_com = dados[0].startswith("https://www.") or ".com" in dados[0]
        candidatos.append((len(kw), pref_com, kw, dados))

    if candidatos:
        candidatos.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidatos[0][3]

    # 3. Palavras — todas as palavras da keyword existem na query
    q_palavras = set(q.split())
    for kw, dados in _KEYWORDS_SITES.items():
        kw_palavras = set(kw.split())
        if kw_palavras and kw_palavras.issubset(q_palavras):
            return dados

    return None


def _normalizar(texto: str) -> str:
    """Normaliza texto: remove acentos, minúsculas, prefixos comuns (jarvis, verbos, possessivos)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", texto.lower().strip())
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    # 1. Remove prefixo "Jarvis" e variáveis de chamada
    sem_acento = re.sub(
        r"^(?:jarvis[,.]?\s+|ei\s+jarvis[,.]?\s+|hey\s+jarvis[,.]?\s+"
        r"|oi\s+jarvis[,.]?\s+|e\s+ai\s+jarvis[,.]?\s+|j\s*a\s*r\s*v\s*i\s*s[,.]?\s+)",
        "", sem_acento, flags=re.I,
    )
    # 2. Remove verbos comuns de abertura
    sem_acento = re.sub(
        r"^\s*(abre?|abrir|entra?|entrar|vai\s+para|navega\s+para|acessa?|acessar|"
        r"abre\s+o|abre\s+a|abrir\s+o|abrir\s+a|mostra\s+o|mostra\s+a|quero\s+ver|"
        r"me\s+leva\s+para|vai\s+no|vai\s+na|ir\s+para|ir\s+no|abre?\s+site|"
        r"abrir\s+site|site\s+do|site\s+da|ir\s+em)\s+",
        "", sem_acento, flags=re.I,
    )
    # 3. Remove possessivos e artigos no início que possam ter sobrado
    sem_acento = re.sub(
        r"^(meu|minha|meus|minhas|o\s+meu|a\s+minha)\s+",
        "", sem_acento, flags=re.I,
    )
    # 4. Remove pontuação residual no início/fim e espaços duplos
    sem_acento = re.sub(r"^[\s,.:;!?]+|[\s,.:;!?]+$", "", sem_acento).strip()
    sem_acento = re.sub(r"\s+", " ", sem_acento).strip()
    return sem_acento


# ==========================================
# FUNÇÕES AUXILIARES (privadas)
# ==========================================

def _abrir_app(win: str, mac: str) -> None:
    """
    Abre um aplicativo usando subprocess.Popen (não bloqueia o processo principal).
    Compatível com Windows, macOS e Linux (xdg-open fallback).
    """
    sistema = platform.system()
    try:
        if sistema == "Windows":
            subprocess.Popen([win], shell=False)
        elif sistema == "Darwin":
            subprocess.Popen(["open", "-a", mac])
        else:
            subprocess.Popen(["xdg-open", win])
    except FileNotFoundError:
        pass  # Aplicativo não encontrado; silencia o erro
