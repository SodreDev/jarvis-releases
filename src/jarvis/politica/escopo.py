"""O escopo do pedido: a ação que está contida no que o dono pediu não pede permissão (ADR-0057).

Pedido do dono (2026-10-29): "se o dono pediu 'abre a CNN no Brave', abrir a aba nova na CNN, trocar
de aba, mantê-la, fechar a que ele mesmo abriu para esse pedido é parte do pedido — 1+1=2, sem
pergunta. […] se sair do escopo ou for de risco (apagar dados, enviar mensagem/dinheiro,
instalar/rodar código, ler credenciais, sair do domínio pedido), pergunta/barra como hoje."

A regra é do **código**, sobre o objetivo do turno (`jarvis.politica.objetivo`, que nasce da fala do
dono e cresce só com o que as ferramentas do objetivo devolvem — nunca com o que o modelo ou uma
página dizem). Contida é a ação de **baixo risco e reversível** sobre **o mesmo alvo** do pedido:

- navegar, abrir site, ler, clicar, digitar, rolar, buscar, ler a web: o endereço é do site
  citado ou alcançado pelo caminho do objetivo, sem levar dado do dono;
- fechar uma aba (`browser.fechar_aba`): a aba que **este pedido** abriu, ou a do site citado;
- abrir o navegador, abrir ou pôr em foco um app: o que o pedido pediu (o PDP e a lista de apps
  liberados seguem valendo);
- fechar a janela, encerrar o app: o app citado no pedido (trabalho não salvo continua
  perguntando, ADR-0046);
- mostrar ou fechar conteúdo na tela do Jarvis: sempre (só mexe na janela dele).

**Nunca** contida, qualquer que seja o pedido: classe de risco que o PDP confirma ou nega
(`RISCOS_FORA_DO_ESCOPO`: apagar, sobrescrever, enviar ou representar o dono, instalar ou rodar
baixado, mudar o sistema, elevação, fora da pasta do dono), e o que o risco dinâmico do navegador
pega (enviar formulário, banco, senha, pagamento, palavra de risco) — esse continua perguntando por
ação. Ler credencial é negado pela lista de negação. O que não está aqui não é julgado: segue a
regra de sempre (o PDP, o guarda da ADR-0049, o Jev). A tabela inteira, dos dois lados, é a da
ADR-0057.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

from jarvis.politica.abertura import nome_de_app
from jarvis.politica.objetivo import Objetivo, termos

NAVEGACAO: Final = frozenset(
    {
        "browser.tabs",
        "browser.read",
        "browser.navigate",
        "browser.click",
        "browser.type",
        "browser.scroll",
        "browser.inspecionar",
        "browser.acionar",
        "sites.open",
        "web.buscar",
        "web.ler",
        "web.canal_videos",
    }
)
"""Os passos de navegação: contidos quando o endereço (se há) está dentro do objetivo."""
FECHAR_ABA: Final = "browser.fechar_aba"
ABRIR_E_FOCAR: Final = frozenset({"browser.launch", "apps.launch", "window.focus_app"})
FECHAR_O_APP: Final = frozenset({"window.close", "apps.quit"})
DA_TELA: Final = frozenset({"tela.mostrar", "tela.ler", "tela.fechar"})
RISCOS_FORA_DO_ESCOPO: Final = frozenset(
    {
        "apagar_permanente",
        "sobrescrita_sem_desfazer",
        "lote_acima_do_teto",
        "renomear_em_massa",
        "egress",
        "representacao_do_dono",
        "instalar_ou_executar_baixado",
        "mudanca_de_sistema",
        "elevacao",
        "fora_do_diretorio_do_dono",
    }
)
"""Classe de risco que o escopo nunca solta: o PDP decide como sempre."""


@dataclass(frozen=True, slots=True)
class Julgamento:
    contido: bool
    motivo: str
    """Por que (frase curta, para a trilha e para a pergunta quando não está contido)."""


FORA: Final = Julgamento(False, "fora do que o dono pediu")


def julgar(
    tool_id: str,
    argumentos: Mapping[str, Any],
    objetivo: Objetivo | None,
    *,
    risco: str = "",
    abertas_pelo_pedido: Collection[int] = (),
    endereco_da_aba: str = "",
) -> Julgamento:
    """A ação está contida no pedido corrente? `risco` é a `risk_class` do manifesto;
    `abertas_pelo_pedido`, as abas que o trabalho deste objetivo abriu; `endereco_da_aba`, o da
    aba que `browser.fechar_aba` fecharia."""
    if objetivo is None:
        return Julgamento(False, "sem pedido do dono neste turno")
    if risco in RISCOS_FORA_DO_ESCOPO:
        return Julgamento(False, f"risco {risco}: o escopo do pedido não solta")
    if tool_id in DA_TELA:
        return Julgamento(True, "só mexe na tela do Jarvis")
    if tool_id in NAVEGACAO:
        url = argumentos.get("url")
        if not (isinstance(url, str) and url):
            return Julgamento(True, "passo de navegação do pedido")
        if objetivo.leva_dado_do_dono(url):
            return Julgamento(False, "o endereço leva dado do dono para um site que ele não citou")
        if objetivo.dentro(url):
            return Julgamento(True, "o site do pedido (citado ou alcançado pelo caminho)")
        return Julgamento(False, "o endereço sai do site que o dono pediu")
    if tool_id == FECHAR_ABA:
        tab_id = argumentos.get("tab_id")
        if isinstance(tab_id, int) and tab_id in abertas_pelo_pedido:
            return Julgamento(True, "a aba que este pedido abriu")
        if endereco_da_aba and objetivo.citado(endereco_da_aba):
            return Julgamento(True, "a aba do site que o dono citou")
        return Julgamento(False, "a aba não foi aberta por este pedido nem é do site que ele citou")
    if tool_id in ABRIR_E_FOCAR:
        return Julgamento(True, "abrir ou pôr em foco o que o dono pediu")
    if tool_id in FECHAR_O_APP:
        alvo = str(argumentos.get("app") or argumentos.get("nome") or "")
        if alvo and _citado(alvo, objetivo):
            return Julgamento(True, "o app que o dono citou")
        return Julgamento(False, "o app não foi citado no pedido")
    return FORA


def _citado(alvo: str, objetivo: Objetivo) -> bool:
    """O nome do app (ou uma palavra dele, de 3 letras ou mais) está no pedido do dono."""
    do_pedido = set(termos(objetivo.pedido))
    palavras = [p for p in termos(nome_de_app(alvo)) if len(p) >= 3]
    return bool(palavras) and any(p in do_pedido for p in palavras)


__all__ = ["FORA", "RISCOS_FORA_DO_ESCOPO", "Julgamento", "julgar"]
