# comandos/notif_history.py — Histórico persistente de notificações
# Instagram: 30 dias | WhatsApp: 7 dias | Discord: não armazena
# -*- coding: utf-8 -*-

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from config import PATHS

# ── Config ────────────────────────────────────────────────────────────────────
_HISTORY_FILE = PATHS["notif_history"]
_RETENTION_DAYS = {
    "instagram": 30,
    "whatsapp":  7,
}
# Discord não é armazenado

_lock = threading.Lock()


# ── Formato de cada linha ─────────────────────────────────────────────────────
# {"ts": "2026-03-01T14:30:00-03:00", "app": "instagram", "sender": "mae",
#  "msgs": [{"type": "text", "content": "Oi filho", "ts": "..."}],
#  "auto_replied": false, "reply_text": ""}  ← campos adicionais opcionais


def salvar(app_key: str, sender: str, msgs: list[dict],
          auto_replied: bool = False, reply_text: str = "") -> None:
    """
    Salva uma notificação no JSONL.
    Ignora apps sem retenção (Discord) a não ser que seja um auto-reply
    (nesse caso salva com retenção de 30 dias para o relatório de away).
    """
    # Discord sem auto-reply: descarta
    if app_key not in _RETENTION_DAYS and not auto_replied:
        return
    agora = datetime.now(timezone.utc).astimezone()
    ts_str = agora.isoformat(timespec="seconds")
    # Garante que cada msg tenha timestamp (usa o horário atual se não tiver)
    for m in msgs:
        if "ts" not in m:
            m["ts"] = ts_str
    entry: dict = {
        "ts":     ts_str,
        "app":    app_key,
        "sender": sender,
        "msgs":   msgs,
    }
    if auto_replied:
        entry["auto_replied"] = True
        entry["reply_text"] = reply_text
    with _lock:
        try:
            with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[HIST] Erro ao salvar: {e}")


def _carregar_tudo() -> list[dict]:
    """Carrega todas as linhas do JSONL."""
    if not os.path.isfile(_HISTORY_FILE):
        return []
    entries = []
    with _lock:
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            print(f"[HIST] Erro ao carregar: {e}")
    return entries


