# comandos/pomodoro_ctrl.py — J.A.R.V.I.S.
# Pomodoro Timer com tracking de sessões
# -*- coding: utf-8 -*-

from __future__ import annotations
import threading, datetime, json, os

_POMODORO_FILE = "pomodoros.json"
_estado: dict = {
    "ativo": False,
    "tipo": "trabalho",
    "inicio": None,
    "duracao": 0,
    "_timer": None,
}
_lock = threading.Lock()


def _load_sessoes() -> list:
    if not os.path.exists(_POMODORO_FILE):
        return []
    try:
        with open(_POMODORO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_sessao(tipo: str, minutos: int):
    sessoes = _load_sessoes()
    sessoes.append({
        "tipo": tipo,
        "minutos": minutos,
        "data": datetime.datetime.now().isoformat(),
    })
    try:
        with open(_POMODORO_FILE, "w", encoding="utf-8") as f:
            json.dump(sessoes[-500:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def iniciar(minutos: int, tipo: str, callback) -> str:
    """Inicia sessão pomodoro. tipo = 'trabalho' | 'pausa'."""
    global _estado
    with _lock:
        # Cancela timer anterior se ativo
        if _estado["ativo"] and _estado["_timer"]:
            _estado["_timer"].cancel()

        def _on_fim():
            with _lock:
                _estado["ativo"] = False
            _save_sessao(tipo, minutos)
            if tipo == "trabalho":
                msg = (
                    f"🍅 Pomodoro concluído, senhor! {minutos} minutos de foco completos. "
                    f"Hora de uma pausa merecida."
                )
            else:
                msg = f"☕ Pausa encerrada, senhor. Voltando ao trabalho."
            callback(msg)

        t = threading.Timer(minutos * 60, _on_fim)
        t.daemon = True
        t.start()
        _estado.update({
            "ativo": True,
            "tipo": tipo,
            "inicio": datetime.datetime.now(),
            "duracao": minutos,
            "_timer": t,
        })

    emoji = "🍅" if tipo == "trabalho" else "☕"
    return f"{emoji} Pomodoro de {minutos} minutos ({tipo}) iniciado, senhor. Foco total até o alerta."


def parar() -> str:
    global _estado
    with _lock:
        if not _estado["ativo"]:
            return "Nenhum pomodoro ativo no momento, senhor."
        if _estado["_timer"]:
            _estado["_timer"].cancel()
        tipo = _estado["tipo"]
        _estado["ativo"] = False
    return f"Pomodoro ({tipo}) cancelado, senhor."


def status() -> str:
    with _lock:
        ativo  = _estado["ativo"]
        inicio = _estado["inicio"]
        dur    = _estado["duracao"]
        tipo   = _estado["tipo"]

    if not ativo:
        sessoes     = _load_sessoes()
        hoje        = datetime.date.today().isoformat()
        n_trabalho  = sum(1 for s in sessoes if s["tipo"] == "trabalho" and s["data"][:10] == hoje)
        return f"Nenhum pomodoro ativo. Sessões de trabalho hoje: {n_trabalho}, senhor."

    elapsed  = max(0, (datetime.datetime.now() - inicio).seconds // 60)
    restante = max(0, dur - elapsed)
    emoji    = "🍅" if tipo == "trabalho" else "☕"
    return (
        f"{emoji} Pomodoro ({tipo}) em andamento — "
        f"{elapsed}min passados, ~{restante}min restantes, senhor."
    )


def listar_sessoes_hoje() -> str:
    sessoes   = _load_sessoes()
    hoje      = datetime.date.today().isoformat()
    hoje_s    = [s for s in sessoes if s["data"][:10] == hoje]
    if not hoje_s:
        return "Nenhuma sessão pomodoro hoje, senhor."
    trabalho  = sum(s["minutos"] for s in hoje_s if s["tipo"] == "trabalho")
    pausas    = sum(s["minutos"] for s in hoje_s if s["tipo"] == "pausa")
    n_trab    = sum(1 for s in hoje_s if s["tipo"] == "trabalho")
    return (
        f"📊 Pomodoro hoje — {n_trab} sessão(ões) de trabalho, "
        f"{trabalho} min de foco, {pausas} min de pausa, senhor."
    )
