"""Qual janela está em foco — a pergunta que decide se mouse e teclado virtuais são perigosos.

Evento de entrada vai para **a janela em foco**, não para onde o modelo imagina. Por isso, antes de
cada ação, o código lê o foco e o classifica; o modelo não diz (nem pode mentir sobre) onde está.

- **X11**: `xprop` (`_NET_ACTIVE_WINDOW`, `WM_CLASS`, `_NET_WM_NAME`).
- **Wayland (KDE)**: o protocolo não deixa um aplicativo ver a janela dos outros; o `kdotool`
  (Apache-2.0, programa separado, opcional) carrega um script no KWin e devolve a janela ativa.
  Sem ele **o foco é desconhecido — e desconhecido é perigoso**, nunca "provavelmente seguro".
  `xprop` em sessão Wayland vê só o XWayland e devolveria uma janela velha: não é usado ali.

Classificar é função pura (`categoria_da_janela`), testada sem janela nenhuma.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from jarvis.executor.comandos import (
    ComandoIndisponivel,
    ComandoRecusado,
    Lancador,
    executar,
    instalado,
)

PRAZO_S: Final = 3.0


@dataclass(frozen=True, slots=True)
class Janela:
    app: str
    titulo: str
    id: str = ""


class Foco(Protocol):
    def atual(self) -> Janela | None:
        """A janela em foco, ou `None` se **não dá para saber**."""
        ...

    def ativar(self, janela: Janela) -> bool:
        """Devolve o foco a `janela` (depois de o dono confirmar no Jarvis). `False` = não deu."""
        ...


class FocoDesconhecido:
    def atual(self) -> Janela | None:
        return None

    def ativar(self, janela: Janela) -> bool:
        return False


class FocoPorKdotool:
    """KDE Plasma (Wayland ou X11): `kdotool getactivewindow …`."""

    def __init__(self, lancar: Lancador = executar) -> None:
        self._lancar = lancar

    def _perguntar(self, *comando: str) -> str:
        saida = self._lancar(["kdotool", *comando], PRAZO_S, None)
        return saida.saida.strip() if saida.ok else ""

    def atual(self) -> Janela | None:
        try:
            identificador = self._perguntar("getactivewindow")
            if not identificador:
                return None
            app = self._perguntar("getactivewindow", "getwindowclassname")
            titulo = self._perguntar("getactivewindow", "getwindowname")
        except (ComandoIndisponivel, ComandoRecusado):
            return None
        return Janela(app=app, titulo=titulo[:120], id=identificador) if app or titulo else None

    def ativar(self, janela: Janela) -> bool:
        if not janela.id or not re.fullmatch(r"[\w{}-]{1,64}", janela.id):
            return False
        try:
            return self._lancar(["kdotool", "windowactivate", janela.id], PRAZO_S, None).ok
        except (ComandoIndisponivel, ComandoRecusado):
            return False


class FocoPorXprop:
    """Sessão X11: `xprop -root _NET_ACTIVE_WINDOW` e as propriedades dessa janela."""

    def __init__(self, lancar: Lancador = executar) -> None:
        self._lancar = lancar

    def atual(self) -> Janela | None:
        try:
            raiz = self._lancar(["xprop", "-root", "_NET_ACTIVE_WINDOW"], PRAZO_S, None)
            achado = re.search(r"\b(0x[0-9a-fA-F]+)\b", raiz.saida) if raiz.ok else None
            if achado is None or int(achado.group(1), 16) == 0:
                return None
            identificador = achado.group(1)
            props = self._lancar(
                ["xprop", "-id", identificador, "WM_CLASS", "_NET_WM_NAME"], PRAZO_S, None
            )
        except (ComandoIndisponivel, ComandoRecusado):
            return None
        if not props.ok:
            return None
        classe = re.search(r'WM_CLASS\(STRING\) = "[^"]*",\s*"([^"]*)"', props.saida)
        nome = re.search(r'_NET_WM_NAME\(\w+\) = "((?:[^"\\]|\\.)*)"', props.saida)
        app = classe.group(1) if classe else ""
        titulo = nome.group(1) if nome else ""
        return Janela(app=app, titulo=titulo[:120], id=identificador) if app or titulo else None

    def ativar(self, janela: Janela) -> bool:
        return False  # sem wmctrl na lista de programas desta peça: o chamador recusa a ação


def foco_do_ambiente(
    ambiente: Mapping[str, str], lancar: Lancador = executar, tem: Callable[[str], bool] = instalado
) -> Foco:
    """O leitor de foco confiável para esta sessão, ou `FocoDesconhecido`."""
    if ambiente.get("WAYLAND_DISPLAY") or ambiente.get("XDG_SESSION_TYPE") == "wayland":
        return FocoPorKdotool(lancar) if tem("kdotool") else FocoDesconhecido()
    if ambiente.get("DISPLAY") and tem("xprop"):
        return FocoPorXprop(lancar)
    return FocoDesconhecido()


# --- classificação -----------------------------------------------------------------------------
def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.casefold()


def _contem(titulo_dobrado: str, palavras: tuple[str, ...]) -> bool:
    """Palavra inteira (ou frase inteira) no título: «entrar» não casa com «concentrar»."""
    return any(re.search(rf"\b{re.escape(p)}\b", titulo_dobrado) for p in palavras)


def _tokens(texto: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", _dobrar(texto))) - {""}


TERMINAIS: Final = frozenset(
    {
        "konsole", "yakuake", "ptyxis", "kitty", "alacritty", "xterm", "uxterm", "wezterm", "foot",
        "tilix", "terminator", "lxterminal", "urxvt", "rxvt", "guake", "terminology", "ghostty",
        "terminal", "tmux", "qterminal", "terminus", "tabby", "hyper", "warp",
    }
)  # fmt: skip
GERENCIADORES_DE_SENHA: Final = frozenset(
    {
        "keepassxc", "keepass", "bitwarden", "1password", "lastpass", "enpass", "kwalletmanager",
        "kwalletmanager5", "seahorse", "dashlane", "nordpass",
    }
)  # fmt: skip
AUTENTICACAO: Final = frozenset(
    {"polkit", "pkexec", "kdesu", "pinentry", "ksshaskpass", "kwalletd", "kwalletd5", "kwalletd6"}
)  # fmt: skip
PALAVRAS_DE_BANCO: Final = (
    "nubank", "itau", "bradesco", "santander", "banco do brasil", "caixa economica", "c6 bank",
    "sicredi", "sicoob", "btg pactual", "paypal", "mercado pago", "pagseguro", "picpay",
    "binance", "coinbase", "internet banking", "interactive brokers", "banco inter",
)  # fmt: skip
PALAVRAS_DE_MENSAGEIRO: Final = (
    "whatsapp", "instagram", "telegram", "discord", "messenger", "slack", "signal", "gmail",
    "outlook", "caixa de entrada", "inbox", "direct message", "mensagens diretas",
)  # fmt: skip
PALAVRAS_DE_AUTENTICACAO: Final = (
    "senha", "password", "entrar", "autenticacao", "authentication", "sign in", "log in", "login",
    "verificacao em duas etapas", "two-factor", "2fa", "codigo de verificacao",
)  # fmt: skip
PROPRIO_JARVIS: Final = frozenset({"jarvis", "dev.sodredev.jarvis"})

ROTULOS: Final[dict[str, str]] = {
    "jarvis": "o próprio Jarvis",
    "terminal": "terminal",
    "senha": "gerenciador de senhas",
    "autenticacao": "janela de autenticação",
    "banco": "banco ou pagamento",
    "mensageiro": "mensageiro ou e-mail",
    "desconhecida": "janela desconhecida",
}


def categoria_da_janela(janela: Janela | None) -> str:
    """`""` = janela comum; senão o motivo de a ação ser perigosa (`jarvis` é recusa)."""
    if janela is None:
        return "desconhecida"
    app, titulo = _dobrar(janela.app), _dobrar(janela.titulo)
    if app in PROPRIO_JARVIS or app.endswith(".jarvis") or titulo == "jarvis":
        return "jarvis"
    tokens = _tokens(janela.app)
    if tokens & TERMINAIS:
        return "terminal"
    if tokens & GERENCIADORES_DE_SENHA:
        return "senha"
    if tokens & AUTENTICACAO or _contem(titulo, PALAVRAS_DE_AUTENTICACAO):
        return "autenticacao"
    if _contem(titulo, PALAVRAS_DE_BANCO):
        return "banco"
    if _contem(titulo, PALAVRAS_DE_MENSAGEIRO):
        return "mensageiro"
    return ""
