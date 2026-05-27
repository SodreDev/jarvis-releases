# comandos/rotinas_ctrl.py — J.A.R.V.I.S.
# Rotinas agendadas diárias (cron-like) — sem dependências externas
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import time
import datetime
import threading
import re
import uuid
from typing import Callable, Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
_FILE = os.path.join(_ROOT, "rotinas.json")

# ── Estrutura de uma rotina ───────────────────────────────────────────────────
# {
#   "id": "uuid4",
#   "nome": "Briefing matinal",
#   "hora": "08:00",            # HH:MM
#   "dias": ["seg","ter","qua","qui","sex","sab","dom"],  # "todo_dia" = todos
#   "acao": "briefing",         # acao para _executar_sys
#   "arg": "",
#   "ativo": true,
#   "ultima_execucao": "2026-03-08",
# }

_DIAS_SEMANA = {
    "seg": 0, "segunda": 0, "monday": 0,
    "ter": 1, "terça": 1, "tuesday": 1,
    "qua": 2, "quarta": 2, "wednesday": 2,
    "qui": 3, "quinta": 3, "thursday": 3,
    "sex": 4, "sexta": 4, "friday": 4,
    "sab": 5, "sábado": 5, "saturday": 5,
    "dom": 6, "domingo": 6, "sunday": 6,
}

_monitor_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_execute_cb: Optional[Callable[[str, str], None]] = None  # callback(acao, arg)


