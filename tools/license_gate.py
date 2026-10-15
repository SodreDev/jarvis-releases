"""Porta de licença: nada não comercial entra no repositório (ADR-0011, cartão F0-09).

Inventaria **dependências instaladas** e **modelos** (embedding, reranker, VAD, ASR, TTS) com
licença e origem, e sai com código diferente de zero se achar cláusula não comercial ou
"research only" — e também se um item em uso estiver sem licença conhecida.

Uso:

    uv run --frozen python tools/license_gate.py            # o que o CI roda (offline)
    uv run --frozen python tools/license_gate.py --tabela   # imprime a tabela completa
    uv run --frozen python tools/license_gate.py --online   # confere os model cards na origem

O modo `--online` existe para refazer a verificação de `licenses/modelos.toml` contra o model
card oficial; o CI roda offline, porque uma porta de qualidade não pode depender de rede.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from importlib import metadata
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
ARQUIVO_MODELOS: Final = RAIZ / "licenses" / "modelos.toml"
ARQUIVO_EXCECOES: Final = RAIZ / "licenses" / "dependencias-sem-metadados.toml"
ARQUIVO_TABELA: Final = RAIZ / "docs" / "licencas.md"


class Categoria(StrEnum):
    PERMISSIVA = auto()
    ATRIBUICAO = auto()
    """Uso comercial permitido, com atribuição obrigatória no produto (CC-BY, BSD-4)."""

    COPYLEFT_FORTE = auto()
    """Comercial é permitido, mas obriga abrir o derivado: aviso, não bloqueio."""

    NAO_COMERCIAL = auto()
    """Bloqueio: é o que a ADR-0011 proíbe."""

    DESCONHECIDA = auto()


PERMISSIVAS: Final[frozenset[str]] = frozenset(
    {
        "apache-2.0",
        "apache 2.0",
        "apache software license",
        "mit",
        "mit license",
        "mit-0",
        "bsd",
        "bsd-2-clause",
        "bsd-3-clause",
        "bsd license",
        "isc",
        "0bsd",
        "unlicense",
        "cc0-1.0",
        "psf-2.0",
        "python-2.0",
        "python software foundation license",
        "zlib",
        "mpl-2.0",
        "apache-2.0 or mit",
        "mit or apache-2.0",
        "bsl-1.0",
        "lgpl-2.1-or-later",
        "lgpl-3.0-or-later",
    }
)
ATRIBUICAO_OBRIGATORIA: Final[frozenset[str]] = frozenset(
    {"cc-by-4.0", "cc-by-3.0", "cc-by-sa-4.0", "bsd-4-clause", "openrail", "cdla-permissive-2.0"}
)
COPYLEFT_FORTE: Final[frozenset[str]] = frozenset(
    {"gpl-2.0", "gpl-3.0", "gpl-3.0-only", "gpl-3.0-or-later", "agpl-3.0", "sspl-1.0"}
)
PADROES_NAO_COMERCIAIS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bnon-?commercial\b"),
    re.compile(r"\bnc\b"),
    re.compile(r"cc-by-nc"),
    re.compile(r"\bresearch[\s-]*(only|purposes)\b"),
    re.compile(r"polyform[\s-]*(noncommercial|non-commercial)"),
    re.compile(r"coqui[\s-]*public[\s-]*model[\s-]*license|\bcpml\b"),
    re.compile(r"creativeml[\s-]*openrail[\s-]*m-nc"),
)


PADROES_POR_NOME: Final[tuple[tuple[re.Pattern[str], Categoria], ...]] = (
    # Nome livre em vez de SPDX: muito pacote ainda escreve a licença em prosa.
    # A ordem importa: "lesser general public" tem de ser vista antes de "gpl".
    (re.compile(r"lesser general public|\blgpl\b"), Categoria.PERMISSIVA),
    (re.compile(r"mozilla public license|\bmpl[\s-]*2"), Categoria.PERMISSIVA),
    (re.compile(r"\bapache\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bmit\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bbsd\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bisc\b"), Categoria.PERMISSIVA),
    (re.compile(r"python software foundation|\bpsf\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bzlib\b|\bunlicense\b|public domain|\bcc0\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bboost software license\b"), Categoria.PERMISSIVA),
    (re.compile(r"creative commons attribution(?!.*non)|\bcc[\s-]*by\b"), Categoria.ATRIBUICAO),
    (re.compile(r"affero|\bagpl\b|\bsspl\b|gnu general public|\bgpl\b"), Categoria.COPYLEFT_FORTE),
)


def classificar(licenca: str | None) -> Categoria:
    """Categoria de uma licença a partir do texto declarado (SPDX ou nome)."""
    if licenca is None:
        return Categoria.DESCONHECIDA
    texto = licenca.strip().lower()
    if not texto or texto in {"unknown", "other", "none", "proprietary"}:
        return Categoria.DESCONHECIDA
    if any(padrao.search(texto) for padrao in PADROES_NAO_COMERCIAIS):
        return Categoria.NAO_COMERCIAL
    if texto in PERMISSIVAS:
        return Categoria.PERMISSIVA
    if texto in ATRIBUICAO_OBRIGATORIA:
        return Categoria.ATRIBUICAO
    if texto in COPYLEFT_FORTE:
        return Categoria.COPYLEFT_FORTE
    for padrao, categoria in PADROES_POR_NOME:
        if padrao.search(texto):
            return categoria
    return Categoria.DESCONHECIDA


@dataclass(frozen=True, slots=True)
class Item:
    """Uma coisa com licença: um pacote instalado ou um modelo."""

    tipo: str
    nome: str
    licenca: str | None
    origem: str
    estado: str = "em_uso"
    data_de_acesso: str = ""
    nota: str = ""

    @property
    def categoria(self) -> Categoria:
        return classificar(self.licenca)

    @property
    def bloqueia(self) -> bool:
        """Falha a porta? Não comercial sempre; desconhecida só no que está em uso."""
        if self.estado == "barrado":
            return False  # registrado justamente para ficar fora
        if self.categoria is Categoria.NAO_COMERCIAL:
            return True
        return self.categoria is Categoria.DESCONHECIDA and self.estado == "em_uso"


def _licenca_de_metadados(meta: Any) -> str | None:
    """Licença de um pacote instalado, pela ordem de confiança dos metadados."""
    expressao = meta.get("License-Expression")
    if isinstance(expressao, str) and expressao.strip():
        return expressao.strip()
    classificadores = [
        valor.split("::")[-1].strip()
        for valor in meta.get_all("Classifier") or []
        if isinstance(valor, str) and valor.startswith("License ::")
    ]
    uteis = [c for c in classificadores if c.lower() not in {"osi approved"}]
    if uteis:
        return " AND ".join(sorted(set(uteis)))
    licenca = meta.get("License")
    if isinstance(licenca, str) and licenca.strip():
        primeira = licenca.strip().splitlines()[0]
        return primeira[:120]
    return None


def inventariar_dependencias(pastas: Sequence[str] | None = None) -> list[Item]:
    distribuicoes = (
        metadata.distributions(path=list(pastas)) if pastas else metadata.distributions()
    )
    excecoes = _carregar_excecoes()
    itens: list[Item] = []
    for dist in distribuicoes:
        nome = dist.metadata["Name"] or "?"
        licenca = _licenca_de_metadados(dist.metadata)
        excecao = excecoes.get(nome.lower())
        origem = f"metadados de {nome} {dist.version}"
        if licenca is None and excecao is not None:
            licenca = str(excecao["licenca"])
            origem = str(excecao["fonte"])
        itens.append(
            Item(
                tipo="dependência",
                nome=f"{nome} {dist.version}",
                licenca=licenca,
                origem=origem,
                data_de_acesso=str(excecao["data_de_acesso"]) if excecao else "",
            )
        )
    return sorted(itens, key=lambda i: i.nome.lower())


def _carregar_excecoes() -> dict[str, dict[str, Any]]:
    """Pacotes cujos metadados não declaram licença, verificados à mão com fonte e data."""
    if not ARQUIVO_EXCECOES.exists():
        return {}
    dados = tomllib.loads(ARQUIVO_EXCECOES.read_text(encoding="utf-8"))
    return {str(e["pacote"]).lower(): e for e in dados.get("dependencia", [])}


def inventariar_modelos(arquivo: Path = ARQUIVO_MODELOS) -> list[Item]:
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    itens = [
        Item(
            tipo=f"modelo/{modelo['papel']}",
            nome=str(modelo["id"]),
            licenca=str(modelo["licenca"]),
            origem=str(modelo["fonte"]),
            estado=str(modelo.get("estado", "candidato")),
            data_de_acesso=str(modelo.get("data_de_acesso", "")),
            nota=str(modelo.get("nota", "")),
        )
        for modelo in dados.get("modelo", [])
    ]
    return sorted(itens, key=lambda i: (i.tipo, i.nome.lower()))


def conferir_online(modelos: Iterable[Item], arquivo: Path = ARQUIVO_MODELOS) -> list[str]:
    """Compara a licença registrada com o model card oficial. Devolve as divergências."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    por_id = {str(m["id"]): m for m in dados.get("modelo", [])}
    divergencias: list[str] = []
    for item in modelos:
        registro = por_id[item.nome]
        fonte = str(registro["fonte"])
        if not fonte.startswith("https://"):
            divergencias.append(f"{item.nome}: fonte não é https ({fonte})")
            continue
        if "huggingface.co/api/models/" not in fonte and "api.github.com/repos/" not in fonte:
            print(f"  (pulado, fonte não consultável por API) {item.nome}: {fonte}")
            continue
        try:
            with urllib.request.urlopen(fonte, timeout=30) as resposta:  # noqa: S310
                card: dict[str, Any] = json.load(resposta)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as erro:
            divergencias.append(f"{item.nome}: não deu para consultar a origem ({erro})")
            continue
        oficial = _licenca_do_card(card)
        if oficial.lower() != str(item.licenca).lower():
            divergencias.append(
                f"{item.nome}: registrado {item.licenca!r}, model card diz {oficial!r}"
            )
        else:
            print(f"  ok {item.nome}: {oficial}")
    return divergencias


