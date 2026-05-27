# comandos/descanso_ctrl.py — J.A.R.V.I.S.
# Timer de descanso ergonômico (lembretes para levantar, beber água, etc.)
# -*- coding: utf-8 -*-

from __future__ import annotations
import threading
import time
import datetime
import json
import os
from typing import Callable, Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
_HIST_FILE = os.path.join(_ROOT, "descanso_hist.json")

# ── Tipos de lembrete ─────────────────────────────────────────────────────────
_TIPOS = {
    "levantar":   ("Hora de levantar e se movimentar, senhor. Alguns minutos de caminhada fazem diferença.", "🦵"),
    "agua":       ("Hora de beber água, senhor. Hidratação é fundamental para a concentração.", "💧"),
    "olhos":      ("Hora do descanso ocular, senhor. Olhe para algo distante por 20 segundos — regra 20-20-20.", "👁"),
    "alongar":    ("Hora de se alongar, senhor. Ombros, pescoço e pulsos agradecem.", "🤸"),
    "respira":    ("Uma pausa para respirar fundo, senhor. Inspire por 4 segundos, expire por 6.", "🫁"),
    "geral":      ("Hora de uma pausa, senhor. Levante, se mova, descanse os olhos.", "⏸"),
}

# ── Estado global ─────────────────────────────────────────────────────────────
_timers: list[threading.Timer] = []
_paused: bool = False
_intervalo_config: dict = {}
_callback_ref: Optional[Callable[[str], None]] = None


def _load_hist() -> list:
    if os.path.exists(_HIST_FILE):
        try:
            with open(_HIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_hist(entrada: dict) -> None:
    hist = _load_hist()
    hist.append(entrada)
    hist = hist[-200:]  # Mantém últimos 200
    with open(_HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _lancar_timer(intervalo_s: int, tipo: str, callback: Callable[[str], None],
                  repetir: bool = True) -> threading.Timer:
    def _disparar():
        global _paused
        if not _paused:
            msg, icone = _TIPOS.get(tipo, _TIPOS["geral"])
            full_msg = f"{icone} {msg}"
            try:
                callback(full_msg)
            except Exception:
                pass
            _save_hist({
                "ts": datetime.datetime.now().isoformat(),
                "tipo": tipo,
                "mensagem": msg,
            })
        if repetir and not _paused:
            t = _lancar_timer(intervalo_s, tipo, callback, repetir)
            _timers.append(t)

    t = threading.Timer(intervalo_s, _disparar)
    t.daemon = True
    t.start()
    return t


# ── API Pública ──────────────────────────────────────────────────────────────

def iniciar(
    intervalo_min: int,
    tipo: str = "geral",
    callback: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Inicia lembretes de descanso a cada `intervalo_min` minutos.
    tipo: levantar | agua | olhos | alongar | respira | geral
    """
    global _timers, _paused, _intervalo_config, _callback_ref

    parar()  # Cancela timers existentes
    _paused = False

    tipo_n = tipo.lower().strip()
    if tipo_n not in _TIPOS:
        tipo_n = "geral"

    intervalo_s = intervalo_min * 60
    _intervalo_config = {"intervalo_min": intervalo_min, "tipo": tipo_n}
    _callback_ref = callback

    cb = callback or (lambda m: print(f"[DESCANSO] {m}"))
    t = _lancar_timer(intervalo_s, tipo_n, cb, repetir=True)
    _timers.append(t)

    _, icone = _TIPOS[tipo_n]
    return (
        f"{icone} Lembretes de '{tipo_n}' a cada {intervalo_min} minuto(s) ativados, senhor. "
        f"Vou avisá-lo regularmente."
    )


def parar() -> str:
    """Cancela todos os timers de descanso."""
    global _timers, _paused
    for t in _timers:
        try:
            t.cancel()
        except Exception:
            pass
    _timers.clear()
    _paused = False
    return "Lembretes de descanso cancelados, senhor."


def pausar() -> str:
    """Pausa temporariamente — os timers continuam mas não disparam."""
    global _paused
    _paused = True
    return "Lembretes pausados, senhor. Use 'retomar descanso' para continuar."


def retomar() -> str:
    """Retoma após pausa — relança os timers com o último intervalo configurado."""
    global _paused
    _paused = False
    if _intervalo_config and _callback_ref:
        iniciar(_intervalo_config["intervalo_min"], _intervalo_config["tipo"], _callback_ref)
        return "Lembretes de descanso retomados, senhor."
    _paused = False
    return "Lembretes retomados, senhor (configure novamente se necessário)."


def status() -> str:
    """Retorna o status atual dos lembretes."""
    timers_ativos = [t for t in _timers if t.is_alive()]
    if not timers_ativos:
        return "Nenhum lembrete de descanso ativo, senhor."
    conf = _intervalo_config
    tipo  = conf.get("tipo", "geral")
    intv  = conf.get("intervalo_min", "?")
    estado = "pausado" if _paused else "ativo"
    _, icone = _TIPOS.get(tipo, _TIPOS["geral"])
    return f"{icone} Lembrete '{tipo}' a cada {intv}min — {estado}, senhor."


def historico(n: int = 10) -> str:
    """Retorna os últimos `n` lembretes disparados."""
    hist = _load_hist()[-n:]
    if not hist:
        return "Nenhum lembrete disparado ainda, senhor."
    linhas = []
    for h in reversed(hist):
        ts   = h.get("ts", "")[:16].replace("T", " ")
        tipo = h.get("tipo", "geral")
        _, icone = _TIPOS.get(tipo, _TIPOS["geral"])
        linhas.append(f"{icone} [{ts}] {tipo}")
    return f"Últimos {len(linhas)} lembretes:\n" + "\n".join(linhas)


# Alias
def iniciar_hidratacao(intervalo_min: int = 30, callback=None) -> str:
    return iniciar(intervalo_min, "agua", callback)


def iniciar_ergonomia(intervalo_min: int = 60, callback=None) -> str:
    return iniciar(intervalo_min, "levantar", callback)
