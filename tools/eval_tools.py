# tools/eval_tools.py — J.A.R.V.I.S.
# Harness de avaliação OFFLINE (sem GUI) do DISCERNIMENTO de memória, do
# ROTEAMENTO de domínio e da RECUPERAÇÃO SEMÂNTICA de tools (SkillMemory) —
# estilo BFCL. Roda só com o MiniLM (zero custo de LLM).
#
# Uso:
#   .venv/Scripts/python.exe tools/eval_tools.py             # eval + gate (CI)
#   .venv/Scripts/python.exe tools/eval_tools.py --calibrate # sweep thr×margem
# Casos extras (opcional): data/eval/triage_cases.jsonl
#   {"text": "...", "remember": true, "segment": "semantic", "secret": false}
#
# Métricas: precisão/recall/F1 de lembrar-vs-ignorar, acurácia de segmento,
# TAXA DE VAZAMENTO DE SEGREDO (deve ser 0), acurácia do roteador de domínio,
# e RECALL@k da SkillMemory (a tool certa aparece no top-k?). Sai com código !=0
# se vazar segredo ou se alguma métrica cair abaixo do mínimo — pronto p/ CI.
#
# NOTA (pesquisa 2026-06-26, Gorilla 2305.15334): um retriever RUIM é PIOR que
# mandar todas as tools. Por isso a recall@k é GATE: só ligar SKILL_MEMORY_ENABLED
# (etapa 2 = plugar no _filter_tools_for_text) depois que ela passar aqui.
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Gates de CI (mínimos de aprovação) ────────────────────────────────────────
_MIN_F1 = 0.80
_MIN_SEG = 0.80
_MIN_ROUTER = 0.80
_MIN_SKILL_RECALL = 0.85   # recall@k da SkillMemory (gate do Gorilla)

# Conjunto-ouro embutido (cobre as categorias da tabela de discernimento).
# remember=False → deve ser IGNORADO (efêmero/pergunta/saudação/segredo).
_GOLD: list[dict] = [
    # ── conversa / efêmero → NÃO lembrar (o requisito do usuário) ──
    {"text": "oi, bom dia!", "remember": False},
    {"text": "haha que engraçado isso", "remember": False},
    {"text": "tô meio cansado hoje", "remember": False},
    {"text": "valeu, obrigado", "remember": False},
    {"text": "que dia bonito lá fora", "remember": False},
    {"text": "qual a capital da França?", "remember": False},
    {"text": "qual o meu nome mesmo?", "remember": False},
    {"text": "quanto é 2 mais 2?", "remember": False},
    # ── identidade / preferência / fato → lembrar (semantic) ──
    {"text": "meu nome é João", "remember": True, "segment": "semantic"},
    {"text": "pode me chamar de chefe", "remember": True, "segment": "semantic"},
    {"text": "sou engenheiro de software", "remember": True, "segment": "semantic"},
    {"text": "prefiro tema escuro e respostas curtas", "remember": True, "segment": "semantic"},
    {"text": "minha IDE é o VS Code", "remember": True, "segment": "semantic"},
    {"text": "meu endereço é Rua das Flores, 123", "remember": True, "segment": "semantic"},
    {"text": "vou usar postgres em vez de mysql no projeto", "remember": True, "segment": "semantic"},
    # ── rotina → procedural ──
    {"text": "toda manhã eu abro o email e o calendário", "remember": True, "segment": "procedural"},
    {"text": "sempre que eu pedir um deck, use o tema escuro", "remember": True, "segment": "procedural"},
    # ── tarefa → episodic ──
    {"text": "me lembra da reunião amanhã às 15h", "remember": True, "segment": "episodic"},
    # ── correção → atualizar (semantic) ──
    {"text": "na verdade não é Ana, é Anna", "remember": True, "segment": "semantic"},
    # ── pedido explícito de lembrar ──
    {"text": "lembra que eu moro em São Paulo", "remember": True, "segment": "semantic"},
    # ── SEGREDOS → NUNCA lembrar (vazamento deve ser 0) ──
    {"text": "minha senha do banco é 1234abcd", "remember": False, "secret": True},
    {"text": "o token é sk-abc123def456ghi789", "remember": False, "secret": True},
    {"text": "meu cartão é 4111 1111 1111 1111", "remember": False, "secret": True},
]

