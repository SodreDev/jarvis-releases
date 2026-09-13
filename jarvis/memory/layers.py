# jarvis/memory/layers.py — J.A.R.V.I.S.
# CAMADAS da memória do orquestrador. Organiza a memória em camadas NOMEADAS, cada
# uma com DESCRIÇÃO e PROPÓSITO ("quando consultar") — p/ o modelo saber ONDE procurar
# e DIFERENCIAR (ex.: a FUNÇÃO "aprender" [camada Ferramentas] ≠ a camada APRENDIZADOS).
# Fachada sobre as fontes existentes (skills + store) + escrita SELETIVA + uma camada
# META auto-descritiva (o "mapa" que o modelo consulta primeiro). Best-effort.
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Optional

_MARKER_RE = re.compile(r"^\s*\[LONGO\]\s*", re.I)


def clean_text(s: str) -> str:
    """Remove marcadores de DISPLAY (ex.: [LONGO]) — instrução de exibição, não
    conteúdo. Sem isso a memória "aprende" o marcador em vez do texto real."""
    return _MARKER_RE.sub("", str(s or "")).strip()


# Registro das camadas. source: ("skills", kind) | ("store", segment[, camada]).
LAYERS: dict[str, dict] = {
    "tools": {
        "name": "Ferramentas", "icon": "🛠️", "color": "#ffb347",
        "desc": "Instruções de cada ferramenta que o JARVIS pode CHAMAR.",
        "purpose": "Consulte para descobrir QUAL função executa uma ação (ex.: 'aprenda X' → ache a tool de pesquisa). NÃO é onde mora o conhecimento.",
        "source": ("skills", "tool"), "writable": False,
    },
    "situacoes": {
        "name": "Situações de uso", "icon": "🎯", "color": "#ff4d6d",
        "desc": "Frases curtas que casam um pedido à ferramenta certa.",
        "purpose": "Consulte para resolver um pedido ambíguo escolhendo a tool correta.",
        "source": ("skills", "situacao"), "writable": True,
    },
    "aprendizagem": {
        "name": "Aprendizados", "icon": "📚", "color": "#00e88a",
        "desc": "Temas que o JARVIS estudou e domina, em subcamadas (básico → aprofundado).",
        "purpose": "Consulte quando perguntarem se ele SABE/conhece algo, ou para responder com CONHECIMENTO aprendido — não para achar uma função.",
        "source": ("store", "semantic", "aprendizagem"), "writable": True,
        "subs": [("basico", "Contextos básicos"), ("aprofundado", "Aprofundado / especialização")],
    },
    "pesquisa": {
        "name": "Pesquisas", "icon": "🔎", "color": "#00d8ff",
        "desc": "Relatórios de pesquisa consolidados (web/agentes).",
        "purpose": "Consulte para fatos buscados; é a entrada de conhecimento novo que vira Aprendizado.",
        "source": ("store", "semantic", "pesquisa"), "writable": True,
    },
    "contexto_chat": {
        "name": "Contexto de chat", "icon": "💬", "color": "#7aa0c8",
        "desc": "Conversas e ações passadas (turnos, artefatos criados).",
        "purpose": "Consulte para continuidade: 'aquele PDF', 'de novo', 'manda pra ele'.",
        "source": ("store", "episodic"), "writable": False,
    },
    "erros": {
        "name": "Erros & lições", "icon": "⚠️", "color": "#ff9f1c",
        "desc": "Erros que o JARVIS cometeu e como evitá-los.",
        "purpose": "Consulte ANTES de agir para PREVER e não repetir um erro (evita alucinação / info incompleta).",
        "source": ("store", "semantic", "erros"), "writable": True,
    },
    "auto": {
        "name": "Memória própria", "icon": "🪪", "color": "#c77dff",
        "desc": "Identidade do JARVIS e do Senhor: persona, preferências.",
        "purpose": "Consulte para manter a persona coerente e respeitar preferências.",
        "source": ("store", "semantic", "auto"), "writable": True,
    },
    "meta": {
        "name": "Como a memória funciona", "icon": "🧭", "color": "#d9e7ff",
        "desc": "Mapa auto-descritivo das camadas: o que cada uma guarda e QUANDO consultar.",
        "purpose": "Consulte PRIMEIRO para saber ONDE procurar e diferenciar uma camada da outra.",
        "source": ("store", "semantic", "meta"), "writable": True,
    },
}

WRITABLE = [k for k, v in LAYERS.items() if v.get("writable")]


