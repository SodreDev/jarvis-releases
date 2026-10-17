"""Embeddings multilíngues **locais** para o índice da memória (SPEC §6.3, §8.1).

Nada sai da máquina: o modelo é um `.onnx` lido pelo `onnxruntime` (MIT), com o tokenizador do
próprio modelo (`tokenizers`, Apache-2.0). O modelo é o `intfloat/multilingual-e5-small` (MIT,
card oficial), o mesmo que o Orchestrator do dono já usa e mediu; o arquivo vem do repositório
**oficial**, fixado por commit e sha256 em `licenses/modelos.toml`, baixado no primeiro uso.

O e5 pede prefixo: `query: ` na pergunta e `passage: ` no que é indexado. O vetor é a média dos
estados da última camada, pesada pela máscara, normalizada (como o card ensina) — então o
produto interno é o cosseno.

`EmbedderDeTeste` existe para a suíte rodar sem modelo e sem rede: é determinístico, e serve
para provar o contrato, **não** para medir acerto.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, Protocol

PASTA_DO_MODELO: Final = (
    Path.home() / ".cache" / "jarvis" / "modelos" / "intfloat--multilingual-e5-small"
)
ARQUIVO_DO_MODELO: Final = "onnx/model.onnx"
VERSAO_E5: Final = "intfloat/multilingual-e5-small@614241f6"
DIMENSAO: Final = 384
TOKENS_MAXIMOS: Final = 256
"""Memória é curta; teto baixo deixa a latência previsível (o Orchestrator usa 512)."""

Tipo = Literal["query", "passage"]


class Embedder(Protocol):
    @property
    def versao(self) -> str: ...

    @property
    def dimensao(self) -> int: ...

    def embed(self, textos: Sequence[str], tipo: Tipo) -> list[list[float]]: ...


@dataclass(slots=True)
class EmbedderE5:
    """O e5 em ONNX, na CPU. `threads` limita o que ele tira da voz (SLO-1/2)."""

    pasta: Path = PASTA_DO_MODELO
    arquivo: str = ARQUIVO_DO_MODELO
    threads: int = 2
    versao: str = VERSAO_E5
    dimensao: int = DIMENSAO
    _sessao: object = field(default=None, repr=False)
    _tokenizador: object = field(default=None, repr=False)

    def abrir(self) -> None:
        if self._sessao is not None:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        opcoes = onnxruntime.SessionOptions()
        opcoes.intra_op_num_threads = self.threads
        opcoes.inter_op_num_threads = 1
        self._sessao = onnxruntime.InferenceSession(
            str(self.pasta / self.arquivo), opcoes, providers=["CPUExecutionProvider"]
        )
        tokenizador = Tokenizer.from_file(str(self.pasta / "tokenizer.json"))
        tokenizador.enable_truncation(TOKENS_MAXIMOS)
        tokenizador.enable_padding()
        self._tokenizador = tokenizador

    def embed(self, textos: Sequence[str], tipo: Tipo) -> list[list[float]]:
        import numpy as np

        self.abrir()
        if not textos:
            return []
        codificados = self._tokenizador.encode_batch(  # type: ignore[attr-defined]
            [f"{tipo}: {t}" for t in textos]
        )
        ids = np.array([c.ids for c in codificados], dtype=np.int64)
        mascara = np.array([c.attention_mask for c in codificados], dtype=np.int64)
        saida = self._sessao.run(  # type: ignore[attr-defined]
            ["last_hidden_state"],
            {"input_ids": ids, "attention_mask": mascara, "token_type_ids": np.zeros_like(ids)},
        )[0]
        pesos = mascara[..., None].astype(np.float32)
        media = (saida * pesos).sum(axis=1) / np.clip(pesos.sum(axis=1), 1e-9, None)
        normas = np.linalg.norm(media, axis=1, keepdims=True)
        vetores: list[list[float]] = (
            (media / np.clip(normas, 1e-12, None)).astype(np.float32).tolist()
        )
        return vetores


@dataclass(slots=True)
class EmbedderDeTeste:
    """Determinístico, sem modelo: sacola de termos espalhada por hash, normalizada."""

    versao: str = "teste-hash-v0"
    dimensao: int = 64

    def embed(self, textos: Sequence[str], tipo: Tipo) -> list[list[float]]:
        del tipo
        vetores: list[list[float]] = []
        for texto in textos:
            vetor = [0.0] * self.dimensao
            for termo in re.findall(r"\w+", texto.casefold()):
                posicao = int(hashlib.sha256(termo.encode()).hexdigest()[:8], 16) % self.dimensao
                vetor[posicao] += 1.0
            norma = sum(v * v for v in vetor) ** 0.5 or 1.0
            vetores.append([v / norma for v in vetor])
        return vetores
