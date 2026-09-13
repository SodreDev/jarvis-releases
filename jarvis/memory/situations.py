# jarvis/memory/situations.py — J.A.R.V.I.S.
# Situações CURADAS → tool. Frases CURTAS (estilo âncora) que afinam o retrieval
# da camada de skills (jarvis/memory/skills.py) para pedidos ambíguos onde a
# descrição verbosa da tool dilui o embedding — ex.: "gera um pdf de um tema" →
# criar_relatorio (não exportar_pdf); "tira um print" → controle_sistema.
#
# Esta é só a SEMENTE inicial. As situações crescem com o uso real e com a tool
# agregadora (skills.add_situation), que é a "fonte de informação" do orquestrador.
# -*- coding: utf-8 -*-
from __future__ import annotations

# (situação em PT-BR  →  nome EXATO da tool no tool_registry)
CURATED: list[tuple[str, str]] = [
    # ── documentos ──
    ("fazer um pdf sobre um assunto", "criar_relatorio"),
    ("gerar um relatório em pdf de um tema", "criar_relatorio"),
    ("montar uma apresentação de slides", "criar_apresentacao"),
    ("criar um powerpoint sobre um tema", "criar_apresentacao"),
    ("fazer uma planilha de gastos no excel", "criar_planilha"),
    ("converter um documento existente para pdf", "exportar_pdf"),
    ("criar ou gerar uma imagem de algo", "gerar_imagem"),
    # ── sistema ──
    ("tirar um print da tela", "controle_sistema"),
    ("tirar uma captura de tela / screenshot", "controle_sistema"),
    ("ajustar o volume do computador", "controle_sistema"),
    ("rodar um comando no terminal", "comando_terminal"),
    ("criar um alarme para um horário", "criar_alarme"),
    ("criar um timer de contagem regressiva", "criar_timer"),
    ("consultar o clima de uma cidade", "clima"),
    # ── midia ──
    ("tocar uma música ou playlist no spotify", "tocar_musica"),
    ("colocar um som, lofi ou playlist pra focar ou relaxar", "tocar_musica"),
    ("botar uma música de fundo enquanto trabalho", "tocar_musica"),
    ("música ou playlist de estudo, lofi ou foco", "tocar_musica"),
    ("pausar, pular ou retomar a música", "controle_spotify"),
    ("tocar um vídeo no youtube", "reproduzir_youtube"),
    # ── mensageria ──
    ("mandar uma mensagem para um contato", "enviar_mensagem"),
    ("avisar, falar ou dar um recado para alguém", "enviar_mensagem"),
    ("mandar um recado rápido para uma pessoa", "enviar_mensagem"),
    ("ler as notificações pendentes", "ler_notificacoes"),
    # ── web ──
    ("pesquisar na internet sobre um assunto", "pesquisa_web"),
    ("abrir um site no navegador", "abrir_site"),
    ("abrir um aplicativo do computador", "abrir_app"),
    # ── visao ──
    ("ver ou analisar o que está na tela", "analisar_tela"),
    # ── jogos ──
    ("abrir ou jogar um jogo", "abrir_jogo"),
    ("listar os jogos instalados", "listar_jogos"),
    # ── memória / aprendizado ──
    ("aprender ou estudar sobre um tema", "aprender_sobre"),
    ("se especializar num assunto e guardar o conhecimento", "aprender_sobre"),
    ("buscar o que já sei sobre um assunto na memória", "memoria_buscar"),
    ("lembrar um fato durável sobre o Senhor", "memoria_salvar_fato"),
]


def items() -> list[dict]:
    """[{tool, layer, text, kind:'situacao'}] p/ alimentar a camada de skills."""
    try:
        from comandos import tool_registry as tr
        _layer = tr.layer_of
    except Exception:
        def _layer(_n: str) -> str:
            return ""
    out: list[dict] = []
    for sit, tool in CURATED:
        try:
            lay = _layer(tool)
        except Exception:
            lay = ""
        out.append({"tool": tool, "layer": lay, "text": sit, "kind": "situacao"})
    return out