# ── Roteador de domínio (sub-agentes, roadmap/15 Fase 3) ──────────────────────
# Paráfrases PT-BR dos 7 domínios + casos de FRONTEIRA (overlap web×midia,
# sistema×midia) + conversa→None. Serve para CALIBRAR threshold/margem antes de
# tornar AGENT_SUBAGENTS default.
_ROUTER_GOLD: list[tuple[str, str | None]] = [
    # ── documentos ──
    ("gere uma apresentação powerpoint do enem", "documentos"),
    ("cria uma planilha de gastos", "documentos"),
    ("faz um relatório em pdf", "documentos"),
    ("monta uns slides sobre a revolução francesa", "documentos"),
    ("exporta esse texto pra pdf", "documentos"),
    ("preciso de um dossiê sobre o cliente", "documentos"),
    ("gera uma imagem de um gato astronauta", "documentos"),
    # ── midia ──
    ("toca uma música no spotify", "midia"),
    ("pula essa faixa", "midia"),
    ("coloca uma playlist relaxante", "midia"),
    ("põe um lofi pra estudar", "midia"),
    ("que música tá tocando agora", "midia"),
    ("aumenta o volume da música no spotify", "midia"),  # fronteira sistema×midia
    # ── web ──
    ("abre o youtube", "web"),
    ("pesquisa na web sobre física quântica", "web"),
    ("procura no google quem descobriu o brasil", "web"),
    ("abre o gmail", "web"),
    ("entra no site da receita federal", "web"),
    ("traduz essa frase pro inglês", "web"),
    ("abre o spotify", "web"),                            # fronteira web×midia (abrir≠tocar)
    # ── sistema ──
    ("tira um print da tela", "sistema"),
    ("que horas são", "sistema"),
    ("põe um alarme pras 7 da manhã", "sistema"),
    ("aumenta o brilho", "sistema"),
    ("como tá o clima hoje", "sistema"),
    ("cria um timer de 10 minutos", "sistema"),
    ("bloqueia a tela", "sistema"),
    # ── mensageria ──
    ("manda mensagem pro joão no whatsapp", "mensageria"),
    ("avisa a ana que vou chegar atrasado", "mensageria"),
    ("lê minhas notificações", "mensageria"),
    ("responde o pedro no discord", "mensageria"),
    # ── visao ──
    ("o que tem na minha tela", "visao"),
    ("analisa o que tá aparecendo aqui", "visao"),
    ("descreve o que você vê na câmera", "visao"),
    # ── jogos ──
    ("abre a steam e joga cs", "jogos"),
    ("quais jogos eu tenho instalados", "jogos"),
    ("instala o stardew valley", "jogos"),
    # ── conversa/ambíguo → None (fallback, não escopar) ──
    ("me conta uma piada", None),
    ("tô meio cansado hoje", None),
    ("bom dia, tudo bem?", None),
    ("o que você acha disso?", None),
    ("obrigado, valeu", None),
]

# ── SkillMemory (recuperação semântica de tools) ──────────────────────────────
# (query → CONJUNTO de tools aceitáveis). Recall = (aceitáveis ∩ top-k) != ∅.
# Conjuntos (em vez de 1 tool) porque alguns pedidos têm >1 tool válida (ex.:
# "abre o youtube" pode ser navegador OU reproduzir_youtube). Nomes reais do
# comandos/tool_registry.py (45 tools).
_SKILL_GOLD: list[tuple[str, set[str]]] = [
    ("toca uma música no spotify", {"tocar_musica", "controle_spotify"}),
    ("pula essa faixa", {"controle_spotify"}),
    ("aumenta o volume da música", {"controle_spotify", "controle_audio_sistema"}),
    ("que música tá tocando agora", {"controle_spotify"}),
    ("põe um lofi pra estudar", {"tocar_musica", "controle_spotify"}),
    ("toca o trailer de um filme no youtube", {"reproduzir_youtube"}),
    ("abre o youtube", {"controle_navegador", "abrir_site", "reproduzir_youtube"}),
    ("pesquisa na web sobre física quântica", {"pesquisa_web", "pesquisa_rapida"}),
    ("procura no google quem descobriu o brasil", {"pesquisa_web", "pesquisa_rapida"}),
    ("abre o gmail", {"abrir_site", "controle_navegador"}),
    ("abre o aplicativo do spotify", {"abrir_app"}),
    ("traduz essa frase pro inglês", {"traduzir"}),
    ("põe um alarme pras 7 da manhã", {"criar_alarme"}),
    ("cria um timer de 10 minutos", {"criar_timer"}),
    ("como tá o clima hoje", {"clima"}),
    ("aumenta o brilho da tela", {"controle_sistema", "controle_ambiente"}),
    ("manda mensagem pro joão no whatsapp", {"enviar_mensagem"}),
    ("avisa a ana que vou chegar atrasado", {"enviar_mensagem"}),
    ("lê minhas notificações", {"ler_notificacoes"}),
    ("responde o pedro no discord", {"enviar_mensagem", "abrir_dm_discord"}),
    ("o que tem na minha tela agora", {"analisar_tela"}),
    ("descreve o que você vê na câmera", {"controle_visao", "analisar_tela"}),
    ("abre a steam e joga cs", {"abrir_jogo"}),
    ("quais jogos eu tenho instalados", {"listar_jogos"}),
    ("instala o stardew valley", {"instalar_jogo"}),
    ("gera uma apresentação de powerpoint sobre o enem", {"criar_apresentacao"}),
    ("cria uma planilha de gastos", {"criar_planilha"}),
    ("faz um relatório em pdf sobre vendas", {"criar_relatorio", "exportar_pdf"}),
    ("exporta esse documento pra pdf", {"exportar_pdf"}),
    ("gera uma imagem de um gato astronauta", {"gerar_imagem"}),
    ("aprende a fundo sobre buracos negros", {"aprender_sobre"}),
    ("o que você já sabe sobre mim", {"memoria_buscar"}),
    ("abre o terminal e roda um comando", {"comando_terminal"}),
    ("lista os drives do meu pc", {"listar_drives"}),
    ("acha a pasta dos meus projetos", {"procurar_pasta"}),
]