def purgar_expirados() -> int:
    """Remove entradas além do período de retenção. Retorna qtd removidas."""
    entries = _carregar_tudo()
    if not entries:
        return 0
    agora = datetime.now(timezone.utc)
    kept = []
    removed = 0
    for e in entries:
        app = e.get("app", "")
        # Entradas com auto_replied usam retenção de 30 dias mesmo para Discord
        if e.get("auto_replied"):
            ret_days = 30
        else:
            ret_days = _RETENTION_DAYS.get(app)
        if ret_days is None:
            removed += 1
            continue
        try:
            ts = datetime.fromisoformat(e["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = agora - ts.astimezone(timezone.utc)
            if age > timedelta(days=ret_days):
                removed += 1
                continue
        except Exception:
            removed += 1
            continue
        kept.append(e)
    if removed > 0:
        with _lock:
            try:
                with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                    for e in kept:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
            except Exception as ex:
                print(f"[HIST] Erro ao purgar: {ex}")
    return removed


def consultar(app_key: str | None = None,
              de: datetime | None = None,
              ate: datetime | None = None,
              sender: str | None = None,
              so_away_replies: bool = False) -> list[dict]:
    """
    Consulta o histórico filtrado.
    - app_key: "instagram" | "whatsapp" | None (todos)
    - de/ate: intervalo de datas (inclusive)
    - sender: filtrar por remetente (substring, case-insensitive)
    - so_away_replies: se True, retorna apenas entradas com auto_replied=True
    """
    entries = _carregar_tudo()
    results = []
    for e in entries:
        if app_key and e.get("app") != app_key:
            continue
        if sender and sender.lower() not in e.get("sender", "").lower():
            continue
        if so_away_replies and not e.get("auto_replied"):
            continue
        try:
            ts = datetime.fromisoformat(e["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_local = ts.astimezone()
        except Exception:
            continue
        if de and ts_local < de:
            continue
        if ate and ts_local > ate:
            continue
        results.append(e)
    return results


def ultimas(n: int = 20, app_key: str | None = None) -> list[dict]:
    """Retorna as N entradas mais recentes (opcionalmente filtradas por app)."""
    entries = _carregar_tudo()
    if app_key:
        entries = [e for e in entries if e.get("app") == app_key]
    return entries[-n:]


# ── Formatação de relatório ───────────────────────────────────────────────────

def _ts_legivel(ts_str: str) -> str:
    """Converte ISO timestamp para formato legível em PT-BR."""
    try:
        dt = datetime.fromisoformat(ts_str).astimezone()
        agora = datetime.now(timezone.utc).astimezone()
        diff = agora - dt
        if diff.days == 0:
            return f"hoje às {dt.strftime('%H:%M')}"
        elif diff.days == 1:
            return f"ontem às {dt.strftime('%H:%M')}"
        elif diff.days < 7:
            dias = ["segunda", "terça", "quarta", "quinta",
                    "sexta", "sábado", "domingo"]
            return f"{dias[dt.weekday()]} às {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%d/%m às %H:%M")
    except Exception:
        return ts_str


def formatar_ultimas(entries: list[dict]) -> str:
    """Formata lista de entries em texto para leitura do JARVIS."""
    if not entries:
        return "Não há notificações nesse período, senhor."

    # Agrupa por app + sender
    from collections import OrderedDict
    grupos: dict[str, dict[str, list]] = OrderedDict()
    for e in entries:
        app = e.get("app", "?")
        sender = e.get("sender", "?")
        ts = e.get("ts", "")
        msgs = e.get("msgs", [])
        key = f"{app}|{sender}"
        if key not in grupos:
            grupos[key] = {"app": app, "sender": sender, "entries": []}
        grupos[key]["entries"].append({"ts": ts, "msgs": msgs})

    app_nomes = {"instagram": "Instagram", "whatsapp": "WhatsApp"}
    partes = []
    for key, grp in grupos.items():
        app_nome = app_nomes.get(grp["app"], grp["app"])
        sender = grp["sender"]
        n_total = sum(len(e["msgs"]) for e in grp["entries"])
        ultimo_ts = grp["entries"][-1]["ts"]
        # Mostra horário da última interação
        quando = _ts_legivel(ultimo_ts)

        # Junta conteúdos de texto
        textos = []
        for ent in grp["entries"]:
            for m in ent["msgs"]:
                c = m.get("content", "")
                t = m.get("type", "text")
                if t == "text" and c:
                    textos.append(c)
                elif t == "audio":
                    textos.append("[áudio]")
                elif t == "media":
                    textos.append(m.get("content", "[mídia]"))

        resumo_msgs = "; ".join(textos[:5])
        if len(textos) > 5:
            resumo_msgs += f" e mais {len(textos) - 5} mensagem(ns)"

        partes.append(
            f"{sender} no {app_nome} ({quando}, "
            f"{n_total} mensagem{'ns' if n_total > 1 else ''}): "
            f"{resumo_msgs}"
        )

    return "Senhor, as últimas notificações: " + ". ".join(partes) + "."


def formatar_resumo(entries: list[dict], periodo_desc: str = "") -> str:
    """Formata um resumo compacto para um período."""
    if not entries:
        return f"Não há notificações {periodo_desc}, senhor."

    # Conta por app e sender
    contagem: dict[str, dict[str, int]] = {}
    for e in entries:
        app = e.get("app", "?")
        sender = e.get("sender", "?")
        n = len(e.get("msgs", []))
        contagem.setdefault(app, {})
        contagem[app][sender] = contagem[app].get(sender, 0) + n

    app_nomes = {"instagram": "Instagram", "whatsapp": "WhatsApp"}
    partes = []
    total_geral = 0
    for app, senders in contagem.items():
        app_nome = app_nomes.get(app, app)
        total_app = sum(senders.values())
        total_geral += total_app
        top = sorted(senders.items(), key=lambda x: -x[1])[:5]
        remetentes = ", ".join(f"{s} ({n})" for s, n in top)
        if len(senders) > 5:
            remetentes += f" e mais {len(senders) - 5}"
        partes.append(f"{app_nome}: {total_app} mensagens de {len(senders)} "
                      f"contato{'s' if len(senders) > 1 else ''} — {remetentes}")

    header = f"Resumo {periodo_desc}: {total_geral} notificações no total. "
    return "Senhor, " + header + ". ".join(partes) + "."
