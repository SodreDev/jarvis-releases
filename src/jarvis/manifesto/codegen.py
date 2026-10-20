"""Gera o stub tipado de uma capacidade a partir do manifesto (SPEC §4; cartão F0-07).

Por que gerar em vez de escrever à mão: a assinatura, os campos de política e a
pós-condição passam a vir **do contrato**, não da memória de quem implementa. Se o
manifesto mudar e o stub não for regenerado, o teste de geração acusa.

O stub **não implementa nada**: ele valida a entrada contra o `input_schema`, chama o corpo
que o executor registra e confere que a saída bate com o `output_schema`. Quem executa de
verdade é o `executor`, com credencial de menor privilégio e sandbox (§2).
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any, Final

TIPOS: Final[dict[str, str]] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict[str, Any]",
    "array": "list[Any]",
}

CABECALHO: Final = '''"""Stub gerado de `{id}` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/{id}.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: {tier}
  risco: {risk_class} · confirmação: {confirmation} · egress: {data_egress}
  modo mínimo: {access_level_min} · elevação: {requires_elevation} · raízes: {roots}
{postcondition}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "{id}"
CAPABILITY: Final = "{capability}"
RISK_CLASS: Final = "{risk_class}"
CONFIRMATION: Final = "{confirmation}"
TIER: Final = "{tier}"
DATA_EGRESS: Final = "{data_egress}"
ACCESS_LEVEL_MIN: Final = "{access_level_min}"
REQUIRES_ELEVATION: Final = {requires_elevation}
IDEMPOTENCY: Final = "{idempotency}"
TIMEOUT_MS: Final = {timeout_ms}
ROOTS: Final[tuple[str, ...]] = {roots_tupla}
{postcondition_linha}
'''


def _tupla_literal(valores: list[str]) -> str:
    """Tupla no estilo que o formatador do projeto produz — o CI compara byte a byte."""
    if not valores:
        return "()"
    corpo = ", ".join(f'"{v}"' for v in valores)
    return f"({corpo},)" if len(valores) == 1 else f"({corpo})"


LARGURA: Final = 100
"""A largura de linha do `ruff format` do projeto (`line-length` no pyproject)."""
RECUO: Final = len("    ")
"""O recuo da linha de dentro dos parênteses."""


def _conjunto(nome: str, valores: list[str]) -> str:
    """`NOME: Final[frozenset[str]] = frozenset((...))` como o `ruff format` deixaria.

    Com dois ou mais itens não há vírgula final — com ela, o formatador expande a tupla item a
    item (*magic trailing comma*) e o `conferir` acusaria stub velho. Linha longa demais quebra
    como o formatador quebra: a tupla inteira na linha de baixo; se nem assim couber, um item
    por linha, agora com a vírgula final.
    """
    cabeca = f"{nome}: Final[frozenset[str]] = frozenset("
    tupla = _tupla_literal(valores)
    numa_linha = f"{cabeca}{tupla})"
    if len(numa_linha) <= LARGURA:
        return numa_linha
    if len(f"    {tupla}") <= LARGURA:
        return f"{cabeca}\n    {tupla}\n)"
    itens = "".join(f'        "{v}",\n' for v in valores)
    return f"{cabeca}\n    (\n{itens}    )\n)"


def _constante(nome: str, texto: str) -> str:
    """`NOME: Final = "texto"`, entre parênteses se passa de 100 colunas (como o `ruff format`).

    Se nem entre parênteses a string cabe, ela sai em pedaços concatenados, quebrados no espaço:
    o `ruff format` mantém (juntos não caberiam) e o E501 aceita. Uma pós-condição longa num
    manifesto deixava o stub fora do formato e o `verificar.py` vermelho (input.*, 1fc6450)."""
    literal = _literal(texto)
    linha = f"{nome}: Final = {literal}"
    if len(linha) <= LARGURA:
        return linha
    if len(literal) + RECUO <= LARGURA:
        return f"{nome}: Final = (\n    {literal}\n)"
    corpo = "\n".join(f"    {_literal(p)}" for p in _pedacos(texto))
    return f"{nome}: Final = (\n{corpo}\n)"


def _literal(texto: str) -> str:
    """A string como o `ruff format` a escreve: aspas duplas, salvo quando o texto tem aspas
    duplas e nenhuma simples — aí simples, que dispensam o escape."""
    duplas = json.dumps(texto, ensure_ascii=False)
    if '"' in texto and "'" not in texto:
        return "'" + duplas[1:-1].replace('\\"', '"') + "'"
    return duplas


def _pedacos(texto: str) -> list[str]:
    """O texto em pedaços que, entre aspas e recuados, cabem em 100 colunas. Cada um leva o
    espaço que o separa do seguinte, então a concatenação devolve o texto exato. Palavra maior
    que a linha fica sozinha (não se corta palavra)."""
    pedacos: list[str] = []
    atual = ""
    for palavra in re.findall(r"\s*\S+\s*", texto) or [texto]:
        candidato = atual + palavra
        if atual and len(_literal(candidato)) + RECUO > LARGURA:
            pedacos.append(atual)
            atual = palavra
        else:
            atual = candidato
    pedacos.append(atual)
    return pedacos


def _linha_da_poscondicao(texto: str) -> str:
    """A pós-condição na docstring, quebrada em 100 colunas como o linter cobra."""
    return textwrap.fill(
        f"pós-condição verificada pelo executor: {texto}",
        width=LARGURA,
        initial_indent="  ",
        subsequent_indent="    ",
    )


def _anotacao(propriedade: dict[str, Any]) -> str:
    return TIPOS.get(str(propriedade.get("type", "")), "Any")


def _campos(schema: dict[str, Any]) -> list[tuple[str, str, bool]]:
    obrigatorios = set(schema.get("required", []))
    campos: list[tuple[str, str, bool]] = []
    for nome, propriedade in (schema.get("properties") or {}).items():
        if not isinstance(propriedade, dict):
            continue
        campos.append((str(nome), _anotacao(propriedade), str(nome) in obrigatorios))
    # Obrigatórios primeiro: dataclass não aceita campo sem padrão depois de um com padrão.
    return sorted(campos, key=lambda c: (not c[2], c[0]))


def gerar_stub(manifesto: dict[str, Any]) -> str:
    """Devolve o código do stub. Quem escreve em disco é o CLI."""
    identificador = str(manifesto["id"])
    classe = "".join(parte.title() for parte in identificador.replace(".", "_").split("_"))
    entrada = manifesto["input_schema"]
    saida = manifesto["output_schema"]

    partes = [
        CABECALHO.format(
            id=identificador,
            capability=manifesto["capability"],
            risk_class=manifesto["risk_class"],
            confirmation=manifesto["confirmation"],
            tier=manifesto["tier"],
            data_egress=manifesto["data_egress"],
            access_level_min=manifesto["access_level_min"],
            requires_elevation=bool(manifesto["requires_elevation"]),
            idempotency=manifesto["idempotency"],
            timeout_ms=int(manifesto["timeout_ms"]),
            roots=", ".join(manifesto["roots"]) or "(nenhuma)",
            roots_tupla=_tupla_literal(manifesto["roots"]),
            postcondition=_linha_da_poscondicao(str(manifesto["postcondition"])),
            postcondition_linha=_constante("POSTCONDITION", str(manifesto["postcondition"])),
        )
    ]

    partes.append(f"\n\n@dataclass(frozen=True, slots=True)\nclass {classe}Entrada:")
    partes.append(f'    """Argumentos normalizados de `{identificador}` (input_schema do §4)."""\n')
    campos_entrada = _campos(entrada)
    if campos_entrada:
        for nome, tipo, obrigatorio in campos_entrada:
            partes.append(f"    {nome}: {tipo}" + ("" if obrigatorio else " | None = None"))
    else:
        partes.append("    pass")

    partes.append(f"\n\n@dataclass(frozen=True, slots=True)\nclass {classe}Saida:")
    partes.append(f'    """Resultado de `{identificador}` (output_schema do §4)."""\n')
    campos_saida = _campos(saida) or [
        (nome, "Any", True) for nome in saida.get("required", []) or ["resultado"]
    ]
    for nome, tipo, obrigatorio in campos_saida:
        partes.append(f"    {nome}: {tipo}" + ("" if obrigatorio else " | None = None"))

    obrigatorios_entrada = [n for n, _, o in campos_entrada if o]
    permitidos = _conjunto("PERMITIDOS", [n for n, _, _ in campos_entrada])
    obrigatorios = _conjunto("OBRIGATORIOS", obrigatorios_entrada)
    partes.append(
        f'''

{permitidos}
{obrigatorios}


def validar_entrada(bruto: dict[str, Any]) -> {classe}Entrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{{ID}}: argumento fora do contrato: {{sorted(extras)}}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{{ID}}: argumento obrigatório ausente: {{sorted(faltando)}}")
    return {classe}Entrada(**bruto)


def executar(_entrada: {classe}Entrada) -> {classe}Saida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{{ID}} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
'''
    )
    return "\n".join(partes).replace("\n\n\n\n", "\n\n\n")