# ── leitura das fontes ────────────────────────────────────────────────────────
def _store_records(segment: str, camada: Optional[str] = None) -> list[dict]:
    try:
        from . import store as _s
        st = _s.get_store(); st._ensure_loaded()
        recs = st._seg.get(segment, {}).get("records", []) or []
        if camada is None:
            # só os SEM camada (camada-puros pertencem às suas próprias layers)
            return [r for r in recs if not (r.get("meta", {}) or {}).get("camada")]
        return [r for r in recs if (r.get("meta", {}) or {}).get("camada") == camada]
    except Exception:
        return []


def _skills_records(kind: str) -> list[dict]:
    try:
        from . import skills as _sk
        sk = _sk.get_skills(); sk._ensure_loaded()
        return [r for r in (sk._records or []) if r.get("kind") == kind]
    except Exception:
        return []


def _rec_item(r: dict) -> dict:
    t = clean_text(r.get("text", ""))
    return {"label": t[:48], "text": t,
            "meta": {"fonte": r.get("source", "—"),
                     "importância": r.get("importance", "—")}}


# ── snapshot (para a UI / o agente) ───────────────────────────────────────────
def snapshot(seed: bool = True) -> dict:
    if seed:
        try:
            seed_meta()
        except Exception:
            pass
    layers = []
    for lid, L in LAYERS.items():
        src = L["source"]
        items: list[dict] = []
        subs: list[dict] = []
        if src[0] == "skills":
            for r in _skills_records(src[1]):
                items.append({"label": r.get("tool") or clean_text(r.get("text", ""))[:48],
                              "text": r.get("text", ""),
                              "meta": {"tool": r.get("tool", ""), "domínio": r.get("layer", "")}})
        else:
            seg = src[1]
            camada = src[2] if len(src) > 2 else None
            recs = _store_records(seg, camada)
            if L.get("subs"):
                bys: dict[str, list] = {}
                default_sub = L["subs"][0][0]
                for r in recs:
                    s = (r.get("meta", {}) or {}).get("sub") or default_sub
                    bys.setdefault(s, []).append(r)
                for sid, sname in L["subs"]:
                    srecs = bys.get(sid, [])
                    subs.append({"id": sid, "name": sname, "count": len(srecs),
                                 "items": [_rec_item(r) for r in srecs]})
            else:
                items = [_rec_item(r) for r in recs]
        count = sum(s["count"] for s in subs) if subs else len(items)
        layers.append({"id": lid, "name": L["name"], "icon": L["icon"], "color": L["color"],
                       "desc": L["desc"], "purpose": L["purpose"],
                       "writable": bool(L.get("writable")), "count": count,
                       "subs": subs, "items": items})
    return {"layers": layers}


# ── escrita SELETIVA (conteúdo COMPLETO, marcador removido) ───────────────────
def save(layer: str, text: str, *, sub: Optional[str] = None,
         importance: float = 0.7, **meta) -> Optional[int]:
    """Grava numa camada GRAVÁVEL (só as de WRITABLE). Armazena o conteúdo
    COMPLETO (sem truncar) e sem o marcador [LONGO] — para realmente "aprender"."""
    L = LAYERS.get(layer)
    if not L or not L.get("writable"):
        return None
    text = clean_text(text)
    if not text:
        return None
    src = L["source"]
    try:
        if src[0] == "skills":
            from . import skills as _sk
            ok = _sk.get_skills().add_situation(text, tool=meta.get("tool", ""),
                                                layer=meta.get("dominio", ""))
            return 1 if ok else None
        from . import store as _s
        seg = src[1]
        camada = src[2] if len(src) > 2 else layer
        m = {"camada": camada}
        if sub:
            m["sub"] = sub
        m.update({k: v for k, v in meta.items() if v is not None})
        return _s.get_store().add(seg, text, importance=importance, source=layer, meta=m)
    except Exception:
        return None


def seed_meta() -> int:
    """Semeia a camada META (1x) com o mapa auto-descritivo das camadas."""
    try:
        if _store_records("semantic", "meta"):
            return 0
        n = 0
        guide = ("MAPA DA MEMÓRIA — consulte META primeiro para saber ONDE procurar. "
                 "Diferencie a FUNÇÃO de uma ação (camada Ferramentas) da camada de "
                 "CONHECIMENTO (Aprendizados): se pedirem para 'aprender', use a Ferramenta "
                 "de pesquisa; se perguntarem se você 'sabe' algo, consulte Aprendizados. "
                 "Antes de responder, PREVEJA a resposta e cheque Erros & lições para não "
                 "repetir falhas, não alucinar e não responder com info incompleta.")
        if save("meta", guide, importance=0.95):
            n += 1
        for lid, L in LAYERS.items():
            if lid == "meta":
                continue
            if save("meta", f"Camada '{L['name']}' ({lid}): {L['desc']} {L['purpose']}",
                    importance=0.85, alvo=lid):
                n += 1
        return n
    except Exception:
        return 0