def _licenca_do_card(card: dict[str, Any]) -> str:
    """Licença oficial, seja do model card do Hugging Face, seja da API do GitHub."""
    if "license" in card and isinstance(card["license"], dict):  # API do GitHub
        return str(card["license"].get("spdx_id", "") or "")
    dados = card.get("cardData", {})
    declarada = str(dados.get("license", "") or "")
    nome = str(dados.get("license_name", "") or "")
    return nome if declarada == "other" and nome else declarada


CABECALHO_TABELA: Final = """# Licenças dos modelos — tabela licença × modelo × fonte

Gerado por `tools/license_gate.py --escrever-tabela` a partir de `licenses/modelos.toml`.
**Não edite à mão**: o CI compara este arquivo com o registro e falha se divergirem
(aceite (b) do cartão F0-09).

Fonte válida é o model card oficial do repositório do modelo (API do Hugging Face) ou o
arquivo de licença do repositório de origem (API do GitHub) — nunca agregador de terceiro.
Refazer a verificação na origem: `tools/license_gate.py --online`.

| papel | modelo | licença | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|---|
"""


def tabela_de_modelos(modelos: Sequence[Item]) -> str:
    """Tabela markdown dos modelos — é o que fica comitado em `docs/licencas.md`."""
    linhas = [
        f"| {item.tipo.removeprefix('modelo/')} | `{item.nome}` | {item.licenca} "
        f"| {item.categoria} | {item.estado} | <{item.origem}> | {item.data_de_acesso} |"
        for item in modelos
    ]
    rodape = (
        "\n**Barrados** (verificados e recusados pela ADR-0011): "
        + ", ".join(f"`{i.nome}` ({i.licenca})" for i in modelos if i.estado == "barrado")
        + ".\n"
    )
    return CABECALHO_TABELA + "\n".join(linhas) + "\n" + rodape


