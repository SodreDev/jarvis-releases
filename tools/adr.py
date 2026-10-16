"""Confere a procedência das ADRs (cartão F0-10).

    uv run --frozen python tools/adr.py conferir
    uv run --frozen python tools/adr.py republicar --adr docs/adr/0014-....md

O que o cartão F0-10 cobra, em forma executável:

* (a) **cada ADR que traz número traz também** hardware, `n`, data e commit — senão o número
  não é reproduzível e não serve de decisão;
* (b) **nenhuma afirmação sem fonte ou sem marca [SUPOSIÇÃO]** — esta parte é verificada no
  que dá para verificar por máquina: toda ADR tem cabeçalho com data, estado e quem decide, e
  nenhuma deixa uma `[SUPOSIÇÃO]` solta sem dizer o que a confirma ou derruba;
* (c) **o número publicado é o número medido** — cada valor de tabela com unidade de tempo é
  comparado com o CSV que a própria ADR cita. Estrutura ("tem p50? tem p95?") não serve: foi
  por isso que a republicação da medição de D1 (commit `5feb551`) passou sem a tabela da
  ADR-0014 acompanhar, e o p99 do piso ficou publicado 3,4× menor do que o medido.

`republicar` é o outro lado da mesma regra: o valor da ADR vem do CSV por máquina, nunca
digitado à mão. A precisão de cada célula é decisão editorial e fica como está; o que o
comando troca é o número.
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_ADR: Final = RAIZ / "docs" / "adr"
PASTA_MEDICOES: Final = RAIZ / "docs" / "medicoes"
TEMPLATE: Final = "0000-template.md"

TOLERANCIA_RELATIVA: Final = 0.01
"""1% do valor medido: cobre arredondamento de publicação sem deixar passar número velho."""
TOLERANCIA_ABSOLUTA_MS: Final = 0.002
"""2 µs: embaixo disto a diferença é da casa decimal publicada, não da medição."""
SLO1_MS: Final = 80.0
"""Orçamento do SLO-1, usado na soma publicada da ADR de D1."""
UNIDADES_EM_MS: Final[dict[str, float]] = {"ms": 1.0, "us": 0.001, "µs": 0.001, "s": 1000.0}

REFERENCIA_DE_CSV = re.compile(r"docs/medicoes/([\w.-]+?)\.(?:csv|\{csv,md\}|\{md,csv\})")
"""A ADR diz de onde vem o número: `docs/medicoes/x.csv` ou `docs/medicoes/x.{csv,md}`."""
NUMERO_PUBLICADO = re.compile(r"-?\d+(?:,\d+)?")
"""Número em tabela de ADR: vírgula decimal, como o resto do texto em português."""
SEPARADOR_DE_TABELA = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
SOMA_DO_SLO1 = re.compile(
    r"(Somando o que é nosso[^:]*:\s*\*\*)([\d,]+)( ms p95 em Python\*\* e\s+)([\d,]+)"
    r"( ms em Rust[^—]*—\s*)([\d,]+)(% e )([\d,]+)(%)"
)
"""A soma que a ADR de D1 publica como manchete: é derivada, então também é conferida.