def _load_extra() -> list[dict]:
    p = _ROOT / "data" / "eval" / "triage_cases.jsonl"
    out = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def _eval_router(thr: float, mgn: float, erros: list[str]) -> float:
    """Acurácia do roteador de domínio sob (thr, mgn). Anota divergências."""
    try:
        from jarvis.agents import router as _R
    except Exception as e:
        erros.append(f"router indisponível: {e}")
        return 1.0
    r_ok = r_tot = 0
    for txt, exp in _ROUTER_GOLD:
        r_tot += 1
        dom, conf, margin = _R.route(txt)
        routed = dom if (dom and conf >= thr and margin >= mgn) else None
        if routed == exp:
            r_ok += 1
        else:
            erros.append(f"ROTA: {txt[:42]} → {routed} (esperado {exp}) "
                         f"conf={conf:.2f} mgn={margin:.2f}")
    return r_ok / r_tot if r_tot else 1.0


def _eval_skill(erros: list[str]) -> dict:
    """Recall@1/@3/@k da SkillMemory sobre _SKILL_GOLD. Reconstrói o índice
    (instruções do registry + situações curadas) antes de medir."""
    try:
        from jarvis.memory import skills as _sk
        import config as _c
        k = int(getattr(_c, "SKILL_MEMORY_K", 8) or 8)
        n = _sk.sync_from_registry()  # garante índice atual (com situações)
        sm = _sk.get_skills()
    except Exception as e:
        erros.append(f"SkillMemory indisponível: {e}")
        return {"recall@1": 1.0, "recall@3": 1.0, "recall@k": 1.0, "k": 0, "indexed": 0}

    hit1 = hit3 = hitk = tot = 0
    for q, accept in _SKILL_GOLD:
        tot += 1
        names = sm.retrieve_tool_names(q, k=k)
        if accept & set(names[:1]):
            hit1 += 1
        if accept & set(names[:3]):
            hit3 += 1
        if accept & set(names[:k]):
            hitk += 1
        else:
            erros.append(f"SKILL: {q[:42]} → top{k}={names[:5]} "
                         f"(esperava ∈ {sorted(accept)})")
    return {
        "recall@1": hit1 / tot if tot else 1.0,
        "recall@3": hit3 / tot if tot else 1.0,
        "recall@k": hitk / tot if tot else 1.0,
        "k": k, "indexed": n,
    }


def calibrate() -> int:
    """Sweep thr×margem sobre _ROUTER_GOLD: imprime a grade de acurácia + o
    melhor ponto (mais acerto; empate → menos MISROTA [domínio errado≠None] →
    margem maior = mais conservador). Roda route() 1x por texto (cache)."""
    try:
        from jarvis.agents import router as _R
    except Exception as e:
        print(f"router indisponível: {e}")
        return 1
    routed = [(_R.route(txt), exp) for txt, exp in _ROUTER_GOLD]
    thrs = [0.40, 0.42, 0.45, 0.48, 0.50]
    mgns = [0.00, 0.01, 0.02, 0.03, 0.04, 0.06]

    print(f"\n=== CALIBRAÇÃO roteador ({len(routed)} casos) — acurácia por thr × margem ===")
    print("        " + "   ".join(f"m{m:.2f}" for m in mgns))
    best = None  # (acc, -misroutes, mgn, thr)
    for thr in thrs:
        cells = []
        for mgn in mgns:
            ok = mis = 0
            for (dom, conf, margin), exp in routed:
                r = dom if (dom and conf >= thr and margin >= mgn) else None
                if r == exp:
                    ok += 1
                elif r is not None:      # roteou pra um domínio ERRADO (não-None)
                    mis += 1
            acc = ok / len(routed)
            cells.append(f"{acc:.2f}")
            key = (acc, -mis, mgn, thr)
            if best is None or key > best:
                best = key
        print(f"thr{thr:.2f}  " + "  ".join(cells))

    acc, negmis, mgn, thr = best
    # Recalcula misrotas/Nones no melhor ponto para o relatório
    mis = none_miss = 0
    for (dom, conf, margin), exp in routed:
        r = dom if (dom and conf >= thr and margin >= mgn) else None
        if r != exp:
            if r is None:
                none_miss += 1
            else:
                mis += 1
    print(f"\n→ MELHOR: acc={acc:.2f}  thr={thr:.2f}  margem={mgn:.2f}  "
          f"(misrotas={mis}, miss-conservador→None={none_miss})")
    print(f"  Config atual: AGENT_SUBAGENT_THRESHOLD={thr:.2f} · "
          f"AGENT_SUBAGENT_MARGIN={mgn:.2f}")
    print("  (misrota = escopou domínio ERRADO = perigoso; None = cai no filtro "
          "padrão = seguro)")

    # SkillMemory junto (exploração)
    erros: list[str] = []
    sk = _eval_skill(erros)
    print(f"\n=== SkillMemory (recall) — {sk['indexed']} instruções indexadas, k={sk['k']} ===")
    print(f"recall@1={sk['recall@1']:.2f}  recall@3={sk['recall@3']:.2f}  "
          f"recall@{sk['k']}={sk['recall@k']:.2f}")
    if erros:
        print("\n-- divergências SkillMemory --")
        for e in erros:
            print("  •", e)
    return 0


