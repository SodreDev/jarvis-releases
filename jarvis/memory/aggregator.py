# jarvis/memory/aggregator.py — J.A.R.V.I.S.
# Tool AGREGADORA: pesquisa um assunto (web quando preciso, dimensionada à demanda),
# CONSOLIDA os relatos de tools/pesquisa e MEMORIZA nas camadas (Pesquisas →
# Aprendizados). É a "fonte de informação" do orquestrador — adiciona conhecimento
# que vira nó nas camadas e pode ser consultado depois. Best-effort.
# -*- coding: utf-8 -*-
from __future__ import annotations


def _buscar(query: str, app) -> str:
    """Reusa a tool de pesquisa web existente (DuckDuckGo) via dispatch. Limpa
    o marcador [LONGO]. Retorna '' em erro/vazio (o chamador decide)."""
    if app is None or not (query or "").strip():
        return ""
    try:
        from comandos import tool_registry as _tr
        res = _tr.dispatch("pesquisa_web", {"query": query}, app)
    except Exception as e:
        return f"(falha na pesquisa: {e})"
    from . import layers as _lay
    txt = _lay.clean_text(res)
    return "" if txt.startswith("ERRO") else txt


def aprender_sobre(assunto: str, profundidade: str = "basico", *,
                   app=None, buscar: bool = True, conteudo: str = "") -> dict:
    """Pesquisa + MEMORIZA um assunto nas camadas.

    - profundidade: 'basico' (1 busca, visão geral) | 'aprofundado' (várias
      sub-buscas, p/ especializar). Dimensiona o tamanho guardado à demanda.
    - conteudo: texto já pronto a memorizar (pula a busca) — p/ agregar relatos
      de outros agentes/tools.
    Grava na camada Pesquisas (relato bruto) e Aprendizados (subcamada por
    profundidade). Retorna {ok, assunto, sub, chars, ids, resumo|erro}.
    """
    from . import layers as _lay
    assunto = (assunto or "").strip()
    if not assunto:
        return {"ok": False, "erro": "assunto vazio"}
    sub = "aprofundado" if str(profundidade).lower().startswith("aprof") else "basico"

    partes: list[str] = []
    if conteudo and conteudo.strip():
        partes.append(_lay.clean_text(conteudo))
    elif buscar:
        queries = [assunto]
        if sub == "aprofundado":
            queries += [f"{assunto} — explicação detalhada",
                        f"{assunto} — exemplos e aplicações práticas"]
        for q in queries:
            t = _buscar(q, app)
            if t:
                partes.append(t)

    corpo = "\n\n".join(p for p in partes if p).strip()
    if not corpo:
        return {"ok": False, "erro": "sem conteúdo (pesquisa vazia/indisponível)",
                "assunto": assunto}

    # Dimensiona à demanda: básico mais curto, aprofundado guarda mais.
    cap = 6000 if sub == "aprofundado" else 2500
    if len(corpo) > cap:
        corpo = corpo[:cap].rsplit(" ", 1)[0] + " …"

    pid = _lay.save("pesquisa", f"{assunto}\n{corpo}", assunto=assunto)
    aid = _lay.save("aprendizagem", f"[{assunto}] {corpo}", sub=sub, assunto=assunto)

    nome_prof = "aprofundado" if sub == "aprofundado" else "básico"
    return {
        "ok": bool(aid or pid), "assunto": assunto, "sub": sub, "chars": len(corpo),
        "ids": {"pesquisa": pid, "aprendizagem": aid},
        "resumo": (f"Aprendi sobre '{assunto}' ({nome_prof}, {len(corpo)} caracteres) "
                   f"e guardei nos Aprendizados, Senhor."),
    }
