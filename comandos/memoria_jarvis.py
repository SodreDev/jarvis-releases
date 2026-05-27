# comandos/memoria_jarvis.py — J.A.R.V.I.S.
# Persistência do histórico de conversa entre sessões.
# Salva cada troca (user + assistant) em JSONL. Ao iniciar, recarrega
# as últimas N trocas no _groq_history para que o Groq tenha contexto
# das conversas anteriores sem gastar tokens desnecessários.
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import datetime
import threading

_BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR  = os.path.join(_BASE, "data")
_FILE      = os.path.join(_DATA_DIR, "memoria_jarvis.jsonl")

# Número máximo de trocas (user+assistant) recarregadas no boot.
# Mantido propositalmente baixo (8 pares = 16 mensagens) para evitar que
# tópicos antigos contaminem o contexto da sessão atual — o JARVIS estava
# alucinando "informações financeiras" no meio de um envio de WhatsApp
# por causa de histórico arrastado de sessões anteriores.
_MAX_TURNS   = 8
_MAX_STORED  = 100  # linhas máximas no arquivo antes de trimar

_lock = threading.Lock()


# ─── helpers ──────────────────────────────────────────────────────────────────

def _garantir_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _ler_linhas() -> list[dict]:
    """Lê todas as linhas do JSONL sem travar."""
    if not os.path.isfile(_FILE):
        return []
    linhas = []
    with open(_FILE, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    linhas.append(json.loads(linha))
                except json.JSONDecodeError:
                    pass
    return linhas


def _escrever_linhas(linhas: list[dict]):
    _garantir_dir()
    with open(_FILE, "w", encoding="utf-8") as f:
        for l in linhas:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")


# ─── API pública ──────────────────────────────────────────────────────────────

def carregar(n: int = _MAX_TURNS) -> list[dict]:
    """
    Carrega as últimas n trocas (user + assistant) do disco.

    Retorna lista no formato [{role, content}, ...] sem entrada system —
    pronta para ser passada diretamente ao _groq_history após o system prompt.
    Retorna [] se o arquivo não existir ou estiver vazio.
    """
    with _lock:
        linhas = _ler_linhas()

    # Filtra só role user/assistant (ignora eventuais entradas system)
    turns = [l for l in linhas if l.get("role") in ("user", "assistant")]

    # Pega últimas 2*n entradas (n pares user+assistant)
    recentes = turns[-(2 * n):]

    # Retorna apenas os campos necessários para o _groq_history
    return [{"role": e["role"], "content": e.get("content", "")} for e in recentes]


def salvar_turno(user_text: str, assistant_text: str):
    """
    Persiste um par de mensagens (user + assistant) no JSONL.
    Mantém o arquivo com no máximo _MAX_STORED linhas (trim pelo topo).
    Thread-safe.
    """
    if not user_text and not assistant_text:
        return

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    novas = []
    if user_text:
        novas.append({"role": "user",      "content": str(user_text),      "ts": ts})
    if assistant_text:
        novas.append({"role": "assistant", "content": str(assistant_text), "ts": ts})

    with _lock:
        _garantir_dir()
        linhas = _ler_linhas()
        linhas.extend(novas)

        # Trim: mantém somente as últimas _MAX_STORED linhas
        if len(linhas) > _MAX_STORED:
            linhas = linhas[-_MAX_STORED:]

        _escrever_linhas(linhas)


def limpar():
    """Remove todo o histórico salvo (uso manual / debug)."""
    with _lock:
        if os.path.isfile(_FILE):
            os.remove(_FILE)
    print("[MEMÓRIA JARVIS] Histórico apagado.")
