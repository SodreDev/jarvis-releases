"""Abrir um site no navegador padrão do dono — sem lançar processo (pedido do dono, 2026-10-17).

Só `http`/`https`, com host, sem usuário e senha na URL. Quem abre é o **portal** do desktop
(`org.freedesktop.portal.OpenURI`, por D-Bus): o Jarvis não escolhe navegador, não passa
argumento a ele e não fica com processo filho — o desktop abre no navegador que o dono
configurou. No Windows, `os.startfile` (o mesmo "abrir com o padrão" do Explorer).

Não há controle do navegador aqui (é a ADR-0027, proposta para a fase seguinte): a página abre
e o Jarvis não lê nem mexe nela. A política de confirmação por domínio é do PDP
(`jarvis.politica.abertura`).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from jarvis.politica.abertura import UrlRecusada, dominio, validar_url

__all__ = ["Abridor", "UrlRecusada", "abrir_pelo_portal", "dominio", "validar_url"]

Abridor = Callable[[str], None]


def abrir_pelo_portal(url: str) -> None:
    """`OpenURI` do xdg-desktop-portal. Erro do portal sobe como `OSError` com o motivo."""
    if sys.platform == "win32":  # pragma: no cover — não executado nesta máquina
        os.startfile(url)  # noqa: S606 — abrir com o padrão do sistema, sem shell
        return
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError as erro:  # pragma: no cover — depende do grupo instalado
        raise OSError("sem o cliente D-Bus (jeepney): instale o grupo gui") from erro
    portal = DBusAddress(
        "/org/freedesktop/portal/desktop",
        bus_name="org.freedesktop.portal.Desktop",
        interface="org.freedesktop.portal.OpenURI",
    )
    with open_dbus_connection(bus="SESSION") as conexao:
        resposta = conexao.send_and_get_reply(
            new_method_call(portal, "OpenURI", "ssa{sv}", ("", url, {})), timeout=5
        )
    if resposta.header.message_type.name == "error":
        raise OSError(f"o portal recusou abrir: {resposta.body}")
