"""SPEC §8.1 — ChromaDB × LanceDB atrás da mesma `MemoryIndex`, no corpus C2 sintético (fatia 7).

    uv run --frozen python -m tools.harness_indice                 # publica em docs/medicoes
    uv run --frozen python -m tools.harness_indice --saida /tmp/x  # em outra pasta

Protocolo (o da §8.1, com o que mudou dito):

- **mesmo embedding** para os dois (`intfloat/multilingual-e5-small`, local, `jarvis.memoryd.
  embedding`): os vetores do corpus e das consultas são calculados **uma vez** no processo pai e
  entregues aos dois — o tempo de índice medido é só do índice; o do embedding sai à parte;
- **cada execução num processo novo** (3 por candidato): a primeira busca depois de abrir é a
  "fria"; as outras, "quentes"; o RSS é o do processo filho, que não carrega o modelo;
- mesmo `k` (20), mesmo filtro (`tipo=memoria`, `status=active`, **antes** do ranking);
- recall@20/nDCG@10 só da lista densa (é o que muda de um índice para o outro); a abstinência é
  por limiar no melhor cosseno, calibrado em 70% das consultas e reportado nos 30% retidos;
- **exclusão verificável (veto):** apaga uma unidade e procura os **bytes do vetor** em todos os
  arquivos da pasta do índice — depois da exclusão, e depois da manutenção que a API pública
  oferece. Vetor que fica no disco é dado derivado da memória apagada (gate 2);
- Windows: não há máquina Windows aqui. O relatório diz o que o `uv.lock` publica (rodas
  `win_amd64`) e que **não** foi executado.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version as versao
from pathlib import Path
from typing import Any, Final

import numpy as np

from jarvis.medicao import hardware, percentil
from jarvis.memoryd.embedding import Embedder, EmbedderE5
from jarvis.memoryd.indice import Acerto, ItemDoIndice
from jarvis.memoryd.indice_vetorial import COLECAO, IndiceLance
from tools.corpus_c2 import Consulta, gerar, montar

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
NOME: Final = "f3-01-indice"
CANDIDATOS: Final = ("chroma", "lance")
EXECUCOES: Final = 3
K: Final = 20
LOTE: Final = 256
SO_MEMORIA: Final = {"tipo": "memoria", "status": "active"}


@dataclass(slots=True)
class EmbedderPronto:
    """Devolve o vetor já calculado no pai: os dois índices recebem exatamente o mesmo."""

    vetores: dict[str, list[float]]
    versao: str = "e5-small-pre-calculado"
    dimensao: int = 384

    def embed(self, textos: Sequence[str], tipo: str) -> list[list[float]]:
        return [self.vetores[f"{tipo}:{t}"] for t in textos]


@dataclass(slots=True)
class IndiceChroma:
    """O candidato perdedor da §8.1, só para a medição: HNSW cosseno, telemetria desligada."""

    pasta: Path
    embedder: Embedder
    _colecao: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        import chromadb
        from chromadb.config import Settings

        cliente = chromadb.PersistentClient(
            path=str(self.pasta), settings=Settings(anonymized_telemetry=False)
        )
        self._colecao = cliente.get_or_create_collection(
            COLECAO,
            metadata={"hnsw:space": "cosine", "embedding_version": self.embedder.versao},
            embedding_function=None,
        )

    def upsert(self, itens: Sequence[ItemDoIndice]) -> int:
        if not itens:
            return 0
        vetores = self.embedder.embed([i.text_redacted for i in itens], "passage")
        self._colecao.upsert(
            ids=[i.id for i in itens],
            embeddings=vetores,
            metadatas=[
                {**i.metadata, "content_hash": i.content_hash, "versao": self.embedder.versao}
                for i in itens
            ],
        )
        return len(itens)

    def delete(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        existentes = self._colecao.get(ids=list(ids), include=[])["ids"]
        if existentes:
            self._colecao.delete(ids=existentes)
        return len(existentes)

    def search(self, query: str, k: int, onde: Mapping[str, str] | None = None) -> list[Acerto]:
        (vetor,) = self.embedder.embed([query], "query")
        filtro: dict[str, Any] | None = None
        if onde:
            condicoes = [{chave: valor} for chave, valor in onde.items()]
            filtro = condicoes[0] if len(condicoes) == 1 else {"$and": condicoes}
        resposta = self._colecao.query(
            query_embeddings=[vetor], n_results=k, where=filtro, include=["distances"]
        )
        return [
            Acerto(id=i, score=1.0 - float(d), rank_source="denso")
            for i, d in zip(resposta["ids"][0], resposta["distances"][0], strict=True)
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "count": int(self._colecao.count()),
            "bytes": sum(p.stat().st_size for p in self.pasta.rglob("*") if p.is_file()),
            "embedding_version": self.embedder.versao,
        }


def _abrir(candidato: str, pasta: Path, embedder: EmbedderPronto) -> Any:
    return (IndiceChroma if candidato == "chroma" else IndiceLance)(pasta=pasta, embedder=embedder)


def _onde_esta(pasta: Path, vetor: Sequence[float]) -> list[str]:
    """Arquivos que ainda guardam o vetor: os 16 primeiros floats, como vieram **ou**
    renormalizados (o Chroma normaliza no espaço cosseno, com arredondamento próprio), com
    tolerância de 1e-6 e em qualquer alinhamento de 4 bytes."""
    cru = np.asarray(vetor, np.float32)
    agulhas = [cru[:16], (cru / np.linalg.norm(cru)).astype(np.float32)[:16]]
    achados = []
    for arquivo in sorted(p for p in pasta.rglob("*") if p.is_file()):
        dados = arquivo.read_bytes()
        if any(_contem(dados, desvio, agulha) for desvio in range(4) for agulha in agulhas):
            achados.append(arquivo.relative_to(pasta).as_posix())
    return achados


def _contem(dados: bytes, desvio: int, agulha: np.ndarray) -> bool:
    util = (len(dados) - desvio) // 4
    if util < len(agulha):
        return False
    valores = np.frombuffer(dados, np.float32, count=util, offset=desvio)
    with np.errstate(invalid="ignore", over="ignore"):  # bytes quaisquer viram NaN/inf
        candidatos = np.flatnonzero(np.abs(valores - agulha[0]) < 1e-6)
    return any(
        i + len(agulha) <= len(valores)
        and np.allclose(valores[i : i + len(agulha)], agulha, atol=1e-6, rtol=0)
        for i in candidatos
    )


def _rss_de_pico_mib() -> float:
    """`VmHWM` do processo: o `ru_maxrss` no Linux carrega o pico do pai através do `exec`."""
    for linha in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if linha.startswith("VmHWM:"):
            return int(linha.split()[1]) / 1024
    return float("nan")


def _cpu() -> float:
    uso = resource.getrusage(resource.RUSAGE_SELF)
    return uso.ru_utime + uso.ru_stime


def filho(candidato: str, dados: Path, saida: Path) -> None:
    """Uma execução, num processo novo: indexa, consulta, apaga e procura o resto."""
    bruto = json.loads(dados.read_text(encoding="utf-8"))
    embedder = EmbedderPronto(vetores=bruto["vetores"])
    itens = [ItemDoIndice(**i) for i in bruto["itens"]]
    consultas: list[str] = bruto["consultas"]
    resultado: dict[str, Any] = {"candidato": candidato}
    with tempfile.TemporaryDirectory(prefix=f"indice-{candidato}-") as pasta_tmp:
        pasta = Path(pasta_tmp)
        inicio_cpu, inicio = _cpu(), time.monotonic()
        indice = _abrir(candidato, pasta, embedder)
        for n in range(0, len(itens), LOTE):
            indice.upsert(itens[n : n + LOTE])
        resultado["indexar_s"] = time.monotonic() - inicio
        resultado["indexar_cpu_s"] = _cpu() - inicio_cpu
        resultado["n"] = indice.stats()["count"]

        # carga "fria": índice reaberto do disco, primeira busca
        del indice
        indice = _abrir(candidato, pasta, embedder)
        inicio = time.monotonic()
        indice.search(consultas[0], K, onde=SO_MEMORIA)
        resultado["fria_ms"] = (time.monotonic() - inicio) * 1000.0

        latencias: list[float] = []
        listas: list[list[list[Any]]] = []
        for _ in range(3):
            for texto in consultas:
                inicio = time.monotonic()
                acertos = indice.search(texto, K, onde=SO_MEMORIA)
                latencias.append((time.monotonic() - inicio) * 1000.0)
                if len(listas) < len(consultas):
                    listas.append([[a.id, a.score] for a in acertos])
        resultado["quente_ms"] = latencias
        resultado["listas"] = listas

        # o filtro desce antes do ranking? pede só turnos e confere tipo e quantidade
        turnos = indice.search(consultas[0], K, onde={"tipo": "turno"})
        tipos = {i.id: i.metadata["tipo"] for i in itens}
        resultado["filtro_k_cheio"] = len(turnos) == K
        resultado["filtro_so_turno"] = all(tipos[a.id] == "turno" for a in turnos)

        resultado["disco_bytes"] = indice.stats()["bytes"]
        resultado["rss_mib"] = _rss_de_pico_mib()

        # exclusão verificável
        # o turno e a memória dele têm o mesmo texto (o mesmo vetor): apaga os dois, como o
        # "esquecer o turno" em cascata faz
        memorias = [i for i in itens if i.metadata["tipo"] == "memoria"]
        alvo, segundo = memorias[0], memorias[-1]
        gemeos = {
            t: [i.id for i in itens if i.text_redacted == t]
            for t in (alvo.text_redacted, segundo.text_redacted)
        }
        agulha = embedder.vetores[f"passage:{alvo.text_redacted}"]
        resultado["vetor_antes"] = _onde_esta(pasta, agulha)
        removidos = indice.delete(gemeos[alvo.text_redacted])
        resultado["apagou"] = removidos == len(gemeos[alvo.text_redacted]) and all(
            a.id != alvo.id for a in indice.search(alvo.text_redacted, K)
        )
        resultado["vetor_depois_de_apagar"] = _onde_esta(pasta, agulha)
        agulha2 = embedder.vetores[f"passage:{segundo.text_redacted}"]
        if candidato == "lance":
            indice.compactar()
            resultado["vetor_depois_de_compactar"] = _onde_esta(pasta, agulha)
            indice.delete(gemeos[segundo.text_redacted])  # agora num fragmento só, já compactado
            indice.compactar()
            resultado["segundo_depois_de_compactar"] = _onde_esta(pasta, agulha2)
            inicio = time.monotonic()
            indice.expurgar()
            resultado["expurgar_ms"] = (time.monotonic() - inicio) * 1000.0
            resultado["segundo_depois_de_expurgar"] = _onde_esta(pasta, agulha2)
            resultado["n_depois"] = indice.stats()["count"]
        else:
            indice.delete(gemeos[segundo.text_redacted])
            del indice
            indice = _abrir(candidato, pasta, embedder)  # "reiniciar" o processo do índice
            resultado["vetor_depois_de_reabrir"] = _onde_esta(pasta, agulha)
            resultado["segundo_depois_de_reabrir"] = _onde_esta(pasta, agulha2)
            del indice
            subprocess.run(  # a manutenção documentada do Chroma local
                [
                    str(Path(sys.executable).with_name("chroma")),
                    "vacuum",
                    "--path",
                    str(pasta),
                    "--force",
                ],
                check=True,
                capture_output=True,
            )
            indice = _abrir(candidato, pasta, embedder)
            resultado["vetor_depois_do_vacuum"] = _onde_esta(pasta, agulha)
            resultado["segundo_depois_do_vacuum"] = _onde_esta(pasta, agulha2)
            resultado["n_depois"] = indice.stats()["count"]
        resultado["disco_depois_bytes"] = indice.stats()["bytes"]
    saida.write_text(json.dumps(resultado), encoding="utf-8")


# --- métricas ---------------------------------------------------------------------------
def recall(lista: Sequence[str], gabarito: set[str], k: int = K) -> float:
    return len(set(lista[:k]) & gabarito) / len(gabarito)


def ndcg(lista: Sequence[str], gabarito: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, u in enumerate(lista[:k]) if u in gabarito)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gabarito), k)))
    return dcg / ideal


def calibrar_limiar(pares: Sequence[tuple[float, bool]]) -> float:
    """Limiar que maximiza a acurácia balanceada (abster nos negativos × responder nos
    positivos). `pares` = (melhor escore, é negativo)."""
    candidatos = sorted({round(e, 4) for e, _ in pares})
    negativos = [e for e, neg in pares if neg]
    positivos = [e for e, neg in pares if not neg]

    def acuracia(limiar: float) -> float:
        abstem = sum(e < limiar for e in negativos) / max(len(negativos), 1)
        responde = sum(e >= limiar for e in positivos) / max(len(positivos), 1)
        return (abstem + responde) / 2

    return max(candidatos, key=lambda limiar: (acuracia(limiar), -limiar)) if candidatos else 0.0


def qualidade(
    consultas: Sequence[Consulta],
    listas: dict[str, list[tuple[str, float]]],
    gabaritos: dict[str, set[str]],
    calibracao: set[str],
    retidas: set[str],
) -> dict[str, float]:
    limiar = calibrar_limiar(
        [
            (listas[c.id][0][1] if listas[c.id] else 0.0, c.subconjunto == "C2d")
            for c in consultas
            if c.id in calibracao
        ]
    )
    saida: dict[str, float] = {"limiar": limiar}
    reportadas = [c for c in consultas if c.id in retidas]
    for sub in ("C2a", "C2b", "C2c"):
        do_sub = [c for c in reportadas if c.subconjunto == sub]
        ids = {c.id: [u for u, _ in listas[c.id]] for c in do_sub}
        saida[f"recall20_{sub}"] = sum(recall(ids[c.id], gabaritos[c.id]) for c in do_sub) / len(
            do_sub
        )
        saida[f"ndcg10_{sub}"] = sum(ndcg(ids[c.id], gabaritos[c.id]) for c in do_sub) / len(do_sub)
    positivas = [c for c in reportadas if c.subconjunto != "C2d"]
    saida["recall20"] = sum(
        recall([u for u, _ in listas[c.id]], gabaritos[c.id]) for c in positivas
    ) / len(positivas)
    negativas = [c for c in reportadas if c.subconjunto == "C2d"]
    melhor = {c.id: (listas[c.id][0][1] if listas[c.id] else 0.0) for c in reportadas}
    saida["abstencao_correta"] = sum(melhor[c.id] < limiar for c in negativas) / len(negativas)
    saida["abstencao_indevida"] = sum(melhor[c.id] < limiar for c in positivas) / len(positivas)
    saida["n_retidas"] = len(reportadas)
    return saida


# --- o pai ------------------------------------------------------------------------------
def medir(pasta_saida: Path) -> dict[str, Any]:
    corpus = gerar()
    montado = montar(corpus, _Nulo())
    itens = [i for i in montado.itens]
    embedder = EmbedderE5()
    inicio = time.monotonic()
    vetores: dict[str, list[float]] = {}
    textos = sorted({i.text_redacted for i in itens})
    for n in range(0, len(textos), 64):
        lote = textos[n : n + 64]
        for texto, vetor in zip(lote, embedder.embed(lote, "passage"), strict=True):
            vetores[f"passage:{texto}"] = vetor
    embed_passagens_s = time.monotonic() - inicio
    alvo = next(i for i in itens if i.metadata["tipo"] == "memoria")
    (vetores[f"query:{alvo.text_redacted}"],) = embedder.embed([alvo.text_redacted], "query")
    tempos_de_consulta: list[float] = []
    for c in corpus.consultas:
        inicio = time.monotonic()
        (vetores[f"query:{c.texto}"],) = embedder.embed([c.texto], "query")
        tempos_de_consulta.append((time.monotonic() - inicio) * 1000.0)

    with tempfile.TemporaryDirectory(prefix="harness-indice-") as tmp:
        dados = Path(tmp) / "dados.json"
        dados.write_text(
            json.dumps(
                {
                    "vetores": vetores,
                    "itens": [
                        {
                            "id": i.id,
                            "text_redacted": i.text_redacted,
                            "content_hash": i.content_hash,
                            "metadata": dict(i.metadata),
                        }
                        for i in itens
                    ],
                    "consultas": [c.texto for c in corpus.consultas],
                }
            ),
            encoding="utf-8",
        )
        execucoes: dict[str, list[dict[str, Any]]] = {c: [] for c in CANDIDATOS}
        for rodada in range(EXECUCOES):
            for candidato in CANDIDATOS:
                saida = Path(tmp) / f"{candidato}-{rodada}.json"
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "tools.harness_indice",
                        "--filho",
                        candidato,
                        "--dados",
                        str(dados),
                        "--saida-filho",
                        str(saida),
                    ],
                    check=True,
                    cwd=RAIZ,
                )
                execucoes[candidato].append(json.loads(saida.read_text(encoding="utf-8")))

    calibracao, retidas = corpus.dividir()
    gabaritos = {c.id: montado.gabarito(c) for c in corpus.consultas}
    resumo: dict[str, Any] = {
        "corpus_hash": corpus.hash,
        "n_unidades": len(itens),
        "n_memoria": sum(i.metadata["tipo"] == "memoria" for i in itens),
        "n_consultas": len(corpus.consultas),
        "n_calibracao": len(calibracao),
        "n_retidas": len(retidas),
        "embed_passagens_s": embed_passagens_s,
        "embed_consulta_p50_ms": percentil(tempos_de_consulta, 50),
        "embed_consulta_p95_ms": percentil(tempos_de_consulta, 95),
        "hardware": hardware(),
        "execucoes": [],
        "veto": {},
    }
    for candidato, rodadas in execucoes.items():
        for numero, dados_da_rodada in enumerate(rodadas, start=1):
            listas = {
                c.id: [(u, s) for u, s in dados_da_rodada["listas"][n]]
                for n, c in enumerate(corpus.consultas)
            }
            resumo["execucoes"].append(
                {
                    "candidato": candidato,
                    "execucao": numero,
                    **qualidade(corpus.consultas, listas, gabaritos, calibracao, retidas),
                    "busca_p50_ms": percentil(dados_da_rodada["quente_ms"], 50),
                    "busca_p95_ms": percentil(dados_da_rodada["quente_ms"], 95),
                    "busca_n": len(dados_da_rodada["quente_ms"]),
                    "fria_ms": dados_da_rodada["fria_ms"],
                    "indexar_por_1k_ms": dados_da_rodada["indexar_s"] * 1e6 / len(itens),
                    "indexar_cpu_por_1k_ms": dados_da_rodada["indexar_cpu_s"] * 1e6 / len(itens),
                    "rss_pico_mib": dados_da_rodada["rss_mib"],
                    "disco_mib": dados_da_rodada["disco_bytes"] / 2**20,
                    "expurgar_ms": dados_da_rodada.get("expurgar_ms", float("nan")),
                }
            )
        final = [
            v
            for chave, v in rodadas[0].items()
            if chave in ("vetor_depois_do_vacuum", "segundo_depois_do_vacuum")
            or chave in ("vetor_depois_de_compactar", "segundo_depois_de_expurgar")
        ]
        resumo["veto"][candidato] = {
            "filtro_antes_do_ranking": all(
                r["filtro_k_cheio"] and r["filtro_so_turno"] for r in rodadas
            ),
            "delete_tira_da_busca": all(r["apagou"] for r in rodadas),
            "vetor_no_disco_depois_do_delete": bool(rodadas[0]["vetor_depois_de_apagar"]),
            "vetor_no_disco_depois_da_manutencao": any(bool(v) for v in final),
            "manutencao": (
                "chroma vacuum (CLI documentado) e reabrir o cliente"
                if candidato == "chroma"
                else "IndiceLance.expurgar (reescrever + optimize), API pública"
            ),
            "onde_ficou": "; ".join(sorted({x for v in final for x in v})) or "-",
            "listas_iguais_nas_3": all(r["listas"] == rodadas[0]["listas"] for r in rodadas),
        }
    a, b = (execucoes[c][0]["listas"] for c in CANDIDATOS)
    resumo["sobreposicao_top20"] = sum(
        len({x for x, _ in la} & {y for y, _ in lb}) / K for la, lb in zip(a, b, strict=True)
    ) / len(a)
    resumo["decisao"] = decidir(resumo)
    publicar(resumo, pasta_saida)
    return resumo


def _mediana(resumo: dict[str, Any], candidato: str, campo: str) -> float:
    valores = [e[campo] for e in resumo["execucoes"] if e["candidato"] == candidato]
    return float(statistics.median(valores))


def decidir(resumo: dict[str, Any]) -> dict[str, str]:
    """A regra da §8.1, fechada antes de medir, aplicada aos números — na ordem dela."""
    vetados = [
        c
        for c, v in resumo["veto"].items()
        if v["vetor_no_disco_depois_da_manutencao"] or not v["delete_tira_da_busca"]
    ]
    recall = {c: _mediana(resumo, c, "recall20") * 100 for c in CANDIDATOS}
    p95 = {c: _mediana(resumo, c, "busca_p95_ms") for c in CANDIDATOS}
    diferenca = recall["lance"] - recall["chroma"]
    razao = p95["chroma"] / p95["lance"]
    if len(vetados) == 1:
        vencedor = next(c for c in CANDIDATOS if c not in vetados)
        regra = f"regra 1 (veto): {vetados[0]} guarda o vetor apagado no disco"
    elif len(vetados) == 2:
        vencedor, regra = "nenhum", "regra 1: os dois vetados"
    elif abs(diferenca) <= 2 and abs(p95["lance"] - p95["chroma"]) / p95["chroma"] <= 0.30:
        vencedor, regra = "chroma", "regra 2: empate técnico, fica Chroma"
    elif diferenca > 5 or razao > 2:
        vencedor, regra = "lance", "regra 3: LanceDB ganha por margem"
    elif 2 < diferenca <= 5:
        vencedor, regra = "dono", "regra 4: zona cinzenta, decide o dono"
    else:
        vencedor, regra = "chroma", "fora das regras 2–4: fica o mais simples (Chroma, o do dono)"
    return {
        "vencedor": vencedor,
        "regra": regra,
        "recall_lance_menos_chroma_pontos": f"{diferenca:+.1f}",
        "p95_chroma_sobre_lance": f"{razao:.2f}",
    }


@dataclass(slots=True)
class _Nulo:
    def upsert(self, itens: Any) -> int:
        return len(itens)

    def delete(self, ids: Any) -> int:
        return 0

    def search(self, query: str, k: int, onde: Any = None) -> list[Any]:
        return []

    def stats(self) -> dict[str, Any]:
        return {}


def publicar(resumo: dict[str, Any], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    campos = [k for k in resumo["execucoes"][0] if k not in ("candidato", "execucao")]
    with (pasta / f"{NOME}.csv").open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["candidato", "execucao", *campos])
        for linha in resumo["execucoes"]:
            escritor.writerow(
                [linha["candidato"], linha["execucao"], *(_fmt(linha[c]) for c in campos)]
            )
        escritor.writerow([])
        vetos = list(next(iter(resumo["veto"].values())))
        escritor.writerow(["candidato_veto", *vetos])
        for candidato, valores in resumo["veto"].items():
            escritor.writerow([candidato, *(_fmt(valores[c]) for c in vetos)])
    (pasta / f"{NOME}.md").write_text(relatorio(resumo), encoding="utf-8")


def _fmt(valor: Any) -> str:
    if isinstance(valor, float):
        return "nan" if math.isnan(valor) else f"{valor:.4f}"
    return str(valor)


def _commit() -> str:
    resultado = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 — git no PATH, argv explícito
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )
    return resultado.stdout.strip() or "?"


def relatorio(resumo: dict[str, Any]) -> str:
    hw = resumo["hardware"]
    med = {
        c: {
            k: _mediana(resumo, c, k)
            for k in resumo["execucoes"][0]
            if k not in ("candidato", "execucao")
        }
        for c in CANDIDATOS
    }
    decisao = resumo["decisao"]
    linhas = [
        "# F3-01 — índice da memória: ChromaDB × LanceDB (SPEC §8.1)",
        "",
        f"**Gerado por** `tools/harness_indice.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}. **Commit:** `{_commit()}`.",
        "",
        "> **Corpus sintético.** O C2 da SPEC é anotado pelo dono sobre a vida dele; este é o "
        "substituto gerado com semente (`tools/corpus_c2.py`), com gabarito por construção. Ele "
        "compara os dois índices **no mesmo** corpus — não diz quanto o Jarvis acerta na vida do "
        "dono. A decisão abaixo é provisória até o C2 real.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {hw['cpu']}, {hw['nucleos']} fios, {hw['memoria']} de RAM; "
        f"{hw['plataforma']}, Python {hw['python']}",
        f"- corpus `{resumo['corpus_hash']}`: {resumo['n_unidades']} unidades no índice "
        f"({resumo['n_memoria']} memórias, o resto turnos), {resumo['n_consultas']} consultas "
        f"(C2a–C2d); limiar de abstinência calibrado em {resumo['n_calibracao']} consultas e "
        f"métricas de qualidade nas {resumo['n_retidas']} retidas",
        "- embedding: `intfloat/multilingual-e5-small` (ONNX, CPU, 2 fios), calculado **uma "
        f"vez** e entregue aos dois — {resumo['embed_passagens_s']:.1f} s para as passagens; "
        f"por consulta p50 {resumo['embed_consulta_p50_ms']:.1f} ms, "
        f"p95 {resumo['embed_consulta_p95_ms']:.1f} ms (fora dos números de busca abaixo)",
        "- 3 execuções por candidato, cada uma num processo novo; busca = 3 passadas pelas "
        "consultas com `k=20` e filtro `tipo=memoria, status=active`; percentil por execução, "
        "publicada a mediana das 3",
        f"- versões: chromadb {versao('chromadb')}, lancedb {versao('lancedb')}",
        "",
        "## Resultado (mediana das 3 execuções)",
        "",
        _linha(
            "candidato",
            "recall@20",
            "nDCG@10 C2a",
            "abstinência correta (C2d)",
            "abstinência indevida",
            "busca p50",
            "busca p95",
            "busca fria",
            "indexar por 1k unidades",
            "CPU por 1k",
            "RSS de pico",
            "disco",
        ),
        "|---|" + "---:|" * 11,
    ]
    for c in CANDIDATOS:
        m = med[c]
        linhas.append(
            _linha(
                f"`{c}`",
                f"{m['recall20']:.3f}",
                f"{m['ndcg10_C2a']:.3f}",
                f"{m['abstencao_correta']:.2f}",
                f"{m['abstencao_indevida']:.2f}",
                f"{m['busca_p50_ms']:.2f} ms",
                f"{m['busca_p95_ms']:.2f} ms",
                f"{m['fria_ms']:.2f} ms",
                f"{m['indexar_por_1k_ms']:.0f} ms",
                f"{m['indexar_cpu_por_1k_ms']:.0f} ms",
                f"{m['rss_pico_mib']:.0f} MiB",
                f"{m['disco_mib']:.1f} MiB",
            )
        )
    linhas += [
        "",
        "Sobreposição média do top-20 entre os dois (1ª execução): "
        f"{resumo['sobreposicao_top20']:.3f}. Por subconjunto (retidas, mediana): "
        + "; ".join(
            f"`{c}` "
            + ", ".join(
                f"{sub} recall@20 {med[c][f'recall20_{sub}']:.3f}" for sub in ("C2a", "C2b", "C2c")
            )
            for c in CANDIDATOS
        )
        + ".",
        "",
        "## Critérios de veto",
        "",
        _linha(
            "candidato",
            "filtro antes do ranking",
            "`delete` tira da busca",
            "vetor no disco depois do `delete`",
            "vetor no disco depois da manutenção",
            "manutenção tentada",
            "onde ficou",
            "listas iguais nas 3 execuções",
        ),
        "|---|:-:|:-:|:-:|:-:|---|---|:-:|",
    ]
    for c, v in resumo["veto"].items():
        linhas.append(
            _linha(
                f"`{c}`",
                _sim(v["filtro_antes_do_ranking"]),
                _sim(v["delete_tira_da_busca"]),
                _sim(v["vetor_no_disco_depois_do_delete"]),
                f"**{_sim(v['vetor_no_disco_depois_da_manutencao'])}**",
                v["manutencao"],
                f"`{v['onde_ficou']}`",
                _sim(v["listas_iguais_nas_3"]),
            )
        )
    linhas += [
        "",
        "Como a exclusão é verificada: o harness apaga as unidades de uma memória (a memória e o "
        "turno de mesmo texto) e procura os **bytes do vetor** — os 16 primeiros floats, crus ou "
        "renormalizados, com tolerância 1e-6, em qualquer alinhamento — em todos os arquivos da "
        "pasta do índice. No LanceDB, um segundo vetor é apagado depois de a tabela já estar "
        "compactada num fragmento só: é o caso em que o `optimize` sozinho não reescreve o "
        "fragmento (menos de 10% de linhas apagadas). `expurgar` custou "
        f"{med['lance']['expurgar_ms']:.1f} ms com {resumo['n_unidades']} unidades.",
        "",
        "Windows: o `uv.lock` tem rodas `win_amd64` das duas bibliotecas; **não executado** — não "
        "há máquina Windows aqui. Os dois são embutidos (sem serviço), em Linux verificado.",
        "",
        "## Decisão pela regra da §8.1 (fechada antes de medir)",
        "",
        f"- **{decisao['regra']}** → vencedor: **{decisao['vencedor']}**",
        f"- recall@20 LanceDB − Chroma: {decisao['recall_lance_menos_chroma_pontos']} pontos; "
        f"p95 Chroma ÷ LanceDB: {decisao['p95_chroma_sobre_lance']}",
        "",
        "## O que não foi medido",
        "",
        "- **C1 e C2 reais** (memórias exportadas do Orchestrator e consultas anotadas pelo dono): "
        "o corpus aqui é sintético",
        "- **C3, latência sob indexação concorrente**",
        "- **híbrido nativo**: os dois candidatos ficam só com a lista densa, porque a léxica "
        "(FTS5) e a fusão (RRF) já estão no livro-razão SQLite (`jarvis.memoryd.recuperacao`), "
        "para qualquer índice — o FTS do LanceDB não foi usado nem medido",
        "- **reranker** e outros embeddings (e5-base, bge-m3, Qwen3-Embedding): a §8.1 lista; aqui "
        "só o e5-small, o que o Orchestrator do dono já usa",
        "- **Windows**, ver acima",
        "",
    ]
    return "\n".join(linhas)


def _linha(*celulas: str) -> str:
    return "| " + " | ".join(celulas) + " |"


def _sim(valor: bool) -> str:
    return "sim" if valor else "não"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    parser.add_argument("--filho", choices=CANDIDATOS)
    parser.add_argument("--dados", type=Path)
    parser.add_argument("--saida-filho", type=Path)
    args = parser.parse_args(argv)
    if args.filho:
        filho(args.filho, args.dados, args.saida_filho)
        return 0
    resumo = medir(args.saida)
    print(
        json.dumps(
            {k: v for k, v in resumo.items() if k != "embed_consulta_ms"},
            indent=1,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
