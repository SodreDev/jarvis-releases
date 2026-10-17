"""Mede o detector de endereçamento no corpus sintético (ADR-0029).

    uv run python tools/medir_enderecamento.py --regras        # baseline por regras, local
    uv run python tools/medir_enderecamento.py --oraculo       # confere a conta (acerta tudo)
    uv run python tools/medir_enderecamento.py --openrouter    # Jev na nuvem: UMA chamada por fala

Publica **falso-aceite** (fala alheia que virou pedido — o erro caro), **falso-rejeito** (fala
para o Jarvis ignorada — o erro barato), acerto da intenção entre as aceitas e a latência
p50/p95. `--openrouter` manda o texto das falas do corpus (sintéticas, sem dado do dono) ao
OpenRouter com a chave do ambiente/chaveiro, nunca impressa; recusa sob `CI=1`.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jarvis.ambiente import em_ci
from jarvis.decisao.enderecamento import DetectorDeEnderecamento, Intencao, Limiares
from jarvis.decisao.fake import ClassificadorFalso, Roteiro, endereco
from jarvis.decisao.interface import ClassificadorDeDecisao, Pergunta, Resposta

CORPUS = Path(__file__).resolve().parent.parent / "medicao" / "enderecamento" / "falas.jsonl"

IMPERATIVOS = (
    "abre", "abrir", "anota", "cria", "procura", "toca", "fecha", "agenda", "liga", "para ",
    "repete", "pausa", "me conta", "me explica", "me recomenda", "sugere", "me passa",
)  # fmt: skip


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


def roteiro_de_regras() -> Roteiro:
    """O baseline que qualquer um escreveria em dez minutos: o nome, um verbo de ordem no começo,
    ou uma pergunta. Serve de régua: o classificador só vale a nuvem se bater isto."""

    def responder(estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        fala = _sem_acento(str(estado["fala"]))
        perguntou = estado["o_assistente_acabou_de_fazer_uma_pergunta"] == "sim"
        chamou = bool(re.search(r"\bjarvis\b", fala)) and not re.search(
            r"(o|do|pro|pelo) jarvis", fala
        )
        ordem = fala.startswith(IMPERATIVOS)
        pergunta = fala.endswith("?") and not re.search(r"\b(amor|vovo|voce tem)\b", fala)
        resposta_curta = perguntou and fala.strip(" ,.!") in {"sim", "nao", "pode ser"}
        endereçada = chamou or ordem or pergunta or resposta_curta
        intencao = (
            "acao" if ordem else "sugestao" if re.search(r"recomenda|sugere|acha", fala)
            else "resposta"
        )  # fmt: skip
        return endereco(0.95 if endereçada else 0.05, intencao if endereçada else "ignorar")(
            estado, perguntas
        )

    return responder


def roteiro_do_oraculo(corpus: list[dict[str, Any]]) -> Roteiro:
    por_fala = {linha["fala"]: linha for linha in corpus}

    def responder(estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        linha = por_fala[str(estado["fala"])]
        alta = linha["rotulo"] == "jarvis"
        return endereco(0.97 if alta else 0.03, linha["intencao"])(estado, perguntas)

    return responder


@dataclass(slots=True)
class Resultado:
    total: int = 0
    para_o_jarvis: int = 0
    alheias: int = 0
    falso_aceite: int = 0
    falso_rejeito: int = 0
    intencao_certa: int = 0
    aceitas_certas: int = 0
    falhas: int = 0


def medir(
    classificador: ClassificadorDeDecisao, corpus: list[dict[str, Any]], limiares: Limiares
) -> tuple[Resultado, list[float], list[dict[str, Any]], list[dict[str, Any]]]:
    resultado = Resultado()
    itens: list[dict[str, Any]] = []
    latencias: list[float] = []
    erros: list[dict[str, Any]] = []
    for linha in corpus:
        # Detector novo por fala: cada fala é avaliada sem a histerese da anterior, para o
        # número ser do limiar de ENTRADA (o pior caso para falso-rejeito).
        detector = DetectorDeEnderecamento(classificador=classificador, limiares=limiares)
        d = detector.avaliar(linha["fala"], jarvis_perguntou=linha["jarvis_perguntou"])
        resultado.total += 1
        # Toda fala com o seu `p`, não só os erros: é o que deixa escolher outro limiar sem
        # gastar a nuvem de novo (a 1ª rodada real, de 2026-10-17, só guardou os erros).
        itens.append(
            {
                "id": linha["id"],
                "rotulo": linha["rotulo"],
                "p": d.p_com_o_jarvis,
                "intencao": d.intencao.value,
                "agiu": d.agir,
            }
        )
        if d.motivo.value == "classificador fora":
            resultado.falhas += 1
        else:
            latencias.append(d.ms)
        para = linha["rotulo"] == "jarvis"
        resultado.para_o_jarvis += para
        resultado.alheias += not para
        if d.agir and not para:
            resultado.falso_aceite += 1
            erros.append({"id": linha["id"], "erro": "falso-aceite", "p": d.p_com_o_jarvis})
        if not d.agir and para:
            resultado.falso_rejeito += 1
            erros.append({"id": linha["id"], "erro": "falso-rejeito", "p": d.p_com_o_jarvis})
        if d.agir and para:
            resultado.aceitas_certas += 1
            resultado.intencao_certa += d.intencao is Intencao(linha["intencao"])
    return resultado, latencias, erros, itens


def relatorio(nome: str, r: Resultado, latencias: list[float], erros: list[dict[str, Any]]) -> str:
    def pct(a: int, b: int) -> str:
        return f"{100.0 * a / b:.1f}%" if b else "n/d"

    ordenadas = sorted(latencias)
    p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))] if ordenadas else 0.0
    p50 = statistics.median(ordenadas) if ordenadas else 0.0
    return "\n".join(
        [
            f"== {nome} · {r.total} falas ({r.para_o_jarvis} com o Jarvis, {r.alheias} alheias)",
            f"falso-aceite   {r.falso_aceite:3d} / {r.alheias:3d}  = "
            f"{pct(r.falso_aceite, r.alheias)}   (fala alheia que virou pedido)",
            f"falso-rejeito  {r.falso_rejeito:3d} / {r.para_o_jarvis:3d}  = "
            f"{pct(r.falso_rejeito, r.para_o_jarvis)}   (pedido ignorado)",
            f"intenção certa {r.intencao_certa:3d} / {r.aceitas_certas:3d}  = "
            f"{pct(r.intencao_certa, r.aceitas_certas)}   (entre as aceitas que eram do Jarvis)",
            f"falhas do classificador: {r.falhas}",
            f"latência por consulta: p50 {p50:.0f} ms · p95 {p95:.0f} ms (n={len(latencias)})",
            "erros: " + (", ".join(f"{e['id']}:{e['erro']}" for e in erros) or "nenhum"),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    modo = analisa.add_mutually_exclusive_group(required=True)
    modo.add_argument("--regras", action="store_true")
    modo.add_argument("--oraculo", action="store_true")
    modo.add_argument("--openrouter", action="store_true")
    analisa.add_argument("--corpus", type=Path, default=CORPUS)
    analisa.add_argument("--json", type=Path, help="grava o resultado bruto aqui")
    args = analisa.parse_args(argv)
    corpus = [
        json.loads(linha) for linha in args.corpus.read_text("utf-8").splitlines() if linha.strip()
    ]
    classificador: ClassificadorDeDecisao
    if args.regras:
        nome, classificador = "regras", ClassificadorFalso(roteiro=roteiro_de_regras())
    elif args.oraculo:
        nome, classificador = "oráculo", ClassificadorFalso(roteiro=roteiro_do_oraculo(corpus))
    else:
        if em_ci():
            print("recuso: CI=1 e esta medição fala com a nuvem de verdade", file=sys.stderr)
            return 2
        from jarvis.decisao.openrouter import REGISTRADO, ClassificadorOpenRouter

        aberto = ClassificadorOpenRouter(nuvem_ligada=[REGISTRADO], prazo_s=5.0)
        aberto.abrir()
        nome, classificador = f"openrouter {aberto.modelo}", aberto
    r, latencias, erros, itens = medir(classificador, corpus, Limiares())
    print(relatorio(nome, r, latencias, erros))
    if args.json:
        bruto = {
            "nome": nome,
            "resultado": asdict(r),
            "latencias_ms": latencias,
            "erros": erros,
            "itens": itens,
        }
        args.json.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
