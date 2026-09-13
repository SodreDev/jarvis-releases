#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/nila_corpus_teacher.py — gera corpus de treino da Nila via teacher (DeepSeek/OpenRouter).

Diferença do nila_corpus.py (determinístico):
  • As queries são NATURAIS (geradas por LLM, não templates)
  • Os args são EXTRAÍDOS da query (o modelo sabe o que copiar)
  • Resultado: pares (query real → JSON exato) com 15-20 variações por tool

Custo estimado: ~47 tools × 800 tokens ≈ 37k tokens ≈ centavos no DeepSeek V4 Flash.

USO
---
  # Requer OPENROUTER_API_KEY no .env (mesma chave do JARVIS)
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py --model deepseek/deepseek-chat-v4-5
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py --n 20 --out data/nila/corpus_teacher.txt
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py --dry-run   # só mostra prompt do 1º tool

  # LM Studio local (modelo carregado no LM Studio, sem custo de API)
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py --local
  .venv\\Scripts\\python.exe tools\\nila_corpus_teacher.py --local --port 1234 --n 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Modelo padrão — ajuste se o ID exato no OpenRouter for diferente
_DEFAULT_MODEL = "deepseek/deepseek-chat-v4-5"
_DEFAULT_N = 15  # exemplos por tool
_DEFAULT_OUT = ROOT / "data" / "nila" / "corpus_teacher_deepseek.txt"

# Tools de baixa prioridade (menos usadas na prática) — menos exemplos
_N_LOW_PRIORITY = 8
_LOW_PRIORITY = {
    "criar_planilha", "criar_apresentacao", "reproduzir_youtube",
    "gerar_imagem", "criar_alarme", "analisar_tela", "aprender_sobre",
}


def _load_or_client(model: str, lm_studio: bool = False, lm_port: int = 1234):
    """Cria client OpenAI apontando pro OpenRouter ou LM Studio local."""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("ERRO: `openai` não instalado. Rode: pip install openai")

    if lm_studio:
        # LM Studio roda servidor OpenAI-compatível em localhost — sem chave real.
        # O modelo carregado no LM Studio é servido independente do model_id passado.
        base_url = f"http://localhost:{lm_port}/v1"
        key = "lm-studio"
        print(f"[teacher] modo LOCAL (LM Studio em {base_url})")
        return OpenAI(base_url=base_url, api_key=key), model

    # OpenRouter
    try:
        from dotenv import load_dotenv  # noqa
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        try:
            import config as _cfg
            key = getattr(_cfg, "OPENROUTER_API_KEY", "").strip()
        except Exception:
            pass
    if not key:
        sys.exit("ERRO: OPENROUTER_API_KEY não encontrado no .env / ambiente.")
    base_url = "https://openrouter.ai/api/v1"
    try:
        import config as _cfg
        base_url = getattr(_cfg, "OPENROUTER_BASE_URL", base_url)
    except Exception:
        pass
    return OpenAI(base_url=base_url, api_key=key), model


def _load_tools(specs_path: Path | None = None) -> dict:
    """Carrega as tool specs → nome: function_spec.

    Por padrão importa o tool_registry do JARVIS. Com `specs_path` carrega de um
    JSON exportado (--export-specs) — permite rodar o script STANDALONE em outra
    máquina (só precisa de python + openai + LM Studio + este arquivo + o JSON).
    """
    if specs_path is not None:
        return json.loads(Path(specs_path).read_text(encoding="utf-8"))
    from comandos import tool_registry as tr
    fns = {}
    for s in tr.to_openai_tools():
        fn = (s.get("function") or {}) if isinstance(s, dict) else {}
        name = fn.get("name", "")
        if name:
            fns[name] = fn
    return fns


def _props(fn: dict) -> list[str]:
    return list(((fn.get("parameters") or {}).get("properties") or {}).keys())


def _required(fn: dict) -> list[str]:
    return list(((fn.get("parameters") or {}).get("required") or []))


def _first_sentence(desc: str, limit: int = 120) -> str:
    desc = " ".join((desc or "").split())
    for sep in (". ", " — ", "; "):
        i = desc.find(sep)
        if 0 < i <= limit:
            return desc[:i]
    return desc[:limit]


def _build_prompt(name: str, fn: dict, n: int) -> str:
    """Monta o prompt do teacher para um tool específico."""
    desc = _first_sentence(fn.get("description", f"ferramenta {name}"))
    props = _props(fn)
    req = _required(fn)
    params_desc = []
    prop_defs = (fn.get("parameters") or {}).get("properties") or {}
    for p in props[:4]:
        pd = prop_defs.get(p, {})
        pd_desc = pd.get("description", "")
        params_desc.append(f'  - "{p}": {pd_desc or p}' + (" (obrigatório)" if p in req else ""))

    # Exemplo mínimo de saída esperada
    ex_args = {p: f"[{p}]" for p in (req or props)[:2]}
    ex_json = json.dumps({"acao": name, **ex_args}, ensure_ascii=False)

    return f"""Gere {n} exemplos de pedidos em português brasileiro (variado: coloquial, formal, abreviado) para a ferramenta "{name}" do assistente JARVIS.

FERRAMENTA: {name} — {desc}
PARÂMETROS:
{chr(10).join(params_desc) or "  (nenhum)"}

FORMATO (par frase+JSON, linha em branco entre pares; args concretos copiados da frase, sem placeholders; sem numeração nem comentários):
Senhor: [frase do usuário]
{ex_json}

Gere os {n} exemplos:"""


