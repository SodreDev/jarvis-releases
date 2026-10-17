"""O índice do produto (LanceDB) atrás da `MemoryIndex`, e o embedding local — sem rede.

O vetor vem do `EmbedderDeTeste` (determinístico); o e5 de verdade só é exercitado se o modelo
já estiver baixado nesta máquina (nunca baixa em teste).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from tools.harness_indice import _onde_esta

from jarvis.memoryd.embedding import PASTA_DO_MODELO, EmbedderDeTeste, EmbedderE5
from jarvis.memoryd.indice import ItemDoIndice
from jarvis.memoryd.indice_vetorial import IndiceLance


class EmbedderDenso:
    """Vetor denso por texto (semente = hash): os 16 primeiros floats identificam o vetor, o que
    a busca de bytes no disco precisa. O de teste é esparso e daria falso positivo."""

    versao = "teste-denso"
    dimensao = 64

    def embed(self, textos: Sequence[str], tipo: str) -> list[list[float]]:
        del tipo
        saida = []
        for texto in textos:
            semente = int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16)
            vetor = np.random.default_rng(semente).standard_normal(self.dimensao)
            saida.append((vetor / np.linalg.norm(vetor)).astype(np.float32).tolist())
        return saida


def _item(i: str, texto: str, status: str = "active", tipo: str = "memoria") -> ItemDoIndice:
    return ItemDoIndice(
        id=i, text_redacted=texto, content_hash=i, metadata={"tipo": tipo, "status": status}
    )


@pytest.fixture
def indice(tmp_path: Path) -> IndiceLance:
    return IndiceLance(pasta=tmp_path / "indice", embedder=EmbedderDeTeste())


def test_embedder_de_teste_e_deterministico_e_normalizado() -> None:
    um, outro = EmbedderDeTeste().embed(["a Bia mandou", "a Bia mandou"], "query")
    assert um == outro
    assert math.isclose(sum(v * v for v in um), 1.0, rel_tol=1e-9)


def test_busca_pelo_mais_parecido_e_upsert_nao_duplica(indice: IndiceLance) -> None:
    indice.upsert([_item("u1", "a bia mandou o orçamento"), _item("u2", "o nando gosta de café")])
    indice.upsert([_item("u1", "a bia mandou o orçamento")])

    assert indice.stats()["count"] == 2
    assert indice.search("nando café", 2)[0].id == "u2"


def test_filtro_vale_antes_do_ranking(indice: IndiceLance) -> None:
    """§8.1: pedir `status=active` devolve `k` ativas, não as `k` melhores cortadas depois."""
    indice.upsert(
        [_item(f"p{n}", "nando café proposto", status="proposed") for n in range(5)]
        + [_item("a1", "nando chá"), _item("a2", "bia chá")]
    )
    achados = indice.search("nando café", 2, onde={"status": "active"})
    assert [a.id for a in achados] == ["a1", "a2"]


def test_apagar_tira_da_busca(indice: IndiceLance) -> None:
    indice.upsert([_item("u1", "segredo zebra"), _item("u2", "outra coisa")])
    assert indice.delete(["u1", "nao-existe"]) == 1
    assert all(a.id != "u1" for a in indice.search("segredo zebra", 5))


def test_expurgar_tira_o_vetor_do_disco(tmp_path: Path) -> None:
    """Gate 2 no índice de verdade: `delete` só marca; depois de `expurgar`, os bytes do vetor
    apagado não estão em arquivo nenhum da pasta — mesmo com a tabela num fragmento só."""
    embedder = EmbedderDenso()
    indice = IndiceLance(pasta=tmp_path / "indice", embedder=embedder)
    textos = [f"memória número {n} sobre o assunto {n * 7}" for n in range(40)]
    indice.upsert([_item(f"u{n}", t) for n, t in enumerate(textos)])
    indice.compactar()
    (alvo,) = embedder.embed([textos[3]], "passage")

    indice.delete(["u3"])
    indice.compactar()
    assert _onde_esta(indice.pasta, alvo), (
        "o optimize sozinho deixa o vetor (é o que a medição viu)"
    )

    indice.expurgar()
    assert _onde_esta(indice.pasta, alvo) == []
    assert indice.stats()["count"] == 39


@pytest.mark.skipif(
    not (PASTA_DO_MODELO / "onnx" / "model.onnx").exists(), reason="e5-small não baixado"
)
def test_e5_local_aproxima_o_que_e_parecido_em_portugues() -> None:
    e5 = EmbedderE5()
    (consulta,) = e5.embed(["quando é o aniversário da minha irmã?"], "query")
    certa, errada = e5.embed(
        [
            "O aniversário da Beatriz, minha irmã, é em 12 de março.",
            "Corro no parque aos domingos.",
        ],
        "passage",
    )
    assert len(consulta) == 384

    def cosseno(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosseno(consulta, certa) > cosseno(consulta, errada)
