# comandos/contato_ctrl.py — Gerenciamento de contatos (agenda)
# -*- coding: utf-8 -*-
"""
CRUD simples sobre contatos.json + import VCF reaproveitando importar_contatos.
Formato de contatos.json: { "Nome Title-Cased": "+55DDDNUMERO", "_meta": ... }
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from config import PATHS

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTATOS_FILE = PATHS["contatos"]
COUNTRY_CODE = "55"


def _load() -> dict:
    if not os.path.isfile(CONTATOS_FILE):
        return {}
    try:
        with open(CONTATOS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(db: dict) -> None:
    with open(CONTATOS_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def _normalizar_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if not digits.startswith(COUNTRY_CODE):
        digits = COUNTRY_CODE + digits
    return f"+{digits}"


def _eh_meta(k: str) -> bool:
    return k.startswith("_")


def adicionar(nome: str, telefone: str) -> str:
    nome = (nome or "").strip().title()
    if not nome:
        return "ERRO: nome vazio."
    phone = _normalizar_phone(telefone)
    if not phone or len(phone) < 10:
        return "ERRO: telefone inválido."
    db = _load()
    existente = db.get(nome)
    db[nome] = phone
    _save(db)
    if existente and existente != phone:
        return f"Atualizei {nome}: {existente} → {phone}."
    if existente:
        return f"{nome} já estava salvo com esse número."
    return f"Contato salvo: {nome} → {phone}."


def remover(nome: str) -> str:
    nome_q = (nome or "").strip().lower()
    if not nome_q:
        return "ERRO: nome vazio."
    db = _load()
    alvo = None
    for k in db:
        if _eh_meta(k):
            continue
        if k.lower() == nome_q:
            alvo = k
            break
    if not alvo:
        # match parcial
        for k in db:
            if _eh_meta(k):
                continue
            if nome_q in k.lower():
                alvo = k
                break
    if not alvo:
        return f"Não encontrei '{nome}' na agenda."
    phone = db.pop(alvo)
    _save(db)
    return f"Removido: {alvo} ({phone})."


def buscar(query: str) -> str:
    q = (query or "").strip().lower()
    if not q:
        return "ERRO: busca vazia."
    db = _load()
    matches: list[tuple[str, str]] = []
    for k, v in db.items():
        if _eh_meta(k):
            continue
        if q in k.lower() or q in str(v):
            matches.append((k, str(v)))
    if not matches:
        return f"Nenhum contato com '{query}'."
    if len(matches) == 1:
        n, p = matches[0]
        return f"{n}: {p}"
    linhas = "\n".join(f"• {n}: {p}" for n, p in matches[:15])
    extra = "" if len(matches) <= 15 else f"\n... e mais {len(matches)-15}."
    return f"{len(matches)} contatos:\n{linhas}{extra}"


def listar(top: int = 20) -> str:
    db = _load()
    nomes = [k for k in db if not _eh_meta(k)]
    if not nomes:
        return "Agenda vazia."
    nomes.sort()
    amostra = nomes[:top]
    extra = "" if len(nomes) <= top else f"\n... e mais {len(nomes)-top}."
    return f"{len(nomes)} contatos. Primeiros {len(amostra)}:\n" + "\n".join(f"• {n}" for n in amostra) + extra


def importar_vcf(caminho: str) -> str:
    if not caminho or not os.path.isfile(caminho):
        return f"ERRO: arquivo não encontrado: {caminho}"
    try:
        # Reaproveita o parser existente
        import sys as _sys
        _sys.path.insert(0, _BASE)
        from importar_contatos import importar as _imp
        n = _imp(caminho, preview=False)
        return f"Importação concluída: {n} contatos no arquivo."
    except Exception as e:
        return f"ERRO importando VCF: {e}"
