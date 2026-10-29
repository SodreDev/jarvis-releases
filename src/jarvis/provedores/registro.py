"""O registro dos provedores de modelo: o portão dos motores de voz, num arquivo próprio (ADR-0056).

`licenses/provedores-de-modelo.toml` tem um `[[motor]]` por provedor, no formato e com as regras de
`licenses/motores.toml` (ADR-0017): licença do cliente permissiva, procedência com fonte e data,
os quatro campos de termos para quem é de nuvem, e **nuvem desligada** até o dono ligar. Quem
confere é a mesma função (`jarvis.voz.registro.exigir_motor`), com outro `arquivo`. O que este
registro acrescenta:

- `modelos` é a **lista estática** de cada provedor — conferida na página oficial, com
  `fonte_dos_modelos` e `data_dos_modelos` — e é o último recurso do catálogo, quando nem a
  listagem ao vivo nem o cache servem;
- `[[capacidade]]` diz, por padrão de id (`fnmatch`), o que um modelo faz quando o provedor não
  informa (a OpenAI, por exemplo, lista modelos sem dizer qual vê imagem). Cada regra traz `fonte`
  e `data`; a primeira que diz algo vence, campo a campo, e o que o provedor informa vence o
  registro.

Abrir um provedor para **listar** não passa pelo interruptor da nuvem: a listagem não leva nada
do dono, como a lista de vozes da ElevenLabs (ADR-0017, emenda). **Chamar** passa
(`exigir`).
"""

from __future__ import annotations

import fnmatch
import importlib
import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jarvis.dados import caminho
from jarvis.provedores.interface import (
    ESFORCOS,
    Capacidades,
    Modelo,
    ProvedorDeModelos,
    id_valido,
)
from jarvis.voz.registro import Motor, MotorRecusado, exigir_motor, ler_motores

ARQUIVO: Final = caminho("licenses/provedores-de-modelo.toml")
PAPEL: Final = "conversa"

ECO: Final = "conversa-eco"
CLAUDE_CLI: Final = "conversa-claude-cli"


@dataclass(frozen=True, slots=True)
class RegraDeCapacidade:
    """O que o registro sabe de um grupo de modelos de um provedor."""

    provedor: str
    padrao: str
    capacidades: Capacidades
    fonte: str
    data: str


def ler_provedores(arquivo: Path = ARQUIVO) -> tuple[Motor, ...]:
    """Os provedores do registro, na ordem do arquivo."""
    return ler_motores(arquivo)


def provedor_registrado(identificador: str, *, arquivo: Path = ARQUIVO) -> Motor | None:
    return next((m for m in ler_provedores(arquivo) if m.id == identificador), None)


def ler_regras(arquivo: Path = ARQUIVO) -> tuple[RegraDeCapacidade, ...]:
    """As `[[capacidade]]` do registro. Regra sem fonte ou sem data é ignorada: fato sem
    procedência não é fato (ADR-0012) — e o teste do registro cobra que não haja nenhuma."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    regras: list[RegraDeCapacidade] = []
    for bruta in dados.get("capacidade", []):
        if not isinstance(bruta, Mapping):
            continue
        fonte, data = str(bruta.get("fonte", "")).strip(), str(bruta.get("data", "")).strip()
        provedor, padrao = str(bruta.get("provedor", "")), str(bruta.get("padrao", ""))
        if not (fonte and data and provedor and padrao):
            continue
        regras.append(RegraDeCapacidade(provedor, padrao, _capacidades(bruta), fonte, data))
    return tuple(regras)


def _capacidades(bruta: Mapping[str, Any]) -> Capacidades:
    esforcos = bruta.get("esforcos")
    return Capacidades(
        visao=bruta.get("visao") if isinstance(bruta.get("visao"), bool) else None,
        ferramentas=bruta.get("ferramentas")
        if isinstance(bruta.get("ferramentas"), bool)
        else None,
        esforcos=tuple(e for e in esforcos if e in ESFORCOS)
        if isinstance(esforcos, list)
        else None,
        contexto=bruta.get("contexto") if isinstance(bruta.get("contexto"), int) else None,
    )


def capacidades_do_registro(
    provedor: str, modelo: str, regras: tuple[RegraDeCapacidade, ...]
) -> Capacidades:
    """O que o registro diz de `modelo`: as regras do provedor que casam, na ordem do arquivo."""
    resultado = Capacidades()
    for regra in regras:
        if regra.provedor == provedor and fnmatch.fnmatchcase(modelo, regra.padrao):
            resultado = resultado.completar(regra.capacidades)
    return resultado


def modelos_estaticos(
    motor: Motor, regras: tuple[RegraDeCapacidade, ...] = ()
) -> tuple[Modelo, ...]:
    """A lista do registro (`modelo` e `modelos`), com as capacidades das regras."""
    return tuple(
        Modelo(id=m, capacidades=capacidades_do_registro(motor.id, m, regras))
        for m in motor.modelos_permitidos
        if id_valido(m)
    )


def classe_de(motor: Motor) -> type[Any]:
    """A classe que `implementacao` nomeia (`modulo:Classe`), importada só agora: o provedor
    que o dono não usa não carrega nada."""
    modulo, _, nome = motor.implementacao.partition(":")
    if not modulo or not nome:
        raise MotorRecusado(f"provedor {motor.id!r} sem `implementacao` no registro")
    return getattr(importlib.import_module(modulo), nome)  # type: ignore[no-any-return]


def abrir(
    identificador: str,
    *,
    ambiente: Mapping[str, str] | None = None,
    pasta_de_trabalho: Path,
    arquivo: Path = ARQUIVO,
) -> ProvedorDeModelos:
    """O provedor, para **listar** — sem o interruptor da nuvem, porque listar não leva nada do
    dono. Chamar um modelo passa antes por `exigir`."""
    motor = provedor_registrado(identificador, arquivo=arquivo)
    if motor is None:
        raise MotorRecusado(
            f"provedor {identificador!r} não está em {arquivo.name}: provedor que ninguém "
            "verificou não roda (ADR-0012, ADR-0056)"
        )
    provedor = classe_de(motor)(
        registro=motor, ambiente=ambiente, pasta_de_trabalho=pasta_de_trabalho
    )
    if not isinstance(provedor, ProvedorDeModelos):
        raise MotorRecusado(f"{motor.implementacao} não é um provedor de modelos")
    return provedor


def exigir(
    identificador: str,
    *,
    ligados: Collection[str],
    sem_termos: Collection[str] = (),
    arquivo: Path = ARQUIVO,
) -> Motor:
    """O portão de chamar: licença, termos e o interruptor da nuvem (ADR-0017, regras 1–4)."""
    return exigir_motor(
        identificador, arquivo=arquivo, nuvem_ligada=ligados, sem_termos_aceitos=sem_termos
    )


__all__ = [
    "ARQUIVO",
    "CLAUDE_CLI",
    "ECO",
    "PAPEL",
    "RegraDeCapacidade",
    "abrir",
    "capacidades_do_registro",
    "classe_de",
    "exigir",
    "ler_provedores",
    "ler_regras",
    "modelos_estaticos",
    "provedor_registrado",
]
