#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/nila_corpus.py — gera o CORPUS DE TREINO das ferramentas do JARVIS para o
modelo local (Nila), Fase B2 do orquestrador local.
Ver planning/ESCOPO-NILA-ORQUESTRADORA-2026-06-27.md (PARTE 2 · Fase B2).

POR QUÊ
-------
Na B1 a ponte `_orquestrar_nila` (main.py) já EXECUTA ações `{"acao":"<nome>", ...}`
localmente — mas a Nila só conhece o vocabulário DELA. A B2 ensina o vocabulário do
JARVIS: este script lê o `tool_registry` + situações curadas e emite um texto de
treino com os nomes EXATOS das tools do JARVIS + params reais + exemplos "pedido →
ação". O dono treina a Nila nesse texto; ela passa a emitir os nomes do JARVIS direto
e a ponte (forward-compat) despacha SEM mapa novo.

DIVERSIDADE (lição do 1º treino, 2026-06-27)
--------------------------------------------
O 1º corpus era repetitivo (5× idêntico, args="...") → a Nila DECOROU a sequência e
cuspia o placeholder "X" em vez do argumento real. Correções aqui:
  • ARGS REAIS E VARIADOS: cada tool tem paráfrases × um pool de valores reais → ela
    aprende que o param é um SLOT a copiar do pedido (não a letra "X").
  • MAIS PARÁFRASES por tool → acerta a tool certa (não a vizinha).
  • EMBARALHADO (seed fixo, reprodutível) → não decora a ordem.

LIMITES (de propósito)
----------------------
- NÃO documenta a arquitetura interna da Nila. Só o formato PÚBLICO `{"acao":...}`.
- Determinístico (seed fixo), sem rede e sem LLM. OUTPUT gitignored (data/nila/).

USO
---
  .venv\\Scripts\\python.exe tools\\nila_corpus.py              # gera data/nila/corpus_tools_jarvis.txt
  .venv\\Scripts\\python.exe tools\\nila_corpus.py --out X.txt   # caminho custom
  .venv\\Scripts\\python.exe tools\\nila_corpus.py --stats       # só conta (não escreve)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "nila" / "corpus_tools_jarvis.txt"
_SEED = 1337  # embaralhamento reprodutível

