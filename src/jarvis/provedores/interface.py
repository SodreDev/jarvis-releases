"""A fronteira de um provedor de modelos: listar, dizer o que cada modelo faz, chamar (ADR-0056).

Um provedor é quem atende um modelo de linguagem — a Anthropic pela CLI do Claude, a OpenAI, o
OpenRouter, a Groq, a CLI do Codex, a do OpenCode, um roteador compatível com a OpenAI, ou o eco
local. Três coisas são pedidas a todos, e nenhuma decide segurança:

1. **Listar** os modelos que ele oferece **agora** (`listar`), pelo endpoint ou comando oficial
   dele. Quem guarda a lista em cache e cai na lista do registro quando não dá é o catálogo
   (`jarvis.provedores.catalogo`), não o provedor.
2. **Dizer o que cada modelo faz** (`Capacidades`): visão, ferramentas, esforço de raciocínio,
   contexto, preço — o que o provedor informa. O que ele não informa fica `None`
   (**desconhecido**), que não é "não": a tela diz "não informado" e o roteamento não aposta.
3. **Chamar** (`motor`): devolver um `MotorDeConversa` (ADR-0025) com o modelo e o esforço
   escolhidos. O cérebro não muda: ele continua falando com um motor, sem saber de quem é.

O que vem do provedor — nomes, descrições, preços — é **dado de terceiros**: passa pela forma
(`FORMA_DO_ID`, `limpar_texto`) antes de chegar à tela e nunca vai ao prompt do modelo. E nada aqui
mexe no tier de ferramenta: quem decide se uma proposta roda é o PDP, igual para todo modelo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from jarvis.s2.motor import Modo, MotorDeConversa
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado

ESFORCOS: Final[tuple[str, ...]] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
"""O esforço de raciocínio, do menor para o maior, nos nomes que os provedores usam. Cada provedor
traduz para o parâmetro dele (`--effort`, `reasoning_effort`, `reasoning.effort`,
`model_reasoning_effort`); o que um modelo aceita vem em `Capacidades.esforcos`."""

ESFORCO_AO_PENSAR: Final = "high"
"""O modo `pensar` do cérebro (ADR-0025, regra 4) sobe o esforço para ao menos isto."""

FORMA_DO_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\]]{0,159}")
"""Um id de modelo como os provedores escrevem (`gpt-5-mini`, `openai/gpt-4o:free`,
`sonnet[1m]`). Espaço, aspas e controle recusam: o id vai num
argumento de processo ou no corpo de um pedido, e a lista vem de terceiros."""

MAXIMO_DO_NOME: Final = 120
MAXIMO_DE_MODELOS: Final = 3000
"""Teto de uma listagem. O OpenRouter tem algumas centenas; mais que isto é resposta estranha."""


class ListagemIndisponivel(RuntimeError):
    """A lista ao vivo não veio: sem chave, sem rede, sem o comando, formato inesperado. O
    catálogo cai no cache ou na lista do registro e diz por quê."""


class ProvedorIndisponivel(RuntimeError):
    """O provedor não consegue chamar o modelo agora (a CLI não está instalada, falta login,
    falta a chave). A mensagem diz o que o dono faz para resolver."""


class Papel(StrEnum):
    """Para que um preset serve (ADR-0056)."""

    CEREBRO = "cerebro"
    """O motor da conversa (ADR-0025)."""
    JEV = "jev"
    """O classificador de decisão por perguntas fechadas (ADR-0029)."""
    VISAO = "visao"
    """Quem recebe a imagem quando o modelo do cérebro não vê (roteamento por capacidade)."""
    RESUMO = "resumo"
    """Quem resume texto longo para o dono."""


PAPEIS: Final[tuple[str, ...]] = tuple(p.value for p in Papel)


def limpar_texto(valor: object, *, limite: int = MAXIMO_DO_NOME) -> str:
    """Texto de terceiros pronto para a tela: sem controle, sem quebra, com teto. A tela ainda o
    mostra como texto puro (nunca HTML)."""
    if not isinstance(valor, str):
        return ""
    limpo = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in valor)
    limpo = " ".join(limpo.split())
    return limpo[:limite]


def id_valido(valor: object) -> str:
    """O id, se tiver a forma de um id de modelo; senão vazio."""
    return valor if isinstance(valor, str) and FORMA_DO_ID.fullmatch(valor) else ""


def esforco_do_modo(esforco: str, modo: Modo, aceitos: tuple[str, ...] | None = None) -> str:
    """O esforço de um pedido: o do preset no modo rápido; no `pensar`, ao menos
    `ESFORCO_AO_PENSAR` (nunca desce). Com `aceitos`, o resultado é um deles: o mais perto por
    baixo do pedido, senão o menor que o modelo aceita. Vazio = o provedor decide."""
    pedido = esforco
    if modo is Modo.PENSAR and _posicao(pedido) < _posicao(ESFORCO_AO_PENSAR):
        pedido = ESFORCO_AO_PENSAR
    if not pedido or aceitos is None:
        return pedido
    if not aceitos:
        return ""
    if pedido in aceitos:
        return pedido
    abaixo = [e for e in aceitos if _posicao(e) <= _posicao(pedido)]
    return max(abaixo, key=_posicao) if abaixo else min(aceitos, key=_posicao)


def _posicao(esforco: str) -> int:
    return ESFORCOS.index(esforco) if esforco in ESFORCOS else -1


@dataclass(frozen=True, slots=True)
class Capacidades:
    """O que um modelo faz, como o provedor (ou o registro) informa. `None` = não informado."""

    visao: bool | None = None
    """Recebe imagem junto do texto."""
    ferramentas: bool | None = None
    """Chamada de ferramenta nativa. O cérebro propõe ferramenta pelo protocolo de texto
    (ADR-0038), então isto informa — não barra nem libera nada."""
    esforcos: tuple[str, ...] | None = None
    """Os esforços que o modelo aceita, na ordem de `ESFORCOS`. `()` = não aceita esforço."""
    contexto: int | None = None
    """Janela de contexto, em tokens."""
    saida_maxima: int | None = None
    preco_entrada: float | None = None
    """US$ por milhão de tokens de entrada, como o provedor publica."""
    preco_saida: float | None = None
    latencia: str = ""
    """Latência, quando o provedor publica (raro). Texto do provedor, já limpo."""

    def completar(self, outra: Capacidades) -> Capacidades:
        """Estas, com o que faltar preenchido por `outra` (o registro completa o provedor)."""
        return Capacidades(
            visao=self.visao if self.visao is not None else outra.visao,
            ferramentas=self.ferramentas if self.ferramentas is not None else outra.ferramentas,
            esforcos=self.esforcos if self.esforcos is not None else outra.esforcos,
            contexto=self.contexto if self.contexto is not None else outra.contexto,
            saida_maxima=self.saida_maxima if self.saida_maxima is not None else outra.saida_maxima,
            preco_entrada=self.preco_entrada
            if self.preco_entrada is not None
            else outra.preco_entrada,
            preco_saida=self.preco_saida if self.preco_saida is not None else outra.preco_saida,
            latencia=self.latencia or outra.latencia,
        )

    def para_dict(self) -> dict[str, Any]:
        return {
            "visao": self.visao,
            "ferramentas": self.ferramentas,
            "esforcos": list(self.esforcos) if self.esforcos is not None else None,
            "contexto": self.contexto,
            "saida_maxima": self.saida_maxima,
            "preco_entrada": self.preco_entrada,
            "preco_saida": self.preco_saida,
            "latencia": self.latencia,
        }

    @classmethod
    def de_dict(cls, bruto: object) -> Capacidades:
        """A volta de `para_dict` — e o que vier fora da forma vira "não informado"."""
        if not isinstance(bruto, Mapping):
            return cls()
        esforcos = bruto.get("esforcos")
        return cls(
            visao=_booleano(bruto.get("visao")),
            ferramentas=_booleano(bruto.get("ferramentas")),
            esforcos=tuple(e for e in esforcos if e in ESFORCOS)
            if isinstance(esforcos, list | tuple)
            else None,
            contexto=_inteiro(bruto.get("contexto")),
            saida_maxima=_inteiro(bruto.get("saida_maxima")),
            preco_entrada=_numero(bruto.get("preco_entrada")),
            preco_saida=_numero(bruto.get("preco_saida")),
            latencia=limpar_texto(bruto.get("latencia"), limite=60),
        )


def _booleano(valor: object) -> bool | None:
    return valor if isinstance(valor, bool) else None


def _inteiro(valor: object) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return None
    return int(valor) if 0 < valor < 10**9 else None


def _numero(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return None
    return float(valor) if 0 <= valor < 10**6 else None


@dataclass(frozen=True, slots=True)
class Modelo:
    """Um modelo de um provedor, com o que se sabe dele."""

    id: str
    nome: str = ""
    capacidades: Capacidades = field(default_factory=Capacidades)

    def __post_init__(self) -> None:
        if not FORMA_DO_ID.fullmatch(self.id):
            raise ValueError(f"id de modelo fora da forma: {self.id[:40]!r}")

    def com_capacidades(self, capacidades: Capacidades) -> Modelo:
        return replace(self, capacidades=capacidades)

    def para_dict(self) -> dict[str, Any]:
        return {"id": self.id, "nome": self.nome, "capacidades": self.capacidades.para_dict()}


@runtime_checkable
class ProvedorDeModelos(Protocol):
    """O que o resto do Jarvis precisa de um provedor."""

    @property
    def id(self) -> str:
        """O id no registro (`licenses/provedores-de-modelo.toml`)."""
        ...

    @property
    def onde(self) -> Onde: ...

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        """Os modelos de agora, do endpoint ou comando oficial. `ListagemIndisponivel` se não
        der; a listagem não leva nada do dono (só a chave, no cabeçalho)."""
        ...

    def motor(
        self, modelo: str, esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        """Um motor de conversa com este modelo e este esforço (vazio = o padrão do provedor).
        `capacidades` é o que se sabe do modelo sem rede (cache e registro: a fachada as dá).
        `ProvedorIndisponivel` quando não dá para chamar agora."""
        ...


__all__ = [
    "ESFORCOS",
    "ESFORCO_AO_PENSAR",
    "FORMA_DO_ID",
    "PAPEIS",
    "Capacidades",
    "ListagemIndisponivel",
    "Modelo",
    "Papel",
    "ProvedorDeModelos",
    "ProvedorIndisponivel",
    "esforco_do_modo",
    "id_valido",
    "limpar_texto",
]
