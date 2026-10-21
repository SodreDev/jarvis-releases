"""Qual método executa o pedido (dono, 2026-10-20, ADR-0035): o mais direto para AQUELE contexto.

Pedido sobre site vai **direto à extensão** do navegador — sem abrir o navegador como app, sem
atalho de teclado, sem terminal; app local vai pelo **resolvedor de apps e pelo foco**; trabalho de
terminal ou de arquivos do sistema vai a um **subagente** (`tarefa.iniciar`). O roteador é do
código, não do modelo: lê a fala do dono e o que está ligado nesta sessão e devolve o método, o
motivo (um código curto) e as ferramentas que ficam **de fora** do turno — quem as chamar ouve o
porquê e o caminho certo. A trilha guarda só isso, nunca a fala.

Pedido que cai em mais de um método ("abre o Spotify e pesquisa no Google") não bloqueia nada: o
roteador só restringe quando o caminho é inequívoco. E o dono que pede o teclado ou o mouse pelo
nome ("aperta ctrl+L") tem o teclado e o mouse.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Metodo(StrEnum):
    NAVEGADOR = "navegador"
    """A extensão: `browser.*` e `sites.open` na aba atual."""
    ENTRADA_VIRTUAL = "entrada_virtual"
    """Mouse e teclado virtuais: o dono pediu, ou o site proíbe automação (ADR-0027)."""
    WEB = "web"
    """Sem extensão: `web.buscar`/`web.ler` e `sites.open` no navegador padrão."""
    APP = "app"
    """O resolvedor de apps (`apps.launch`, `browser.launch`) e o foco (`window.*`)."""
    SUBAGENTE = "subagente"
    """Terminal e arquivos do sistema: `tarefa.iniciar` (o Jarvis não tem shell, ADR-0028)."""
    SISTEMA = "sistema"
    """Volume, brilho, mídia, hora, bateria, lembrete, área de transferência."""
    MEMORIA = "memoria"
    CONVERSA = "conversa"
    """Nada específico, ou pedido misto: o modelo escolhe, e nada fica de fora."""


ENTRADA: Final = frozenset(
    {"input.key.press", "input.key.type", "input.mouse.click", "input.mouse.move"}
)
ABRIR_COMO_APP: Final = frozenset({"apps.launch", "browser.launch"})
SITES_SEM_AUTOMACAO: Final = ("instagram", "whatsapp")
"""Sites que proíbem automação: ali a interação é por mouse e teclado virtuais (ADR-0027)."""

_SITES: Final = (
    "youtube", "google", "gmail", "wikipedia", "wikipédia", "twitter", "facebook", "netflix",
    "amazon", "mercado livre", "mercadolivre", "reddit", "linkedin", "github", "spotify web",
    "site", "página", "pagina", "aba", "link", "url", "na internet", "na web", "no navegador",
    "pesquisa", "pesquisar", "procura na", "busca na", "notícia", "noticia",
)  # fmt: skip
_DOMINIO: Final = re.compile(r"\b[\w-]+\.(?:com|org|net|br|io|app|dev|gov|edu|tv|me)\b")
_TERMINAL: Final = (
    "terminal", "comando", "linha de comando", "shell", "bash", "script", "sudo", "console",
    "arquivos do sistema", "pasta do sistema", "systemctl", "compila",
)  # fmt: skip
_TECLADO: Final = ("aperta", "aperte", "tecla", "atalho", "teclado", "mouse", "cursor")
_SISTEMA: Final = (
    "volume", "brilho", "música", "musica", "toca ", "tocar", "pausa", "pausar", "próxima música",
    "que horas", "hora", "bateria", "internet está", "wi-fi", "wifi", "lembrete", "me lembra",
    "timer", "alarme", "área de transferência", "copia o texto",
)  # fmt: skip
_MIDIA: Final = ("música", "musica", "toca ", "tocar", "pausa", "pausar", "próxima música")
"""Tocar e pausar com um site citado ("toca um vídeo no YouTube") é pedido do site, não do sistema:
sozinhas, estas palavras não fazem do pedido um pedido misto (auditoria da extensão, 2026-10-21)."""
_SISTEMA_COM_SITE: Final = tuple(p for p in _SISTEMA if p not in _MIDIA)
_QUER_VER: Final = (
    "abre", "abra", "abrir", "abram", "mostra", "mostre", "mostrar", "coloca", "coloque",
    "colocar", "bota", "bote", "botar", "põe", "ponha", "toca", "toque", "tocar", "assistir",
    "assiste", "assista", "quero ver", "pra eu ver", "para eu ver", "deixa aberto", "na tela",
)  # fmt: skip
"""O dono quer **ver** o resultado ("abre um vídeo no YouTube"), e não que o Jarvis leia por ele
("pesquisa quantos inscritos tem o canal"): aí a página termina à vista dele."""
_MEMORIA: Final = (
    "anota",
    "guarda que",
    "lembra que",
    "o que eu disse",
    "combinamos",
    "você lembra",
)
_ABRIR_O_NAVEGADOR: Final = re.compile(
    r"\babr[ae]\b.{0,20}\b(?:navegador|brave|firefox|chrome|chromium)\b"
)


@dataclass(frozen=True, slots=True)
class ContextoDoMetodo:
    """O que está ligado nesta sessão — do código, nunca do modelo."""

    navegador: bool = False
    """O controle do navegador pela extensão está ligado (`navegador_controlado`)."""
    entrada: bool = False
    """Mouse e teclado virtuais estão ligados."""
    apps: frozenset[str] = frozenset()
    """Os nomes dos apps que o dono autorizou, sem acento e em minúsculas."""


@dataclass(frozen=True, slots=True)
class Escolha:
    metodo: Metodo
    motivo: str
    """Código curto e estável (`cita_site`, `pede_terminal`…): é o que vai para a trilha."""
    evitar: frozenset[str] = frozenset()
    """Ferramentas fora deste turno: o executor as recusa dizendo o caminho certo."""
    caminho: str = ""
    """O que usar em vez delas, para a frase da recusa e para a nota do prompt."""

    def nota(self) -> str:
        """A linha do prompt do turno; vazia quando o modelo escolhe sozinho."""
        if self.metodo is Metodo.CONVERSA or not self.caminho:
            return ""
        return f"Método deste pedido: {self.metodo} ({self.motivo}) — {self.caminho}."

    def recusa(self, tool_id: str) -> str:
        return (
            f"este pedido vai pelo método {self.metodo} ({self.motivo}): {tool_id} fica de fora "
            f"neste turno — {self.caminho}"
        )


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return f" {' '.join(sem_acento.casefold().split())} "


def _algum(texto: str, palavras: tuple[str, ...]) -> bool:
    return any(_dobrar(p).strip() in texto for p in palavras)


def quer_ver(fala: str) -> bool:
    """O pedido é para o dono **ver** o que o Jarvis abrir (abrir, mostrar, pôr, tocar, assistir):
    a página tem de terminar à vista dele — não numa janela de trabalho nem atrás de outra. Do
    código, pela fala do dono, como o método; nunca do modelo nem da página."""
    texto = _dobrar(fala)
    return any(f" {_dobrar(p).strip()} " in texto for p in _QUER_VER)


def escolher_metodo(fala: str, contexto: ContextoDoMetodo) -> Escolha:
    """A tabela de casos (ADR-0035, testada em `test_metodo.py`): a primeira regra inequívoca."""
    texto = _dobrar(fala)
    if _algum(texto, _TECLADO):
        return Escolha(Metodo.ENTRADA_VIRTUAL, "pede_teclado_ou_mouse")
    candidatos: list[Escolha] = []
    if _algum(texto, _TERMINAL):
        candidatos.append(
            Escolha(
                Metodo.SUBAGENTE,
                "pede_terminal",
                ENTRADA | ABRIR_COMO_APP,
                "delegue com tarefa.iniciar; nada de abrir terminal nem digitar comando",
            )
        )
    sem_automacao = any(site in texto for site in SITES_SEM_AUTOMACAO)
    cita_site = bool(_DOMINIO.search(texto)) or _algum(texto, _SITES) or sem_automacao
    abre_o_navegador = bool(_ABRIR_O_NAVEGADOR.search(texto)) and not (
        _DOMINIO.search(texto) or _algum(texto, _SITES)
    )
    if abre_o_navegador:
        # Uma instância só (dono, 2026-10-21): o browser.launch (e o apps.launch de um navegador)
        # traz para a frente o que já está aberto e só lança quando não há um.
        candidatos.append(
            Escolha(
                Metodo.APP,
                "abre_o_navegador",
                ENTRADA,
                "use browser.launch (só o navegador: traz para a frente o que já está aberto, ou "
                "abre um)",
            )
        )
    elif cita_site and sem_automacao and contexto.navegador and contexto.entrada:
        candidatos.append(
            Escolha(
                Metodo.ENTRADA_VIRTUAL,
                "site_sem_automacao",
                frozenset(),
                "o site proíbe automação: leia pela extensão e aja com mouse e teclado virtuais",
            )
        )
    elif cita_site and contexto.navegador:
        candidatos.append(
            Escolha(
                Metodo.NAVEGADOR,
                "cita_site",
                ENTRADA | ABRIR_COMO_APP,
                "use a extensão (browser.navigate, browser.read, browser.click, web.buscar), sem "
                "abrir o navegador como app nem atalho de teclado",
            )
        )
    elif cita_site:
        candidatos.append(
            Escolha(
                Metodo.WEB,
                "cita_site_sem_extensao",
                ENTRADA,
                "use web.buscar, web.ler e sites.open; o controle do navegador está desligado",
            )
        )
    nomes = {app for app in contexto.apps if app and f" {app} " in texto}
    if nomes:  # com site também: "abre o Spotify e pesquisa no Google" é misto, nada fica de fora
        candidatos.append(
            Escolha(
                Metodo.APP,
                "cita_app",
                ENTRADA,
                "use apps.launch (o foco vai sozinho para a janela quando ela abrir) e "
                "window.focus_app para um app já aberto",
            )
        )
    if _algum(texto, _SISTEMA_COM_SITE if cita_site else _SISTEMA):
        candidatos.append(
            Escolha(
                Metodo.SISTEMA,
                "pede_sistema",
                ENTRADA,
                "use as ferramentas system.*, media.*, timer.* ou clipboard.*",
            )
        )
    if _algum(texto, _MEMORIA):
        candidatos.append(Escolha(Metodo.MEMORIA, "pede_memoria", frozenset(), "use memoria.*"))
    metodos = {c.metodo for c in candidatos}
    if len(metodos) == 1:
        return candidatos[0]
    if len(metodos) > 1:
        return Escolha(Metodo.CONVERSA, "pedido_misto")
    return Escolha(Metodo.CONVERSA, "sem_metodo_especifico")