# ── Exemplos RICOS por tool: paráfrases (slot {x}) × pool de argumentos REAIS ──
# O `param` é VALIDADO contra o schema em runtime (se não existir, cai p/ o primário).
_TOOL_EXAMPLES: dict[str, dict] = {
    "pesquisa_web": {
        "param": "query",
        "phrasings": ["pesquisa sobre {x}", "busca na web {x}", "procura informação sobre {x}",
                      "o que é {x}", "me explica {x}", "pesquisa na internet {x}",
                      "quero saber sobre {x}", "dá uma pesquisada em {x}"],
        "args": ["fotossíntese", "a história de Roma", "o preço do bitcoin hoje", "como funciona um motor a diesel",
                 "inteligência artificial", "a teoria da relatividade", "a Segunda Guerra Mundial",
                 "quem foi Santos Dumont", "o que causa as marés", "energia nuclear"],
    },
    "comando_terminal": {
        "param": "comando",
        "phrasings": ["roda o comando {x}", "executa {x}", "roda {x} no terminal",
                      "manda um {x}", "executa o comando {x} aí"],
        "args": ["dir", "ipconfig", "ping google.com", "tasklist", "whoami", "ipconfig /all",
                 "echo ola", "systeminfo", "ping 8.8.8.8"],
    },
    "criar_relatorio": {
        "param": "tema",
        "phrasings": ["faz um pdf sobre {x}", "gera um relatório de {x}", "monta um relatório sobre {x}",
                      "cria um documento sobre {x}", "escreve um relatório de {x}", "faz um relatório sobre {x}"],
        "args": ["energia solar", "a Amazônia", "o sistema solar", "a Revolução Francesa",
                 "mudanças climáticas", "a história do Brasil", "o corpo humano", "a cultura japonesa"],
    },
    "criar_apresentacao": {
        "param": "tema",
        "phrasings": ["monta uma apresentação sobre {x}", "faz uns slides de {x}",
                      "cria um powerpoint sobre {x}", "prepara uma apresentação de {x}"],
        "args": ["o aquecimento global", "marketing digital", "a Grécia antiga", "células-tronco",
                 "o ciclo da água", "fontes de energia renovável"],
    },
    "criar_planilha": {
        "param": "tema",
        "phrasings": ["faz uma planilha de {x}", "cria uma planilha pra {x}", "monta uma planilha de {x}"],
        "args": ["gastos do mês", "controle de estoque", "notas dos alunos", "orçamento da viagem",
                 "horas trabalhadas"],
    },
    "tocar_musica": {
        "param": "query",
        "phrasings": ["toca {x}", "põe {x} pra tocar", "coloca um som de {x}", "bota {x}", "toca uma de {x}"],
        "args": ["lofi pra focar", "rock dos anos 80", "MPB", "playlist de estudo", "jazz tranquilo",
                 "Pink Floyd", "música clássica", "pagode"],
    },
    "clima": {
        "param": "cidade",
        "phrasings": ["como está o clima em {x}", "qual a previsão pra {x}", "vai chover em {x}",
                      "me diz o tempo em {x}", "clima de {x}"],
        "args": ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Salvador", "Recife", "Manaus"],
    },
    "aprender_sobre": {
        "param": "assunto",
        "phrasings": ["aprende sobre {x}", "estuda {x} e guarda", "se especializa em {x}",
                      "pesquisa a fundo {x} e memoriza"],
        "args": ["redes neurais", "a fotossíntese", "o mercado de ações", "história da arte",
                 "programação em Python", "economia comportamental"],
    },
    "analisar_tela": {
        "param": "pergunta",
        "phrasings": ["olha minha tela e me diz {x}", "vê o que tem na tela sobre {x}",
                      "analisa a tela: {x}"],
        "args": ["o que é esse erro", "qual app está aberto", "o que diz essa mensagem",
                 "que site é esse"],
    },
    "abrir_app": {
        "param": "nome",
        "phrasings": ["abre o {x}", "abre o aplicativo {x}", "inicia o {x}", "roda o programa {x}"],
        "args": ["Spotify", "Word", "calculadora", "bloco de notas", "Excel", "Chrome", "Discord"],
    },
    "abrir_site": {
        "param": "url_ou_query",
        "phrasings": ["abre o site {x}", "abre {x} no navegador", "entra no {x}", "vai pra {x}"],
        "args": ["youtube.com", "github.com", "wikipedia", "gmail", "o site da NASA"],
    },
    "reproduzir_youtube": {
        "param": "query",
        "phrasings": ["toca no youtube {x}", "põe um vídeo de {x}", "abre no youtube {x}"],
        "args": ["tutorial de violão", "documentário sobre o espaço", "show do Coldplay",
                 "como fazer pão", "lofi hip hop"],
    },
    "gerar_imagem": {
        "param": "prompt",
        "phrasings": ["gera uma imagem de {x}", "cria uma imagem de {x}", "desenha {x}", "faz uma arte de {x}"],
        "args": ["um gato astronauta", "uma praia ao pôr do sol", "uma cidade futurista",
                 "um dragão de fogo", "uma floresta encantada"],
    },
    "criar_alarme": {
        "param": "horario",
        "phrasings": ["põe um alarme pra {x}", "me acorda às {x}", "cria um alarme às {x}"],
        "args": ["7 da manhã", "06:30", "meio-dia", "14h", "às 8 horas"],
    },
}

# Multi-param (preenche >1 argumento real) — só os params que existirem no schema entram.
_MULTI: list[tuple[str, str, dict]] = [
    ("manda mensagem pro João dizendo que vou chegar atrasado", "enviar_mensagem",
     {"destinatario": "João", "mensagem": "vou chegar atrasado"}),
    ("avisa a Maria no whatsapp que a reunião foi cancelada", "enviar_mensagem",
     {"destinatario": "Maria", "mensagem": "a reunião foi cancelada", "app": "whatsapp"}),
    ("fala pro Pedro que o almoço está pronto", "enviar_mensagem",
     {"destinatario": "Pedro", "mensagem": "o almoço está pronto"}),
    ("manda pra Ana no discord um feliz aniversário", "enviar_mensagem",
     {"destinatario": "Ana", "mensagem": "feliz aniversário", "app": "discord"}),
]


def _load_fns() -> dict:
    """nome → function-spec (OpenAI tools, formato NÃO compacto p/ a mente ver o uso)."""
    sys.path.insert(0, str(ROOT))
    from comandos import tool_registry as tr  # noqa: E402
    fns: dict = {}
    for s in tr.to_openai_tools():
        fn = s.get("function", {}) if isinstance(s, dict) else {}
        name = fn.get("name", "")
        if name:
            fns[name] = fn
    return fns


def _load_curated() -> list[tuple[str, str]]:
    try:
        from jarvis.memory import situations as _sit  # noqa: E402
        return list(_sit.CURATED)
    except Exception as e:
        print(f"[nila_corpus] situações indisponíveis: {e}")
        return []


def _props(fn: dict) -> list[str]:
    return list(((fn.get("parameters") or {}).get("properties") or {}).keys())


def _primary_param(fn: dict) -> str | None:
    params = fn.get("parameters") or {}
    req = params.get("required") or []
    props = _props(fn)
    if req:
        return req[0]
    return props[0] if props else None


