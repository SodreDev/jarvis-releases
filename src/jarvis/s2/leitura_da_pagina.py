"""Ler a página antes de agir nela, e reler depois do erro (ADR-0069 §2; dono, 2026-11-15: «os erros
de execução vêm de ele não saber que pode inspecionar a página»).

O motor clicava e digitava pelo texto que imaginava estar na tela e, quando o passo falhava, tentava
de novo às cegas ou desistia. Aqui o **código** garante a ordem de um assistente que olha antes de
mexer: a ação na página (`browser.click`, `browser.type`, `browser.acionar`, `browser.gesto`) só
roda depois de uma leitura da página (`browser.inspecionar`, `browser.read`, `browser.tela`) que
ainda vale.
A leitura deixa de valer quando:

- a página mudou: abriu outra (`browser.navigate`, `sites.open`, `browser.launch`) ou um clique /
  acionamento / gesto deu certo (pode ter navegado ou aberto outra coisa) — digitar não muda;
- um passo na página **falhou**: antes de tentar de novo, relê para achar o campo ou o botão certo.

Quando falta a leitura, quem propõe é o código: a inspeção da página (o mapa com papel, rótulo,
estado e `ref` de cada elemento) no lugar da ação, e o motor decide de novo com o mapa na mão. O
teto de leituras forçadas por pedido evita laço; depois dele, vale o orçamento de tentativas da
recuperação (ADR-0038) e a guarda de laço (ADR-0062).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from jarvis.s2.motor import PedidoDeTool

ACOES_NA_PAGINA: Final = frozenset(
    {"browser.click", "browser.type", "browser.acionar", "browser.gesto"}
)
LEITURAS_DA_PAGINA: Final = frozenset({"browser.inspecionar", "browser.read", "browser.tela"})
MUDAM_A_PAGINA: Final = frozenset(
    {"browser.navigate", "sites.open", "browser.launch", "browser.fechar_aba"}
)
NAO_MUDAM_A_PAGINA: Final = frozenset({"browser.type"})
"""Ação que, dando certo, deixa a leitura valendo: o campo recebeu o texto, a página é a mesma."""
LEITURAS_FORCADAS: Final = 6
"""Quantas leituras o código propõe por pedido antes de deixar a ação seguir sem ela."""
NOTA_DA_LEITURA: Final = (
    "LER ANTES DE AGIR: antes da ação que você propôs, o Jarvis leu a página — o mapa dos "
    "elementos (papel, rótulo, estado e `ref` de cada um) está no último resultado. Escolha nele o "
    "campo ou botão certo, aja pelo `ref` e, se um passo falhar, leia de novo e depure (outro "
    "rótulo, role a página, outro elemento) em vez de desistir."
)


def falta_ler(passos: Iterable[tuple[str, str]]) -> str:
    """Por que a próxima ação na página precisa de uma leitura antes: `"antes"` (nada lido desde
    que a página mudou), `"depois_do_erro"` (o último passo na página falhou) ou vazio (já leu).

    `passos` = (ferramenta, status) de cada passo do pedido, na ordem."""
    lida = False
    motivo = "antes"
    for tool_id, status in passos:
        ok = status == "ok"
        if tool_id in LEITURAS_DA_PAGINA:
            if ok:
                lida, motivo = True, ""
        elif tool_id in MUDAM_A_PAGINA:
            if ok:
                lida, motivo = False, "antes"
        elif tool_id in ACOES_NA_PAGINA:
            if not ok:
                lida, motivo = False, "depois_do_erro"
            elif tool_id not in NAO_MUDAM_A_PAGINA:
                lida, motivo = False, "antes"
    return "" if lida else motivo


def leitura_antes(
    pedido: PedidoDeTool,
    passos: Iterable[tuple[str, str]],
    disponiveis: Iterable[str],
    *,
    forcadas: int = 0,
) -> PedidoDeTool | None:
    """A leitura que o código propõe no lugar da ação, ou `None` quando a ação pode seguir."""
    if pedido.tool_id not in ACOES_NA_PAGINA or forcadas >= LEITURAS_FORCADAS:
        return None
    if not falta_ler(passos):
        return None
    ids = set(disponiveis)
    ferramenta = next((t for t in ("browser.inspecionar", "browser.read") if t in ids), None)
    if ferramenta is None:
        return None
    args: dict[str, object] = {}
    aba = _aba(pedido.args)
    if aba is not None:
        args["tab_id"] = aba
    return PedidoDeTool(ferramenta, args)


def _aba(args: Mapping[str, object]) -> int | None:
    valor = args.get("tab_id")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


__all__ = [
    "ACOES_NA_PAGINA",
    "LEITURAS_DA_PAGINA",
    "LEITURAS_FORCADAS",
    "NOTA_DA_LEITURA",
    "falta_ler",
    "leitura_antes",
]
