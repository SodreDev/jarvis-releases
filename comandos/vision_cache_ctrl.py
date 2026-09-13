# comandos/vision_cache_ctrl.py — J.A.R.V.I.S.
# Cache de análises visuais do Qwen: salva, recupera e comprime em sumários.
# Permite follow-ups sem recarregar o modelo de visão.
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import json
import datetime
from typing import Optional, Callable

from config import PATHS
_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)

_CACHE_FILE   = PATHS["vision_cache"]
_SUMMARY_FILE = os.path.join(_ROOT, "vision_summary.json")  # sumários por dia (não sensível)


# ── Detecta app ativo (opcional, melhor contexto no cache) ────────────────────

def _get_app_ativo() -> str:
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        titulo = buf.value.strip()
        # Simplifica: pega nome do app da barra de título (ex: "main.py - VS Code" → "VS Code")
        if " - " in titulo:
            return titulo.rsplit(" - ", 1)[-1]
        return titulo[:40]
    except Exception:
        return ""


# ── Salvar análise ────────────────────────────────────────────────────────────

def salvar_analise(pergunta: str, resposta: str, app_ativo: str = "") -> None:
    """Salva uma análise visual no cache persistente."""
    if not resposta or not resposta.strip():
        return
    if not app_ativo:
        app_ativo = _get_app_ativo()
    entrada: dict = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "pergunta": pergunta.strip()[:200],
        "resposta": resposta.strip(),
        "app_ativo": app_ativo,
        "resumido": False,
    }
    with open(_CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")


# ── Recuperar análises ────────────────────────────────────────────────────────

def _ler_cache() -> list[dict]:
    if not os.path.exists(_CACHE_FILE):
        return []
    entradas = []
    with open(_CACHE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entradas.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entradas


def get_ultima() -> Optional[dict]:
    """Retorna a análise mais recente, ou None se não houver."""
    entradas = _ler_cache()
    return entradas[-1] if entradas else None


def get_recentes(n: int = 3, horas: float = 4.0) -> list[dict]:
    """
    Retorna até N análises dentro das últimas `horas` horas.
    Mais recente primeiro.
    """
    limite = datetime.datetime.now() - datetime.timedelta(hours=horas)
    entradas = _ler_cache()
    recentes = []
    for e in reversed(entradas):
        try:
            ts = datetime.datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= limite:
            recentes.append(e)
        if len(recentes) >= n:
            break
    return recentes  # mais recente primeiro


def get_contexto_para_followup(max_chars: int = 2000) -> str:
    """
    Retorna contexto formatado das últimas análises para injetar num prompt
    de follow-up, sem precisar recarregar o Qwen.
    """
    recentes = get_recentes(n=3, horas=4.0)
    if not recentes:
        return ""

    partes = []
    chars = 0
    for e in recentes:
        ts_fmt = e.get("ts", "")[:16].replace("T", " às ")
        app = f" ({e['app_ativo']})" if e.get("app_ativo") else ""
        bloco = (
            f"[Análise de {ts_fmt}{app}]\n"
            f"Pergunta: {e['pergunta']}\n"
            f"Resposta: {e['resposta']}"
        )
        if chars + len(bloco) > max_chars:
            bloco = bloco[:max_chars - chars]
            partes.append(bloco)
            break
        partes.append(bloco)
        chars += len(bloco)

    return "\n\n".join(partes)


def tem_contexto_recente(minutos: float = 30.0) -> bool:
    """True se existe uma análise de visão feita nos últimos N minutos."""
    ultima = get_ultima()
    if not ultima:
        return False
    try:
        ts = datetime.datetime.fromisoformat(ultima["ts"])
        return (datetime.datetime.now() - ts).total_seconds() <= minutos * 60
    except (KeyError, ValueError):
        return False


# ── Sumários por dia ──────────────────────────────────────────────────────────

def _ler_sumarios() -> dict:
    if not os.path.exists(_SUMMARY_FILE):
        return {}
    try:
        with open(_SUMMARY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _salvar_sumarios(dados: dict) -> None:
    with open(_SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def comprimir_dia(
    summarize_fn: Callable[[str], str],
    data: Optional[str] = None,
) -> str:
    """
    Comprime as análises de um dia num sumário compacto usando o LLM de texto.
    `summarize_fn(prompt) -> str` — pode ser Groq ou Llama local.
    `data` no formato "YYYY-MM-DD" — padrão: hoje.
    Retorna o sumário gerado.
    """
    if data is None:
        data = datetime.date.today().isoformat()

    entradas = _ler_cache()
    do_dia = [
        e for e in entradas
        if e.get("ts", "").startswith(data) and not e.get("resumido", False)
    ]

    if not do_dia:
        return f"Nenhuma análise visual nova em {data}."

    # Monta bloco para o LLM resumir
    linhas = []
    for e in do_dia:
        hora = e.get("ts", "")[11:16]
        app  = f" [{e['app_ativo']}]" if e.get("app_ativo") else ""
        linhas.append(f"{hora}{app} — Pergunta: {e['pergunta']}\nResposta: {e['resposta']}")

    bloco = "\n\n".join(linhas)
    prompt = (
        f"Abaixo estão análises visuais de tela feitas em {data}. "
        f"Crie um sumário compacto em português descrevendo o que o usuário estava fazendo "
        f"ao longo do dia, em ordem cronológica. Máximo 150 palavras, sem markdown.\n\n"
        f"{bloco[:3000]}"
    )

    try:
        resumo = summarize_fn(prompt)
    except Exception as e:
        return f"Erro ao comprimir: {e}"

    # Salva o sumário
    sumarios = _ler_sumarios()
    sumarios[data] = {
        "resumo": resumo.strip(),
        "n_entradas": len(do_dia),
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _salvar_sumarios(sumarios)

    # Marca entradas como resumidas no cache
    todas = _ler_cache()
    novas: list[str] = []
    for e in todas:
        if e.get("ts", "").startswith(data) and not e.get("resumido", False):
            e["resumido"] = True
        novas.append(json.dumps(e, ensure_ascii=False))
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(novas) + ("\n" if novas else ""))

    return resumo.strip()


def get_resumo_historico(dias: int = 7) -> str:
    """
    Retorna os sumários dos últimos N dias formatados para consulta.
    """
    sumarios = _ler_sumarios()
    hoje = datetime.date.today()
    partes = []
    for i in range(dias):
        data = (hoje - datetime.timedelta(days=i)).isoformat()
        if data in sumarios:
            s = sumarios[data]
            partes.append(f"[{data}] {s['resumo']}")
    if not partes:
        return "Nenhum sumário visual registrado nos últimos dias, senhor."
    return "Histórico visual:\n\n" + "\n\n".join(partes)


def status() -> str:
    """Retorna quantas análises existem no cache e quando foi a última."""
    entradas = _ler_cache()
    if not entradas:
        return "Nenhuma análise visual registrada ainda, senhor."
    ultima = entradas[-1]
    ts = ultima.get("ts", "")[:16].replace("T", " às ")
    hoje = sum(1 for e in entradas if e.get("ts", "").startswith(datetime.date.today().isoformat()))
    total = len(entradas)
    return (
        f"Cache visual: {total} análises no total, {hoje} hoje. "
        f"Última às {ts}."
    )