def _first_sentence(desc: str, limit: int = 160) -> str:
    desc = " ".join((desc or "").split())
    for sep in (". ", " — ", "; "):
        i = desc.find(sep)
        if 0 < i <= limit:
            return desc[:i]
    return desc[:limit]


def _acao_json(tool: str, **kw) -> str:
    obj = {"acao": tool}
    obj.update(kw)
    # separators=(", ", ":") casa o byte-pattern do FERRAMENTAS.md da Nila
    # ({"acao":"x", "p":"..."}, sem espaço após ':') — consistência p/ modelo byte-level.
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ":"))


def build_corpus() -> tuple[str, dict]:
    fns = _load_fns()
    curated = _load_curated()
    rng = random.Random(_SEED)

    out: list[str] = []
    out.append("# Ferramentas do JARVIS — o vocabulário de agir")
    out.append("")
    out.append('A mente pode AGIR no JARVIS. Formato de ação: {"acao":"<nome>", ...}.')
    out.append("Quando o Senhor pede algo, ela responde com a ação certa em JSON e nada mais.")
    out.append("")

    # ── 1. Catálogo de tools (nome + 1ª frase + params reais + exemplo) ───────
    out.append("## Ferramentas")
    n_tools = 0
    for name in sorted(fns):
        fn = fns[name]
        props = _props(fn)
        desc = _first_sentence(fn.get("description", ""))
        plist = ", ".join(props) if props else "sem parâmetros"
        out.append(f"- **{name}** — {desc} (parâmetros: {plist}).")
        if props:
            ex = {p: "..." for p in props[:3]}
            out.append(f"  - exemplo: {_acao_json(name, **ex)}")
        else:
            out.append(f"  - exemplo: {_acao_json(name)}")
        n_tools += 1

    # ── 2. Exemplos DIVERSOS pedido→ação (paráfrases × args reais, embaralhado) ─
    pairs: list[tuple[str, str]] = []  # (linha "Senhor:", linha ação)
    n_div = 0
    for tool, spec in _TOOL_EXAMPLES.items():
        fn = fns.get(tool)
        if not fn:
            continue
        props = _props(fn)
        param = spec["param"] if spec["param"] in props else _primary_param(fn)
        for phr in spec["phrasings"]:
            for arg in spec["args"]:
                phrase = phr.format(x=arg)
                act = _acao_json(tool, **({param: arg} if param else {}))
                pairs.append((f"Senhor: {phrase}", act))
                n_div += 1
    # multi-param
    n_multi = 0
    for phrase, tool, kw in _MULTI:
        fn = fns.get(tool)
        if not fn:
            continue
        props = _props(fn)
        kw2 = {k: v for k, v in kw.items() if k in props}
        if not kw2:  # nenhum param bateu com o schema → usa o primário c/ a 1ª frase
            prim = _primary_param(fn)
            if prim:
                kw2 = {prim: next(iter(kw.values()))}
        pairs.append((f"Senhor: {phrase}", _acao_json(tool, **kw2)))
        n_multi += 1

    rng.shuffle(pairs)  # embaralha p/ não decorar a sequência
    out.append("")
    out.append("## Pedidos do Senhor → ação")
    for senhor, act in pairs:
        out.append(senhor)
        out.append(act)
        out.append("")

    # ── 3. Situações curadas (mais paráfrases; param primário = slot) ─────────
    out.append("## Outras formas de pedir")
    n_sit = 0
    for phrase, tool in curated:
        fn = fns.get(tool)
        if not fn:
            continue
        primary = _primary_param(fn)
        out.append(f"Senhor: {phrase}")
        out.append(_acao_json(tool, **({primary: "..."} if primary else {})))
        out.append("")
        n_sit += 1

    text = "\n".join(out).rstrip() + "\n"
    stats = {
        "tools": n_tools,
        "exemplos_diversos": n_div,
        "exemplos_multi": n_multi,
        "exemplos_curados": n_sit,
        "bytes": len(text.encode("utf-8")),
    }
    return text, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera o corpus de treino das tools do JARVIS p/ a Nila (B2).")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="arquivo de saída (default: data/nila/corpus_tools_jarvis.txt)")
    ap.add_argument("--stats", action="store_true", help="só conta e mostra uma amostra; não escreve")
    args = ap.parse_args()

    text, stats = build_corpus()
    print(f"[nila_corpus] {stats['tools']} tools · {stats['exemplos_diversos']} diversos · "
          f"{stats['exemplos_multi']} multi-param · {stats['exemplos_curados']} curados · {stats['bytes']} bytes")

    if args.stats:
        lines = text.splitlines()
        sample = "\n".join(lines[:6] + ["..."] + lines[60:78])
        print("\n--- amostra ---\n" + sample + "\n--- ... ---")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"[nila_corpus] escrito: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
