# jarvis/memory/triage.py — J.A.R.V.I.S.
# STEP DE DISCERNIMENTO de escrita de memória (roadmap/14): dado um turno,
# decide SE vira memória, em QUAL segmento, com que IMPORTÂNCIA e qual OPERAÇÃO
# (ADD/UPDATE/DELETE/NOOP/PIN) — através de dezenas de situações distintas.
#
# Cascata BARATA (pesquisa A-MAC/CoALA/Mem0/Generative Agents):
#   1. privacidade  → segredo/PII? NOOP + redige (NUNCA persiste senha/token).
#   2. regra (regex PT-BR) → resolve a maioria a custo ~0.
#   3. embedding (MiniLM âncoras por categoria) → desempata o resto.
#   4. (opcional) juiz-LLM → só no incerto, atrás de toggle (default OFF).
# Qualquer exceção → {'remember': False, 'op': 'NOOP'} (nunca quebra o turno).
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import threading
from typing import Optional

# ── Privacidade: segredos NUNCA persistidos; PII marcada ─────────────────────
_SECRET_RE = re.compile(
    r"(senha|password|api[\s_-]?key|token|secret|chave\s+secreta|cvv|"
    r"c[óo]digo\s+(de\s+)?(verifica|2fa|otp)|bearer\s+[\w.\-]+|"
    r"\b\d{13,16}\b|\bsk-[A-Za-z0-9]{10,}\b)", re.I)
_PII_RE = re.compile(
    r"(\b[\w.+-]+@[\w-]+\.[\w.]+\b|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|"
    r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b)", re.I)

# ── Regras regex de alta precedência (categoria → padrão) ────────────────────
# Resolvem a maioria das situações sem embedding. Ordem importa.
_RULES: list[tuple[str, "re.Pattern"]] = [
    ("esquecer",   re.compile(r"\b(esquece|esqueça|esquecer|apaga(r)?|remove(r)?)\b.*\b(isso|aquilo|o que eu disse|da mem[óo]ria|minha|meu)\b", re.I)),
    ("fixar",      re.compile(r"\b(lembra disso|guarda isso|isso é importante|sempre (considere|lembre)|nunca esqueça|n[aã]o esquece)\b", re.I)),
    ("lembrar",    re.compile(r"\b(lembra que|lembre que|anota que|anote que|guarda que|salva que|n[aã]o esquece que)\b", re.I)),
    ("correcao",   re.compile(r"\b(na verdade|me enganei|me confundi|errei|t[áa] errado|n[aã]o é\b.*\bé\b|corrige|corrija|pare de|nunca mais|n[aã]o uso mais|n[aã]o quero mais)\b", re.I)),
    ("identidade", re.compile(r"\b(meu nome é|me chama de|pode me chamar de|eu me chamo|eu sou (o|a)\b|sou (engenheiro|m[ée]dico|advogad|estudante|programador|dev|professor))", re.I)),
    ("preferencia",re.compile(r"\b(prefiro|eu gosto de|n[aã]o gosto de|meu .{0,20}favorit|sempre uso|costumo usar|gosto que|seja (conciso|breve|formal))\b", re.I)),
    ("fato_duravel",re.compile(r"\b(meu endere[çc]o é|minha ide (é|fica)|meu editor( favorito)? é|meu projeto (é|se chama|chama)|meu (telefone|email|e-mail|n[úu]mero) é|minha empresa é|meu time é|eu moro em|moro em|minha cidade é)\b", re.I)),
    ("rotina",     re.compile(r"\b(toda (manh[ãa]|noite|dia)|todo dia|sempre que eu|o jeito que eu|passo a passo|minha rotina|sempre fa[çc]o)\b", re.I)),
    ("decisao",    re.compile(r"\b(vou usar|vamos usar|decidi|optei por|melhor usar|escolhi|decidimos)\b", re.I)),
    ("tarefa",     re.compile(r"\b(me lembra de|tenho (uma )?(reuni[ãa]o|consulta|prova|entrega)|compromisso|prazo|at[ée] (amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|julho|agosto|hoje)|[àa]s \d{1,2}h)\b", re.I)),
]

