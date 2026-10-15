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
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from jarvis.licencas import (
    Categoria,
    classificar,
)

RAIZ: Final = Path(__file__).resolve().parent.parent
ARQUIVO_MODELOS: Final = RAIZ / "licenses" / "modelos.toml"
ARQUIVO_EXCECOES: Final = RAIZ / "licenses" / "dependencias-sem-metadados.toml"
ARQUIVO_FERRAMENTAS: Final = RAIZ / "licenses" / "ferramentas-externas.toml"
TIPO_FERRAMENTA: Final = "ferramenta externa"
ARQUIVO_TABELA: Final = RAIZ / "docs" / "licencas.md"
ARQUIVOS_DE_ATRIBUICAO: Final[tuple[Path, ...]] = (
    RAIZ / "NOTICE",
    RAIZ / "README.md",
)
"""Onde a atribuição obrigatória (CC-BY) tem de aparecer, além da tela "sobre" da `ui`."""


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
        """Falha a porta? Não comercial sempre; copyleft forte quando entra no produto.

        Ferramenta externa (binário do sistema) com GPL/AGPL/SSPL e estado `em_uso` **bloqueia**:
        abrir o derivado é decisão do dono, não de uma dependência que entrou de lado. A mesma
        ferramenta com estado `fora_do_produto` (geração de dado, em processo separado) só gera
        aviso — é o caso do espeak-ng no cartão F1-02.
        """
        if self.estado == "barrado":
            return False  # registrado justamente para ficar fora
        if self.categoria is Categoria.NAO_COMERCIAL:
            return True
        if (
            self.tipo == TIPO_FERRAMENTA
            and self.categoria is Categoria.COPYLEFT_FORTE
            and self.estado == "em_uso"
        ):
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


def inventariar_ferramentas(arquivo: Path = ARQUIVO_FERRAMENTAS) -> list[Item]:
    """Programas do sistema que o repositório usa (não aparecem no inventário de pacotes)."""
    if not arquivo.exists():
        return []
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    itens = [
        Item(
            tipo=TIPO_FERRAMENTA,
            nome=f"{ferramenta['id']} {ferramenta.get('versao', '')}".strip(),
            licenca=str(ferramenta["licenca"]),
            origem=str(ferramenta["fonte"]),
            estado=str(ferramenta.get("estado", "em_uso")),
            data_de_acesso=str(ferramenta.get("data_de_acesso", "")),
            nota=str(ferramenta.get("nota", "")),
        )
        for ferramenta in dados.get("ferramenta", [])
    ]
    return sorted(itens, key=lambda i: i.nome.lower())


def conferir_online(
    modelos: Iterable[Item], arquivo: Path = ARQUIVO_MODELOS, *, chave: str = "modelo"
) -> list[str]:
    """Compara a licença registrada com o model card oficial. Devolve as divergências."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    por_id = {str(m["id"]): m for m in dados.get(chave, [])}
    divergencias: list[str] = []
    for item in modelos:
        registro = por_id.get(item.nome) or por_id[item.nome.rsplit(" ", 1)[0]]
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


def conferir_atribuicao(
    modelos: Sequence[Item], *, arquivos: Sequence[Path] = ARQUIVOS_DE_ATRIBUICAO
) -> list[str]:
    """Aceite (d) do cartão F1-06: atribuição obrigatória que não está no produto é falha.

    Vale para modelo `em_uso` **e** `candidato`: a CC-BY pede atribuição em qualquer uso ou
    distribuição de material derivado, e as tabelas de medição que publicamos são material
    derivado. Modelo `barrado` não precisa — ele existe no registro justamente para ficar fora.
    """
    from jarvis.ui.sobre import texto_sobre

    obrigados = [
        item
        for item in modelos
        if item.categoria is Categoria.ATRIBUICAO and item.estado != "barrado"
    ]
    faltando: list[str] = []
    for item in obrigados:
        for arquivo in arquivos:
            if not arquivo.exists():
                faltando.append(f"{arquivo.name} não existe e a atribuição tem de estar lá")
                continue
            if item.nome not in arquivo.read_text(encoding="utf-8"):
                faltando.append(f"{item.nome} ({item.licenca}) não aparece em {arquivo.name}")
    try:
        sobre = texto_sobre()
    except OSError as erro:  # pragma: no cover
        faltando.append(f"tela 'sobre' não pôde ser lida: {erro}")
    else:
        faltando += [
            f"{item.nome} ({item.licenca}) não aparece na tela 'sobre' da ui"
            for item in obrigados
            if item.nome not in sobre
        ]
    return faltando


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

SECAO_FERRAMENTAS: Final = """
## Ferramentas externas

