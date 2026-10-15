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

from jarvis.corpus.rotulos import ErroDeRotulo, Rotulo, contagem, ler_rotulos, validar_arquivo

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_CORPUS: Final = RAIZ / "corpus"
ARQUIVO_MANIFESTO: Final = PASTA_CORPUS / "manifesto.json"
IGNORADOS: Final = ("manifesto.json",)
PREFIXOS_IGNORADOS: Final = ("exportado", "turnos/audio")
"""Caminhos derivados, que ficam fora do repositório (ver `.gitignore`) e fora do manifesto.

- `exportado/`: C1 exportado do Orchestrator, com texto do dono;
- `turnos/audio/`: o áudio das pausas. O sintético é **regenerável** pelo gerador
  (`tools/corpus_sintetico.py --verificar`) e o `sha256` de cada arquivo mora no **rótulo**,
  que é versionado — então o manifesto não carrega 500 entradas de arquivo que o CI não tem, e
  mesmo assim ninguém mede hoje com um áudio e compara amanhã com outro. O áudio real do dono
  (F1-15) entra por pedido dele, nunca por acidente de `git add`.
"""


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


def _derivado(relativo: Path) -> bool:
    caminho = relativo.as_posix()
    return any(
        caminho == prefixo or caminho.startswith(f"{prefixo}/") for prefixo in PREFIXOS_IGNORADOS
    )


def arquivos(pasta: Path = PASTA_CORPUS) -> list[Path]:
    achados = [
        caminho
        for caminho in sorted(pasta.rglob("*"))
        if caminho.is_file()
        and caminho.name not in IGNORADOS
        and not _derivado(caminho.relative_to(pasta))
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


def problemas_de_rotulos(pasta: Path = PASTA_CORPUS) -> list[str]:
    """Valida `turnos/rotulos.jsonl`: formato fechado, split da criação, áudio que não mudou."""
    caminho = pasta / "turnos" / "rotulos.jsonl"
    if not caminho.exists():
        return []
    try:
        _, problemas = validar_arquivo(caminho)
    except ErroDeRotulo as erro:
        return [str(erro)]
    return problemas


def rotulos_do_corpus(pasta: Path = PASTA_CORPUS) -> list[Rotulo]:
    """Rótulos válidos de `turnos/`, ou lista vazia se o arquivo não existe."""
    caminho = pasta / "turnos" / "rotulos.jsonl"
    return ler_rotulos(caminho) if caminho.exists() else []


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
        problemas = problemas_de_rotulos(args.pasta)
        for problema in problemas:
            print(f"RÓTULO {problema}")
        if divergencias or problemas:
            print(
                f"\n{len(divergencias)} divergência(s) de manifesto e {len(problemas)} "
                "problema(s) de rótulo"
            )
            return 1
        print("corpus confere com o manifesto e os rótulos são válidos")
        return 0

    for chave, quantos in sorted(resumo(args.pasta).items()):
        print(f"{chave}: {quantos}")
    try:
        rotulos = rotulos_do_corpus(args.pasta)
    except ErroDeRotulo as erro:
        print(f"RÓTULO {erro}")
        return 1
    if rotulos:
        # Contagem SEPARADA de sintético e real: média que mistura os dois não é número.
        print("\npausas de turno (sintético e real nunca somados):")
        for chave, quantos in contagem(rotulos).items():
            print(f"  {chave}: {quantos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
