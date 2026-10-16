"""Backends de atalho do PTT, **injetáveis** (cartão F1-13).

`JARVIS_HOTKEYS_BACKEND=falso|portal|windows|nenhum`. A razão de existir a variável é a mesma
do `JARVIS_AUDIO_BACKEND`: o caminho do atalho **global** depende da sessão gráfica do dono
(portal `GlobalShortcuts`/KGlobalAccel no Wayland, `RegisterHotKey` no Windows) e não pode ser
verificado no CI — então o teste injeta um backend falso e o resto do PTT fica provado sem
máquina nenhuma.

Os dois backends de sistema estão aqui **declarados e não implementados**, e isso é escolha:
pôr um cliente D-Bus que ninguém pode exercitar no CI seria código de produto sem teste no
caminho mais sensível da tela. Eles levantam `AtalhoIndisponivel` dizendo o que falta, a `ui`
cai no botão da tela e o cartão F1-16 (máquina do dono) fecha o assunto — inclusive a pergunta
que só se responde lá: se **outro aplicativo** já tomou a combinação.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from jarvis.arquivos import LeituraOcupada, escrever_atomico, ler_texto

VARIAVEL_BACKEND: Final = "JARVIS_HOTKEYS_BACKEND"
VARIAVEL_ARQUIVO: Final = "JARVIS_HOTKEYS_ARQUIVO"
COMBINACAO_PADRAO: Final = "Super+Espaço"
VERDADEIROS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on", "sim", "apertado"})


class AtalhoIndisponivel(RuntimeError):
    """Não há caminho de atalho global aqui. A `ui` continua com o botão da tela."""


class Backend(StrEnum):
    FALSO = "falso"
    """Arquivo (ou memória) no lugar da tecla: é o do teste e o do botão da tela."""

    PORTAL = "portal"
    """XDG Desktop Portal `org.freedesktop.portal.GlobalShortcuts` (Wayland)."""

    WINDOWS = "windows"
    """`RegisterHotKey` da API do Windows."""

    NENHUM = "nenhum"
    """Sem atalho: a tecla nunca está apertada e quem fala usa o botão da tela."""


@runtime_checkable
class BackendDeAtalho(Protocol):
    """De onde vem "a tecla está apertada". A `ui` não sabe qual implementação veio."""

    nome: str
    combinacao: str

    def abrir(self) -> None:
        """Registra o atalho. Recusa aqui o que não dá para fazer nesta máquina."""
        ...

    def pressionado(self) -> bool: ...

    def fechar(self) -> None: ...


@dataclass(slots=True)
class AtalhoFalso:
    """A tecla vem de um arquivo (`1`/`0`) ou da memória, quando `arquivo` é `None`.

    Com arquivo, outro processo (o teste, ou o botão da tela da `ui`) aperta e solta sem
    precisar de sessão gráfica. Arquivo ausente é **tecla solta**: na dúvida, microfone fechado.
    """

    arquivo: Path | None = None
    combinacao: str = COMBINACAO_PADRAO
    nome: str = "falso"
    _apertado: bool = field(default=False, repr=False)

    def abrir(self) -> None:
        return None

    def apertar(self) -> None:
        self._gravar(valor=True)

    def soltar(self) -> None:
        self._gravar(valor=False)

    def _gravar(self, *, valor: bool) -> None:
        self._apertado = valor
        if self.arquivo is not None:
            escrever_atomico(self.arquivo, "1" if valor else "0")

    def pressionado(self) -> bool:
        """Tecla solta por omissão: arquivo ausente ou ocupado **não** abre microfone."""
        if self.arquivo is None:
            return self._apertado
        try:
            bruto = ler_texto(self.arquivo)
        except LeituraOcupada:
            return self._apertado
        if bruto is None:
            return False
        self._apertado = bruto.strip().lower() in VERDADEIROS
        return self._apertado

    def fechar(self) -> None:
        return None


@dataclass(slots=True)
class AtalhoDeSistema:
    """Declarado, não implementado: levanta no `abrir` dizendo o que falta e onde fecha."""

    nome: str
    combinacao: str = COMBINACAO_PADRAO
    detalhe: str = ""

    def abrir(self) -> None:
        raise AtalhoIndisponivel(
            f"atalho global por {self.nome} não está implementado no v0 ({self.detalhe}); "
            "a ui segue com o botão da tela, e o caminho real é o cartão F1-16"
        )

    def pressionado(self) -> bool:
        return False

    def fechar(self) -> None:
        return None


@dataclass(slots=True)
class SemAtalho:
    """A tecla nunca está apertada. Quem fala usa o botão da tela."""

    nome: str = "nenhum"
    combinacao: str = COMBINACAO_PADRAO

    def abrir(self) -> None:
        return None

    def pressionado(self) -> bool:
        return False

    def fechar(self) -> None:
        return None


def backend_escolhido(ambiente: Mapping[str, str] | None = None) -> Backend:
    """Valor desconhecido é erro, não padrão silencioso (mesma regra do `JARVIS_AUDIO_BACKEND`)."""
    fonte = os.environ if ambiente is None else ambiente
    bruto = fonte.get(VARIAVEL_BACKEND, "").strip().lower()
    if not bruto:
        return Backend.NENHUM
    try:
        return Backend(bruto)
    except ValueError:
        validos = ", ".join(b.value for b in Backend)
        raise ValueError(f"{VARIAVEL_BACKEND}={bruto!r} não existe; use um de: {validos}") from None


def atalho_do_ambiente(
    *, raiz: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> BackendDeAtalho:
    """O backend que o ambiente pediu, já com o arquivo do falso resolvido."""
    fonte = os.environ if ambiente is None else ambiente
    backend = backend_escolhido(ambiente)
    if backend is Backend.FALSO:
        bruto = fonte.get(VARIAVEL_ARQUIVO, "").strip()
        if bruto:
            return AtalhoFalso(arquivo=Path(bruto))
        return AtalhoFalso(arquivo=None if raiz is None else raiz / "atalho-falso")
    if backend is Backend.PORTAL:
        return AtalhoDeSistema(
            nome="portal",
            detalhe="org.freedesktop.portal.GlobalShortcuts exige sessão gráfica e consentimento",
        )
    if backend is Backend.WINDOWS:
        return AtalhoDeSistema(
            nome="windows", detalhe="RegisterHotKey exige laço de mensagens de janela"
        )
    return SemAtalho()
