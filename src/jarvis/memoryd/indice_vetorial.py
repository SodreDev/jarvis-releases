"""O índice vetorial do produto atrás da `MemoryIndex` (SPEC §6.3): LanceDB embutido.

Escolhido pela medição da §8.1 (`docs/medicoes/f3-01-indice.md`, emenda da ADR-0005): o
ChromaDB, comparado no mesmo harness (`tools/harness_indice.py`), deixa o vetor apagado no
disco mesmo depois da manutenção que ele documenta — veto pelo gate 2.

Guarda **só** `id`, vetor e os metadados do filtro (`tipo`, `status`) — nunca o texto: o
livro-razão é a fonte de verdade (P7) e o índice se reconstrói dele, então texto aqui seria só
mais um lugar de onde a exclusão teria de tirar. O vetor vem do `Embedder` local
(`jarvis.memoryd.embedding`); nada chama rede. A busca é exata (varredura) enquanto não houver
índice ANN — com milhares de memórias, é o que cabe; o filtro vale **antes** do ranking
(`prefilter=True`).
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.memoryd.embedding import Embedder
from jarvis.memoryd.indice import Acerto, ItemDoIndice

COLECAO: Final = "memoria"


def _sql(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


@dataclass(slots=True)
class IndiceLance:
    pasta: Path
    embedder: Embedder
    _banco: Any = field(default=None, repr=False)
    _tabela: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        import lancedb
        import pyarrow as pa

        self._banco = banco = lancedb.connect(str(self.pasta))
        esquema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.embedder.dimensao)),
                pa.field("tipo", pa.string()),
                pa.field("status", pa.string()),
                pa.field("content_hash", pa.string()),
                pa.field("versao", pa.string()),
            ]
        )
        self._tabela = banco.create_table(COLECAO, schema=esquema, exist_ok=True)

    def upsert(self, itens: Sequence[ItemDoIndice]) -> int:
        if not itens:
            return 0
        vetores = self.embedder.embed([i.text_redacted for i in itens], "passage")
        linhas = [
            {
                "id": i.id,
                "vector": v,
                "tipo": str(i.metadata.get("tipo", "")),
                "status": str(i.metadata.get("status", "")),
                "content_hash": i.content_hash,
                "versao": self.embedder.versao,
            }
            for i, v in zip(itens, vetores, strict=True)
        ]
        (
            self._tabela.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(linhas)
        )
        return len(itens)

    def delete(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        lista = ", ".join(_sql(i) for i in ids)
        antes = int(self._tabela.count_rows())
        self._tabela.delete(f"id IN ({lista})")
        return antes - int(self._tabela.count_rows())

    def search(self, query: str, k: int, onde: Mapping[str, str] | None = None) -> list[Acerto]:
        (vetor,) = self.embedder.embed([query], "query")
        busca = self._tabela.search(vetor).distance_type("cosine").limit(k).select(["id"])
        if onde:
            busca = busca.where(
                " AND ".join(f"{chave} = {_sql(valor)}" for chave, valor in onde.items()),
                prefilter=True,
            )
        return [
            Acerto(id=str(linha["id"]), score=1.0 - float(linha["_distance"]), rank_source="denso")
            for linha in busca.to_list()
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "count": int(self._tabela.count_rows()),
            "bytes": sum(p.stat().st_size for p in self.pasta.rglob("*") if p.is_file()),
            "embedding_version": self.embedder.versao,
        }

    def expurgar(self) -> None:
        """Tira do disco o que foi apagado (gate 2), só com API pública do LanceDB.

        `delete` só marca a linha num arquivo de deleção; `optimize` compacta, mas não reescreve
        um fragmento com menos de 10% de linhas apagadas — o vetor fica no disco
        (`docs/medicoes/f3-01-indice.md`). Então: reescreve a tabela com o que está vivo e
        apaga as versões antigas. Custo medido no mesmo relatório; roda depois de um "esquecer",
        nunca no caminho da voz.
        """
        from datetime import timedelta

        vivos = self._tabela.to_arrow()
        self._tabela = self._banco.create_table(COLECAO, data=vivos, mode="overwrite")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # o aviso é sobre leitor concorrente
            self._tabela.optimize(cleanup_older_than=timedelta(0), delete_unverified=True)

    def compactar(self) -> None:
        """A manutenção comum (`optimize`): junta fragmentos. Não basta para o gate 2."""
        from datetime import timedelta

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._tabela.optimize(cleanup_older_than=timedelta(0), delete_unverified=True)
