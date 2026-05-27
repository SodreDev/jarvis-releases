# comandos/agenda_ctrl.py — J.A.R.V.I.S.
# Agenda / Calendário local (JSON)
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, os, datetime

_AGENDA_FILE = "agenda.json"


def _load() -> list:
    if not os.path.exists(_AGENDA_FILE):
        return []
    try:
        with open(_AGENDA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(eventos: list):
    with open(_AGENDA_FILE, "w", encoding="utf-8") as f:
        json.dump(eventos, f, ensure_ascii=False, indent=2)


def adicionar_evento(titulo: str, data: str, hora: str = "", descricao: str = "") -> str:
    """Adiciona evento à agenda. data=YYYY-MM-DD, hora=HH:MM."""
    titulo = titulo.strip()
    data   = data.strip()
    hora   = hora.strip()
    if not titulo or not data:
        return "Preciso do título e da data do evento, senhor."
    eventos = _load()
    eid = max((e.get("id", 0) for e in eventos), default=0) + 1
    eventos.append({
        "id": eid,
        "titulo": titulo,
        "data": data,
        "hora": hora,
        "descricao": descricao.strip(),
    })
    _save(eventos)
    hora_str = f" às {hora}" if hora else ""
    return f"Evento '{titulo}' agendado para {data}{hora_str}, senhor. (ID #{eid})"


def listar_hoje() -> str:
    hoje = datetime.date.today().isoformat()
    eventos = [e for e in _load() if e.get("data") == hoje]
    if not eventos:
        return f"Nenhum evento agendado para hoje ({hoje}), senhor."
    linhas = [f"📅 Agenda de hoje ({hoje}):"]
    for e in sorted(eventos, key=lambda x: x.get("hora", "")):
        hora_str = f" {e['hora']}" if e.get("hora") else ""
        desc_str = f" — {e['descricao']}" if e.get("descricao") else ""
        linhas.append(f"  [#{e['id']}]{hora_str} {e['titulo']}{desc_str}")
    return "\n".join(linhas)


def listar_proximos(dias: int = 7) -> str:
    hoje    = datetime.date.today()
    limite  = (hoje + datetime.timedelta(days=dias)).isoformat()
    hoje_s  = hoje.isoformat()
    eventos = [e for e in _load() if hoje_s <= e.get("data", "") <= limite]
    if not eventos:
        return f"Nenhum evento nos próximos {dias} dias, senhor."
    linhas = [f"📅 Próximos {dias} dias:"]
    for e in sorted(eventos, key=lambda x: (x.get("data", ""), x.get("hora", ""))):
        hora_str = f" {e['hora']}" if e.get("hora") else ""
        linhas.append(f"  {e['data']}{hora_str} — {e['titulo']}")
    return "\n".join(linhas)


def remover_evento(eid: int) -> str:
    eventos = _load()
    before  = len(eventos)
    eventos = [e for e in eventos if e.get("id") != eid]
    if len(eventos) == before:
        return f"Evento #{eid} não encontrado, senhor."
    _save(eventos)
    return f"Evento #{eid} removido da agenda, senhor."
