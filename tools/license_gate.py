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
    compartilha_igual,
)

RAIZ: Final = Path(__file__).resolve().parent.parent
ARQUIVO_MODELOS: Final = RAIZ / "licenses" / "modelos.toml"
ARQUIVO_EXCECOES: Final = RAIZ / "licenses" / "dependencias-sem-metadados.toml"
ARQUIVO_FERRAMENTAS: Final = RAIZ / "licenses" / "ferramentas-externas.toml"
ARQUIVO_MOTORES: Final = RAIZ / "licenses" / "motores.toml"
ARQUIVO_BIBLIOTECAS: Final = RAIZ / "licenses" / "bibliotecas-distribuidas.toml"
TIPO_FERRAMENTA: Final = "ferramenta externa"
TIPO_BIBLIOTECA: Final = "biblioteca distribuída"
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

        Ferramenta externa (binário do sistema) e biblioteca distribuída dentro do pacote
        (ADR-0019/0020) com GPL/AGPL/SSPL e estado `em_uso` **bloqueiam**:
        abrir o derivado é decisão do dono, não de uma dependência que entrou de lado. A mesma
        ferramenta com estado `fora_do_produto` (geração de dado, em processo separado) só gera
        aviso — é o caso do espeak-ng no cartão F1-02.
        """
        if self.estado == "barrado":
            return False  # registrado justamente para ficar fora
        if self.categoria is Categoria.NAO_COMERCIAL:
            return True
        if (
            self.tipo in {TIPO_FERRAMENTA, TIPO_BIBLIOTECA}
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


def inventariar_motores(arquivo: Path = ARQUIVO_MOTORES) -> list[Item]:
    """Motores de voz (ADR-0017): a licença aqui é a do **cliente**, não a do peso.

    Um motor de nuvem não tem peso para licenciar: o que ele tem é contrato de serviço, e é
    `jarvis.voz.registro` que barra campo de termo vazio. A porta cuida da parte dela — a
    licença da biblioteca que faz a chamada — e **avisa** sobre o resto, que é o que o dono
    precisa ver: quem manda dado para fora, com que retenção, e o que sai marcado.
    """
    if not arquivo.exists():
        return []
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    itens = [
        Item(
            tipo=f"motor/{motor['papel']}",
            nome=str(motor["id"]),
            licenca=str(motor.get("licenca_do_cliente", "")) or None,
            origem=str(motor.get("fonte", "")),
            estado=str(motor.get("estado", "em_uso")),
            data_de_acesso=str(motor.get("data_de_acesso", "")),
            nota=str(motor.get("nota", "")),
        )
        for motor in dados.get("motor", [])
    ]
    return sorted(itens, key=lambda i: (i.tipo, i.nome.lower()))


def inventariar_bibliotecas(arquivo: Path = ARQUIVO_BIBLIOTECAS) -> list[Item]:
    """Bibliotecas de terceiros que o **produto distribui** dentro do pacote (ADR-0019/0020).

    Elas também aparecem no inventário de dependências instaladas, e isso não é redundância: lá
    a pergunta é "esta licença permite uso comercial?", e o CI responde com o que o ambiente
    tem hoje. Aqui a pergunta é a da redistribuição — "o que esta licença me obriga a entregar
    junto?" — e a resposta é um registro comitado, que não depende do que está instalado.
    """
    if not arquivo.exists():
        return []
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    itens = [
        Item(
            tipo=TIPO_BIBLIOTECA,
            nome=f"{biblioteca['id']} {biblioteca.get('versao', '')}".strip(),
            licenca=str(biblioteca.get("licenca_escolhida") or biblioteca["licenca"]),
            origem=str(biblioteca["fonte"]),
            estado=str(biblioteca.get("estado", "em_uso")),
            data_de_acesso=str(biblioteca.get("data_de_acesso", "")),
            nota=str(biblioteca.get("papel", "")),
        )
        for biblioteca in dados.get("biblioteca", [])
    ]
    return sorted(itens, key=lambda i: i.nome.lower())


def _no_pacote_instalado(pacote: str, relativo: str) -> bool | None:
    """O arquivo está dentro do pacote instalado? `None` = o pacote não está instalado aqui.

    Distinguir "não cumpre" de "não dá para conferir" é o ponto: o CI roda sem o grupo `gui`,
    e uma conferência que passa calada quando o pacote falta não confere nada.
    """
    try:
        distribuicao = metadata.distribution(pacote)
    except metadata.PackageNotFoundError:
        return None
    pasta = distribuicao.locate_file("")
    return (Path(str(pasta)) / relativo).exists()


def _licenca_instalada(pacote: str) -> str | None:
    """A licença que o pacote instalado declara. `None` = não está instalado aqui."""
    try:
        return _licenca_de_metadados(metadata.distribution(pacote).metadata)
    except metadata.PackageNotFoundError:
        return None


def conferir_bibliotecas(arquivo: Path = ARQUIVO_BIBLIOTECAS) -> tuple[list[str], list[str]]:
    """As obrigações de redistribuição, conferidas por máquina. Devolve (falhas, avisos).

    Quatro perguntas, e cada uma existe por uma obrigação concreta do LGPL (ADR-0019):

    1. a licença escolhida é mesmo uma das que a origem publica, e o pacote instalado declara
       a mesma expressão? (escolher "LGPL" de uma expressão que só tem GPL seria inventar
       permissão; e metadados que mudaram de uma versão para outra têm de aparecer aqui);
    2. a ligação é dinâmica e a biblioteca não foi modificada? — ligar estaticamente ou alterar
       o Qt mata o direito de **re-ligar**, que é a obrigação central;
    3. o texto da licença existe no repositório (é ele que o empacotador copia) e, quando o
       registro aponta para um arquivo que vem dentro da roda, ele existe lá?
    4. o `NOTICE` cita o item?
    """
    if not arquivo.exists():
        return [], []
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    aviso_legal = (
        (RAIZ / "NOTICE").read_text(encoding="utf-8") if (RAIZ / "NOTICE").exists() else ""
    )
    falhas: list[str] = []
    avisos: list[str] = []
    for biblioteca in dados.get("biblioteca", []):
        identificador = str(biblioteca["id"])
        if str(biblioteca.get("estado", "em_uso")) != "em_uso":
            continue
        publicada = str(biblioteca["licenca"])
        escolhida = str(biblioteca.get("licenca_escolhida") or publicada)
        if escolhida.casefold() not in publicada.casefold():
            falhas.append(
                f"{identificador}: licenca_escolhida {escolhida!r} não está na expressão "
                f"publicada pela origem ({publicada!r})"
            )
        copyleft = "gpl" in escolhida.casefold()
        if copyleft and str(biblioteca.get("ligacao", "")) not in {"dinamica", "python"}:
            falhas.append(
                f"{identificador}: {escolhida} com ligação "
                f"{biblioteca.get('ligacao', '(não declarada)')!r} — ligar estaticamente tira do "
                "dono o direito de re-ligar a biblioteca"
            )
        if copyleft and bool(biblioteca.get("modificada", False)):
            falhas.append(
                f"{identificador}: {escolhida} e biblioteca modificada — aí a fonte modificada "
                "tem de ser entregue, e este registro não declara como"
            )
        for relativo in biblioteca.get("textos_de_licenca", []):
            if not (RAIZ / str(relativo)).exists():
                falhas.append(
                    f"{identificador}: o texto da licença {relativo} não está no repositório, "
                    "e é ele que o empacotador copia para dentro do artefato"
                )
        for relativo in biblioteca.get("arquivos_no_pacote", []):
            existe = _no_pacote_instalado(identificador, str(relativo))
            if existe is None:
                avisos.append(
                    f"{identificador}: não está instalado aqui, então {relativo} não foi "
                    "conferido (instale o grupo `gui` para conferir)"
                )
            elif not existe:
                falhas.append(
                    f"{identificador}: {relativo} não existe dentro do pacote instalado, e é "
                    "ele que leva a licença para dentro do artefato"
                )
        instalada = _licenca_instalada(identificador)
        if instalada is None:
            avisos.append(
                f"{identificador}: não está instalado aqui, então a licença registrada "
                f"({publicada}) não foi comparada com a dos metadados"
            )
        elif instalada.casefold() != publicada.casefold():
            falhas.append(
                f"{identificador}: o registro diz {publicada!r} e o pacote instalado declara "
                f"{instalada!r} — um dos dois envelheceu"
            )
        if identificador not in aviso_legal:
            falhas.append(f"{identificador}: não aparece no NOTICE, e a licença exige o aviso")
    return falhas, avisos


def avisos_de_motores(arquivo: Path = ARQUIVO_MOTORES) -> list[str]:
    """As frases que a porta imprime sobre motor de voz: nuvem, marca d'água e extra LGPL.

    Não são bloqueios — bloquear nuvem é trabalho do `jarvis.voz.registro`, em tempo de
    execução, com o interruptor do dono. Aqui é a lista que fica no log do CI para ninguém
    descobrir depois que o produto ganhou um caminho de saída de dado sem ninguém ler.
    """
    from jarvis.voz.registro import ler_motores

    if not arquivo.exists():
        return []
    frases: list[str] = []
    for motor in ler_motores(arquivo):
        if motor.na_nuvem:
            vazios = ", ".join(motor.campos_vazios) or "nenhum"
            frases.append(
                f"NUVEM: {motor.id} manda {motor.o_que_sai} para {motor.servico} "
                f"(ligado por padrão: {'sim' if motor.ligado else 'não'}; "
                f"campos de termo vazios: {vazios})"
            )
        if motor.marca_o_audio:
            frases.append(f"MARCA D'ÁGUA: {motor.id} — {motor.marca_dagua}")
        if motor.estado == "extra_opcional":
            frases.append(
                f"EXTRA OPCIONAL: {motor.id} usa {motor.cliente} ({motor.licenca_do_cliente}) — "
                "não é dependência do produto e não é distribuído junto; o dono instala"
            )
    return frases


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


SECAO_MOTORES: Final = """
## Motores de voz