Regra da soma, escrita aqui para não virar aritmética de cabeça: p95 do VAD do braço + p95 de
`evento-no-barramento` + p95 do piso de agendamento, e a fração é isso sobre o SLO-1.
"""

CABECALHO_DATA = re.compile(r"\*\*Data:\*\*\s*(\d{4}-\d{2}-\d{2})")
CABECALHO_ESTADO = re.compile(r"\*\*Estado:\*\*\s*(\S+)")
CABECALHO_DECIDE = re.compile(r"\*\*Decide:\*\*\s*(.+)")
COMMIT = re.compile(r"`[0-9a-f]{7,40}`")
DECLARA_MEDICAO = re.compile(r"\*\*Mede:\*\*|\*\*Commits? d")
TABELA_DE_MEDICAO = re.compile(r"(?s)\|\s*p50\b.*\|\s*p95\b")
"""Uma ADR é "de medição" quando se declara assim no cabeçalho **ou** publica tabela com
p50 e p95. ADR antiga que apenas cita o orçamento de um SLO não cai nesta regra: ela não
está publicando número nosso."""
SUPOSICAO = re.compile(r"\[SUPOSIÇÃO")
ESTADOS_VALIDOS: Final = frozenset({"proposta", "aceita", "emendada", "revogada"})
PONTUACAO_DO_ESTADO: Final = ".,;:"
"""O cabeçalho das ADRs do arquiteto às vezes continua a frase depois do estado
(`**Estado:** aceita; emendada pela 0008`), então a pontuação é aparada antes de comparar."""


@dataclass(frozen=True, slots=True)
class Alcance:
    """O que a conferência de números alcançou — e o que ficou de fora, com o motivo dito.

    Conferência que não confere nada passa sempre. Por isso o alcance é devolvido junto: um
    teste cobra que a medição de D1 tenha dezenas de valores conferidos, e o que fica fora
    aparece com motivo em vez de silêncio.
    """

    csvs: tuple[str, ...]
    valores: int
    fora: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Bloco:
    """Um bloco de CSV (cabeçalho próprio), já agregado por chave.

    Convenção de publicação do projeto, a mesma que o harness usa: percentil é **mediana das
    execuções** e `max` é o **máximo** delas. Quando a chave e a execução não identificam a
    linha (um CSV com mais de uma dimensão, como `com_ritmo` ou `implementacao`), o bloco fica
    fora do alcance: reconstruir o número publicado exigiria saber qual dimensão foi publicada.
    """

    arquivo: str
    chave: str
    colunas: tuple[str, ...]
    por_chave: dict[str, dict[str, float]]
    ambiguo: str | None = None


def _sem_acento(texto: str) -> str:
    return texto.translate(str.maketrans("áâãàéêíóôõúüç", "aaaaeeiooouuc"))


def _tokens(texto: str) -> frozenset[str]:
    """Palavras comparáveis de um cabeçalho ou de um nome de coluna (`máximo` ≡ `max`)."""
    limpo = _sem_acento(texto.casefold()).replace("`", " ").replace("*", " ")
    palavras = [p for p in re.split(r"[^a-z0-9]+", limpo) if p]
    return frozenset("max" if p.startswith("maxim") else p for p in palavras)


def _unidade_da_coluna(coluna: str) -> float | None:
    for sufixo, fator in UNIDADES_EM_MS.items():
        if coluna.casefold().endswith("_" + sufixo):
            return fator
    return None


def _agregar(coluna: str, valores: list[float]) -> float:
    if "max" in _tokens(coluna):
        return max(valores)
    return statistics.median(valores)


def ler_blocos(arquivo: Path) -> list[Bloco]:
    """Lê um CSV de medição em blocos: linha em branco separa cabeçalhos diferentes."""
    bruto = arquivo.read_text(encoding="utf-8").splitlines()
    blocos: list[Bloco] = []
    atual: list[str] = []
    for linha in [*bruto, ""]:
        if linha.strip():
            atual.append(linha)
            continue
        if len(atual) >= 2:
            blocos.append(_bloco_de(arquivo.name, atual))
        atual = []
    return blocos


def _bloco_de(nome: str, linhas: list[str]) -> Bloco:
    leitor = csv.DictReader(linhas)
    colunas = tuple(leitor.fieldnames or ())
    chave = colunas[0] if colunas else ""
    agrupado: dict[str, dict[str, list[float]]] = {}
    identidade: list[tuple[str, str]] = []
    for linha_lida in leitor:
        valor_da_chave = (linha_lida.get(chave) or "").strip()
        execucao = (linha_lida.get("execucao") or "").strip()
        identidade.append((valor_da_chave, execucao))
        alvo = agrupado.setdefault(valor_da_chave, {})
        for coluna in colunas[1:]:
            cru = (linha_lida.get(coluna) or "").strip()
            try:
                numero = float(cru)
            except ValueError:
                continue  # coluna de texto (observação, nome de dispositivo)
            alvo.setdefault(coluna, []).append(numero)
    ambiguo = None
    if len(set(identidade)) != len(identidade):
        ambiguo = (
            f"{nome}: mais de uma linha por ({chave}, execucao) — o CSV tem outra dimensão, "
            "e qual delas foi publicada não está no arquivo"
        )
    return Bloco(
        arquivo=nome,
        chave=chave,
        colunas=colunas,
        por_chave={
            k: {c: _agregar(c, vs) for c, vs in cols.items()} for k, cols in agrupado.items()
        },
        ambiguo=ambiguo,
    )


def _celulas(linha: str) -> list[str]:
    pedacos = linha.split("|")
    return [p.strip() for p in pedacos[1:-1]] if len(pedacos) > 2 else []


def _tabelas(linhas: list[str]) -> Iterator[tuple[list[str], list[int]]]:
    """Cada tabela markdown do texto: células do cabeçalho e índices das linhas de dados."""
    i = 0
    while i < len(linhas):
        tem_separador = i + 1 < len(linhas) and SEPARADOR_DE_TABELA.match(linhas[i + 1])
        if linhas[i].lstrip().startswith("|") and tem_separador:
            dados = []
            j = i + 2
            while j < len(linhas) and linhas[j].lstrip().startswith("|"):
                dados.append(j)
                j += 1
            yield _celulas(linhas[i]), dados
            i = j
        else:
            i += 1


def _coluna_de(cabecalho: str, bloco: Bloco) -> str | None:
    pedido = _tokens(cabecalho)
    if not pedido:
        return None
    candidatas = [c for c in bloco.colunas[1:] if pedido <= _tokens(c)]
    return candidatas[0] if len(candidatas) == 1 else None


def _chave_de(rotulo: str, bloco: Bloco) -> str | None:
    """Casa o rótulo da linha da ADR com a chave do CSV pelo primeiro termo dela.

    O CSV guarda o nome longo (`dispositivo (monitor de saída alsa_output...)`) e a ADR publica
    uma versão curta (`piso do dispositivo (monitor de saída ociosa)`): o que os dois têm em
    comum, sempre, é o primeiro termo.
    """
    alvo = _tokens(rotulo)
    candidatas = [
        k for k in bloco.por_chave if _tokens(k.split("(")[0]) and _tokens(k.split("(")[0]) <= alvo
    ]
    return candidatas[0] if len(candidatas) == 1 else None


def _numero_e_unidade(celula: str) -> tuple[str, float, float] | None:
    """Número publicado na célula: texto cru, valor e fator da unidade escrita (se houver)."""
    achado = NUMERO_PUBLICADO.search(celula)
    if achado is None:
        return None
    resto = celula[achado.end() :].strip().strip("*").strip()
    fator = 0.0
    for sufixo, valor in UNIDADES_EM_MS.items():
        if resto.startswith(sufixo):
            fator = valor
            break
    return achado.group(0), float(achado.group(0).replace(",", ".")), fator


def _como_medido(valor: float) -> str:
    texto = f"{valor:.6f}".rstrip("0")
    return texto + "0" if texto.endswith(".") else texto


def _formatar_como(antigo: str, valor: float) -> str:
    casas = len(antigo.split(",")[1]) if "," in antigo else 0
    return f"{valor:.{casas}f}".replace(".", ",")


def soma_do_slo1(blocos: list[Bloco]) -> tuple[float, float] | None:
    """p95 do VAD + p95 do evento + p95 do piso de agendamento, em Python e em Rust."""
    valores: dict[str, float] = {}
    for bloco in blocos:
        if bloco.ambiguo is not None:
            continue
        for chave, colunas in bloco.por_chave.items():
            coluna = _coluna_de("p95", bloco)
            if coluna is not None and coluna in colunas:
                valores[chave.split("(")[0].strip()] = colunas[coluna]
    try:
        resto = valores["evento-no-barramento"] + valores["agendamento"]
        return valores["python-onnx"] + resto, valores["rust-std"] + resto
    except KeyError:
        return None


@dataclass(frozen=True, slots=True)
class Problema:
    arquivo: str
    o_que: str

    def __str__(self) -> str:
        return f"{self.arquivo}: {self.o_que}"


def _blocos_citados(texto: str, medicoes: Path) -> tuple[list[Bloco], list[str], list[Problema]]:
    nomes = dict.fromkeys(f"{s}.csv" for s in REFERENCIA_DE_CSV.findall(texto))
    blocos: list[Bloco] = []
    fora: list[str] = []
    problemas: list[Problema] = []
    for nome in nomes:
        arquivo = medicoes / nome
        if not arquivo.exists():
            problemas.append(Problema(nome, "a ADR cita este CSV e ele não existe"))
            continue
        for bloco in ler_blocos(arquivo):
            if bloco.ambiguo is not None:
                fora.append(bloco.ambiguo)
            blocos.append(bloco)
    return blocos, fora, problemas


def _conferir_numeros(
    caminho: Path, medicoes: Path = PASTA_MEDICOES
) -> tuple[list[Problema], Alcance]:
    """Compara cada célula com unidade de tempo contra o CSV que a ADR cita."""
    texto = caminho.read_text(encoding="utf-8")
    nome = caminho.name
    blocos, fora, problemas = _blocos_citados(texto, medicoes)
    uteis = [b for b in blocos if b.ambiguo is None]
    conferidos = 0
    linhas = texto.splitlines()
    for cabecalho, indices in _tabelas(linhas):
        for indice in indices:
            celulas = _celulas(linhas[indice])
            if not celulas:
                continue
            for bloco in uteis:
                chave = _chave_de(celulas[0], bloco)
                if chave is None:
                    continue
                for posicao, celula in list(enumerate(celulas))[1:]:
                    if posicao >= len(cabecalho):
                        continue
                    coluna = _coluna_de(cabecalho[posicao], bloco)
                    if coluna is None or coluna not in bloco.por_chave[chave]:
                        continue
                    unidade_da_coluna = _unidade_da_coluna(coluna)
                    if unidade_da_coluna is None:
                        continue  # coluna sem unidade de tempo: não é o que o achado 3 cobra
                    publicado = _numero_e_unidade(celula)
                    if publicado is None:
                        continue  # célula sem número ("—"): nada a conferir
                    _, valor, fator = publicado
                    em_ms = valor * (fator or unidade_da_coluna)
                    medido = bloco.por_chave[chave][coluna] * unidade_da_coluna
                    conferidos += 1
                    tolerancia = max(abs(medido) * TOLERANCIA_RELATIVA, TOLERANCIA_ABSOLUTA_MS)
                    if abs(em_ms - medido) > tolerancia:
                        problemas.append(
                            Problema(
                                nome,
                                f"{celulas[0]}: {cabecalho[posicao]} publicado "
                                f"{celula} e medido {_como_medido(medido / unidade_da_coluna)} "
                                f"em {bloco.arquivo} (F0-10 c)",
                            )
                        )
    problemas += _conferir_soma(nome, texto, uteis)
    return problemas, Alcance(
        csvs=tuple(dict.fromkeys(b.arquivo for b in blocos)),
        valores=conferidos,
        fora=tuple(dict.fromkeys(fora)),
    )


def _conferir_soma(nome: str, texto: str, blocos: list[Bloco]) -> list[Problema]:
    achado = SOMA_DO_SLO1.search(texto)
    soma = soma_do_slo1(blocos)
    if achado is None or soma is None:
        return []
    publicados = [achado.group(i) for i in (2, 4, 6, 8)]
    esperados = [soma[0], soma[1], 100 * soma[0] / SLO1_MS, 100 * soma[1] / SLO1_MS]
    problemas = []
    for publicado, esperado in zip(publicados, esperados, strict=True):
        valor = float(publicado.replace(",", "."))
        if abs(valor - esperado) > max(abs(esperado) * TOLERANCIA_RELATIVA, 0.005):
            problemas.append(
                Problema(
                    nome,
                    f"soma do SLO-1 publicada {publicado} e medida "
                    f"{_formatar_como(publicado, esperado)} (F0-10 c)",
                )
            )
    return problemas


def conferir_numeros(caminho: Path, medicoes: Path = PASTA_MEDICOES) -> list[Problema]:
    return _conferir_numeros(caminho, medicoes)[0]


def alcance_da_conferencia(caminho: Path, medicoes: Path = PASTA_MEDICOES) -> Alcance:
    return _conferir_numeros(caminho, medicoes)[1]


def republicar_numeros(caminho: Path, medicoes: Path = PASTA_MEDICOES) -> tuple[str, list[str]]:
    """Reescreve os valores da ADR a partir do CSV, mantendo a precisão publicada."""
    texto = caminho.read_text(encoding="utf-8")
    blocos, _, _ = _blocos_citados(texto, medicoes)
    uteis = [b for b in blocos if b.ambiguo is None]
    linhas = texto.splitlines(keepends=True)
    trocas: list[str] = []
    sem_fim = [linha.rstrip("\n") for linha in linhas]
    for cabecalho, indices in _tabelas(sem_fim):
        for indice in indices:
            celulas = _celulas(sem_fim[indice])
            if not celulas:
                continue
            pedacos = linhas[indice].split("|")
            for bloco in uteis:
                chave = _chave_de(celulas[0], bloco)
                if chave is None:
                    continue
                for posicao, celula in list(enumerate(celulas))[1:]:
                    if posicao >= len(cabecalho):
                        continue
                    coluna = _coluna_de(cabecalho[posicao], bloco)
                    unidade = _unidade_da_coluna(coluna) if coluna else None
                    if coluna is None or unidade is None:
                        continue
                    if coluna not in bloco.por_chave[chave]:
                        continue
                    publicado = _numero_e_unidade(celula)
                    if publicado is None:
                        continue
                    cru, _valor, fator = publicado
                    medido = bloco.por_chave[chave][coluna] * unidade / (fator or unidade)
                    novo_numero = _formatar_como(cru, medido)
                    if novo_numero != cru:
                        pedacos[posicao + 1] = pedacos[posicao + 1].replace(cru, novo_numero, 1)
                        trocas.append(
                            f"{caminho.name}: {celulas[0]} / {cabecalho[posicao]}: "
                            f"{cru} -> {novo_numero}"
                        )
            linhas[indice] = "|".join(pedacos)
    novo_texto = "".join(linhas)
    soma = soma_do_slo1(uteis)
    achado = SOMA_DO_SLO1.search(novo_texto)
    if soma is not None and achado is not None:
        valores = [soma[0], soma[1], 100 * soma[0] / SLO1_MS, 100 * soma[1] / SLO1_MS]
        grupos = list(achado.groups())
        for alvo, valor in zip((1, 3, 5, 7), valores, strict=True):
            novo = _formatar_como(grupos[alvo], valor)
            if novo != grupos[alvo]:
                trocas.append(f"{caminho.name}: soma do SLO-1: {grupos[alvo]} -> {novo}")
            grupos[alvo] = novo
        novo_texto = novo_texto[: achado.start()] + "".join(grupos) + novo_texto[achado.end() :]
    return novo_texto, trocas


def conferir_adr(caminho: Path, medicoes: Path = PASTA_MEDICOES) -> list[Problema]:
    texto = caminho.read_text(encoding="utf-8")
    problemas: list[Problema] = []
    nome = caminho.name

    if CABECALHO_DATA.search(texto) is None:
        problemas.append(Problema(nome, "sem **Data:** no cabeçalho"))
    estado = CABECALHO_ESTADO.search(texto)
    if estado is None:
        problemas.append(Problema(nome, "sem **Estado:** no cabeçalho"))
    elif estado.group(1).strip().casefold().rstrip(PONTUACAO_DO_ESTADO) not in ESTADOS_VALIDOS:
        problemas.append(Problema(nome, f"estado desconhecido: {estado.group(1)!r}"))
    if CABECALHO_DECIDE.search(texto) is None:
        problemas.append(Problema(nome, "sem **Decide:** no cabeçalho"))

    de_medicao = (
        DECLARA_MEDICAO.search(texto) is not None or TABELA_DE_MEDICAO.search(texto) is not None
    )
    if de_medicao:
        if COMMIT.search(texto) is None:
            problemas.append(
                Problema(nome, "traz número de medição e não cita o commit da medição (F0-10 a)")
            )
        if not re.search(r"(?i)\bhardware\b|\bRyzen\b|\bCPU\b", texto):
            problemas.append(Problema(nome, "traz número e não descreve o hardware (F0-10 a)"))
        if not re.search(
            r"(?i)`?n`?\s*=\s*\d|\b\d[\d\s.]*\s*(frames|episódios|consultas|modelos)\b", texto
        ):
            problemas.append(Problema(nome, "traz número e não publica o `n` (F0-10 a)"))

    # Por parágrafo, não por linha: o markdown do projeto quebra frase no meio.
    for paragrafo in re.split(r"\n\s*\n", texto):
        if SUPOSICAO.search(paragrafo) and not re.search(
            r"(?i)confirma|derruba|harness|cartão|medi|teste|F0-\d\d", paragrafo
        ):
            problemas.append(
                Problema(
                    nome,
                    f"[SUPOSIÇÃO] sem dizer o que a confirma: {paragrafo.strip()[:80]}",
                )
            )
    problemas += conferir_numeros(caminho, medicoes)
    return problemas


def conferir(pasta: Path = PASTA_ADR, medicoes: Path = PASTA_MEDICOES) -> list[Problema]:
    arquivos = [a for a in sorted(pasta.glob("*.md")) if a.name != TEMPLATE]
    if not arquivos:
        return [Problema(str(pasta), "nenhuma ADR encontrada")]
    problemas: list[Problema] = []
    for arquivo in arquivos:
        problemas += conferir_adr(arquivo, medicoes)
    return problemas


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("acao", choices=["conferir", "listar", "republicar"])
    analisa.add_argument("--pasta", type=Path, default=PASTA_ADR)
    analisa.add_argument("--medicoes", type=Path, default=PASTA_MEDICOES)
    analisa.add_argument("--adr", type=Path, help="ADR a republicar a partir do CSV que ela cita")
    args = analisa.parse_args(argv)

    if args.acao == "republicar":
        if args.adr is None:
            analisa.error("republicar precisa de --adr")
        novo, trocas = republicar_numeros(args.adr, args.medicoes)
        for troca in trocas:
            print(troca)
        if trocas:
            Path(args.adr).write_text(novo, encoding="utf-8")
        print(f"{len(trocas)} valor(es) republicado(s) a partir do CSV")
        return 0

    if args.acao == "listar":
        for arquivo in sorted(args.pasta.glob("*.md")):
            if arquivo.name == TEMPLATE:
                continue
            texto = arquivo.read_text(encoding="utf-8")
            estado = CABECALHO_ESTADO.search(texto)
            titulo = texto.splitlines()[0].lstrip("# ")
            print(f"{arquivo.stem:48.48} {estado.group(1) if estado else '?':12.12} {titulo[:60]}")
        return 0

    problemas = conferir(args.pasta, args.medicoes)
    for problema in problemas:
        print(f"PROBLEMA {problema}")
    if problemas:
        print(f"\n{len(problemas)} problema(s) de procedência nas ADRs")
        return 1
    print("ADRs com data, estado, decisor, hardware/n/commit e número igual ao do CSV")
    return 0


if __name__ == "__main__":
    sys.exit(main())
