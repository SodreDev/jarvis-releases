"""Harness de acerto em pt-BR: a fala do dono → a ferramenta ou a decisão certa (ADR-0064).

Cada cenário é uma fala e o que se espera dela, numa categoria (apps, navegador, web, sistema,
sim/não…). A nota vai de 0 a 2, **sem juiz**, como no ToolCall15 do OpenJarvis
(`evals/scorers/toolcall15.py`, Apache-2.0; aqui só a ideia):

- **2**: a ferramenta certa com os argumentos esperados (os esperados têm de estar lá, com o mesmo
  valor; argumento a mais não tira ponto), ou a decisão certa;
- **1**: a ferramenta certa com algum argumento errado ou faltando;
- **0**: outra ferramenta, nenhuma quando se esperava uma, ou alguma quando se esperava nenhuma.

O que responde a cada tipo de cenário é o **código** do Jarvis, sem rede e sem chave:

- `atalho`: o caminho rápido (`jarvis.politica.atalho`, ADR-0045), com o motivo do roteador;
- `metodo`: o roteador de método (`jarvis.politica.metodo`, ADR-0035);
- `resposta`: o sim/não falado (`jarvis.s2.portao.resposta_literal`, ADR-0048);
- `continuar`: a resposta à pergunta do teto (`jarvis.s2.portao.ler_continuacao`, ADR-0059);
- `nota`: a nota do dono na fala (`jarvis.s2.nota_do_dono`, ADR-0063);
- `motor`: a primeira proposta de um `MotorDeConversa` dado por quem chama. Sem motor, esses
  cenários não rodam. Nos testes e no `verificar.py` só entra motor falso — o motor real (um
  preset do dono) é para rodar à mão, nunca na verificação.

O **gate** compara com a linha de base: o total de pontos não cai e nenhuma categoria cai mais que
`TOLERANCIA`; categoria com menos de `N_MINIMO` cenários não vira gate (diz que é pouca). Cada
rodada repete `RODADAS` vezes e vale a mediana (o código dá sempre o mesmo; o motor real, não).
"""

from __future__ import annotations

import json
import statistics
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.politica.atalho import ContextoDoAtalho, achar
from jarvis.politica.metodo import ContextoDoMetodo, escolher_metodo
from jarvis.s2.motor import Contexto, Mensagem, Modo, MotorDeConversa, PedidoDeTool
from jarvis.s2.nota_do_dono import nota_na_fala
from jarvis.s2.portao import ler_continuacao, resposta_literal
from jarvis.voz.interface import nunca_cancelado

PASTA: Final = Path(__file__).parent
CENARIOS: Final = PASTA / "cenarios.toml"
LINHA_DE_BASE: Final = PASTA / "linha_de_base.json"
TOLERANCIA: Final = 0.05
"""Quanto a fração de pontos de uma categoria pode cair sem reprovar (5 pontos percentuais)."""
N_MINIMO: Final = 5
"""Categoria com menos cenários que isto não reprova ninguém: é pouca para medir."""
RODADAS: Final = 3
BLOCO_DO_TETO: Final = 50
NENHUMA: Final = "nenhuma"
"""O esperado de quem não deve responder nada (não é atalho, não é sim nem não)."""


class Tipo(StrEnum):
    ATALHO = "atalho"
    METODO = "metodo"
    RESPOSTA = "resposta"
    CONTINUAR = "continuar"
    NOTA = "nota"
    MOTOR = "motor"


@dataclass(frozen=True, slots=True)
class Cenario:
    id: str
    categoria: str
    tipo: Tipo
    fala: str
    ferramenta: str = ""
    """O `tool_id` esperado (atalho e motor); `nenhuma` = não deve propor ferramenta."""
    args: Mapping[str, Any] = field(default_factory=dict)
    decisao: str = ""
    """A decisão esperada (método, sim/não, continuar, nota); `nenhuma` = nenhuma."""


@dataclass(frozen=True, slots=True)
class Resultado:
    cenario: Cenario
    pontos: int
    obtido: str
    """O que veio, em texto curto (para o relatório): `apps.launch {"nome": "discord"}`."""