# Geração em MASSA (por-tool): thinking DESLIGADO. Gerar frases não é tarefa de
# raciocínio — com thinking o modelo rascunha os N exemplos no <think>, critica e
# reescreve tudo (3-4× os tokens, zero ganho). Prova: Gemma-3-4b-it (sem thinking)
# fez 194 pares ótimos e rápido; o Qwen3.5 com thinking levava 20-30 min/tool.
_SYSTEM_PROMPT_FAST = (
    "Você gera dados de treino para um classificador de ações. Responda DIRETO com "
    "os exemplos no formato pedido — sem raciocínio, sem análise, sem preâmbulo. "
    "Se não conseguir um exemplo realista, pule — não invente."
)
# Tarefas que SE BENEFICIAM de raciocínio (disambiguação, pedidos indiretos):
# aí o thinking ajuda a escolher a tool certa.
_SYSTEM_PROMPT_THINK = (
    "Você gera dados de treino para um classificador de ações. Pense BREVEMENTE "
    "(2-3 frases) sobre qual ferramenta cada pedido exige, depois emita os exemplos "
    "no formato pedido. Seja honesto: se não conseguir, pule — não invente."
)


def _call_teacher(client, model: str, prompt: str, tool_name: str,
                  think: bool = False, max_seconds: float = 240.0,
                  max_out_tokens: int | None = None) -> str:
    """Chama o teacher via streaming e retorna o texto da resposta final.

    `think=False` (padrão p/ geração em massa): PULA o raciocínio via PREFILL —
      injeta um bloco `<think></think>` já fechado como início da resposta do
      assistant. Builds abliterados do Qwen3 ignoram `/no_think` e
      `enable_thinking=False` (testado: pensam 838 chars só pra dizer "OK"), mas
      obedecem o prefill (2.5s, zero thinking). Gemma/Phi-não-reasoning ignoram
      o prefill sem prejuízo.
    `max_seconds`: teto de wall-clock por request — rede de segurança se o modelo
      ignorar tudo e entrar em loop de raciocínio (aborta e usa o que veio).
    """
    system = _SYSTEM_PROMPT_THINK if think else _SYSTEM_PROMPT_FAST
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": prompt}]
    # max_tokens escalado pelo pedido: sem isso o modelo divaga até o teto e gera
    # exemplos repetidos/inúteis (e queima tempo em modelo lento com offload).
    if max_out_tokens is not None:
        max_tokens = max_out_tokens
    else:
        max_tokens = 6000 if think else 2500

    def _mk_stream(mode: str):
        kw = dict(model=model, messages=list(messages), temperature=0.85,
                  max_tokens=max_tokens, stream=True)
        if think:
            kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": True}}
        elif mode == "prefill_cont":
            # Melhor: continua a resposta a partir do <think></think> fechado.
            kw["messages"] = messages + [{"role": "assistant", "content": "<think>\n\n</think>\n\n"}]
            kw["extra_body"] = {"add_generation_prompt": False, "continue_final_message": True}
        elif mode == "prefill":
            # Fallback: só o prefill (funciona mesmo sem continue_final_message).
            kw["messages"] = messages + [{"role": "assistant", "content": "<think></think>"}]
        # mode == "plain": nada especial (Gemma/Phi já respondem direto)
        return client.chat.completions.create(**kw)

    # Ordem de tentativa quando think=False: prefill+cont → prefill → plain.
    # IMPORTANTE: cada modo roda até o fim e só avança se o output for vazio.
    # Phi-4 com continue_final_message=True gera 0 tokens (vê </think> fechado e para)
    # → cai para "plain", que deixa ele pensar; _strip_thinking remove o raciocínio.
    modes = ["prefill_cont", "prefill", "plain"] if not think else ["think"]

    for mode in modes:
        try:
            stream = _mk_stream(mode)
        except Exception:
            continue

        answer_chunks: list[str] = []
        thinking_chunks: list[str] = []
        t_start = time.time()
        try:
            for chunk in stream:
                if time.time() - t_start > max_seconds:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    answer_chunks.append(delta.content)
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    thinking_chunks.append(rc)
        except Exception:
            pass  # streaming parcial — usa o que chegou antes do erro

        answer = "".join(answer_chunks).strip()
        if not answer and thinking_chunks:
            answer = _strip_thinking("".join(thinking_chunks)).strip()

        if answer:
            return answer
        # Modo retornou vazio — tenta próximo (ex: prefill_cont gerou 0 tokens no Phi-4)

    return ""


