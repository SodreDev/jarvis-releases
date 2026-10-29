"""O guia de design que o modelo recebe **só** no turno que monta ou muda a tela (ADR-0055).

Pedido do dono (2026-10-29): dar ao modelo "skills de frontend — um guia curto de design
(tipografia, espaçamento, tema claro/escuro coerente com o app, tabelas e listas legíveis,
acessibilidade) entregue como bloco fixo enxuto no contexto (respeite o orçamento de tokens da
ADR-0047: meça) ou carregável sob demanda". Sob demanda, pelo código: a nota entra no prompt do
turno quando o pedido fala de tela, tabela, lista, comparação…, quando o dono diz "sim" à oferta de
montar na tela, ou quando há uma exibição aberta (aí só a linha de estado, curta). Nos outros
turnos o custo é zero — medido em `docs/medicoes/prompt-do-turno.md`.

O HTML de uma exibição aberta **não** vai ao prompt: ele pode carregar texto de uma página (dado,
nunca instrução), e o prompt de sistema não é lugar de dado. O modelo o lê com `tela.ler`, que volta
como resultado de ferramenta.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from jarvis.tela.porta import Exibicao
from jarvis.tela.tema import (
    ALERTA,
    CIANO,
    LINHA_FORTE,
    PERIGO,
    POSITIVO,
    TEXTO,
    TEXTO_FORTE,
)

GUIA_DE_DESIGN: Final = (
    "GUIA DA TELA (tela.mostrar). HTML simples com o CSS num <style>; sem script, imagem, link, "
    "formulário nem fonte de fora — o sistema tira e diz o que tirou. O tema do Jarvis já vem "
    f"aplicado: fundo quase preto, texto {TEXTO}, títulos {TEXTO_FORTE}, borda fina "
    f"{LINHA_FORTE}, ciano {CIANO} só em detalhe; classes prontas .fraco .destaque .positivo "
    ".alerta .perigo e .num (número à direita). Tipografia: corpo 14px, h1 18px curto no topo, h2 "
    '15px por seção; nada abaixo de 12px. Tabela: já vem com grade fina (border="0" tira; borda '
    "de célula por CSS não aparece), cabeçalho em <th>, até 6 colunas, unidade no cabeçalho, "
    "número "
    'com class="num"; lista: um item curto por linha; margens de 8 a 12px. '
    "Acessível: contraste de pelo menos 4,5:1 e nunca informação só pela cor (escreva o estado). "
    "Sem neon, sombra, gradiente nem emoji. Tema claro só se o dono pedir: body { "
    "background-color: #f5f7f9; color: #1f2933 }, títulos #0b1520, bordas #c9d3dc, destaque "
    f"#0b7a99. Cores de estado: {POSITIVO} ok, {ALERTA} atenção, {PERIGO} problema. Mudança "
    'pedida por voz ("muda a cor", "coloca em tabela"): leia com tela.ler e mande o HTML '
    'inteiro de novo com tela.mostrar no mesmo id; "fecha" é tela.fechar.'
)
"""O guia inteiro. Curto de propósito: só o que muda o resultado que o dono vê."""

PALAVRAS_DE_TELA: Final[tuple[str, ...]] = (
    "tela", "tabela", "lista", "listinha", "compara", "comparar", "comparativo", "comparacao",
    "resumo", "resume", "monta", "montar", "mostra", "mostrar", "exibe", "exibir", "html",
    "quadro", "planilha", "coluna", "colunas", "cor", "cores", "fonte", "negrito", "destaca",
    "destaque", "tema", "layout", "organiza", "ordena", "card", "grafico",
)  # fmt: skip
"""Palavras (inteiras, sem acento) de um pedido que monta ou muda a tela."""
ACEITES: Final[tuple[str, ...]] = (
    "sim", "pode", "quero", "monta", "manda", "mostra", "claro", "bora", "por favor", "isso",
    "ok", "beleza", "faz", "faca",
)  # fmt: skip
"""O começo de um "sim" à oferta de montar o conteúdo na tela."""


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " " + " ".join(re.sub(r"[^\w\s]", " ", sem_acento.casefold()).split()) + " "


def pede_tela(fala: str) -> bool:
    """O pedido fala de montar, mostrar ou mudar algo na tela."""
    texto = _dobrar(fala)
    return any(f" {palavra} " in texto for palavra in PALAVRAS_DE_TELA)


def aceitou_a_oferta(fala: str, ultima_do_jarvis: str) -> bool:
    """O Jarvis perguntou se monta na tela ("Quer que eu monte o resto na tela?") e o dono disse
    que sim."""
    oferta = _dobrar(ultima_do_jarvis)
    if " tela " not in oferta or not ultima_do_jarvis.rstrip().endswith("?"):
        return False
    resposta = _dobrar(fala)
    return any(resposta.startswith(f" {aceite} ") for aceite in ACEITES)


def nota_da_tela(fala: str, ultima_do_jarvis: str, abertas: Sequence[Exibicao]) -> str:
    """O que vai ao prompt deste turno sobre a tela: nada (o comum), a linha das exibições abertas
    (curta, sem o conteúdo) e o guia — quando o turno monta ou muda a tela."""
    partes: list[str] = []
    if abertas:
        ids = ", ".join(e.id for e in abertas)
        partes.append(
            f"Na tela do Jarvis agora: {len(abertas)} exibição(ões) aberta(s) (id {ids}; a mais "
            "nova é a última). Para mudar uma, leia com tela.ler e refaça com tela.mostrar no "
            "mesmo id."
        )
    if pede_tela(fala) or aceitou_a_oferta(fala, ultima_do_jarvis):
        partes.append(GUIA_DE_DESIGN)
    return "\n".join(partes)


__all__ = ["GUIA_DE_DESIGN", "aceitou_a_oferta", "nota_da_tela", "pede_tela"]