Motores de ASR e TTS de `licenses/motores.toml` (ADR-0017). A licença da coluna é a do
**cliente** (a biblioteca que faz a chamada), não a do peso do modelo — o peso está na tabela
de modelos. `onde = nuvem` significa que áudio ou texto **sai da máquina do dono**: esses
nascem desligados, e campo de termo vazio barra o motor em tempo de execução
(`jarvis.voz.registro`).

| papel | motor | onde | ligado | licença do cliente | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|---|---|---|
"""


SECAO_BIBLIOTECAS: Final = """
## Bibliotecas distribuídas dentro do pacote

De `licenses/bibliotecas-distribuidas.toml` (ADR-0019, ADR-0020). São as bibliotecas de
terceiros que **saem desta máquina** dentro do AppImage, do `.deb` e do `.rpm` — por isso a
coluna que importa não é só a licença, é a obrigação que ela impõe a quem redistribui. A
licença mostrada é a **escolhida** dentro da expressão publicada pela origem; a conferência
das obrigações (ligação dinâmica, direito de re-ligar, texto junto, aviso no NOTICE) roda em
`tools/license_gate.py`.

| biblioteca | licença escolhida | categoria | ligação | modificada | estado | fonte | acesso |
|---|---|---|---|---|---|---|---|
"""


def tabela_de_bibliotecas(arquivo: Path = ARQUIVO_BIBLIOTECAS) -> str:
    if not arquivo.exists():
        return ""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    linhas = []
    for biblioteca in sorted(dados.get("biblioteca", []), key=lambda b: str(b["id"]).lower()):
        escolhida = str(biblioteca.get("licenca_escolhida") or biblioteca["licenca"])
        linhas.append(
            f"| `{biblioteca['id']} {biblioteca.get('versao', '')}`".rstrip()
            + f" | {escolhida} | {classificar(escolhida)} "
            f"| {biblioteca.get('ligacao', '?')} "
            f"| {'sim' if biblioteca.get('modificada', False) else 'não'} "
            f"| {biblioteca.get('estado', 'em_uso')} | <{biblioteca['fonte']}> "
            f"| {biblioteca.get('data_de_acesso', '')} |"
        )
    return SECAO_BIBLIOTECAS + "\n".join(linhas) + "\n"


def tabela_de_motores(arquivo: Path = ARQUIVO_MOTORES) -> str:
    from jarvis.voz.registro import ler_motores

    if not arquivo.exists():
        return ""
    linhas = [
        f"| {motor.papel} | `{motor.id}` | {motor.onde} "
        f"| {'sim' if motor.ligado else 'não'} | {motor.licenca_do_cliente} "
        f"| {motor.categoria_da_licenca} | {motor.estado} | <{motor.fonte}> "
        f"| {motor.data_de_acesso} |"
        for motor in sorted(ler_motores(arquivo), key=lambda m: (m.papel, m.id))
    ]
    return SECAO_MOTORES + "\n".join(linhas) + "\n"


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
    tabela += tabela_de_bibliotecas()
    tabela += tabela_de_motores()
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
        "--motores", type=Path, default=ARQUIVO_MOTORES, help="outro registro de motores de voz"
    )
    analisador.add_argument(
        "--bibliotecas",
        type=Path,
        default=ARQUIVO_BIBLIOTECAS,
        help="outro registro de bibliotecas distribuídas dentro do pacote",
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
    motores = inventariar_motores(args.motores)
    bibliotecas = inventariar_bibliotecas(args.bibliotecas)
    itens = [*modelos, *dependencias, *ferramentas, *motores, *bibliotecas]

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

    falhas_de_distribuicao, avisos_de_distribuicao = conferir_bibliotecas(args.bibliotecas)
    for aviso in avisos_de_distribuicao:
        print(f"NÃO CONFERIDO: {aviso}")
    for falha in falhas_de_distribuicao:
        print(f"OBRIGAÇÃO DE DISTRIBUIÇÃO: {falha}")
    if falhas_de_distribuicao:
        print(
            f"\nFALHOU: {len(falhas_de_distribuicao)} obrigação(ões) de redistribuição não "
            "cumprida(s) (ADR-0019; ver licenses/bibliotecas-distribuidas.toml)"
        )
        return 5

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
    # Modelo barrado não impõe atribuição: ele está no registro justamente para ficar fora.
    atribuicoes = [
        i for i in itens if i.categoria is Categoria.ATRIBUICAO and i.estado != "barrado"
    ]
    barrados = [i for i in modelos if i.estado == "barrado"]

    print(
        f"\nporta de licença: {len(modelos)} modelos, {len(dependencias)} dependências, "
        f"{len(ferramentas)} ferramenta(s) externa(s), {len(motores)} motor(es) de voz, "
        f"{len(bibliotecas)} biblioteca(s) distribuída(s), "
        f"{len(barrados)} barrados por registro"
    )
    for frase in avisos_de_motores(args.motores):
        print(frase)
    for item in atribuicoes:
        if compartilha_igual(item.licenca):
            # ShareAlike não é CC-BY: atribuir não basta, o derivado sai na mesma licença —
            # e numa voz o derivado é o áudio que o produto distribui (ADR-0016).
            print(
                f"AVISO ShareAlike: {item.nome} ({item.licenca}) — o derivado herda a licença, "
                "atribuir não basta"
            )
            continue
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
