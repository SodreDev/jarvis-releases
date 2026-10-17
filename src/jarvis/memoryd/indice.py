"""A interface de índice da SPEC §6.3 — trocável, e descartável (§6.2 d).

`MemoryIndex` é o contrato; o índice nunca é fonte de verdade, e tudo nele se reconstrói do
livro-razão por `content_hash` + `embedding_version`.

**Por que aqui só há um índice falso:** a SPEC escolhe entre `ChromaIndex` e `LanceIndex` pela
medição da §8.1, e nenhum dos dois está nas dependências do produto hoje (ADR-0026, "Ajustes da
implementação"). `IndiceEmMemoria` é determinístico — sobreposição de termos, sem modelo de
embedding, a mesma honestidade da lista densa simulada da F0-05 —, serve para o contrato ser
testado (inclusive a exclusão em cascata do gate 2) e **não mede qualidade de recuperação**. A
lista léxica de verdade é o FTS5 do próprio SQLite, que já existe.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from jarvis.memoryd.fusao import termos

VERSAO_DO_EMBEDDING_FALSO: Final = "termos-v0"


@dataclass(frozen=True, slots=True)
class ItemDoIndice:
    id: str
    text_redacted: str
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Acerto:
    id: str
    score: float
    rank_source: str


class MemoryIndex(Protocol):
    def upsert(self, itens: Sequence[ItemDoIndice]) -> int: ...

    def delete(self, ids: Sequence[str]) -> int: ...

    def search(
        self,
        query: str,
        k: int,
        filtro: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> list[Acerto]: ...

    def stats(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class IndiceEmMemoria:
    """Índice de teste: sobreposição de termos, em memória, sem modelo."""

    _itens: dict[str, ItemDoIndice] = field(default_factory=dict)

    def upsert(self, itens: Sequence[ItemDoIndice]) -> int:
        for item in itens:
            self._itens[item.id] = item
        return len(itens)

    def delete(self, ids: Sequence[str]) -> int:
        return sum(self._itens.pop(i, None) is not None for i in ids)

    def search(
        self,
        query: str,
        k: int,
        filtro: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> list[Acerto]:
        consulta = set(termos(query))
        if not consulta:
            return []
        pontuados: list[tuple[float, str]] = []
        for item in self._itens.values():
            if filtro is not None and not filtro(item.metadata):
                continue
            comuns = consulta & set(termos(item.text_redacted))
            if comuns:
                pontuados.append((len(comuns) / len(consulta), item.id))
        pontuados.sort(key=lambda p: (-p[0], p[1]))
        return [Acerto(id=i, score=s, rank_source="denso-falso") for s, i in pontuados[:k]]

    def stats(self) -> dict[str, Any]:
        return {
            "count": len(self._itens),
            "bytes": sum(len(i.text_redacted.encode("utf-8")) for i in self._itens.values()),
            "embedding_version": VERSAO_DO_EMBEDDING_FALSO,
        }

    def contem_texto(self, trecho: str) -> bool:
        """Para o teste de exclusão: alguma coisa indexada ainda tem este trecho?"""
        return any(trecho in i.text_redacted for i in self._itens.values())
