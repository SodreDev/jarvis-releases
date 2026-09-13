# jarvis/memory/store.py — J.A.R.V.I.S.
# Memória semântica/vetorial residente em RAM (roadmap/14, Fase 1-3).
# - Embedder: MiniLM-L6-v2 COMPARTILHADO com o classificador (sem 2º load de 80MB).
# - Índice: numpy float32 + cosseno top-k (mesma escala de comandos/memoria_contatos).
# - 3 segmentos: episodic (turnos + saídas de tools) / semantic (fatos) / procedural.
# - Recuperação ADAPTATIVA por situação via jarvis/memory/router.py.
# Tudo best-effort: qualquer falha NUNCA quebra o turno (a memória só enriquece).
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from . import retrieval as _ret
from . import router as _router

_SEGMENTS = ("episodic", "semantic", "procedural")
_DIM = 384  # MiniLM-L6-v2

_store_lock = threading.Lock()
_store = None  # singleton


def _project_root() -> Path:
    # jarvis/memory/store.py → parents[2] = raiz do projeto (dev e frozen live-source)
    return Path(__file__).resolve().parents[2]


_MARKER_RE = re.compile(r"^\s*\[LONGO\]\s*", re.I)


def _short(s: str, n: int = 220) -> str:
    # remove o marcador de DISPLAY ([LONGO]) — é instrução de exibição, não
    # conteúdo. Sem isso a memória "aprende" o marcador em vez do texto real.
    s = " ".join(_MARKER_RE.sub("", str(s or "")).split())
    return s if len(s) <= n else s[: n - 1] + "…"


