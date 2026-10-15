"""Manifesto de hashes e resumo do corpus (cartão F0-08).

    uv run --frozen python tools/corpus.py manifesto    # (re)gera corpus/manifesto.json
    uv run --frozen python tools/corpus.py verificar     # falha se algum arquivo mudou
    uv run --frozen python tools/corpus.py resumo        # conta itens por pasta

Por que isto existe: medição feita hoje só continua comparável amanhã se o dado for o mesmo.
O manifesto guarda tamanho e sha256 de cada arquivo do corpus; `verificar` acusa arquivo
alterado, novo ou removido, e é isso que entra no CI quando o corpus começar a ter conteúdo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_CORPUS: Final = RAIZ / "corpus"
ARQUIVO_MANIFESTO: Final = PASTA_CORPUS / "manifesto.json"
IGNORADOS: Final = ("manifesto.json",)
PASTAS_IGNORADAS: Final = ("exportado",)
"""`exportado/` é derivado e fica fora do repositório — não entra no manifesto."""


@dataclass(frozen=True, slots=True)
class Divergencia:
    arquivo: str
    o_que: str

    def __str__(self) -> str:
        return f"{self.arquivo}: {self.o_que}"


def sha256(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            digestor.update(bloco)
    return digestor.hexdigest()


def arquivos(pasta: Path = PASTA_CORPUS) -> list[Path]:
    achados = [
        caminho
        for caminho in sorted(pasta.rglob("*"))
        if caminho.is_file()
        and caminho.name not in IGNORADOS
        and not any(parte in PASTAS_IGNORADAS for parte in caminho.relative_to(pasta).parts)
    ]
    return achados


def gerar_manifesto(pasta: Path = PASTA_CORPUS) -> dict[str, Any]:
    itens = {
        str(caminho.relative_to(pasta)): {
            "sha256": sha256(caminho),
            "bytes": caminho.stat().st_size,
        }
        for caminho in arquivos(pasta)
    }
    return {
        "versao": 1,
        "descricao": "sha256 de cada arquivo do corpus (cartão F0-08). Gerado; não editar.",
        "arquivos": itens,
    }


def verificar(pasta: Path = PASTA_CORPUS, manifesto: Path | None = None) -> list[Divergencia]:
    alvo = manifesto or (pasta / "manifesto.json")
    if not alvo.exists():
        return [Divergencia(alvo.name, "manifesto não existe; rode `corpus.py manifesto`")]
    gravado: dict[str, Any] = json.loads(alvo.read_text(encoding="utf-8"))
    esperados: dict[str, Any] = gravado.get("arquivos", {})
    atuais = {str(c.relative_to(pasta)): c for c in arquivos(pasta)}

    divergencias: list[Divergencia] = []
    for nome, esperado in sorted(esperados.items()):
        caminho = atuais.pop(nome, None)
        if caminho is None:
            divergencias.append(Divergencia(nome, "está no manifesto e não existe mais"))
            continue
        digest = sha256(caminho)
        if digest != esperado.get("sha256"):
            divergencias.append(
                Divergencia(
                    nome,
                    f"conteúdo mudou (sha256 {esperado.get('sha256', '?')[:12]}… → {digest[:12]}…)",
                )
            )
    divergencias += [Divergencia(nome, "existe e não está no manifesto") for nome in sorted(atuais)]
    return divergencias


def resumo(pasta: Path = PASTA_CORPUS) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for caminho in arquivos(pasta):
        relativo = caminho.relative_to(pasta)
        chave = relativo.parts[0] if len(relativo.parts) > 1 else "(raiz)"
        if caminho.suffix == ".jsonl":
            linhas = sum(
                1 for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip()
            )
            contagem[f"{chave} (itens)"] = contagem.get(f"{chave} (itens)", 0) + linhas
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("acao", choices=["manifesto", "verificar", "resumo"])
    analisa.add_argument("--pasta", type=Path, default=PASTA_CORPUS)
    args = analisa.parse_args(argv)

    if args.acao == "manifesto":
        manifesto = gerar_manifesto(args.pasta)
        destino = args.pasta / "manifesto.json"
        destino.write_text(
            json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"{len(manifesto['arquivos'])} arquivo(s) em {destino.relative_to(RAIZ)}")
        return 0

    if args.acao == "verificar":
        divergencias = verificar(args.pasta)
        for divergencia in divergencias:
            print(f"DIVERGÊNCIA {divergencia}")
        if divergencias:
            print(f"\n{len(divergencias)} divergência(s): o corpus mudou desde o manifesto")
            return 1
        print("corpus confere com o manifesto")
        return 0

    for chave, quantos in sorted(resumo(args.pasta).items()):
        print(f"{chave}: {quantos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
