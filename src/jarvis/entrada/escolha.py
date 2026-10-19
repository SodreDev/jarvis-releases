"""Qual backend de entrada usar: o portal por padrão, o `uinput` só se o dono o ligou."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from jarvis.entrada.porta import BackendDeEntrada, EntradaIndisponivel
from jarvis.entrada.portal_remoto import EntradaPorPortal
from jarvis.entrada.uinput import EntradaPorUinput


class EntradaComReserva:
    """Tenta o primeiro backend; se ele estiver indisponível, o segundo (quando existe)."""

    def __init__(self, primario: BackendDeEntrada, reserva: BackendDeEntrada | None) -> None:
        self._backends = [b for b in (primario, reserva) if b is not None]
        self.nome = "+".join(b.nome for b in self._backends)

    def _tentar(self, metodo: str, *args: Any) -> None:
        ultimo: EntradaIndisponivel | None = None
        for backend in self._backends:
            try:
                getattr(backend, metodo)(*args)
            except EntradaIndisponivel as erro:
                ultimo = erro
                continue
            self.nome = backend.nome
            return
        assert ultimo is not None
        raise ultimo

    def mover(self, dx: int, dy: int) -> None:
        self._tentar("mover", dx, dy)

    def clicar(self, botao: str, vezes: int) -> None:
        self._tentar("clicar", botao, vezes)

    def digitar(self, texto: str) -> None:
        self._tentar("digitar", texto)

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None:
        self._tentar("pressionar", modificadores, tecla)

    def fechar(self) -> None:
        for backend in self._backends:
            backend.fechar()


def backend_do_ambiente(
    ambiente: Mapping[str, str],
    *,
    uinput_liberado: bool,
    portal: Callable[[], BackendDeEntrada] | None = None,
    uinput: Callable[[], BackendDeEntrada] | None = None,
) -> BackendDeEntrada:
    """Wayland: portal primeiro, `uinput` de reserva. X11: o portal do Plasma não existe, então o
    `uinput` vem primeiro (se o dono o ligou) e o portal só sobra para dizer por que não dá."""
    do_portal = (portal or (lambda: EntradaPorPortal(ambiente=ambiente)))()
    reserva = (uinput or EntradaPorUinput)() if uinput_liberado else None
    em_x11 = not (ambiente.get("WAYLAND_DISPLAY") or ambiente.get("XDG_SESSION_TYPE") == "wayland")
    if em_x11 and reserva is not None:
        return EntradaComReserva(reserva, do_portal)
    return EntradaComReserva(do_portal, reserva)