@dataclass(frozen=True, slots=True)
class Ambiente:
    """O que a sessão "tem" nos cenários: tudo de mentira, igual em toda máquina."""

    apps: Mapping[str, str] = field(
        default_factory=lambda: {
            "discord": "discord",
            "spotify": "spotify",
            "calculadora": "gnome-calculator",
            "steam": "steam",
            "terminal": "gnome-terminal",
            "obs": "obs",
        }
    )
    navegadores: Mapping[str, str] = field(
        default_factory=lambda: {"brave": "brave", "firefox": "firefox"}
    )
    navegador: bool = True
    entrada: bool = True

    def metodo(self) -> ContextoDoMetodo:
        return ContextoDoMetodo(
            navegador=self.navegador, entrada=self.entrada, apps=frozenset(self.apps)
        )

    def atalho(self, motivo_do_metodo: str) -> ContextoDoAtalho:
        return ContextoDoAtalho(
            disponivel=lambda _tool: True,
            app=lambda nome: self.apps.get(nome.casefold()),
            navegador_configurado=lambda nome: self.navegadores.get(nome.casefold()),
            navegador=self.navegador,
            motivo_do_metodo=motivo_do_metodo,
        )


def carregar(caminho: Path = CENARIOS) -> list[Cenario]:
    dados = tomllib.loads(caminho.read_text("utf-8"))
    cenarios = [
        Cenario(
            id=str(c["id"]),
            categoria=str(c["categoria"]),
            tipo=Tipo(c["tipo"]),
            fala=str(c["fala"]),
            ferramenta=str(c.get("ferramenta", "")),
            args=dict(c.get("args", {})),
            decisao=str(c.get("decisao", "")),
        )
        for c in dados["cenario"]
    ]
    ids = [c.id for c in cenarios]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ValueError(f"id de cenário repetido: {', '.join(repetidos)}")
    return cenarios


def _texto(tool_id: str, args: Mapping[str, Any]) -> str:
    return f"{tool_id} {json.dumps(dict(args), ensure_ascii=False, sort_keys=True)}"


def pontuar_ferramenta(cenario: Cenario, tool_id: str | None, args: Mapping[str, Any]) -> int:
    if cenario.ferramenta == NENHUMA:
        return 2 if tool_id is None else 0
    if tool_id != cenario.ferramenta:
        return 0
    certos = all(k in args and args[k] == v for k, v in cenario.args.items())
    return 2 if certos else 1


def _decisao(cenario: Cenario, ambiente: Ambiente) -> str:
    fala = cenario.fala
    if cenario.tipo is Tipo.METODO:
        return str(escolher_metodo(fala, ambiente.metodo()).metodo)
    if cenario.tipo is Tipo.RESPOSTA:
        resposta = resposta_literal(fala)
        return str(resposta) if resposta is not None else NENHUMA
    if cenario.tipo is Tipo.CONTINUAR:
        opcao = ler_continuacao(fala, BLOCO_DO_TETO)
        return str(opcao) if opcao is not None else NENHUMA
    nota = nota_na_fala(fala)
    return str(nota) if nota is not None else NENHUMA


def primeira_proposta(
    motor: MotorDeConversa, fala: str, ferramentas: Sequence[Mapping[str, Any]]
) -> PedidoDeTool | None:
    """A primeira ferramenta que o motor propõe para a fala, sem rodar nada."""
    contexto = Contexto(
        sistema="Você é o Jarvis. Use uma ferramenta quando o pedido precisar.",
        mensagens=(Mensagem("dono", fala),),
        ferramentas=tuple(ferramentas),
    )
    deltas = motor.gerar(contexto, Modo.RAPIDO, nunca_cancelado)
    try:
        for delta in deltas:
            if isinstance(delta, PedidoDeTool):
                return delta
    finally:
        fechar = getattr(deltas, "close", None)
        if callable(fechar):
            fechar()
    return None


def avaliar(
    cenario: Cenario,
    ambiente: Ambiente,
    *,
    motor: MotorDeConversa | None = None,
    ferramentas: Sequence[Mapping[str, Any]] = (),
) -> Resultado | None:
    """Um cenário, uma vez. `None` = o cenário é de motor e não há motor."""
    if cenario.tipo is Tipo.ATALHO:
        escolha = escolher_metodo(cenario.fala, ambiente.metodo())
        atalho = achar(cenario.fala, ambiente.atalho(escolha.motivo))
        tool_id = atalho.tool_id if atalho else None
        args = atalho.args if atalho else {}
        obtido = _texto(atalho.tool_id, atalho.args) if atalho else NENHUMA
        return Resultado(cenario, pontuar_ferramenta(cenario, tool_id, args), obtido)
    if cenario.tipo is Tipo.MOTOR:
        if motor is None:
            return None
        pedido = primeira_proposta(motor, cenario.fala, ferramentas)
        tool_id = pedido.tool_id if pedido else None
        args = pedido.args if pedido else {}
        obtido = _texto(pedido.tool_id, pedido.args) if pedido else NENHUMA
        return Resultado(cenario, pontuar_ferramenta(cenario, tool_id, args), obtido)
    decisao = _decisao(cenario, ambiente)
    return Resultado(cenario, 2 if decisao == cenario.decisao else 0, decisao)