def imprimir_tabela(itens: Sequence[Item]) -> None:
    print(f"\n| {'tipo':16} | {'item':46} | {'licença':28} | {'categoria':15} | estado |")
    print(f"|{'-' * 18}|{'-' * 48}|{'-' * 30}|{'-' * 17}|--------|")
    for item in itens:
        print(
            f"| {item.tipo:16.16} | {item.nome:46.46} | {item.licenca!s:28.28} "
            f"| {item.categoria:15.15} | {item.estado} |"
        )


def main(argv: Sequence[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--tabela", action="store_true", help="imprime a tabela completa")
    analisador.add_argument(
        "--online", action="store_true", help="confere os model cards na origem (precisa de rede)"
    )
    analisador.add_argument(
        "--modelos", type=Path, default=ARQUIVO_MODELOS, help="outro registro de modelos"
    )
    analisador.add_argument(
        "--pasta-pacotes",
        action="append",
        default=None,
        help="inventaria os pacotes desta pasta em vez do ambiente (usado nos testes)",
    )
    analisador.add_argument(
        "--escrever-tabela",
        action="store_true",
        help=f"regrava {ARQUIVO_TABELA.name} a partir do registro de modelos",
    )
    analisador.add_argument(
        "--verificar-tabela",
        action="store_true",
        help="falha se a tabela comitada estiver desatualizada (é o que o CI roda)",
    )
    analisador.add_argument(
        "--estrito-copyleft",
        action="store_true",
        help="trata copyleft forte (GPL/AGPL/SSPL) como bloqueio, não como aviso",
    )
    args = analisador.parse_args(argv)

    modelos = inventariar_modelos(args.modelos)
    dependencias = inventariar_dependencias(args.pasta_pacotes)
    itens = [*modelos, *dependencias]

    if args.tabela:
        imprimir_tabela(itens)

    if args.escrever_tabela:
        ARQUIVO_TABELA.write_text(tabela_de_modelos(modelos), encoding="utf-8")
        print(f"tabela escrita em {ARQUIVO_TABELA.relative_to(RAIZ)}")

    if args.verificar_tabela:
        esperada = tabela_de_modelos(modelos)
        atual = ARQUIVO_TABELA.read_text(encoding="utf-8") if ARQUIVO_TABELA.exists() else ""
        if atual != esperada:
            print(
                f"FALHOU: {ARQUIVO_TABELA.relative_to(RAIZ)} está desatualizada em relação a "
                f"{args.modelos.name}; rode --escrever-tabela"
            )
            return 3

    if args.online:
        print("\nconferindo os model cards na origem:")
        divergencias = conferir_online(modelos, args.modelos)
        for divergencia in divergencias:
            print(f"DIVERGÊNCIA: {divergencia}")
        if divergencias:
            return 2

    bloqueios = [i for i in itens if i.bloqueia]
    avisos = [i for i in itens if i.categoria is Categoria.COPYLEFT_FORTE]
    atribuicoes = [i for i in itens if i.categoria is Categoria.ATRIBUICAO]
    barrados = [i for i in modelos if i.estado == "barrado"]

    print(
        f"\nporta de licença: {len(modelos)} modelos, {len(dependencias)} dependências, "
        f"{len(barrados)} barrados por registro"
    )
    for item in atribuicoes:
        print(f"ATRIBUIÇÃO OBRIGATÓRIA: {item.nome} ({item.licenca}) — tem de aparecer no produto")
    for item in avisos:
        print(f"AVISO copyleft forte: {item.nome} ({item.licenca}) — {item.origem}")
    for item in bloqueios:
        motivo = (
            "não comercial" if item.categoria is Categoria.NAO_COMERCIAL else "licença desconhecida"
        )
        print(f"BLOQUEIO ({motivo}): {item.tipo} {item.nome} — {item.licenca} — {item.origem}")

    if bloqueios:
        print(f"\nFALHOU: {len(bloqueios)} item(ns) incompatível(is) com uso comercial (ADR-0011)")
        return 1
    if avisos and args.estrito_copyleft:
        print(f"\nFALHOU: {len(avisos)} item(ns) copyleft forte com --estrito-copyleft")
        return 1
    print("OK: nenhuma licença não comercial ou desconhecida no caminho do produto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
