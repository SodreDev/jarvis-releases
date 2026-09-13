# jarvis/memory/skills.py — J.A.R.V.I.S.
# Base semântica de INSTRUÇÕES/SITUAÇÕES das tools — a camada "experts semânticos".
#
# Ideia (dono): em vez de despejar TODOS os schemas de tools a cada prompt, guarda
# as instruções + situações de cada tool num índice vetorial e RECUPERA só as
# relevantes por prompt → reduz tokens e dá um "sabor de treino" SEM treinar o
# modelo. O índice é RECONSTRUÍVEL a partir do tool_registry (não é dado do
# usuário) e fica SEPARADO da memória pessoal (jarvis/memory/store) p/ não poluir
# os fatos do usuário. Reusa o MiniLM compartilhado (mesmo padrão do store.py).
#
# Best-effort: qualquer falha nunca quebra o turno. O USO no orquestrador é gated
# por config.SKILL_MEMORY_ENABLED (OFF); o índice em si pode ser construído/
# consultado de forma independente (testes, rebuild).
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

_DIM = 384  # MiniLM-L6-v2
_lock = threading.Lock()
_inst = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class SkillMemory:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            try:
                import config as _c
                base_dir = getattr(_c, "MEMORY_DIR", "data/memory")
            except Exception:
                base_dir = "data/memory"
        bd = Path(base_dir)
        self._dir = bd if bd.is_absolute() else (_project_root() / bd)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._model = None
        self._matrix = np.zeros((0, _DIM), dtype=np.float32)
        self._records: list[dict] = []
        self._loaded = False

    # ── infra (reusa o MiniLM compartilhado) ──────────────────────────────
    def _get_model(self):
        if self._model is None:
            from classifiers import embeddings as _emb
            self._model = _emb.get_classifier()._model
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        v = self._get_model().encode(texts, normalize_embeddings=True)
        return np.asarray(v, dtype=np.float32).reshape(len(texts), -1)

    def _paths(self) -> tuple[Path, Path]:
        return self._dir / "skills.npy", self._dir / "skills.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            npy, js = self._paths()
            recs: list[dict] = []
            mat = np.zeros((0, _DIM), dtype=np.float32)
            if js.exists():
                try:
                    recs = json.loads(js.read_text(encoding="utf-8"))
                except Exception:
                    recs = []
            if npy.exists():
                try:
                    mat = np.load(npy).astype(np.float32)
                except Exception:
                    mat = np.zeros((0, _DIM), dtype=np.float32)
            if mat.shape[0] != len(recs):  # self-heal: re-embed do texto
                if recs:
                    try:
                        mat = self._embed([r.get("text", "") for r in recs])
                    except Exception:
                        recs, mat = [], np.zeros((0, _DIM), dtype=np.float32)
                else:
                    mat = np.zeros((0, _DIM), dtype=np.float32)
            self._matrix, self._records, self._loaded = mat, recs, True

    def _persist(self) -> None:
        try:
            npy, js = self._paths()
            np.save(npy, self._matrix)
            js.write_text(json.dumps(self._records, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[SKILL] persist falhou: {e}")

    # ── escrita ───────────────────────────────────────────────────────────
    def sync(self, items: list[dict]) -> int:
        """(Re)constrói o índice a partir de items=[{tool, layer?, text, kind?}].
        Rebuild completo (barato p/ ~dezenas de tools). Retorna nº indexado."""
        items = [it for it in (items or []) if it.get("text")]
        if not items:
            return 0
        try:
            with self._lock:
                mat = self._embed([it["text"] for it in items])
                now = time.time()
                self._records = [
                    {
                        "tool": it.get("tool", ""),
                        "layer": it.get("layer", ""),
                        "text": it["text"],
                        "kind": it.get("kind", "tool"),
                        "ts": now,
                    }
                    for it in items
                ]
                self._matrix = mat
                self._loaded = True
                self._persist()
                return len(self._records)
        except Exception as e:
            print(f"[SKILL] sync falhou: {e}")
            return 0

    def add_situation(self, text: str, tool: str = "", layer: str = "",
                      kind: str = "situacao") -> bool:
        """Adiciona UMA instrução/situação extra (curada ou vinda de pesquisa)."""
        text = (text or "").strip()
        if not text:
            return False
        try:
            self._ensure_loaded()
            with self._lock:
                vec = self._embed([text])
                self._records.append({"tool": tool, "layer": layer, "text": text,
                                      "kind": kind, "ts": time.time()})
                self._matrix = (vec if self._matrix.shape[0] == 0
                                else np.vstack([self._matrix, vec]))
                self._persist()
                return True
        except Exception as e:
            print(f"[SKILL] add_situation falhou: {e}")
            return False

    # ── leitura ───────────────────────────────────────────────────────────
    def retrieve(self, query: str, k: int = 8, min_score: float = 0.0) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        try:
            self._ensure_loaded()
            with self._lock:
                if self._matrix.shape[0] == 0:
                    return []
                q = self._embed([query])[0]
                sims = (self._matrix @ q).astype(np.float32)
                order = np.argsort(-sims)[: max(1, k)]
                out = []
                for i in order:
                    sc = float(sims[int(i)])
                    if sc < min_score:
                        continue
                    r = dict(self._records[int(i)])
                    r["_score"] = sc
                    out.append(r)
                return out
        except Exception as e:
            print(f"[SKILL] retrieve falhou: {e}")
            return []

    def retrieve_tool_names(self, query: str, k: int = 8) -> list[str]:
        """Nomes de tools relevantes p/ o prompt (dedup, ordem por relevância)."""
        seen, out = set(), []
        for r in self.retrieve(query, k=k * 2):  # k*2 p/ absorver situações repetidas
            t = r.get("tool")
            if t and t not in seen:
                seen.add(t)
                out.append(t)
            if len(out) >= k:
                break
        return out

    def stats(self) -> dict:
        self._ensure_loaded()
        return {
            "records": len(self._records),
            "tools": len({r.get("tool") for r in self._records if r.get("tool")}),
        }


def get_skills() -> SkillMemory:
    """Singleton global da base semântica de instruções."""
    global _inst
    if _inst is None:
        with _lock:
            if _inst is None:
                _inst = SkillMemory()
    return _inst


def build_items_from_registry() -> list[dict]:
    """Extrai as instruções das tools do tool_registry → items p/ sync().

    Texto indexado por tool: 'nome — descrição | args: ... | domínio: <camada>'.
    A descrição já traz o 'use quando…' e os 'NÃO confundir com…' do registry.
    """
    try:
        from comandos import tool_registry as tr
    except Exception as e:
        print(f"[SKILL] tool_registry indisponível: {e}")
        return []
    try:
        specs = tr.to_openai_tools()
    except Exception as e:
        print(f"[SKILL] to_openai_tools falhou: {e}")
        return []
    items: list[dict] = []
    for s in specs:
        fn = s.get("function", {}) if isinstance(s, dict) else {}
        name = fn.get("name", "")
        if not name:
            continue
        desc = fn.get("description", "")
        props = ((fn.get("parameters", {}) or {}).get("properties", {})) or {}
        args = "; ".join(
            f"{k}: {v.get('description', '')}"
            for k, v in props.items()
            if isinstance(v, dict) and v.get("description")
        )
        try:
            layer = tr.layer_of(name)
        except Exception:
            layer = ""
        text = f"{name} — {desc}"
        if args:
            text += f" | args: {args}"
        if layer:
            text += f" | domínio: {layer}"
        items.append({"tool": name, "layer": layer, "text": text, "kind": "tool"})
    return items


def sync_from_registry(include_situations: bool = True) -> int:
    """Reconstrói o índice: instruções das tools + situações curadas (semente).

    `include_situations` traz `jarvis/memory/situations.py` (frases curtas que
    afinam o retrieval em pedidos ambíguos). Retorna nº de entradas indexadas.
    """
    items = build_items_from_registry()
    if include_situations:
        try:
            from . import situations as _sit
            items += _sit.items()
        except Exception as e:
            print(f"[SKILL] situações indisponíveis: {e}")
    return get_skills().sync(items)


if __name__ == "__main__":
    # Smoke da camada (independe de flag): reconstrói do registry e consulta.
    import sys
    sys.path.insert(0, str(_project_root()))  # raiz do repo p/ import classifiers/comandos
    n = sync_from_registry()
    print(f"indexadas {n} instruções | stats={get_skills().stats()}")
    for q in ("toca uma música no spotify", "gera um pdf do enem",
              "manda mensagem pro joão", "tira um print da tela"):
        print(f"\n[{q}]")
        for r in get_skills().retrieve(q, k=4):
            print(f"  {r['_score']:.2f}  {r['tool']:<20} ({r.get('layer','')})")