def _strip_thinking(raw: str) -> str:
    """Remove seções de raciocínio de modelos pensadores.

    Formatos suportados:
      • <think>...</think>  (Qwen3 padrão)
      • Thinking Process: ... (Qwen3.5 e outros em modo texto)
      • **Reasoning:** ...
    Tudo antes da primeira linha "Senhor:" também é descartado se vier do thinking.
    """
    # Remove blocos de thinking — suporta ambas as variantes de tag:
    #   <think>…</think>    (Qwen3, Phi-4, DeepSeek-R1)
    #   <thinking>…</thinking>  (Gemma 4, alguns builds alternativos)
    raw = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', raw, flags=re.DOTALL)
    # Remove bloco NÃO fechado (thinking truncado por max_tokens — sem tag de fechamento).
    raw = re.sub(r'<think(?:ing)?>.*$', '', raw, flags=re.DOTALL)
    # Remove seção "Thinking Process:" até linha em branco seguida de conteúdo não-thinking
    raw = re.sub(
        r'(?i)(?:^|\n)(thinking\s+process|reasoning|pensamento|racioc[íi]nio)\s*:.*?(?=\n\s*\n)',
        '', raw, flags=re.DOTALL
    )
    return raw.strip()


def _clean_frase(line: str) -> str:
    """Limpa uma linha de frase: tira numeração, markdown e prefixo de locutor.

    Robusto ao que os modelos fazem de fato: "Senhor: X", "Senhor, X" (vírgula),
    "1. X", "**X**", "Usuário: X", ou SEM prefixo nenhum ("Queria abrir o X").
    Retorna só o texto do pedido (sem prefixo) — o chamador re-adiciona "Senhor: ".
    """
    l = line.strip()
    l = re.sub(r'^[\d]+[.)]\s*', '', l)          # numeração "1." / "1)"
    l = re.sub(r'^[-*]\s*', '', l)               # bullets "- " / "* "
    l = re.sub(r'\*+', '', l)                     # markdown bold
    # Prefixo de locutor com : OU , (Senhor:/Senhor,/Usuário:/User:/Humano:)
    l = re.sub(r'^(senhor|usu[áa]rio|user|humano|input)\s*[:,]\s*', '', l, flags=re.I)
    return l.strip()


def _extract_frase(line: str) -> str | None:
    """Como _clean_frase mas EXIGE prefixo de locutor (p/ parser de conversa,
    onde não há JSON pra ancorar). Retorna 'Senhor: <texto>' ou None."""
    l = line.strip()
    l = re.sub(r'^[\d]+[.)]\s*', '', l)
    l = re.sub(r'^[-*]\s*', '', l)
    l = re.sub(r'\*+', '', l)
    m = re.match(r'^(senhor|usu[áa]rio|user|u|humano|input)\s*[:,]\s*(.+)', l, flags=re.I)
    if m and m.group(2).strip():
        return f"Senhor: {m.group(2).strip()}"
    return None


def _extract_json(line: str, tool_name: str) -> dict | None:
    """Tenta extrair e validar JSON de uma linha (incluindo dentro de code fences)."""
    line = line.strip()
    # Remove code fences: ```json ... ``` ou ` ... `
    line = re.sub(r'^```[a-z]*\s*', '', line)
    line = re.sub(r'```$', '', line).strip()
    line = re.sub(r'^`|`$', '', line).strip()
    if not line.startswith('{'):
        return None
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return None
        obj["acao"] = tool_name  # garante nome correto
        return obj
    except json.JSONDecodeError:
        # Tenta encontrar JSON dentro da linha
        m = re.search(r'\{[^{}]{5,300}\}', line)
        if m:
            try:
                obj = json.loads(m.group(0))
                if isinstance(obj, dict):
                    obj["acao"] = tool_name
                    return obj
            except Exception:
                pass
    return None


def _pair_from_json_anchor(lines: list[str], j: int, obj: dict) -> tuple[str, str] | None:
    """Dado que lines[j] é um JSON válido, acha a frase na linha NÃO-vazia e
    NÃO-JSON imediatamente anterior. Ancorar no JSON é robusto: funciona mesmo
    quando o modelo larga o prefixo "Senhor:" (ex: abrir_app gerou "Queria abrir
    o Discord" sem prefixo — parser antigo achava 0 pares)."""
    k = j - 1
    while k >= 0 and not lines[k].strip():
        k -= 1
    if k < 0 or lines[k].strip().startswith('{'):
        return None
    frase = _clean_frase(lines[k])
    if not frase:
        return None
    return (f"Senhor: {frase}", _norm_json(obj))


def _parse_pairs(raw: str, tool_name: str) -> list[tuple[str, str]]:
    """Extrai pares (frase, json) ANCORANDO no JSON (não na frase).

    Para cada linha que é JSON válido com "acao", pega a frase na linha anterior.
    Robusto a: prefixo ausente, "Senhor," com vírgula, numeração, markdown, fences.
    """
    pairs = []
    lines = [l.rstrip() for l in raw.splitlines()]
    for j in range(len(lines)):
        obj = _extract_json(lines[j], tool_name)
        if obj:
            p = _pair_from_json_anchor(lines, j, obj)
            if p:
                pairs.append(p)
    return pairs


def _norm_json(obj: dict) -> str:
    """JSON normalizado para treino da Nila: sem espaço após ':', espaço+vírgula entre items.
    Casa o byte-pattern do nila_corpus.py: {"acao":"x", "p":"v"}
    """
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ":"))