def main() -> int:
    from jarvis.memory.triage import get_triage
    tri = get_triage()
    cases = _GOLD + _load_extra()

    tp = fp = fn = tn = 0          # lembrar-vs-ignorar
    seg_ok = seg_tot = 0          # acurácia de segmento (nos que devem lembrar)
    leaks = 0                      # segredos memorizados (deve ser 0)
    erros: list[str] = []

    for c in cases:
        d = tri.decide(c.get("text", ""))
        got_remember = bool(d.get("remember"))
        exp_remember = bool(c.get("remember"))
        if exp_remember and got_remember:
            tp += 1
        elif exp_remember and not got_remember:
            fn += 1
            erros.append(f"FN (devia lembrar): {c['text'][:50]} → {d['category']}/{d['op']}")
        elif not exp_remember and got_remember:
            fp += 1
            erros.append(f"FP (NÃO devia lembrar): {c['text'][:50]} → {d['category']}/{d['segment']}")
        else:
            tn += 1
        if c.get("secret") and got_remember:
            leaks += 1
            erros.append(f"VAZAMENTO DE SEGREDO: {c['text'][:50]}")
        if exp_remember and c.get("segment"):
            seg_tot += 1
            if d.get("segment") == c["segment"]:
                seg_ok += 1
            else:
                erros.append(f"SEG errado: {c['text'][:50]} → {d.get('segment')} (esperado {c['segment']})")

    # Roteador de domínio (lê thr/margem da config)
    import config as _c
    thr = float(getattr(_c, "AGENT_SUBAGENT_THRESHOLD", 0.42))
    mgn = float(getattr(_c, "AGENT_SUBAGENT_MARGIN", 0.06))
    router_acc = _eval_router(thr, mgn, erros)

    # SkillMemory (recuperação semântica de tools)
    sk = _eval_skill(erros)

    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    seg_acc = seg_ok / seg_tot if seg_tot else 1.0

    print(f"\n=== EVAL discernimento ({len(cases)} casos) ===")
    print(f"lembrar-vs-ignorar:  P={prec:.2f}  R={rec:.2f}  F1={f1:.2f}  (TP={tp} FP={fp} FN={fn} TN={tn})")
    print(f"acurácia de segmento: {seg_acc:.2f}  ({seg_ok}/{seg_tot})")
    print(f"roteador de domínio:  {router_acc:.2f}  (thr={thr:.2f} mgn={mgn:.2f})")
    print(f"SkillMemory recall:   @1={sk['recall@1']:.2f} @3={sk['recall@3']:.2f} "
          f"@{sk['k']}={sk['recall@k']:.2f}  ({sk['indexed']} indexadas)")
    print(f"VAZAMENTO de segredo: {leaks}  (precisa ser 0)")
    if erros:
        print("\n-- divergências --")
        for e in erros:
            print("  •", e)

    # Critérios de aprovação (CI): zero vazamento + métricas razoáveis +
    # recall@k da SkillMemory acima do gate (Gorilla: retriever ruim é pior).
    ok = (leaks == 0) and (f1 >= _MIN_F1) and (seg_acc >= _MIN_SEG) \
        and (router_acc >= _MIN_ROUTER) and (sk["recall@k"] >= _MIN_SKILL_RECALL)
    print(f"\nRESULTADO: {'PASS ✓' if ok else 'FAIL ✗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--calibrate" in sys.argv:
        raise SystemExit(calibrate())
    raise SystemExit(main())