@dataclass(frozen=True, slots=True)
class Placar:
    """Pontos por categoria (mediana das rodadas) e os cenários que não fizeram 2."""

    pontos: Mapping[str, float]
    maximo: Mapping[str, int]
    n: Mapping[str, int]
    erros: tuple[Resultado, ...]

    def fracao(self, categoria: str) -> float:
        return self.pontos[categoria] / self.maximo[categoria] if self.maximo[categoria] else 0.0

    @property
    def total(self) -> float:
        maximo = sum(self.maximo.values())
        return sum(self.pontos.values()) / maximo if maximo else 0.0

    def para_json(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 4),
            "categorias": {
                c: {"fracao": round(self.fracao(c), 4), "n": self.n[c]} for c in sorted(self.n)
            },
        }


def rodar(
    cenarios: Iterable[Cenario],
    ambiente: Ambiente | None = None,
    *,
    motor: MotorDeConversa | None = None,
    ferramentas: Sequence[Mapping[str, Any]] = (),
    rodadas: int = RODADAS,
) -> Placar:
    ambiente = ambiente or Ambiente()
    por_rodada: dict[str, list[float]] = {}
    maximo: dict[str, int] = {}
    n: dict[str, int] = {}
    erros: list[Resultado] = []
    lista = list(cenarios)
    for rodada in range(rodadas):
        soma: dict[str, float] = {}
        for cenario in lista:
            resultado = avaliar(cenario, ambiente, motor=motor, ferramentas=ferramentas)
            if resultado is None:
                continue
            soma[cenario.categoria] = soma.get(cenario.categoria, 0) + resultado.pontos
            if rodada == 0:
                maximo[cenario.categoria] = maximo.get(cenario.categoria, 0) + 2
                n[cenario.categoria] = n.get(cenario.categoria, 0) + 1
                if resultado.pontos < 2:
                    erros.append(resultado)
        for categoria, da_rodada in soma.items():
            por_rodada.setdefault(categoria, []).append(da_rodada)
    medianas = {c: float(statistics.median(v)) for c, v in por_rodada.items()}
    return Placar(pontos=medianas, maximo=maximo, n=n, erros=tuple(erros))


def gate(placar: Placar, base: Mapping[str, Any], tolerancia: float = TOLERANCIA) -> list[str]:
    """O que piorou em relação à linha de base. Vazio = passou."""
    problemas: list[str] = []
    if placar.total + 1e-9 < float(base.get("total", 0.0)):
        problemas.append(f"o total caiu: {base['total']:.1%} → {placar.total:.1%}")
    for categoria, antes in dict(base.get("categorias", {})).items():
        if categoria not in placar.n:
            problemas.append(f"{categoria}: a categoria sumiu dos cenários")
            continue
        if placar.n[categoria] < N_MINIMO:
            continue
        agora = placar.fracao(categoria)
        if agora + tolerancia + 1e-9 < float(antes["fracao"]):
            problemas.append(f"{categoria}: {float(antes['fracao']):.1%} → {agora:.1%}")
    return problemas


def ler_base(caminho: Path = LINHA_DE_BASE) -> dict[str, Any]:
    dado = json.loads(caminho.read_text("utf-8"))
    return dado if isinstance(dado, dict) else {}


def tabela(placar: Placar) -> list[str]:
    linhas = ["| categoria | n | pontos | acerto |", "|---|---|---|---|"]
    for categoria in sorted(placar.n):
        linhas.append(
            f"| {categoria} | {placar.n[categoria]} | {placar.pontos[categoria]:.0f}/"
            f"{placar.maximo[categoria]} | {placar.fracao(categoria):.1%} |"
        )
    linhas.append(f"| **total** | {sum(placar.n.values())} | | {placar.total:.1%} |")
    return linhas


__all__ = [
    "CENARIOS",
    "LINHA_DE_BASE",
    "NENHUMA",
    "N_MINIMO",
    "RODADAS",
    "TOLERANCIA",
    "Ambiente",
    "Cenario",
    "Placar",
    "Resultado",
    "Tipo",
    "avaliar",
    "carregar",
    "gate",
    "ler_base",
    "pontuar_ferramenta",
    "primeira_proposta",
    "rodar",
    "tabela",
]