class MemoryStore:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            try:
                import config as _cfg
                base_dir = getattr(_cfg, "MEMORY_DIR", "data/memory")
            except Exception:
                base_dir = "data/memory"
        bd = Path(base_dir)
        self._dir = bd if bd.is_absolute() else (_project_root() / bd)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._loaded = False
        self._model = None
        self._next_id = 1
        # por segmento: {"matrix": np.ndarray[N,DIM], "records": list[dict]}
        self._seg: dict[str, dict] = {
            s: {"matrix": np.zeros((0, _DIM), dtype=np.float32), "records": []}
            for s in _SEGMENTS
        }

    # ── infra ────────────────────────────────────────────────────────────
    def _get_model(self):
        if self._model is None:
            from classifiers import embeddings as _emb
            self._model = _emb.get_classifier()._model
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        v = self._get_model().encode(texts, normalize_embeddings=True)
        return np.asarray(v, dtype=np.float32).reshape(len(texts), -1)

    def _paths(self, seg: str) -> tuple[Path, Path]:
        return self._dir / f"{seg}.npy", self._dir / f"{seg}.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            max_id = 0
            for seg in _SEGMENTS:
                npy, js = self._paths(seg)
                records: list[dict] = []
                if js.exists():
                    try:
                        records = json.loads(js.read_text(encoding="utf-8"))
                    except Exception:
                        records = []
                matrix = np.zeros((0, _DIM), dtype=np.float32)
                if npy.exists():
                    try:
                        matrix = np.load(npy).astype(np.float32)
                    except Exception:
                        matrix = np.zeros((0, _DIM), dtype=np.float32)
                # Self-heal: matriz e registros desalinhados → re-embed do texto.
                if matrix.shape[0] != len(records):
                    if records:
                        try:
                            matrix = self._embed([r.get("text", "") for r in records])
                        except Exception:
                            records, matrix = [], np.zeros((0, _DIM), dtype=np.float32)
                    else:
                        matrix = np.zeros((0, _DIM), dtype=np.float32)
                self._seg[seg] = {"matrix": matrix, "records": records}
                for r in records:
                    max_id = max(max_id, int(r.get("id", 0)))
            self._next_id = max_id + 1
            self._loaded = True

    def _persist_segment(self, seg: str) -> None:
        try:
            npy, js = self._paths(seg)
            np.save(npy, self._seg[seg]["matrix"])
            js.write_text(json.dumps(self._seg[seg]["records"], ensure_ascii=False),
                          encoding="utf-8")
        except Exception as e:
            print(f"[MEM] persist {seg} falhou: {e}")

    # ── escrita ──────────────────────────────────────────────────────────
    def add(self, segment: str, text: str, *, importance: float = 0.5,
            source: str = "user", turn_id=None, tags: Optional[list] = None,
            pinned: bool = False, meta: Optional[dict] = None,
            vector: Optional[np.ndarray] = None) -> Optional[int]:
        text = (text or "").strip()
        if not text or segment not in _SEGMENTS:
            return None
        try:
            self._ensure_loaded()
            with self._lock:
                vec = vector if vector is not None else self._embed([text])
                vec = np.asarray(vec, dtype=np.float32).reshape(1, -1)
                now = time.time()
                rid = self._next_id
                self._next_id += 1
                rec = {
                    "id": rid, "segment": segment, "text": text,
                    "ts_created": now, "ts_last_access": now,
                    "importance": float(max(0.0, min(1.0, importance))),
                    "pinned": bool(pinned), "source": source,
                    "turn_id": turn_id, "tags": tags or [], "meta": meta or {},
                }
                self._seg[segment]["records"].append(rec)
                m = self._seg[segment]["matrix"]
                self._seg[segment]["matrix"] = (
                    vec if m.shape[0] == 0 else np.vstack([m, vec])
                )
                self._persist_segment(segment)
                return rid
        except Exception as e:
            print(f"[MEM] add falhou: {e}")
            return None

    def record_turn(self, user_text: str, assistant_text: str,
                    origem: str = "texto", turn_id=None) -> Optional[int]:
        """Grava um turno completo no segmento episódico."""
        u = _short(user_text, 400)
        a = _short(assistant_text, 400)
        if not u and not a:
            return None
        text = f"Usuário: {u}\nJARVIS: {a}"
        return self.add("episodic", text, source="turn", turn_id=turn_id,
                        importance=0.5, meta={"origem": origem})

    def record_tool_outcome(self, turn_id, name: str, args: dict, ok: bool,
                            result: str, latency_ms=None) -> Optional[int]:
        """Grava a saída de uma ferramenta — permite lembrar 'o PDF que gerou'."""
        try:
            args_s = _short(json.dumps(args, ensure_ascii=False), 120) if args else ""
        except Exception:
            args_s = _short(str(args), 120)
        status = "ok" if ok else "erro"
        text = f"Ferramenta {name}({args_s}) → {status}: {_short(result, 240)}"
        return self.add("episodic", text, source="tool", turn_id=turn_id,
                        importance=0.55 if ok else 0.4,
                        meta={"name": name, "ok": bool(ok), "latency_ms": latency_ms})

    def upsert_fact(self, subject: str, predicate: str, value: str,
                    confidence: float = 0.8, pinned: bool = False) -> Optional[int]:
        """Fato semântico atômico — substitui (subject,predicate) existente
        em vez de duplicar (estilo Mem0 ADD/UPDATE)."""
        subject, predicate, value = subject.strip(), predicate.strip(), value.strip()
        if not subject or not predicate:
            return None
        try:
            self._ensure_loaded()
            with self._lock:
                recs = self._seg["semantic"]["records"]
                for i, r in enumerate(recs):
                    m = r.get("meta", {})
                    if m.get("subject") == subject and m.get("predicate") == predicate:
                        text = f"{subject} {predicate} {value}"
                        r["text"] = text
                        r["meta"] = {"subject": subject, "predicate": predicate,
                                     "value": value, "confidence": confidence}
                        r["ts_last_access"] = time.time()
                        if pinned:
                            r["pinned"] = True
                        self._seg["semantic"]["matrix"][i] = self._embed([text])[0]
                        self._persist_segment("semantic")
                        return int(r["id"])
            # não existe → adiciona
            return self.add("semantic", f"{subject} {predicate} {value}",
                            source="fact", importance=0.7, pinned=pinned,
                            meta={"subject": subject, "predicate": predicate,
                                  "value": value, "confidence": confidence})
        except Exception as e:
            print(f"[MEM] upsert_fact falhou: {e}")
            return None

    def forget(self, alvo) -> int:
        """Remove por id (int) ou por subject (str). Retorna nº removidos."""
        self._ensure_loaded()
        removed = 0
        with self._lock:
            for seg in _SEGMENTS:
                recs = self._seg[seg]["records"]
                keep_idx = []
                for i, r in enumerate(recs):
                    hit = (isinstance(alvo, int) and r.get("id") == alvo) or (
                        isinstance(alvo, str) and r.get("meta", {}).get("subject") == alvo)
                    if hit:
                        removed += 1
                    else:
                        keep_idx.append(i)
                if removed and keep_idx != list(range(len(recs))):
                    self._seg[seg]["records"] = [recs[i] for i in keep_idx]
                    if keep_idx:
                        self._seg[seg]["matrix"] = self._seg[seg]["matrix"][keep_idx]
                    else:
                        self._seg[seg]["matrix"] = np.zeros((0, _DIM), dtype=np.float32)
                    self._persist_segment(seg)
        return removed

    def pin(self, rid: int) -> bool:
        self._ensure_loaded()
        with self._lock:
            for seg in _SEGMENTS:
                for r in self._seg[seg]["records"]:
                    if r.get("id") == rid:
                        r["pinned"] = True
                        self._persist_segment(seg)
                        return True
        return False

    # ── leitura ──────────────────────────────────────────────────────────
    def retrieve(self, query: str, *, policy: Optional[str] = None,
                 k: Optional[int] = None) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        try:
            self._ensure_loaded()
            thr = 0.35
            try:
                import config as _cfg
                thr = float(getattr(_cfg, "MEMORY_ROUTER_THRESHOLD", 0.35))
            except Exception:
                pass
            pol = _router.policy_for(query, thr)
            if policy and policy in _router.POLICIES:
                pol = dict(_router.POLICIES[policy]); pol["policy"] = policy; pol["conf"] = 1.0
            segments = pol["segments"]
            kk = k or pol.get("k", 6)

            with self._lock:
                # reúne candidatos dos segmentos da política
                mats, recs = [], []
                for seg in segments:
                    sm = self._seg.get(seg)
                    if sm and sm["matrix"].shape[0]:
                        mats.append(sm["matrix"])
                        recs.extend(sm["records"])
                if not recs:
                    return []
                cand = np.vstack(mats)
                q = self._embed([query])[0]
                sims = (cand @ q).astype(np.float32)
                now = time.time()
                ts = np.array([r.get("ts_last_access", r.get("ts_created", now)) for r in recs])
                imp = np.array([r.get("importance", 0.5) for r in recs], dtype=np.float32)
                pin = np.array([1.0 if r.get("pinned") else 0.0 for r in recs], dtype=np.float32)
                decay = 0.995
                try:
                    import config as _cfg
                    decay = float(getattr(_cfg, "MEMORY_RECENCY_DECAY", 0.995))
                except Exception:
                    pass
                rec_signal = _ret.recency_decay(ts, now, decay)
                base = _ret.composite_score(sims, rec_signal, imp, pin, pol["weights"])

                if pol.get("mmr"):
                    lam = 0.6
                    try:
                        import config as _cfg
                        lam = float(getattr(_cfg, "MEMORY_MMR_LAMBDA", 0.6))
                    except Exception:
                        pass
                    sel = _ret.mmr(q, cand, base, lambda_=lam, k=kk)
                else:
                    sel = list(np.argsort(-base)[:kk])

                out = []
                for i in sel:
                    r = recs[int(i)]
                    r["ts_last_access"] = now  # touch (persistido no próximo add)
                    rr = dict(r); rr["_score"] = float(base[int(i)])
                    out.append(rr)
                return out
        except Exception as e:
            print(f"[MEM] retrieve falhou: {e}")
            return []

    @staticmethod
    def format_for_prompt(results: list[dict]) -> str:
        if not results:
            return ""
        linhas = ["[Memórias relevantes]"]
        tag = {"turn": "conversa", "tool": "ação", "fact": "fato",
               "user": "nota", "reflection": "reflexão"}
        for r in results:
            kind = tag.get(r.get("source", ""), r.get("segment", ""))
            linhas.append(f"- ({kind}) {_short(r.get('text', ''), 240)}")
        return "\n".join(linhas)

    def stats(self) -> dict:
        self._ensure_loaded()
        return {s: len(self._seg[s]["records"]) for s in _SEGMENTS}


def get_store() -> MemoryStore:
    """Singleton global do MemoryStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = MemoryStore()
    return _store