Programas do sistema usados pelo repositório, de `licenses/ferramentas-externas.toml`. Estado
`fora_do_produto` significa que a ferramenta roda só na geração de dado, em processo separado;
copyleft forte com estado `em_uso` **bloqueia** a porta.

| ferramenta | licença | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|
"""


def tabela_de_modelos(modelos: Sequence[Item], ferramentas: Sequence[Item] = ()) -> str:
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
    tabela = CABECALHO_TABELA + "\n".join(linhas) + "\n" + rodape
    if ferramentas:
        tabela += (
            SECAO_FERRAMENTAS
            + "\n".join(
                f"| `{item.nome}` | {item.licenca} | {item.categoria} | {item.estado} "
                f"| <{item.origem}> | {item.data_de_acesso} |"
                for item in ferramentas
            )
            + "\n"
        )
    return tabela


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
        "--ferramentas",
        type=Path,
        default=ARQUIVO_FERRAMENTAS,
        help="outro registro de ferramentas externas",
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
        "--verificar-atribuicao",
        action="store_true",
        help="falha se a atribuição de um modelo CC-BY não estiver no NOTICE, README e ui",
    )
    analisador.add_argument(
        "--estrito-copyleft",
        action="store_true",
        help="trata copyleft forte (GPL/AGPL/SSPL) como bloqueio, não como aviso",
    )
    args = analisador.parse_args(argv)

    modelos = inventariar_modelos(args.modelos)
    dependencias = inventariar_dependencias(args.pasta_pacotes)
    ferramentas = inventariar_ferramentas(args.ferramentas)
    itens = [*modelos, *dependencias, *ferramentas]

    if args.tabela:
        imprimir_tabela(itens)

    if args.escrever_tabela:
        ARQUIVO_TABELA.write_text(tabela_de_modelos(modelos, ferramentas), encoding="utf-8")
        print(f"tabela escrita em {ARQUIVO_TABELA.relative_to(RAIZ)}")

    if args.verificar_tabela:
        esperada = tabela_de_modelos(modelos, ferramentas)
        atual = ARQUIVO_TABELA.read_text(encoding="utf-8") if ARQUIVO_TABELA.exists() else ""
        if atual != esperada:
            print(
                f"FALHOU: {ARQUIVO_TABELA.relative_to(RAIZ)} está desatualizada em relação a "
                f"{args.modelos.name}; rode --escrever-tabela"
            )
            return 3

    if args.verificar_atribuicao:
        faltando = conferir_atribuicao(modelos)
        for falta in faltando:
            print(f"ATRIBUIÇÃO FALTANDO: {falta}")
        if faltando:
            print(
                f"\nFALHOU: {len(faltando)} atribuição(ões) obrigatória(s) fora do produto "
                "(CC-BY exige atribuição; ver NOTICE)"
            )
            return 4

    if args.online:
        print("\nconferindo os model cards na origem:")
        divergencias = conferir_online(modelos, args.modelos)
        divergencias += conferir_online(ferramentas, args.ferramentas, chave="ferramenta")
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
        f"{len(ferramentas)} ferramenta(s) externa(s), {len(barrados)} barrados por registro"
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
