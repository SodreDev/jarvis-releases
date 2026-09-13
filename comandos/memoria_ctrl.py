# comandos/memoria_ctrl.py — J.A.R.V.I.S.
# Memória persistente por chave-valor + notas livres
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import datetime

_MEMORIA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "memoria.json"
)


def _carregar() -> dict:
    if not os.path.isfile(_MEMORIA_FILE):
        return {"facts": {}, "notes": []}
    with open(_MEMORIA_FILE, encoding="utf-8") as f:
        return json.load(f)


def _salvar(data: dict):
    with open(_MEMORIA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# —————————————————— Fatos ——————————————————


def salvar_fato(chave: str, valor: str) -> str:
    """Salva ou atualiza um fato sobre o usuário."""
    data = _carregar()
    chave_norm = chave.strip().lower()
    data["facts"][chave_norm] = {
        "valor": valor,
        "atualizado": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _salvar(data)
    return f"Anotado, senhor: {chave_norm} = {valor}"


def consultar_fato(chave: str) -> str | None:
    """Retorna o valor de um fato ou None."""
    data = _carregar()
    entry = data["facts"].get(chave.strip().lower())
    return entry["valor"] if entry else None


def listar_fatos() -> str:
    """Lista todos os fatos persistidos."""
    data = _carregar()
    if not data["facts"]:
        return "Nenhuma memória persistente, senhor."
    linhas = [f"Memória persistente ({len(data['facts'])} itens):"]
    for k, v in data["facts"].items():
        linhas.append(f"  • {k}: {v['valor']}")
    return "\n".join(linhas)


def remover_fato(chave: str) -> str:
    data = _carregar()
    chave_norm = chave.strip().lower()
    if chave_norm in data["facts"]:
        del data["facts"][chave_norm]
        _salvar(data)
        return f"Memória '{chave_norm}' removida, senhor."
    return f"Não encontrei '{chave_norm}' na memória, senhor."


# —————————————————— Notas livres ——————————————————


def salvar_nota(texto: str) -> str:
    """Salva uma nota livre."""
    data = _carregar()
    data["notes"].append({
        "texto": texto,
        "criado": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    _salvar(data)
    return f"Nota salva, senhor."


def listar_notas() -> str:
    data = _carregar()
    if not data["notes"]:
        return "Nenhuma nota salva, senhor."
    linhas = [f"Notas ({len(data['notes'])}):"]
    for i, n in enumerate(data["notes"], 1):
        linhas.append(f"  {i}. {n['texto']}")
    return "\n".join(linhas)


def remover_nota(indice: int) -> str:
    data = _carregar()
    if 1 <= indice <= len(data["notes"]):
        nota = data["notes"].pop(indice - 1)
        _salvar(data)
        return f"Nota removida: '{nota['texto'][:50]}...'"
    return f"Índice inválido, senhor. Tenho {len(data['notes'])} notas."


# —————————————————— Contexto para IA ——————————————————


def obter_contexto_ia() -> str:
    """Retorna resumo da memória para injetar no prompt da IA."""
    data = _carregar()
    partes = []
    if data["facts"]:
        fatos = "; ".join(f"{k}: {v['valor']}" for k, v in data["facts"].items())
        partes.append(f"Fatos sobre o usuário: {fatos}")
    if data["notes"]:
        ultimas = data["notes"][-5:]
        notas = "; ".join(n["texto"] for n in ultimas)
        partes.append(f"Últimas notas: {notas}")
    return "\n".join(partes) if partes else ""