# Perguntas e small-talk → NUNCA viram fato (NOOP de escrita)
_QUESTION_RE = re.compile(r"^\s*(qual|quais|quando|onde|quem|como|quanto|quantos|que horas|por que|porque|o que (é|sao|são)|cad[êe])\b", re.I)
_SMALLTALK_RE = re.compile(r"^\s*(oi|ol[áa]|e a[íi]|bom dia|boa tarde|boa noite|tchau|at[ée] mais|valeu|obrigad[oa]|beleza|blz|tudo bem|legal|massa|show|nossa|pois é|verdade|entendi|ok|okay|certo|sim|n[aã]o|uhum)\b[\s.!?]*$", re.I)

# ── Categorias → política de escrita ─────────────────────────────────────────
# segment, importance base, operação default. (importância estilo Generative
# Agents / poignancy, normalizada 0-1.)
_CATEGORY_POLICY: dict[str, dict] = {
    "identidade":  {"segment": "semantic",   "importance": 0.85, "op": "ADD",  "pin": False},
    "preferencia": {"segment": "semantic",   "importance": 0.65, "op": "ADD",  "pin": False},
    "decisao":     {"segment": "semantic",   "importance": 0.75, "op": "ADD",  "pin": False},
    "fato_duravel":{"segment": "semantic",   "importance": 0.65, "op": "ADD",  "pin": False},
    "rotina":      {"segment": "procedural", "importance": 0.78, "op": "ADD",  "pin": False},
    "tarefa":      {"segment": "episodic",   "importance": 0.75, "op": "ADD",  "pin": False},
    "correcao":    {"segment": "semantic",   "importance": 0.80, "op": "UPDATE","pin": False},
    "lembrar":     {"segment": "semantic",   "importance": 0.85, "op": "ADD",  "pin": True},
    "fixar":       {"segment": "semantic",   "importance": 0.92, "op": "PIN",  "pin": True},
    "esquecer":    {"segment": None,         "importance": 0.0,  "op": "DELETE","pin": False},
    "emocao":      {"segment": "episodic",   "importance": 0.5,  "op": "ADD",  "pin": False},
    "efemero":     {"segment": None,         "importance": 0.0,  "op": "NOOP", "pin": False},
}

# Âncoras PT-BR por categoria (embedding desempata o que a regra não pegou).
_CATEGORY_ANCHORS: dict[str, list[str]] = {
    "identidade": ["meu nome é joão", "pode me chamar de chefe", "eu sou engenheiro",
                   "trabalho com finanças", "estou em são paulo", "fala comigo em português"],
    "preferencia": ["prefiro tema escuro", "gosto de respostas curtas", "meu editor favorito é o vscode",
                    "minha ide é pycharm", "sempre uso o spotify pra música", "não gosto de emojis"],
    "decisao": ["vou usar numpy em vez de faiss", "decidi seguir com postgres",
                "optei pela arquitetura monolítica", "melhor usar o modelo barato aqui"],
    "rotina": ["toda manhã eu abro o email e o calendário", "sempre que eu pedir um deck, use o tema escuro",
               "minha rotina de deploy é build test push", "o jeito que eu faço backup"],
    "tarefa": ["me lembra da reunião amanhã às 15h", "tenho uma entrega na sexta",
               "preciso terminar o relatório até julho", "compromisso com o cliente segunda"],
    "emocao": ["ficou perfeito adorei", "detestei esse resultado", "você sempre erra isso",
               "gostei muito do trabalho"],
    "efemero": ["que dia bonito hoje", "haha que engraçado", "tô cansado", "e aí beleza",
                "a água ferve a 100 graus", "qual a capital da frança"],
}

_lock = threading.Lock()
_triage = None  # singleton


def _cfg_get(name: str, default):
    try:
        import config as _c
        return getattr(_c, name, default)
    except Exception:
        return default


