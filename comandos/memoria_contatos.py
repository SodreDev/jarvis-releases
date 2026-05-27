# comandos/memoria_contatos.py — J.A.R.V.I.S.
# Memória individual por contato: perfis + busca semântica por embeddings.
#
# Estrutura de diretórios:
#   data/memoria_contatos/_perfis.json          — fatos / metadados por contato
#   data/memoria_contatos/mensagens/<slug>.jsonl — mensagens (ts, app, direcao, texto)
#   data/memoria_contatos/vetores/<slug>.npy     — vetores float32 [N, 384]
#
# A busca semântica usa sentence-transformers/all-MiniLM-L6-v2 (o mesmo
# modelo já carregado pelo classificador). Se não disponível, faz busca
# por data (últimas k mensagens).
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import re
import unicodedata
import datetime
import threading
from typing import Optional

_BASE         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONTATOS_DIR = os.path.join(_BASE, "data", "memoria_contatos")
_MSG_DIR      = os.path.join(_CONTATOS_DIR, "mensagens")
_VET_DIR      = os.path.join(_CONTATOS_DIR, "vetores")
_PERFIS_FILE  = os.path.join(_CONTATOS_DIR, "_perfis.json")

_lock = threading.Lock()

# Cache em memória: {slug: np.ndarray shape [N, 384]}
_embed_cache: dict[str, "np.ndarray"] = {}
# Cache de textos paralelo ao embed: {slug: list[str]}
_texto_cache: dict[str, list[str]]    = {}

_model = None  # SentenceTransformer singleton (lazy)
_model_lock = threading.Lock()


# ─── helpers internos ─────────────────────────────────────────────────────────

def _garantir_dir():
    os.makedirs(_MSG_DIR, exist_ok=True)
    os.makedirs(_VET_DIR, exist_ok=True)


