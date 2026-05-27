# comandos/alarme_ctrl.py — J.A.R.V.I.S.
# Alarmes e lembretes com persistência JSON (sobrevive a reinícios)
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import threading
import datetime
import time

from config import PATHS

_ALARMES_FILE = PATHS["alarmes"]
_lock = threading.Lock()
_timers_ativos: dict[str, threading.Timer] = {}


def _carregar() -> list[dict]:
    if not os.path.isfile(_ALARMES_FILE):
        return []
    with open(_ALARMES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _salvar(alarmes: list[dict]):
    with open(_ALARMES_FILE, "w", encoding="utf-8") as f:
        json.dump(alarmes, f, ensure_ascii=False, indent=2)


def _gerar_id() -> str:
    return f"a{int(time.time() * 1000) % 1_000_000}"


def criar_alarme(segundos: int, descricao: str, callback) -> str:
    """
    Cria um alarme que dispara em `segundos`.
    `callback(mensagem)` é chamado quando disparar.
    Retorna mensagem de confirmação.
    Persiste em disco para verificação na próxima inicialização.
    """
    alarme_id = _gerar_id()
    agora = datetime.datetime.now()
    disparo = agora + datetime.timedelta(seconds=segundos)

    alarme = {
        "id": alarme_id,
        "descricao": descricao,
        "criado": agora.isoformat(timespec="seconds"),
        "disparo": disparo.isoformat(timespec="seconds"),
        "disparou": False,
        "notificado": False,
    }

    with _lock:
        alarmes = _carregar()
        alarmes.append(alarme)
        _salvar(alarmes)

    # Agenda o timer em memória
    _agendar_timer(alarme_id, segundos, descricao, callback)

    dur = _fmt_duracao(segundos)
    hora = disparo.strftime("%H:%M")
    return (
        f"Alarme criado, senhor. '{descricao}' em {dur} "
        f"(às {hora})."
    )


def _agendar_timer(alarme_id: str, segundos: int, descricao: str, callback):
    """Agenda timer em memória para disparar o alarme."""
    def _disparar():
        _marcar_disparado(alarme_id)
        with _lock:
            _timers_ativos.pop(alarme_id, None)
        callback(
            f"⏰ Alarme disparando: '{descricao}', Senhor!"
        )

    t = threading.Timer(max(0.1, segundos), _disparar)
    t.daemon = True
    with _lock:
        # Cancela timer anterior se existir
        old = _timers_ativos.pop(alarme_id, None)
        if old:
            old.cancel()
        _timers_ativos[alarme_id] = t
    t.start()


def _marcar_disparado(alarme_id: str):
    """Marca o alarme como disparado no JSON."""
    with _lock:
        alarmes = _carregar()
        for a in alarmes:
            if a["id"] == alarme_id:
                a["disparou"] = True
                a["notificado"] = True
                break
        _salvar(alarmes)


def verificar_alarmes_perdidos() -> list[str]:
    """
    Verifica alarmes que deveriam ter disparado enquanto JARVIS estava offline.
    Retorna lista de mensagens para cada alarme perdido.
    """
    agora = datetime.datetime.now()
    mensagens = []

    with _lock:
        alarmes = _carregar()
        modificado = False
        for a in alarmes:
            if a["disparou"] and a["notificado"]:
                continue  # já tratado
            disparo = datetime.datetime.fromisoformat(a["disparo"])
            if disparo <= agora and not a["disparou"]:
                # Alarme perdido — JARVIS não estava ativo
                a["disparou"] = True
                a["notificado"] = True
                modificado = True
                mensagens.append(
                    f"⚠️ Senhor, o alarme '{a['descricao']}' "
                    f"(programado para {disparo.strftime('%H:%M de %d/%m')}) "
                    f"não foi ativado porque eu não estava iniciado."
                )
        if modificado:
            _salvar(alarmes)

    return mensagens


def reagendar_alarmes_pendentes(callback):
    """
    Na inicialização, reagenda alarmes futuros que ainda não dispararam.
    """
    agora = datetime.datetime.now()
    with _lock:
        alarmes = _carregar()
        for a in alarmes:
            if a["disparou"]:
                continue
            disparo = datetime.datetime.fromisoformat(a["disparo"])
            restante = (disparo - agora).total_seconds()
            if restante > 0:
                _agendar_timer(a["id"], restante, a["descricao"], callback)
                print(f"[ALARME] Reagendado: '{a['descricao']}' em {int(restante)}s")


def listar_alarmes() -> str:
    """Lista alarmes pendentes (não disparados)."""
    agora = datetime.datetime.now()
    with _lock:
        alarmes = _carregar()

    pendentes = [a for a in alarmes if not a["disparou"]]
    if not pendentes:
        return "Nenhum alarme ativo, senhor."

    linhas = [f"Alarmes ativos ({len(pendentes)}):"]
    for a in pendentes:
        disparo = datetime.datetime.fromisoformat(a["disparo"])
        restante = max(0, int((disparo - agora).total_seconds()))
        linhas.append(
            f"  • {a['descricao']} — {disparo.strftime('%H:%M %d/%m')} "
            f"(em {_fmt_duracao(restante)})"
        )
    return "\n".join(linhas)


def cancelar_alarmes() -> str:
    """Cancela todos os alarmes pendentes."""
    with _lock:
        n = 0
        for tid, t in list(_timers_ativos.items()):
            t.cancel()
            n += 1
        _timers_ativos.clear()

        alarmes = _carregar()
        for a in alarmes:
            if not a["disparou"]:
                a["disparou"] = True
                a["notificado"] = True
        _salvar(alarmes)

    return f"{n} alarme(s) cancelado(s), senhor." if n else "Nenhum alarme ativo, senhor."


def limpar_historico():
    """Remove alarmes já disparados do JSON (manutenção)."""
    with _lock:
        alarmes = _carregar()
        alarmes = [a for a in alarmes if not a["disparou"]]
        _salvar(alarmes)


def _fmt_duracao(secs: int) -> str:
    if secs >= 86400:
        n = secs // 86400
        return f"{n} dia{'s' if n > 1 else ''}"
    if secs >= 3600:
        h, m = divmod(secs // 60, 60)
        return f"{h}h{m:02d}min" if m else f"{h}h"
    if secs >= 60:
        return f"{secs // 60} min"
    return f"{secs}s"
