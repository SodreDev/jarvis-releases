# jarvis/memory/compaction.py — J.A.R.V.I.S.
# Compactação de contexto (roadmap/14): reduzir tokens mantendo o que importa.
#
# DOIS mecanismos (pesquisa Morph / MemGPT / Anthropic auto-compact):
#   • COMPACTAÇÃO (mask_tool_outputs): apaga saídas de tools JÁ CONSUMIDAS,
#     mantendo a CHAMADA visível e os últimos N resultados VERBATIM (paths,
#     erros, nomes de arquivo são "load-bearing"). Zero LLM, 60-80% de economia.
#   • RESUMO (summarize_turns): condensa diálogo/decisões antigas em prosa curta
#     via LLM barato, PRESERVANDO verbatim caminhos/IDs/decisões. Vira um nó
#     'summary' no episódico e substitui N turnos na montagem do contexto.
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from typing import Callable, Optional

# Tokens grosseiros ≈ chars/4 (heurística barata, sem tokenizer).
def approx_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


# Padrões "load-bearing" que NUNCA devem ser mascarados/resumidos (mantidos crus)
_KEEP_VERBATIM = re.compile(
    r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+/[^\s\"']+|\b\w[\w.-]*\.(?:pdf|pptx|xlsx|docx|png|jpg|csv|txt|py|md)\b|ERRO[:\s]|https?://\S+)",
    re.I)


def mask_tool_outputs(messages: list[dict], keep_last: int = 4) -> list[dict]:
    """Mascara o CONTEÚDO de mensagens role='tool' já consumidas, preservando as
    últimas `keep_last` e qualquer linha com path/erro/URL. Mantém a estrutura da
    conversa (a chamada da tool continua visível). Retorna NOVA lista."""
    out = []
    tool_idxs = [i for i, m in enumerate(messages or [])
                 if isinstance(m, dict) and m.get("role") == "tool"]
    keep = set(tool_idxs[-keep_last:]) if keep_last > 0 else set()
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict):
            out.append(m); continue
        if m.get("role") == "tool" and i not in keep:
            content = str(m.get("content", ""))
            # preserva linhas com path/erro/URL; mascara o resto
            survivors = [ln for ln in content.splitlines() if _KEEP_VERBATIM.search(ln)]
            freed = approx_tokens(content) - sum(approx_tokens(s) for s in survivors)
            new_c = ("\n".join(survivors) + f"\n[compactado — ~{max(0, freed)} tokens liberados]").strip()
            mm = dict(m); mm["content"] = new_c
            out.append(mm)
        else:
            out.append(m)
    return out


def needs_compaction(messages: list[dict], budget_tokens: int, at_ratio: float = 0.70) -> bool:
    total = sum(approx_tokens(str(m.get("content", "")))
               for m in (messages or []) if isinstance(m, dict))
    return budget_tokens > 0 and total >= int(budget_tokens * at_ratio)


_SUMMARY_SYSTEM = (
    "Você condensa uma conversa entre o Senhor e o JARVIS num RESUMO CURTO em "
    "português (máx. ~120 palavras). REGRAS: preserve VERBATIM caminhos de "
    "arquivo, nomes de arquivos gerados, IDs, URLs e DECISÕES tomadas (com a "
    "razão). Descarte saudações, repetições e raciocínio supérfluo. Sem markdown, "
    "sem opinião — só os fatos/decisões que importam para o futuro."
)


def summarize_turns(turns_text: str, llm_call: Callable[[str, str], str]) -> str:
    """Resume `turns_text` chamando llm_call(system, user)->str. Best-effort."""
    if not (turns_text or "").strip():
        return ""
    try:
        s = llm_call(_SUMMARY_SYSTEM, f"Conversa:\n{turns_text}\n\nResumo curto:")
        return (s or "").strip()
    except Exception:
        return ""


def rolling_summary(old_summary: str, new_chunk: str,
                    llm_call: Callable[[str, str], str]) -> str:
    """Atualiza um resumo rolante: (resumo antigo + novo trecho) → novo resumo."""
    base = (old_summary or "").strip()
    chunk = (new_chunk or "").strip()
    if not chunk:
        return base
    payload = (f"Resumo até agora:\n{base}\n\nNovo trecho:\n{chunk}" if base
               else f"Conversa:\n{chunk}")
    try:
        return (llm_call(_SUMMARY_SYSTEM, payload + "\n\nResumo atualizado:") or "").strip() or base
    except Exception:
        return base