def _load() -> list[dict]:
    if os.path.exists(_FILE):
        try:
            with open(_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save(rotinas: list[dict]) -> None:
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(rotinas, f, ensure_ascii=False, indent=2)


def _normalizar_hora(texto: str) -> Optional[str]:
    """Extrai HH:MM de texto natural. Ex: '8h', '08:00', '20h30'"""
    m = re.search(r"(\d{1,2})[h:](\d{0,2})", texto.lower())
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    m2 = re.search(r"(\d{1,2})\s*h(?:oras?)?", texto.lower())
    if m2:
        h = int(m2.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    return None


def _normalizar_dias(texto: str) -> list[str]:
    """Converte 'todo dia', 'seg e sex', etc. para lista de abreviaçoes."""
    tl = texto.lower()
    if re.search(r"todo\s*dia|todos\s*os\s*dias|diariamente|daily|semana\s+toda", tl):
        return ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    if re.search(r"dia\s+de\s+semana|dias?\s+[uú]teis?|semana", tl):
        return ["seg", "ter", "qua", "qui", "sex"]
    if re.search(r"fim\s+de\s+semana|final\s+de\s+semana|weekend", tl):
        return ["sab", "dom"]
    dias = []
    for abrev, idx in _DIAS_SEMANA.items():
        if abrev in tl:
            dia_num_to_abrev = {0:"seg",1:"ter",2:"qua",3:"qui",4:"sex",5:"sab",6:"dom"}
            d = dia_num_to_abrev[idx]
            if d not in dias:
                dias.append(d)
    return dias if dias else ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def _deve_executar(rotina: dict, agora: datetime.datetime) -> bool:
    """Verifica se a rotina deve ser executada agora."""
    if not rotina.get("ativo", True):
        return False
    hora_str = rotina.get("hora", "")
    if not hora_str:
        return False
    try:
        h, m = map(int, hora_str.split(":"))
    except Exception:
        return False
    if agora.hour != h or agora.minute != m:
        return False
    # Verifica dias da semana
    dias = rotina.get("dias", [])
    if dias:
        abrev_hoje = ["seg","ter","qua","qui","sex","sab","dom"][agora.weekday()]
        if abrev_hoje not in dias:
            return False
    # Evita execução dupla no mesmo dia
    hoje_str = agora.strftime("%Y-%m-%d")
    if rotina.get("ultima_execucao") == hoje_str:
        return False
    return True


def _monitor_loop() -> None:
    """Loop que verifica e executa rotinas agendadas."""
    while not _stop_event.is_set():
        agora = datetime.datetime.now()
        # Verifica no início de cada minuto
        if agora.second == 0:
            rotinas = _load()
            atualizadas = False
            for rot in rotinas:
                if _deve_executar(rot, agora):
                    acao = rot.get("acao", "")
                    arg  = rot.get("arg", "")
                    print(f"[ROTINA] Executando '{rot['nome']}' — {acao}:{arg}")
                    if _execute_cb:
                        try:
                            _execute_cb(acao, arg)
                        except Exception as e:
                            print(f"[ROTINA] Erro em {rot['nome']}: {e}")
                    rot["ultima_execucao"] = agora.strftime("%Y-%m-%d")
                    atualizadas = True
            if atualizadas:
                _save(rotinas)
        _stop_event.wait(1)  # verifica a cada segundo


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start_monitor(execute_callback: Callable[[str, str], None]) -> None:
    """Inicia monitor de rotinas. Deve ser chamado no __init__ do JARVIS."""
    global _monitor_thread, _stop_event, _execute_cb
    _execute_cb = execute_callback
    _stop_event.clear()
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _monitor_thread.start()
    print("[ROTINAS] Monitor iniciado.")


def stop_monitor() -> None:
    _stop_event.set()


# ── API Pública ──────────────────────────────────────────────────────────────

def criar(
    nome: str,
    hora: str,
    acao: str,
    arg: str = "",
    dias: Optional[list[str]] = None,
) -> str:
    """Cria uma nova rotina agendada."""
    hora_fmt = _normalizar_hora(hora) or hora
    if not re.fullmatch(r"\d{2}:\d{2}", hora_fmt):
        return f"Hora inválida: '{hora}'. Use formato HH:MM ou '8h', '20h30', senhor."
    rotinas = _load()
    nova = {
        "id":              str(uuid.uuid4())[:8],
        "nome":            nome,
        "hora":            hora_fmt,
        "dias":            dias or ["seg","ter","qua","qui","sex","sab","dom"],
        "acao":            acao,
        "arg":             arg,
        "ativo":           True,
        "ultima_execucao": "",
        "criada_em":       datetime.datetime.now().isoformat()[:16],
    }
    rotinas.append(nova)
    _save(rotinas)
    dias_str = ", ".join(nova["dias"])
    return f"Rotina '{nome}' criada: todo(s) {dias_str} às {hora_fmt}, ação: {acao}, senhor."


def listar() -> str:
    """Lista todas as rotinas configuradas."""
    rotinas = _load()
    if not rotinas:
        return "Nenhuma rotina agendada, senhor."
    linhas = []
    for r in rotinas:
        estado = "✅" if r.get("ativo", True) else "⏸"
        dias = ", ".join(r.get("dias", []))
        linhas.append(
            f"{estado} [{r['id']}] '{r['nome']}' — {r['hora']} ({dias}) → {r['acao']}"
        )
    return f"Rotinas ({len(linhas)}):\n" + "\n".join(linhas)


def pausar_rotina(id_ou_nome: str) -> str:
    rotinas = _load()
    for r in rotinas:
        if r["id"] == id_ou_nome or r["nome"].lower() == id_ou_nome.lower():
            r["ativo"] = False
            _save(rotinas)
            return f"Rotina '{r['nome']}' pausada, senhor."
    return f"Rotina '{id_ou_nome}' não encontrada, senhor."


def retomar_rotina(id_ou_nome: str) -> str:
    rotinas = _load()
    for r in rotinas:
        if r["id"] == id_ou_nome or r["nome"].lower() == id_ou_nome.lower():
            r["ativo"] = True
            r["ultima_execucao"] = ""  # permite executar hoje
            _save(rotinas)
            return f"Rotina '{r['nome']}' retomada, senhor."
    return f"Rotina '{id_ou_nome}' não encontrada, senhor."


def remover(id_ou_nome: str) -> str:
    rotinas = _load()
    antes = len(rotinas)
    rotinas = [r for r in rotinas
               if r["id"] != id_ou_nome and r["nome"].lower() != id_ou_nome.lower()]
    if len(rotinas) == antes:
        return f"Rotina '{id_ou_nome}' não encontrada, senhor."
    _save(rotinas)
    return f"Rotina '{id_ou_nome}' removida, senhor."


def proximas(n: int = 5) -> str:
    """Lista as próximas rotinas que serão executadas."""
    rotinas = [r for r in _load() if r.get("ativo", True)]
    if not rotinas:
        return "Nenhuma rotina ativa, senhor."
    agora = datetime.datetime.now()
    hoje_num = agora.weekday()
    _dia_abbr = ["seg","ter","qua","qui","sex","sab","dom"]
    resultados = []
    for r in rotinas:
        try:
            h, m = map(int, r["hora"].split(":"))
        except Exception:
            continue
        for offset in range(7):
            dia_alvo = (hoje_num + offset) % 7
            dia_s = _dia_abbr[dia_alvo]
            if dia_s in r.get("dias", _dia_abbr):
                dt_alvo = agora + datetime.timedelta(days=offset)
                dt_alvo = dt_alvo.replace(hour=h, minute=m, second=0, microsecond=0)
                if dt_alvo > agora:
                    resultados.append((dt_alvo, r["nome"], r["acao"]))
                    break
    resultados.sort(key=lambda x: x[0])
    linhas = [
        f"• {dt.strftime('%d/%m %H:%M')} — '{nome}' ({acao})"
        for dt, nome, acao in resultados[:n]
    ]
    if not linhas:
        return "Nenhuma execução nas próximas horas, senhor."
    return f"Próximas rotinas:\n" + "\n".join(linhas)