def _slug(nome: str) -> str:
    """Normaliza nome → snake_case sem acentos (ex: 'Lilian Silva' → 'lilian_silva')."""
    s = unicodedata.normalize("NFD", nome.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # remove acentos
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "contato"


def _jsonl_path(slug: str) -> str:
    return os.path.join(_MSG_DIR, f"{slug}.jsonl")


def _npy_path(slug: str) -> str:
    return os.path.join(_VET_DIR, f"{slug}.npy")


def _migrar_layout_antigo():
    """Move arquivos do layout antigo (raiz) para os subdiretórios corretos.
    Executado uma única vez na importação do módulo."""
    if not os.path.isdir(_CONTATOS_DIR):
        return
    try:
        os.makedirs(_MSG_DIR, exist_ok=True)
        os.makedirs(_VET_DIR, exist_ok=True)
        for nome in os.listdir(_CONTATOS_DIR):
            origem = os.path.join(_CONTATOS_DIR, nome)
            if not os.path.isfile(origem):
                continue
            if nome.endswith(".jsonl") and nome != "_perfis.jsonl":
                destino = os.path.join(_MSG_DIR, nome)
                if not os.path.exists(destino):
                    os.rename(origem, destino)
            elif nome.endswith(".npy"):
                destino = os.path.join(_VET_DIR, nome)
                if not os.path.exists(destino):
                    os.rename(origem, destino)
    except Exception as _e_mig:
        print(f"[MEM CONTATOS] Aviso na migração de layout: {_e_mig}")


_migrar_layout_antigo()


def _ler_jsonl(slug: str) -> list[dict]:
    path = _jsonl_path(slug)
    if not os.path.isfile(path):
        return []
    linhas = []
    with open(path, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    linhas.append(json.loads(linha))
                except json.JSONDecodeError:
                    pass
    return linhas


def _append_jsonl(slug: str, entry: dict):
    _garantir_dir()
    with open(_jsonl_path(slug), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _carregar_perfis() -> dict:
    if not os.path.isfile(_PERFIS_FILE):
        return {}
    with open(_PERFIS_FILE, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _salvar_perfis(dados: dict):
    _garantir_dir()
    with open(_PERFIS_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


# ─── Modelo de embedding (lazy, singleton) ────────────────────────────────────

def _get_model():
    """Retorna SentenceTransformer singleton. None se não disponível."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            # Lê EMBEDDING_MODEL de config para consistência
            try:
                from config import EMBEDDING_MODEL as _em
                model_name = _em
            except ImportError:
                model_name = "sentence-transformers/all-MiniLM-L6-v2"
            _model = SentenceTransformer(model_name)
            print(f"[MEM CONTATOS] Modelo de embedding carregado: {model_name}")
        except Exception as e:
            print(f"[MEM CONTATOS] sentence-transformers indisponível ({e}) — usando busca por data.")
            _model = None
    return _model


def _embed(textos: list[str]) -> "Optional[np.ndarray]":
    """Gera embeddings para uma lista de textos. Retorna None se modelo ausente."""
    m = _get_model()
    if m is None:
        return None
    try:
        import numpy as np
        vecs = m.encode(textos, convert_to_numpy=True, show_progress_bar=False)
        return vecs.astype("float32")
    except Exception as e:
        print(f"[MEM CONTATOS] Erro ao embedar: {e}")
        return None


def _cosine_top_k(query_vec: "np.ndarray", matrix: "np.ndarray", k: int) -> list[int]:
    """Retorna índices dos top-k vetores mais similares ao query (cosine sim)."""
    import numpy as np
    # Normaliza
    qn = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    mn = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    sims = mn @ qn
    k = min(k, len(sims))
    return list(np.argsort(sims)[::-1][:k])


# ─── Cache de vetores em RAM ──────────────────────────────────────────────────

def _carregar_cache(slug: str):
    """Carrega vetores .npy e textos .jsonl para memória se ainda não carregados."""
    if slug in _embed_cache:
        return
    npy_p = _npy_path(slug)
    import numpy as np
    if os.path.isfile(npy_p):
        try:
            _embed_cache[slug] = np.load(npy_p)
        except Exception:
            _embed_cache[slug] = np.empty((0, 384), dtype="float32")
    else:
        _embed_cache[slug] = np.empty((0, 384), dtype="float32")

    linhas = _ler_jsonl(slug)
    _texto_cache[slug] = [l.get("texto", "") for l in linhas]


def _salvar_cache(slug: str):
    """Persiste vetores em RAM para disco."""
    if slug not in _embed_cache:
        return
    import numpy as np
    _garantir_dir()
    np.save(_npy_path(slug), _embed_cache[slug])


# ─── API pública ──────────────────────────────────────────────────────────────

def registrar_mensagem(
    contato: str,
    app: str,
    texto: str,
    direcao: str = "recebida",   # "recebida" | "enviada"
):
    """
    Grava uma mensagem do/para um contato e atualiza o índice de embeddings.
    Operação incremental — não reembed o histórico inteiro.
    Thread-safe.
    """
    if not texto or not texto.strip():
        return

    slug = _slug(contato)
    ts   = datetime.datetime.now().isoformat(timespec="seconds")
    entry = {
        "ts":       ts,
        "app":      app,
        "direcao":  direcao,
        "texto":    texto.strip(),
        "contato":  contato,
    }

    with _lock:
        _append_jsonl(slug, entry)

        # Atualiza perfil: apps usados e last_seen
        perfis = _carregar_perfis()
        perfil = perfis.setdefault(slug, {
            "display_name": contato,
            "apps": [],
            "facts": {},
            "last_seen": ts,
        })
        if app not in perfil.get("apps", []):
            perfil.setdefault("apps", []).append(app)
        if direcao == "recebida":
            perfil["last_seen"] = ts
        perfis[slug] = perfil
        _salvar_perfis(perfis)

        # Atualiza embedding incremental
        vec = _embed([texto.strip()])
        if vec is not None:
            import numpy as np
            _carregar_cache(slug)
            _embed_cache[slug] = np.vstack([_embed_cache[slug], vec])
            _texto_cache[slug].append(texto.strip())
            _salvar_cache(slug)


def buscar_contexto(
    contato: str,
    query: str,
    k: int = 3,
) -> str:
    """
    Busca as k mensagens mais relevantes para 'query' no histórico do contato.

    Retorna string formatada para injetar como contexto adicional no prompt.
    Retorna "" se não houver histórico ou se query for vazio.
    """
    if not query or not contato:
        return ""

    slug = _slug(contato)

    with _lock:
        _carregar_cache(slug)
        matrix = _embed_cache.get(slug)
        textos = _texto_cache.get(slug, [])

    import numpy as np

    # Verifica se há vetores suficientes
    if matrix is None or len(matrix) == 0 or len(textos) == 0:
        return ""

    # Tentativa com embedding semântico
    q_vec = _embed([query])
    if q_vec is not None and len(q_vec) > 0:
        try:
            indices = _cosine_top_k(q_vec[0], matrix, k)
        except Exception:
            indices = list(range(min(k, len(textos))))[::-1]
    else:
        # Fallback: últimas k mensagens
        indices = list(range(max(0, len(textos) - k), len(textos)))[::-1]

    # Lê datas do JSONL para enriquecer o resultado
    linhas = _ler_jsonl(slug)
    partes = []
    for i in sorted(set(indices)):
        if i < len(linhas):
            l = linhas[i]
            data = l.get("ts", "")[:10]
            direcao_label = "recebida" if l.get("direcao", "recebida") == "recebida" else "enviada"
            app_label = l.get("app", "")
            txt = l.get("texto", "")[:200]  # limita tamanho de cada mensagem
            partes.append(f"[{data} | {app_label} | {direcao_label}] {txt}")

    if not partes:
        return ""

    return f"Histórico relevante com {contato}:\n" + "\n".join(partes)


def salvar_fato(contato: str, chave: str, valor: str):
    """Persiste um fato sobre um contato (ex: 'aniversario' = '20/05')."""
    slug = _slug(contato)
    with _lock:
        perfis = _carregar_perfis()
        perfil = perfis.setdefault(slug, {
            "display_name": contato, "apps": [], "facts": {}, "last_seen": "",
        })
        perfil.setdefault("facts", {})[chave.strip().lower()] = valor
        _salvar_perfis(perfis)


def obter_perfil(contato: str) -> dict:
    """Retorna o perfil completo do contato (ou {} se não existir)."""
    slug = _slug(contato)
    with _lock:
        perfis = _carregar_perfis()
        return dict(perfis.get(slug, {}))


def resumo_contato(contato: str) -> str:
    """
    Retorna um bloco de texto curto com informações do contato:
    apps usados, último contato, fatos salvos, últimas 3 mensagens.
    Para injeção direta no system prompt.
    """
    perfil = obter_perfil(contato)
    if not perfil:
        return ""

    linhas_perfil = [f"Contato: {perfil.get('display_name', contato)}"]
    apps = perfil.get("apps", [])
    if apps:
        linhas_perfil.append(f"Apps: {', '.join(apps)}")
    last = perfil.get("last_seen", "")
    if last:
        linhas_perfil.append(f"Último contato: {last[:10]}")
    fatos = perfil.get("facts", {})
    for k, v in fatos.items():
        linhas_perfil.append(f"{k}: {v}")

    # Últimas 3 mensagens cronológicas
    slug = _slug(contato)
    recentes = _ler_jsonl(slug)[-3:]
    if recentes:
        linhas_perfil.append("Mensagens recentes:")
        for m in recentes:
            txt = m.get("texto", "")[:120]
            data = m.get("ts", "")[:10]
            dir_lbl = "→" if m.get("direcao") == "enviada" else "←"
            linhas_perfil.append(f"  {dir_lbl} [{data}] {txt}")

    return "\n".join(linhas_perfil)


def listar_contatos() -> list[str]:
    """Retorna lista de display_names de todos os contatos com memória."""
    with _lock:
        perfis = _carregar_perfis()
    return [p.get("display_name", slug) for slug, p in perfis.items()]