def _fallback_parse(raw: str, tool_name: str) -> list[tuple[str, str]]:
    """Fallback: tenta achar qualquer JSON com 'acao' no texto."""
    pairs = []
    json_pattern = re.compile(r'\{[^{}]{10,300}\}')
    blocks = re.split(r'\n\s*\n', raw.strip())
    for block in blocks:
        block = block.strip()
        lines = block.splitlines()
        frase = None
        for l in lines:
            l = l.strip()
            if re.match(r'^(Senhor|senhor|S\.?|s\.?):', l):
                frase = l if l.lower().startswith("senhor:") else "Senhor: " + l.split(":", 1)[-1].strip()
            elif l.startswith("{") and frase:
                m = json_pattern.match(l)
                if m:
                    try:
                        obj = json.loads(m.group(0))
                        if isinstance(obj, dict):
                            obj["acao"] = tool_name
                            pairs.append((frase, _norm_json(obj)))
                            frase = None
                    except Exception:
                        pass
    return pairs


def generate_corpus(
    model: str = _DEFAULT_MODEL,
    n_per_tool: int = _DEFAULT_N,
    out: Path = _DEFAULT_OUT,
    dry_run: bool = False,
    tools_filter: list[str] | None = None,
    delay: float = 0.5,
    lm_studio: bool = False,
    lm_port: int = 1234,
    verbose: bool = False,
    specs_path: Path | None = None,
    think: bool = False,
    max_seconds: float = 240.0,
) -> None:
    client, model = _load_or_client(model, lm_studio=lm_studio, lm_port=lm_port)
    fns = _load_tools(specs_path)

    if tools_filter:
        fns = {k: v for k, v in fns.items() if k in tools_filter}

    out.parent.mkdir(parents=True, exist_ok=True)

    tools_sorted = sorted(fns.keys())
    total = len(tools_sorted)
    print(f"[teacher] {total} tools | modelo={model} | n/tool={n_per_tool} | "
          f"thinking={'ON' if think else 'OFF'} | teto={max_seconds:.0f}s")

    all_pairs: list[tuple[str, str]] = []
    failed: list[str] = []

    def _write_out() -> None:
        """Salva o corpus INCREMENTALMENTE — um crash não perde o progresso."""
        lines = [
            "# Corpus teacher (LLM → Nila) — gerado automaticamente",
            "# NÃO commitar (dados de treino do modelo local, IP do dono).",
            "",
            'A mente pode AGIR no JARVIS. Formato de ação: {"acao":"<nome>", ...}.',
            "Quando o Senhor pede algo, ela responde com a ação certa em JSON e nada mais.",
            "",
        ]
        for frase, json_line in all_pairs:
            lines.append(frase)
            lines.append(json_line)
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")

    last_raw = {"text": ""}  # p/ debug verbose fora do _one_call

    def _one_call(tool_name: str, fn: dict, n: int) -> list[tuple[str, str]]:
        # ~70 tokens por par (frase+JSON) + folga; com thinking dá espaço extra.
        # +2500 mesmo p/ think=False: margem p/ modelos de raciocínio (Phi-4, Gemma-4-thinking)
        # que pensam antes mesmo quando o prefill falha. Modelos sem raciocínio ignoram a folga.
        budget = n * 70 + 300 + (2000 if think else 0) + 2500
        raw = _strip_thinking(_call_teacher(
            client, model, prompt_for(tool_name, fn, n), tool_name,
            think=think, max_seconds=max_seconds, max_out_tokens=budget))
        last_raw["text"] = raw
        pairs = _parse_pairs(raw, tool_name)
        if len(pairs) < n // 2:
            pairs2 = _fallback_parse(raw, tool_name)
            if len(pairs2) > len(pairs):
                pairs = pairs2
        return pairs

    def prompt_for(tool_name: str, fn: dict, n: int) -> str:
        return _build_prompt(tool_name, fn, n)

    for idx, tool_name in enumerate(tools_sorted, 1):
        fn = fns[tool_name]
        n = _N_LOW_PRIORITY if tool_name in _LOW_PRIORITY else n_per_tool

        if dry_run:
            print(f"\n{'='*60}")
            print(f"TOOL: {tool_name}")
            print(f"{'='*60}")
            print(_build_prompt(tool_name, fn, n))
            print(f"\n[dry-run] pararia aqui. Use sem --dry-run p/ gerar.")
            break

        print(f"  [{idx:02d}/{total}] {tool_name} (n={n})...", end="", flush=True)
        t0 = time.time()
        pairs: list[tuple[str, str]] = []
        # Até 2 tentativas: a 2ª com n menor (task menor = thinking menor = cabe no budget)
        for attempt in (1, 2):
            try:
                n_try = n if attempt == 1 else max(4, n // 2)
                pairs = _one_call(tool_name, fn, n_try)
                if pairs:
                    break
                if attempt == 1:
                    print(" [0 pares, retry c/ n menor]", end="", flush=True)
            except Exception as e:
                print(f" [erro tentativa {attempt}: {type(e).__name__}]", end="", flush=True)
                time.sleep(2.0)

        all_pairs.extend(pairs)
        _write_out()  # salva progresso a cada tool
        elapsed = time.time() - t0
        print(f" {len(pairs)} pares ({elapsed:.1f}s)")
        if verbose or not pairs:
            r = last_raw["text"]
            print(f"  --- RAW ({len(r)} chars) | ÚLTIMOS 800 ---")
            print(r[-800:])
            print("  --- FIM RAW ---")
        if not pairs:
            failed.append(tool_name)

        if delay > 0 and idx < total:
            time.sleep(delay)

    if dry_run:
        return

    _write_out()
    n_bytes = out.stat().st_size
    print(f"\n[teacher] {len(all_pairs)} pares | {n_bytes:,} bytes → {out}")
    if failed:
        print(f"[teacher] 0 pares mesmo com retry: {failed}")
        print(f"[teacher] re-rode só essas: --tools {' '.join(failed)}")


# ── MODO AVANÇADO: profundidade (disambiguação, conversa, pedidos indiretos) ──
# Grupos de tools que se CONFUNDEM — a Nila precisa aprender a fronteira.
_CONFUSABLE_GROUPS: list[list[str]] = [
    ["tocar_musica", "controle_spotify", "reproduzir_youtube"],
    ["pesquisa_web", "aprender_sobre", "abrir_site"],
    ["abrir_app", "abrir_jogo", "abrir_site"],
    ["criar_relatorio", "criar_documento_word", "criar_apresentacao", "exportar_pdf"],
    ["criar_alarme", "criar_timer"],
    ["comando_terminal", "controle_sistema"],
    ["enviar_mensagem", "abrir_dm_discord"],
    ["clima", "pesquisa_web"],
    # Novos grupos — fronteiras mais sutis
    ["tirar_screenshot", "analisar_tela"],              # capturar ≠ analisar com IA
    ["gerar_imagem", "pesquisa_web"],                   # criar imagem ≠ buscar imagem
    ["criar_planilha", "criar_relatorio", "exportar_pdf"],  # dados → qual formato?
    ["controle_spotify", "controle_sistema"],            # controlar volume: Spotify ≠ sistema
]

# Tools "cotidianas" com maior chance de pedido INDIRETO/implícito.
_INDIRECT_TOOLS = [
    "clima", "criar_timer", "criar_alarme", "tocar_musica", "controle_spotify",
    "enviar_mensagem", "pesquisa_web", "controle_sistema", "abrir_app", "gerar_imagem",
    "abrir_jogo", "criar_documento_word", "tirar_screenshot",
]

# Tools que aparecem em pedidos de NEGAÇÃO / parar / redirecionar.
_NEGATION_TOOLS = [
    "controle_spotify", "tocar_musica", "reproduzir_youtube",
    "criar_timer", "criar_alarme", "controle_sistema",
    "abrir_app", "abrir_jogo", "pesquisa_web", "enviar_mensagem",
]

# Tools para geração de gíria/informal extremo.
_SLANG_TOOLS = [
    "abrir_app", "tocar_musica", "controle_spotify", "pesquisa_web",
    "abrir_jogo", "abrir_dm_discord", "enviar_mensagem", "clima",
    "criar_timer", "controle_sistema", "abrir_site",
]


def _tool_summary(name: str, fn: dict) -> str:
    """Resumo de 1 linha da tool para prompts de disambiguação."""
    desc = _first_sentence(fn.get("description", ""), 100)
    req = _required(fn)
    params = ", ".join(req or _props(fn)[:2]) or "sem params"
    return f'- "{name}": {desc} (params: {params})'


def _build_disambig_prompt(group: list[str], fns: dict, n: int) -> str:
    tools_txt = "\n".join(_tool_summary(t, fns[t]) for t in group if t in fns)
    return f"""O assistente JARVIS tem estas ferramentas PARECIDAS que se confundem:
{tools_txt}

Gere {n} pedidos em português brasileiro que exigem escolher a ferramenta CERTA entre elas.
Misture: alguns pedidos parecem uma mas são outra (ex: "toca no youtube" ≠ "toca no spotify").
Alterne entre TODAS as ferramentas do grupo. Args concretos copiados da frase.

FORMATO (par frase+JSON, linha em branco entre pares, sem numeração):
Senhor: [frase]
{{"acao":"<nome-da-tool-certa>", "<param>":"<valor>"}}

Gere os {n} exemplos:"""


def _build_chat_prompt(n: int) -> str:
    return f"""O assistente JARVIS conversa em português brasileiro. Quando o pedido NÃO é uma ação
(é cumprimento, desabafo, opinião, pergunta pessoal, agradecimento), ele responde TEXTO curto — nunca JSON.

Gere {n} exemplos de conversa SEM ação: small talk, saudações, perguntas pessoais,
comentários do dia-a-dia, agradecimentos, piadas. A resposta é texto natural curto (1 frase),
respeitoso, chamando o usuário de "Senhor".

FORMATO (par frase+resposta, linha em branco entre pares, sem numeração, SEM JSON):
Senhor: [frase de conversa]
[resposta curta em texto]

Gere os {n} exemplos:"""


def _build_indirect_prompt(tools: list[str], fns: dict, n: int) -> str:
    tools_txt = "\n".join(_tool_summary(t, fns[t]) for t in tools if t in fns)
    return f"""O assistente JARVIS tem estas ferramentas:
{tools_txt}

Gere {n} pedidos INDIRETOS/implícitos em português brasileiro — o usuário não nomeia a ação,
mas a intenção é clara. Exemplos do estilo: "me lembra de tirar o bolo em 40 minutos" (timer),
"quero ouvir aquela do Queen" (música), "será que preciso de casaco amanhã?" (clima).
Alterne entre as ferramentas. Args concretos extraídos da frase.

FORMATO (par frase+JSON, linha em branco entre pares, sem numeração):
Senhor: [frase indireta]
{{"acao":"<tool>", "<param>":"<valor>"}}

Gere os {n} exemplos:"""


def _build_false_alarm_prompt(n: int) -> str:
    return f"""O assistente JARVIS conversa em português brasileiro. Algumas frases PARECEM pedir uma
ação mas na verdade são comentário, desabafo, observação ou pergunta retórica — não acionam ferramenta.

Exemplos de FALSO ALARME (não aciona nada):
- "tô com frio hoje" → não é consultar clima, é só comentário
- "preciso trabalhar" → não é abrir app, é desabafo
- "tenho que ligar pra minha mãe" → não é enviar mensagem, é pensando em voz alta
- "que horas são?" → não é criar timer, é pergunta retórica
- "hoje foi pesado" → só desabafo

Gere {n} exemplos de frases que PARECEM ação mas são conversa. Resposta é texto natural curto.

FORMATO (par frase+resposta-texto, linha em branco entre pares, sem numeração, SEM JSON):
Senhor: [frase que parece ação mas é comentário/desabafo]
[resposta curta em texto, sem JSON]

Gere os {n} exemplos:"""


def _build_negation_prompt(tools: list[str], fns: dict, n: int) -> str:
    tools_txt = "\n".join(_tool_summary(t, fns[t]) for t in tools if t in fns)
    return f"""O assistente JARVIS tem estas ferramentas:
{tools_txt}

Gere {n} exemplos onde o usuário PARA, CORRIGE ou REDIRECIONA uma ação:
- parar algo em andamento ("para a música", "cancela o timer")
- corrigir a escolha ("não spotify, bota no youtube", "não esse app, abre o outro")
- mudar de ideia ("esquece o alarme, coloca um timer de 10 min")
- negar e pedir outra coisa ("não busca isso, me fala você mesmo")
A ferramenta do JSON deve ser a que REALIZA a intenção FINAL. Args concretos da frase.

FORMATO (par frase+JSON, linha em branco entre pares, sem numeração):
Senhor: [frase de parada/correção/redirecionamento]
{{"acao":"<tool-final>", "<param>":"<valor>"}}

Gere os {n} exemplos:"""


def _build_slang_prompt(tools: list[str], fns: dict, n: int) -> str:
    tools_txt = "\n".join(_tool_summary(t, fns[t]) for t in tools if t in fns)
    return f"""O assistente JARVIS entende português brasileiro EXTREMAMENTE informal —
gírias, abreviações, palavrões leves, código entre amigos, mensagem de celular sem pontuação.

Ferramentas disponíveis:
{tools_txt}

Gere {n} exemplos com linguagem MUITO coloquial. Estilos:
"bota o spot", "mano pesquisa isso", "slk abre o disc", "pow joga um timer aí de 15",
"q tá o tempo hoje", "fecha essa drg do app", "bora abrir o vscode", "mano que musica eh essa",
"acha um jogo bom pra mim", "mn manda msg pro zé falando q chego tarde".
Alterne entre as ferramentas. Args extraídos da frase mesmo que abreviados.

FORMATO (par frase+JSON, linha em branco entre pares, sem numeração):
Senhor: [frase em gíria/abreviação]
{{"acao":"<tool>", "<param>":"<valor>"}}

Gere os {n} exemplos:"""


def _parse_pairs_any(raw: str, allowed: set[str]) -> list[tuple[str, str]]:
    """Como _parse_pairs (ancorado no JSON), mas aceita QUALQUER acao em `allowed`
    — usado no modo advanced (disambiguação/indiretos escolhem a tool certa)."""
    pairs = []
    lines = [l.rstrip() for l in raw.splitlines()]
    for j in range(len(lines)):
        line = re.sub(r'^```[a-z]*\s*|```$', '', lines[j].strip()).strip()
        if not line.startswith('{'):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not (isinstance(obj, dict) and obj.get("acao") in allowed):
            continue
        p = _pair_from_json_anchor(lines, j, obj)
        if p:
            pairs.append(p)
    return pairs


def _parse_chat_pairs(raw: str) -> list[tuple[str, str]]:
    """Pares (frase, resposta-texto) — a resposta NÃO pode ser JSON nem outra frase 'Senhor:'."""
    pairs = []
    lines = [l.rstrip() for l in raw.splitlines()]
    i = 0
    while i < len(lines):
        frase = _extract_frase(lines[i])
        if frase:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                resp = lines[j].strip()
                resp = re.sub(r'^[-*]\s*|\*+', '', resp).strip()
                if resp and not resp.startswith('{') and _extract_frase(resp) is None and len(resp) < 200:
                    pairs.append((frase, resp))
                    i = j + 1
                    continue
        i += 1
    return pairs


def generate_advanced(
    model: str,
    out: Path,
    fns: dict,
    client,
    n_per_job: int = 12,
    delay: float = 0.0,
    think: bool = True,
    max_seconds: float = 300.0,
) -> None:
    """Gera o corpus de PROFUNDIDADE: disambiguação + conversa + indiretos.

    `think=True` por padrão: aqui o raciocínio AJUDA (escolher a tool certa entre
    parecidas, interpretar pedido implícito). Pode desligar com --no-think se lento.
    """
    jobs: list[tuple[str, str, object]] = []  # (label, prompt, parse_fn)

    # 1. Disambiguação — todos os grupos presentes no JARVIS
    for group in _CONFUSABLE_GROUPS:
        present = [t for t in group if t in fns]
        if len(present) >= 2:
            allowed = set(present)
            jobs.append((
                f"disambig:{'+'.join(present[:2])}",
                _build_disambig_prompt(present, fns, n_per_job),
                lambda raw, a=allowed: _parse_pairs_any(raw, a),
            ))

    # 2. Conversa (6 rodadas — crucial: evita Nila acionar tool p/ qualquer coisa)
    for k in range(6):
        jobs.append((
            f"conversa:{k+1}",
            _build_chat_prompt(n_per_job),
            lambda raw: _parse_chat_pairs(raw),
        ))

    # 3. Falso alarme (4 rodadas — frases que PARECEM tool mas são comentário/desabafo)
    for k in range(4):
        jobs.append((
            f"falso_alarme:{k+1}",
            _build_false_alarm_prompt(n_per_job),
            lambda raw: _parse_chat_pairs(raw),
        ))

    # 4. Indiretos (5 rodadas — usuário não nomeia a ação mas a intenção é clara)
    present_ind = [t for t in _INDIRECT_TOOLS if t in fns]
    allowed_ind = set(present_ind)
    for k in range(5):
        jobs.append((
            f"indireto:{k+1}",
            _build_indirect_prompt(present_ind, fns, n_per_job),
            lambda raw, a=allowed_ind: _parse_pairs_any(raw, a),
        ))

    # 5. Negação/redirecionamento (3 rodadas — para, cancela, corrige escolha)
    present_neg = [t for t in _NEGATION_TOOLS if t in fns]
    allowed_neg = set(present_neg)
    for k in range(3):
        jobs.append((
            f"negacao:{k+1}",
            _build_negation_prompt(present_neg, fns, n_per_job),
            lambda raw, a=allowed_neg: _parse_pairs_any(raw, a),
        ))

    # 6. Gíria/informal extremo (3 rodadas — português coloquial, abreviado, código)
    present_slang = [t for t in _SLANG_TOOLS if t in fns]
    allowed_slang = set(present_slang)
    for k in range(3):
        jobs.append((
            f"giria:{k+1}",
            _build_slang_prompt(present_slang, fns, n_per_job),
            lambda raw, a=allowed_slang: _parse_pairs_any(raw, a),
        ))

    total = len(jobs)
    print(f"[advanced] {total} jobs | modelo={model} | n/job={n_per_job}")

    all_pairs: list[tuple[str, str]] = []
    failed: list[str] = []

    def _write_out() -> None:
        lines = [
            "# Corpus teacher AVANÇADO (disambiguação + conversa + indiretos)",
            "# NÃO commitar.",
            "",
        ]
        for frase, resp in all_pairs:
            lines.append(frase)
            lines.append(resp)
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")

    for idx, (label, prompt, parse_fn) in enumerate(jobs, 1):
        print(f"  [{idx:02d}/{total}] {label}...", end="", flush=True)
        t0 = time.time()
        pairs: list[tuple[str, str]] = []
        for attempt in (1, 2):
            try:
                budget = n_per_job * 90 + 400 + (2500 if think else 0) + 2500
                raw = _strip_thinking(_call_teacher(
                    client, model, prompt, label, think=think, max_seconds=max_seconds,
                    max_out_tokens=budget))
                pairs = parse_fn(raw)
                if pairs:
                    break
                if attempt == 1:
                    print(" [0 pares, retry]", end="", flush=True)
            except Exception as e:
                print(f" [erro tentativa {attempt}: {type(e).__name__}]", end="", flush=True)
                time.sleep(2.0)
        all_pairs.extend(pairs)
        _write_out()
        print(f" {len(pairs)} pares ({time.time()-t0:.1f}s)")
        if not pairs:
            failed.append(label)
        if delay > 0 and idx < total:
            time.sleep(delay)

    _write_out()
    print(f"\n[advanced] {len(all_pairs)} pares | {out.stat().st_size:,} bytes → {out}")
    if failed:
        print(f"[advanced] 0 pares mesmo com retry: {failed}")


def merge_corpora(inputs: list[Path], output: Path) -> None:
    """Une múltiplos corpora teacher em um único arquivo para treino."""
    lines = [
        "# Corpus teacher MERGED — gerado por múltiplos modelos (ensemble)",
        "# NÃO commitar.",
        "",
        'A mente pode AGIR no JARVIS. Formato de ação: {"acao":"<nome>", ...}.',
        "Quando o Senhor pede algo, ela responde com a ação certa em JSON e nada mais.",
        "",
    ]
    total = 0
    for p in inputs:
        if not p.exists():
            print(f"[merge] aviso: {p} não existe — pulando")
            continue
        text = p.read_text(encoding="utf-8")
        # Pula o cabeçalho de cada arquivo (até a primeira linha "Senhor:")
        body_lines = []
        found = False
        for l in text.splitlines():
            if l.startswith("Senhor:"):
                found = True
            if found:
                body_lines.append(l)
        lines.extend(body_lines)
        n = sum(1 for l in body_lines if l.startswith("Senhor:"))
        total += n
        print(f"[merge] {p.name}: {n} pares")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    n_bytes = len("\n".join(lines).encode("utf-8"))
    print(f"[merge] total: {total} pares | {n_bytes:,} bytes → {output}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera corpus teacher p/ Nila via LM Studio local ou OpenRouter")
    ap.add_argument("--model",   default=_DEFAULT_MODEL, help="Modelo OpenRouter (ex: deepseek/deepseek-chat-v4-5)")
    ap.add_argument("--n",       type=int, default=_DEFAULT_N, help=f"Exemplos por tool (default: {_DEFAULT_N})")
    ap.add_argument("--out",     type=Path, default=_DEFAULT_OUT, help="Arquivo de saída")
    ap.add_argument("--tools",   nargs="+", help="Filtrar tools específicas")
    ap.add_argument("--delay",   type=float, default=0.3, help="Delay entre chamadas (default: 0.3s; 0 p/ local)")
    ap.add_argument("--dry-run", action="store_true", help="Só mostra o prompt do 1º tool sem chamar a API")
    ap.add_argument("--local",   action="store_true", dest="lm_studio",
                    help="Usa LM Studio local em vez do OpenRouter (modelo carregado no LM Studio)")
    ap.add_argument("--port",    type=int, default=1234, dest="lm_port",
                    help="Porta do LM Studio (default: 1234)")
    ap.add_argument("--verbose", action="store_true", help="Imprime raw output do modelo (útil p/ debugar parsing)")
    ap.add_argument("--merge",   nargs="+", type=Path, metavar="CORPUS",
                    help="Une múltiplos arquivos corpus em --out (sem chamar API). "
                         "Ex: --merge corpus_gemma.txt corpus_qwen.txt corpus_phi.txt")
    ap.add_argument("--advanced", action="store_true",
                    help="Gera o corpus de PROFUNDIDADE (disambiguação + conversa + indiretos) "
                         "em vez do corpus por-tool")
    ap.add_argument("--specs",   type=Path, default=None,
                    help="Carrega tool specs de um JSON (p/ rodar standalone sem o repo do JARVIS)")
    ap.add_argument("--export-specs", type=Path, default=None, metavar="JSON",
                    help="Exporta as tool specs do JARVIS p/ JSON e sai (mandar junto com o script)")
    # Thinking: OFF na geração em massa (rápido), ON no modo --advanced (raciocínio ajuda).
    ap.add_argument("--think",    action="store_true", default=None,
                    help="Liga o modo raciocínio (mais lento; útil só p/ disambiguação)")
    ap.add_argument("--no-think", action="store_false", dest="think",
                    help="Desliga o raciocínio (padrão na geração por-tool; muito mais rápido)")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="Teto de tempo por request em s (default: 240 normal / 300 advanced). "
                         "Se o modelo entrar em loop de raciocínio, aborta e usa o que veio.")
    args = ap.parse_args()

    if args.export_specs:
        fns = _load_tools()
        args.export_specs.write_text(json.dumps(fns, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[specs] {len(fns)} tools → {args.export_specs}")
        print(f"[specs] na outra máquina: python {Path(sys.argv[0]).name} --local --specs {args.export_specs.name} ...")
        return

    if args.merge:
        merge_corpora(args.merge, args.out)
        return

    if args.advanced:
        client, model = _load_or_client(args.model, lm_studio=args.lm_studio, lm_port=args.lm_port)
        fns = _load_tools(args.specs)
        out = args.out
        if out == _DEFAULT_OUT:
            slug = re.sub(r'[^a-z0-9]+', '_', args.model.lower()).strip('_')
            out = _DEFAULT_OUT.parent / f"corpus_advanced_{slug}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Advanced: thinking ON por padrão (a menos que --no-think)
        think = True if args.think is None else args.think
        max_seconds = args.max_seconds if args.max_seconds is not None else 300.0
        generate_advanced(model, out, fns, client, n_per_job=args.n,
                          delay=args.delay if not args.lm_studio else 0.0,
                          think=think, max_seconds=max_seconds)
        return

    # Auto-nomeia o arquivo de saída pelo modelo quando --out não foi passado
    out = args.out
    if out == _DEFAULT_OUT:
        slug = re.sub(r'[^a-z0-9]+', '_', args.model.lower()).strip('_')
        out = _DEFAULT_OUT.parent / f"corpus_teacher_{slug}.txt"

    # Local: sem delay entre chamadas (é loopback)
    delay = args.delay if not args.lm_studio else 0.0

    # Geração por-tool: thinking OFF por padrão (rápido; ON só se --think explícito)
    think = False if args.think is None else args.think
    max_seconds = args.max_seconds if args.max_seconds is not None else 240.0

    generate_corpus(
        model=args.model,
        n_per_tool=args.n,
        out=out,
        dry_run=args.dry_run,
        tools_filter=args.tools,
        delay=delay,
        lm_studio=args.lm_studio,
        lm_port=args.lm_port,
        verbose=args.verbose,
        specs_path=args.specs,
        think=think,
        max_seconds=max_seconds,
    )


if __name__ == "__main__":
    main()
