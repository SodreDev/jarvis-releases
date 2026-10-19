"""A porta da entrada virtual: o que um backend sabe fazer, e nada mais.

O backend **não decide nada** (foco, risco, taxa e parada são do `ControleDeEntrada`); ele só
sintetiza o evento. Os testes trocam o backend por um falso que grava o que recebeu — nenhum
teste toca portal, `/dev/uinput`, tela, mouse ou teclado reais do dono.
"""

from __future__ import annotations

from typing import Final, Protocol

BOTOES: Final = ("esquerdo", "direito", "meio")
LIMITE_DO_DESLOCAMENTO: Final = 2_000
"""Pixels por movimento, em cada eixo: o ponteiro anda no máximo isto por chamada."""
LIMITE_DE_CLIQUES: Final = 3


class EntradaIndisponivel(RuntimeError):
    """Nenhum backend consegue sintetizar entrada agora (sem portal, sem consentimento, sem
    permissão no `uinput`). A frase diz o que falta."""


class BackendDeEntrada(Protocol):
    nome: str

    def mover(self, dx: int, dy: int) -> None:
        """Move o ponteiro **relativamente** (não há posição absoluta sem captura de tela)."""
        ...

    def clicar(self, botao: str, vezes: int) -> None: ...

    def digitar(self, texto: str) -> None: ...

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None: ...

    def fechar(self) -> None:
        """Encerra a sessão e libera o que o sistema deu (revoga a permissão do portal)."""
        ...
