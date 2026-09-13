# jarvis/agents/registry.py — J.A.R.V.I.S.
# Registro declarativo de SUB-AGENTES de domínio (roadmap/15 Fase 3).
# Um "sub-agente" NÃO é um processo — é um RECORTE: (tools do domínio + um bloco
# curto de prompt). O orquestrador "vira" o sub-agente trocando tools/prompt no
# MESMO motor _pensar_e_agir. As tools de cada domínio são derivadas das camadas
# já existentes em comandos/tool_registry.TOOL_LAYERS (zero duplicação).
# -*- coding: utf-8 -*-
from __future__ import annotations

# domínio → {layers (de TOOL_LAYERS), extra_tools, anchors (PT-BR p/ o roteador),
#            hint (1 linha injetada no prompt do cérebro)}
DOMAINS: dict[str, dict] = {
    "documentos": {
        "layers": ["documentos", "imagem"],
        "extra": ["pesquisa_web", "pesquisa_rapida"],  # pesquisar dados p/ o doc
        "anchors": [
            "gera um pdf", "cria uma apresentação", "monta uma planilha",
            "faz um relatório", "exporta isso pra pdf", "cria um powerpoint",
            "monta slides sobre", "gera uma planilha de excel", "faz um dossiê",
            "gera uma apresentação com os conteúdos", "cria um documento sobre",
            "faz um resumo em pdf", "gera uma imagem de",
        ],
        "hint": "Foco do turno: gerar/editar DOCUMENTOS (pdf/pptx/xlsx) e imagens.",
    },
    "web": {
        "layers": ["web"],
        "extra": [],
        "anchors": [
            "abre o site", "abre o youtube", "pesquisa na web", "procura no google",
            "abre o navegador", "entra no site", "abre o gmail", "busca por",
            "abre o reddit", "abre a wikipedia", "traduz isso", "abre o app",
            "abre o spotify", "abre o discord", "abre o vscode",
        ],
        "hint": "Foco do turno: abrir apps/sites e navegar/pesquisar na web.",
    },
    "midia": {
        "layers": ["midia"],
        "extra": [],
        "anchors": [
            "toca uma música", "coloca uma playlist", "pausa a música",
            "próxima música", "toca no spotify", "coloca um vídeo no youtube",
            "toca o artista", "aumenta o volume da música", "pula essa faixa",
            "que música está tocando", "toca um lofi", "coloca um som pra relaxar",
            "põe uma música pra estudar", "coloca um som ambiente",
        ],
        "hint": "Foco do turno: música e mídia (Spotify/YouTube).",
    },
    "sistema": {
        "layers": ["sistema"],
        "extra": [],
        "anchors": [
            "aumenta o volume", "diminui o brilho", "tira um print",
            "desliga o pc", "reinicia o computador", "abre o terminal",
            "cria um timer", "põe um alarme", "que horas são", "como está o clima",
            "bloqueia a tela", "roda esse comando", "lista os drives",
        ],
        "hint": "Foco do turno: controlar o PC (volume/brilho/timer/terminal/sistema).",
    },
    "mensageria": {
        "layers": ["mensageria"],
        "extra": [],
        "anchors": [
            "manda mensagem pro joão", "envia no whatsapp", "avisa a ana",
            "abre as conversas do discord", "lê as notificações", "responde pra",
            "manda um zap pra", "diz pro pedro que", "abre a dm de",
            "responde a pessoa no discord", "manda mensagem no discord",
            "fala com ele no telegram", "avisa que vou atrasar",
        ],
        "hint": "Foco do turno: enviar mensagens e ver notificações.",
    },
    "visao": {
        "layers": ["visao"],
        "extra": [],
        "anchors": [
            "o que tem na minha tela", "analisa a tela", "olha isso aqui",
            "liga a câmera", "descreve o que você vê", "lê o que está na tela",
        ],
        "hint": "Foco do turno: visão (analisar tela/câmera).",
    },
    "jogos": {
        "layers": ["jogos"],
        "extra": [],
        "anchors": [
            "abre o jogo", "instala o jogo", "quais jogos eu tenho",
            "joga o", "abre a steam e joga", "lista meus jogos",
        ],
        "hint": "Foco do turno: jogos (abrir/instalar/listar).",
    },
}


def domains() -> list[str]:
    return list(DOMAINS.keys())


def tool_names(domain: str) -> list[str]:
    """Nomes de tools do domínio = tools das suas camadas + extras."""
    spec = DOMAINS.get(domain)
    if not spec:
        return []
    try:
        from comandos import tool_registry as _tr
        names = list(_tr.tools_in_layers(spec.get("layers", [])))
    except Exception:
        names = []
    for e in spec.get("extra", []):
        if e not in names:
            names.append(e)
    return names


def hint(domain: str) -> str:
    return (DOMAINS.get(domain, {}) or {}).get("hint", "")
