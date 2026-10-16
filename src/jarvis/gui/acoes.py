"""O vocabulário fechado com que a IA propõe mudanças na tela (ADR-0019, emenda).

**O princípio é o P1 da SPEC, aplicado à interface:** o modelo propõe, o código dispõe. A IA
não desenha tela, não escreve HTML, não manda script: ela emite **ações estruturadas** de um
conjunto fechado, e quem decide se cada uma acontece é o `Workspace` (`jarvis.gui.workspace`),
com as regras do dono em cima.

Por isso este módulo não tem nada de Qt e nada de desenho. Ele é o **contrato**: nove tipos de
ação (o nono, `definirModoDeEscuta`, é da ADR-0021), uma área em unidades de grade, e uma
leitura que recusa o que não entende — porque tudo que vem da IA é `untrusted` (P6), inclusive
quando a IA é a nossa.

A recusa é sempre **com motivo**: ação recusada em silêncio vira IA insistindo no mesmo erro,
e dono sem saber por que a tela não mudou.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from jarvis.voz.escuta import MODOS, ModoDeEscuta

COLUNAS: Final = 12
LINHAS: Final = 8
"""A grade do workspace. Doze por oito dá divisões de 2, 3, 4 e 6 colunas sem sobra."""

LIMITE_DE_TEXTO: Final = 280
"""Título e motivo vindos da IA são cortados aqui: rótulo é rótulo, não parágrafo."""


class AcaoInvalida(ValueError):
    """A proposta não é uma ação deste vocabulário. A mensagem diz o que estava errado."""


class Tipo(StrEnum):
    """As nove ações. Mais nenhuma — acrescentar é emenda de ADR, não detalhe de tela."""

    CRIAR = "createWidget"
    REMOVER = "removeWidget"
    MOVER = "moveWidget"
    REDIMENSIONAR = "resizeWidget"
    FOCAR = "focusWidget"
    MINIMIZAR = "minimizeWidget"
    MODO = "setWorkspaceMode"
    RESTAURAR = "restoreLayout"
    ESCUTA = "definirModoDeEscuta"
    """ADR-0021: trocar atalho ↔ palavra ↔ contínua. Não mexe na tela, mexe em **quando o
    Jarvis escuta** — por isso a política de confirmação é a de `jarvis.voz.escuta`."""


class Modo(StrEnum):
    """Os três modos de workspace. O modo muda a composição, não o que os módulos são."""

    ASSISTENTE = "assistente"
    """Núcleo grande no centro, poucos indicadores, conversa embaixo. Muito espaço vazio."""

    PESQUISA = "pesquisa"
    """O núcleo encolhe e sai do caminho; o conteúdo manda, organizado por importância."""

    EXECUCAO = "execucao"
    """Várias visões ao mesmo tempo: código, console, arquivos, telas, estado das tarefas."""

    @property
    def frase(self) -> str:
        return {
            Modo.ASSISTENTE: "assistente",
            Modo.PESQUISA: "pesquisa",
            Modo.EXECUCAO: "execução",
        }[self]


@dataclass(frozen=True, slots=True)
class Area:
    """Um retângulo em unidades de grade. Pixel é assunto da tela, não deste contrato."""

    coluna: int
    linha: int
    colunas: int
    linhas: int

    def __post_init__(self) -> None:
        if self.colunas <= 0 or self.linhas <= 0:
            raise AcaoInvalida(f"área sem tamanho: {self.colunas}×{self.linhas}")
        if self.coluna < 0 or self.linha < 0:
            raise AcaoInvalida(f"área fora da grade: coluna {self.coluna}, linha {self.linha}")
        if self.coluna + self.colunas > COLUNAS or self.linha + self.linhas > LINHAS:
            raise AcaoInvalida(
                f"área {self.coluna},{self.linha} {self.colunas}×{self.linhas} não cabe na "
                f"grade de {COLUNAS}×{LINHAS}"
            )

    @property
    def direita(self) -> int:
        return self.coluna + self.colunas

    @property
    def baixo(self) -> int:
        return self.linha + self.linhas

    def colide_com(self, outra: Area) -> bool:
        return (
            self.coluna < outra.direita
            and outra.coluna < self.direita
            and self.linha < outra.baixo
            and outra.linha < self.baixo
        )

    def movida(self, coluna: int, linha: int) -> Area:
        return Area(coluna=coluna, linha=linha, colunas=self.colunas, linhas=self.linhas)

    def para_dict(self) -> dict[str, int]:
        return {
            "coluna": self.coluna,
            "linha": self.linha,
            "colunas": self.colunas,
            "linhas": self.linhas,
        }


@dataclass(frozen=True, slots=True)
class Acao:
    """Uma proposta. Imutável: o que a IA pediu fica registrado como ela pediu."""

    tipo: Tipo
    widget: str = ""
    componente: str = ""
    area: Area | None = None
    titulo: str = ""
    dados: Mapping[str, Any] = field(default_factory=dict)
    modo: Modo | None = None
    layout: str = ""
    motivo: str = ""
    """Por que a IA está propondo isto. É o que aparece numa confirmação pedida ao dono."""
    escuta: ModoDeEscuta | None = None
    """Só em `definirModoDeEscuta`: o modo pedido (`ptt`, `palavra` ou `vad`)."""

    def para_dict(self) -> dict[str, Any]:
        bruto: dict[str, Any] = {"tipo": str(self.tipo)}
        for nome, valor in (
            ("widget", self.widget),
            ("componente", self.componente),
            ("titulo", self.titulo),
            ("layout", self.layout),
            ("motivo", self.motivo),
        ):
            if valor:
                bruto[nome] = valor
        if self.area is not None:
            bruto["area"] = self.area.para_dict()
        if self.modo is not None:
            bruto["modo"] = str(self.modo)
        if self.dados:
            bruto["dados"] = dict(self.dados)
        if self.escuta is not None:
            bruto["escuta"] = str(self.escuta)
        return bruto


def _texto(bruto: Mapping[str, Any], chave: str) -> str:
    valor = bruto.get(chave, "")
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise AcaoInvalida(f"{chave}: esperava texto, veio {type(valor).__name__}")
    return valor.strip()[:LIMITE_DE_TEXTO]


def _area(bruto: Mapping[str, Any]) -> Area | None:
    valor = bruto.get("area")
    if valor is None:
        return None
    if not isinstance(valor, Mapping):
        raise AcaoInvalida("area: esperava um mapa com coluna, linha, colunas e linhas")
    faltando = {"coluna", "linha", "colunas", "linhas"} - set(valor)
    if faltando:
        raise AcaoInvalida(f"area: faltam os campos {', '.join(sorted(faltando))}")
    try:
        numeros = {chave: int(valor[chave]) for chave in ("coluna", "linha", "colunas", "linhas")}
    except (TypeError, ValueError) as erro:
        raise AcaoInvalida(f"area: coordenada que não é número inteiro ({erro})") from None
    return Area(**numeros)


def ler_acao(bruto: Mapping[str, Any]) -> Acao:
    """Lê uma proposta vinda de fora. Recusa o que não for exatamente deste vocabulário.

    **Campo desconhecido é recusa, não é tolerância.** Um `html`, um `script` ou um `comando`
    que passasse despercebido viraria, na melhor das hipóteses, um campo ignorado — e, na
    pior, a porta que a ADR-0019 fecha. Aceitar só o que se entende é o que torna "nunca HTML
    ou JS arbitrário da IA" uma propriedade da estrutura, e não uma promessa.
    """
    if not isinstance(bruto, Mapping):
        raise AcaoInvalida(f"ação tem de ser um mapa, veio {type(bruto).__name__}")
    conhecidos = {
        "tipo",
        "widget",
        "componente",
        "area",
        "titulo",
        "dados",
        "modo",
        "layout",
        "motivo",
        "escuta",
    }
    estranhos = sorted(set(bruto) - conhecidos)
    if estranhos:
        raise AcaoInvalida(
            f"campos que este vocabulário não tem: {', '.join(estranhos)}. A IA propõe ação "
            "estruturada, nunca conteúdo para a tela executar"
        )
    cru = bruto.get("tipo")
    try:
        tipo = Tipo(str(cru))
    except ValueError:
        raise AcaoInvalida(
            f"tipo {cru!r} não existe. Os que existem: {', '.join(t.value for t in Tipo)}"
        ) from None
    modo: Modo | None = None
    if bruto.get("modo") is not None:
        try:
            modo = Modo(str(bruto["modo"]))
        except ValueError:
            raise AcaoInvalida(
                f"modo {bruto['modo']!r} não existe. Os que existem: "
                f"{', '.join(m.value for m in Modo)}"
            ) from None
    dados = bruto.get("dados") or {}
    if not isinstance(dados, Mapping):
        raise AcaoInvalida(f"dados: esperava um mapa, veio {type(dados).__name__}")
    escuta = _escuta(bruto, tipo, dados)
    return Acao(
        tipo=tipo,
        widget=_texto(bruto, "widget"),
        componente=_texto(bruto, "componente"),
        area=_area(bruto),
        titulo=_texto(bruto, "titulo"),
        dados=dict(dados),
        modo=modo,
        layout=_texto(bruto, "layout"),
        motivo=_texto(bruto, "motivo"),
        escuta=escuta,
    )


def _escuta(bruto: Mapping[str, Any], tipo: Tipo, dados: Mapping[str, Any]) -> ModoDeEscuta | None:
    """O modo de `definirModoDeEscuta` — e **só** o modo.

    Nada de `dados` aqui: a palavra, o limiar, o atalho e o interruptor da nuvem são escolhas
    do dono na tela, e nenhuma ação do vocabulário chega neles. Um `dados` com `nuvem` ou
    `palavra` não é ignorado — é recusado, para a IA saber que não pode.
    """
    cru = bruto.get("escuta")
    if tipo is not Tipo.ESCUTA:
        if cru is not None:
            raise AcaoInvalida(f"escuta só existe em {Tipo.ESCUTA}, não em {tipo}")
        return None
    if dados:
        raise AcaoInvalida(
            f"{Tipo.ESCUTA} não leva dados ({', '.join(sorted(map(str, dados)))}): palavra, "
            "atalho e nuvem são escolha do dono na tela"
        )
    try:
        return ModoDeEscuta(str(cru))
    except ValueError:
        raise AcaoInvalida(
            f"escuta {cru!r} não existe. Os que existem: {', '.join(MODOS)}"
        ) from None