class _Triage:
    def __init__(self, model) -> None:
        import numpy as np
        self._np = np
        self._model = model
        self._labels: list[str] = []
        texts: list[str] = []
        for cat, exs in _CATEGORY_ANCHORS.items():
            for e in exs:
                self._labels.append(cat)
                texts.append(e)
        self._emb = model.encode(texts, normalize_embeddings=True)

    def _embed_category(self, text: str) -> tuple[str, float, float]:
        """Retorna (categoria, confiança, margem top1-top2)."""
        q = self._model.encode([text], normalize_embeddings=True)
        scores = (self._emb @ q.T).flatten()
        order = self._np.argsort(-scores)
        top1 = int(order[0])
        conf = float(scores[top1])
        margin = conf - (float(scores[int(order[1])]) if len(order) > 1 else 0.0)
        return self._labels[top1], conf, margin

    def decide(self, user_text: str, assistant_text: str = "", *,
               origem: str = "texto") -> dict:
        base = {"remember": False, "segment": None, "category": "efemero",
                "importance": 0.0, "op": "NOOP", "redacted_text": "",
                "confidence": 0.0, "reason": "", "stage": "rule"}
        try:
            text = (user_text or "").strip()
            if not text:
                return base

            # opt-out global
            if _cfg_get("MEMORY_PRIVATE_MODE", False):
                return {**base, "reason": "modo privado"}

            # 1) PRIVACIDADE — segredo nunca persiste
            redact = bool(_cfg_get("MEMORY_PII_REDACT", True))
            if _SECRET_RE.search(text):
                return {**base, "op": "NOOP", "reason": "segredo detectado — não memorizado",
                        "redacted_text": ""}
            safe = _PII_RE.sub("[REDIGIDO]", text) if redact else text

            # 2) descartes óbvios (não viram fato)
            if _SMALLTALK_RE.match(text):
                return {**base, "category": "efemero", "reason": "small-talk"}
            if _QUESTION_RE.match(text):
                return {**base, "category": "efemero", "reason": "pergunta (não afirma fato)"}

            # 3) REGRA (regex) — alta precedência
            cat = None
            for name, rx in _RULES:
                if rx.search(text):
                    cat = name
                    base["stage"] = "rule"
                    break

            # 4) EMBEDDING — desempata o que a regra não pegou
            if cat is None:
                thr = float(_cfg_get("MEMORY_TRIAGE_EMBED_THRESHOLD", 0.45))
                margin_min = float(_cfg_get("MEMORY_TRIAGE_MARGIN", 0.08))
                ecat, conf, margin = self._embed_category(safe)
                base["confidence"] = conf
                base["stage"] = "embed"
                if conf >= thr and margin >= margin_min and ecat != "efemero":
                    cat = ecat
                else:
                    cat = "efemero"

            pol = _CATEGORY_POLICY.get(cat, _CATEGORY_POLICY["efemero"])
            if pol["op"] in ("NOOP",) or pol["segment"] is None and cat != "esquecer":
                return {**base, "category": cat, "op": pol["op"], "reason": "abaixo do limiar / efêmero"}

            # importância heurística (entidade/número/repetição reforçam)
            imp = float(pol["importance"])
            if re.search(r"\b[A-Z][a-zà-ú]{2,}\b", text) or re.search(r"\d", text):
                imp = min(1.0, imp + 0.05)

            # extrai (subject, predicate, value) p/ fatos semânticos quando dá
            subj = pred = val = None
            sv = self._extract_fact(text, cat)
            if sv:
                subj, pred, val = sv

            return {
                "remember": cat != "esquecer",
                "segment": pol["segment"],
                "category": cat,
                "importance": imp,
                "op": pol["op"],
                "redacted_text": safe,
                "subject": subj, "predicate": pred, "value": val,
                "pinned": bool(pol["pin"]),
                "confidence": base["confidence"],
                "reason": f"categoria={cat}",
                "stage": base["stage"],
            }
        except Exception as e:
            return {**base, "reason": f"erro: {e}"}

    @staticmethod
    def _extract_fact(text: str, cat: str):
        """Extração leve de (subject, predicate, value) p/ padrões comuns.
        Retorna None se não conseguir — aí grava-se o texto livre."""
        m = re.search(r"(?:meu nome é|me chama de|pode me chamar de|eu me chamo)\s+(.+)", text, re.I)
        if m:
            return ("nome do usuário", "é", m.group(1).strip(" .!?"))
        m = re.search(r"(?:minha ide é|meu editor( favorito)? é|uso (?:o |a )?)\s*([\w .+-]{2,})", text, re.I)
        if cat in ("identidade", "preferencia") and m:
            return ("editor/IDE", "é", m.group(2).strip(" .!?"))
        m = re.search(r"prefiro\s+(.+)", text, re.I)
        if cat == "preferencia" and m:
            return ("preferência", "é", m.group(1).strip(" .!?"))
        m = re.search(r"(?:meu endereço é)\s+(.+)", text, re.I)
        if m:
            return ("endereço", "é", m.group(1).strip(" .!?"))
        return None


def get_triage(model=None):
    global _triage
    if _triage is None:
        with _lock:
            if _triage is None:
                if model is None:
                    from classifiers import embeddings as _emb
                    model = _emb.get_classifier()._model
                _triage = _Triage(model)
    return _triage
