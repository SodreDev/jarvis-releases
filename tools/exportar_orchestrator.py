"""Exporta as memórias e decisões do Orchestrator para o esquema da §6.2 (C1; cartão F0-08).

    # 1. gere o dump no Orchestrator (a tool MCP `list_memories` salva um arquivo de texto)
    # 2. exporte:
    uv run --frozen python tools/exportar_orchestrator.py \
        --dump dump.txt --saida corpus/exportado/c1.sqlite --relatorio

O dump pode ser o **texto** que o `list_memories` imprime (um bloco por memória, começando em
`[IA: autor · tipo · pN] Título`) ou um **JSONL** com um objeto por linha. O que entra no
banco é sempre texto **redigido**: segredo não atravessa.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

from jarvis.memoryd.esquema import abrir
from jarvis.memoryd.importacao import Contagem, MemoriaDoOrchestrator, exportar, redigir

RAIZ: Final = Path(__file__).resolve().parent.parent
RELATORIO: Final = RAIZ / "docs" / "medicoes" / "f0-08-corpus-c1.md"

CABECALHO = re.compile(
    r"^\[(?:IA:\s*)?(?P<autor>[^·\]]+?)\s*·\s*(?P<tipo>[a-z_]+)(?:\s*·\s*[a-z_]+)?"
    r"(?:\s*·\s*|\s+)p(?P<prioridade>\d+)\]\s*(?P<titulo>.+)$"
)


def parse_dump(texto: str, *, projeto: str) -> list[MemoriaDoOrchestrator]:
    """Lê a saída de `list_memories`: um cabeçalho por memória, corpo até o próximo."""
    memorias: list[MemoriaDoOrchestrator] = []
    atual: dict[str, Any] | None = None
    corpo: list[str] = []
    for linha in texto.splitlines():
        casado = CABECALHO.match(linha.strip())
        if casado is not None:
            if atual is not None:
                memorias.append(_montar(atual, corpo, projeto))
            atual = casado.groupdict()
            corpo = []
        elif atual is not None and linha.strip() != "---":
            corpo.append(linha)
    if atual is not None:
        memorias.append(_montar(atual, corpo, projeto))
    return memorias


def _montar(cabecalho: dict[str, Any], corpo: list[str], projeto: str) -> MemoriaDoOrchestrator:
    return MemoriaDoOrchestrator(
        autor=str(cabecalho["autor"]).strip(),
        tipo=str(cabecalho["tipo"]).strip(),
        prioridade=int(cabecalho["prioridade"]),
        titulo=str(cabecalho["titulo"]).strip(),
        corpo="\n".join(corpo).strip(),
        projeto=projeto,
    )


def parse_jsonl(texto: str, *, projeto: str) -> list[MemoriaDoOrchestrator]:
    memorias: list[MemoriaDoOrchestrator] = []
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        dados: dict[str, Any] = json.loads(linha)
        memorias.append(
            MemoriaDoOrchestrator(
                autor=str(dados.get("autor", "?")),
                tipo=str(dados.get("tipo", "practice")),
                prioridade=int(dados.get("prioridade", 5)),
                titulo=str(dados.get("titulo", "")),
                corpo=str(dados.get("corpo", dados.get("conteudo", ""))),
                projeto=str(dados.get("projeto", projeto)),
                ocorrido_em=str(dados.get("ocorrido_em", "")),
            )
        )
    return memorias


def escrever_relatorio(contagem: Contagem, *, origem: str, caminho: Path = RELATORIO) -> None:
    """Só a contagem vai para o repositório — o conteúdo exportado fica fora (`.gitignore`)."""
    linhas = [
        "# F0-08 — C1: memórias do Orchestrator no esquema da §6.2",
        "",
        "**Gerado por** `tools/exportar_orchestrator.py --relatorio` (não editar à mão). "
        f"**Fonte:** {origem}.",
        "",
        "## `n` de C1",
        "",
        "| tabela | n |",
        "|---|---:|",
        f"| `episode` | {contagem.episodios} |",
        f"| `entity` | {contagem.entidades} |",
        f"| `assertion` | {contagem.assertivas} |",
        f"| `memory_unit` | {contagem.unidades} |",
        f"| `entity_mention` | {contagem.mencoes} |",
        f"| `entity_edge` (todas) | {contagem.arestas} |",
        f"| `entity_edge` com `status='active'` | {contagem.arestas_ativas} |",
        "",
        f"- **{contagem.entidades_por_episodio:.1f} entidades por episódio** e "
        f"**{contagem.arestas_por_episodio:.1f} arestas por episódio** (todas; "
        f"{contagem.arestas_ativas / contagem.episodios if contagem.episodios else 0:.1f} "
        "ativas por episódio).",
        "- Aresta nasce `proposed` e vira `active` só com duas evidências independentes "
        "(§6.7): é por isso que os dois números são diferentes.",
        "",
        "## Redação de segredo (aceite (a))",
        "",
        f"Trechos redigidos: **{contagem.total_redigido}**."
        + (
            " Nenhum padrão de segredo foi encontrado nesta fonte." if not contagem.redacoes else ""
        ),
        "",
    ]
    if contagem.redacoes:
        linhas += ["| padrão | ocorrências |", "|---|---:|"]
        linhas += [f"| `{nome}` | {n} |" for nome, n in sorted(contagem.redacoes.items())]
        linhas.append("")
    linhas += [
        "Classe de PII dos episódios: "
        + ", ".join(f"`{k}`: {v}" for k, v in sorted(contagem.pii.items()))
        + ".",
        "",
        "## Para que serve este número",
        "",
        "O cartão F0-05 dimensiona o grafo sintético pelo corpus real. A medição publicada em "
        "`f0-05-grafo.md` usou **122 episódios** como base, com a razão **[SUPOSIÇÃO]** de 3 "
        "entidades e 8 arestas por episódio; a tabela acima substitui a suposição pela "
        "contagem medida, e a comparação está nas notas do executor "
        "(`docs/notas-executor-F0.md`, seção F0-08).",
        "",
        "## O que **não** está aqui",
        "",
        "- o conteúdo exportado: fica em `corpus/exportado/`, fora do repositório, porque é "
        "texto do dono e é reconstituível;",
        "- extração de entidade por LLM: a extração do C1 é **determinística** (autor, "
        "projeto, tema, caminho de arquivo, commit), como manda a §6.7;",
        "- qualidade: C1 serve para dimensionar e calibrar, não para medir recall — isso é C2 "
        "(`corpus/consultas/`), em F3.",
        "",
    ]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--dump", type=Path, help="saída de texto do `list_memories`")
    analisa.add_argument("--jsonl", type=Path, help="um objeto por linha")
    analisa.add_argument("--saida", type=Path, required=True, help="banco SQLite de destino")
    analisa.add_argument("--projeto", default="Orchestrator")
    analisa.add_argument("--relatorio", action="store_true", help=f"escreve {RELATORIO.name}")
    analisa.add_argument(
        "--mostrar-redacoes", action="store_true", help="imprime os padrões encontrados"
    )
    args = analisa.parse_args(argv)

    if (args.dump is None) == (args.jsonl is None):
        print("passe --dump OU --jsonl")
        return 2
    fonte = args.dump or args.jsonl
    texto = fonte.read_text(encoding="utf-8", errors="replace")
    memorias = (
        parse_dump(texto, projeto=args.projeto)
        if args.dump is not None
        else parse_jsonl(texto, projeto=args.projeto)
    )
    if not memorias:
        print(f"nenhuma memória reconhecida em {fonte}")
        return 1

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    if args.saida.exists():
        args.saida.unlink()
    con = abrir(args.saida)
    try:
        contagem = exportar(con, memorias)
        con.execute("INSERT INTO memory_unit_fts (memory_unit_fts) VALUES ('rebuild')")
    finally:
        con.close()

    print(f"fonte: {fonte.name} ({len(memorias)} memórias reconhecidas)")
    print(
        f"episódios {contagem.episodios} · entidades {contagem.entidades} · "
        f"assertivas {contagem.assertivas} · unidades {contagem.unidades} · "
        f"menções {contagem.mencoes} · arestas {contagem.arestas} "
        f"({contagem.arestas_ativas} ativas)"
    )
    print(
        f"razões medidas: {contagem.entidades_por_episodio:.1f} entidades/episódio, "
        f"{contagem.arestas_por_episodio:.1f} arestas/episódio"
    )
    print(f"trechos redigidos: {contagem.total_redigido}")
    if args.mostrar_redacoes:
        for nome, n in sorted(contagem.redacoes.items()):
            print(f"  {nome}: {n}")
    print(f"pii: {dict(sorted(contagem.pii.items()))}")

    # Prova simples de que nada de segredo sobrou no que foi gravado.
    con = abrir(args.saida, somente_leitura=True)
    try:
        for linha in con.execute("SELECT text_redacted FROM memory_unit"):
            achados = redigir(str(linha["text_redacted"])).achados
            if achados:
                print(f"FALHOU: segredo não redigido no banco: {achados}")
                return 1
    finally:
        con.close()
    print("conferido: nenhum padrão de segredo sobrou no banco exportado")

    if args.relatorio:
        escrever_relatorio(contagem, origem=fonte.name)
        print(f"relatório em {RELATORIO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
