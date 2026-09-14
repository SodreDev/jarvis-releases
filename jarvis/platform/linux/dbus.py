"""D-Bus de sessão via jeepney (``jeepney.io.threading``), com timeout em tudo.

- A API blocking do jeepney NÃO é thread-safe; aqui só se usa io.threading
  (roteador com thread receptora daemon, que despacha respostas e sinais).
- Um roteador de SESSÃO por processo: criado de forma lazy, sob lock, e refeito
  se o endereço do barramento mudar ou a conexão cair.
- ``open_dedicated_router()`` abre uma conexão só sua, para quem precisa de
  estado próprio na conexão (portal GlobalShortcuts: ``Registry.Register`` tem
  de vir antes de qualquer outra chamada de portal nela). Quem abre fecha com
  ``close_router()``.
- O endereço vem SÓ de ``DBUS_SESSION_BUS_ADDRESS``: sem ele não há conexão
  (nada de adivinhar ``$XDG_RUNTIME_DIR/bus``).
- ``jeepney`` é importado dentro das funções: importar este módulo não carrega
  jeepney nem abre conexão.

Timeouts (SPEC-fase2 §2): sonda até 1 s (``PROBE_TIMEOUT``), operação até 3 s
(``CALL_TIMEOUT``). Estourou: ``TimeoutError``. Sem barramento, conexão caída ou
resposta de erro: ``DBusError``.
"""
from __future__ import annotations

import os
import queue as _queue
import threading
import time
from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple

if TYPE_CHECKING:  # pragma: no cover - só para type checkers
    from jeepney import MatchRule, Message
    from jeepney.io.threading import DBusRouter

PROBE_TIMEOUT = 1.0
CALL_TIMEOUT = 3.0

_BUS_NAME = "org.freedesktop.DBus"
_BUS_PATH = "/org/freedesktop/DBus"
_PROPS_IFACE = "org.freedesktop.DBus.Properties"


class DBusError(Exception):
    """Falha de D-Bus que não é timeout.

    ``name`` é o nome do erro D-Bus (ex.: ``org.freedesktop.DBus.Error.ServiceUnknown``)
    quando a falha veio numa resposta de erro; None quando nem houve conexão.
    """

    def __init__(self, message: str, name: Optional[str] = None):
        super().__init__(message)
        self.name = name


_LOCK = threading.Lock()
_ROUTER: Optional["DBusRouter"] = None
_ROUTER_ADDR: Optional[str] = None


def _session_address() -> str:
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").strip()
    if not addr:
        raise DBusError("DBUS_SESSION_BUS_ADDRESS ausente: sem D-Bus de sessão")
    return addr


def open_router(address: Optional[str] = None, *, timeout: float = PROBE_TIMEOUT) -> "DBusRouter":
    """Abre uma conexão NOVA com roteador próprio. Quem abre fecha com close_router()."""
    from jeepney.io.threading import DBusRouter, open_dbus_connection

    addr = address or _session_address()
    try:
        conn = open_dbus_connection(bus=addr, auth_timeout=timeout)
    except Exception as e:
        raise DBusError(f"sem conexão com o D-Bus ({type(e).__name__}: {e})") from e
    return DBusRouter(conn)


def open_dedicated_router(*, timeout: float = PROBE_TIMEOUT) -> "DBusRouter":
    """Conexão exclusiva no D-Bus de sessão (ex.: portal GlobalShortcuts, F2-01)."""
    return open_router(timeout=timeout)


def close_router(router: "DBusRouter") -> None:
    """Fecha o roteador e a conexão por baixo dele. Não levanta."""
    try:
        router.close()
    except Exception:
        pass
    try:
        router.conn.close()
    except Exception:
        pass


def session_router(*, timeout: float = PROBE_TIMEOUT) -> "DBusRouter":
    """Roteador compartilhado do processo (lazy; refeito se o endereço mudar)."""
    global _ROUTER, _ROUTER_ADDR
    addr = _session_address()
    with _LOCK:
        if _ROUTER is not None and _ROUTER_ADDR == addr:
            return _ROUTER
        if _ROUTER is not None:
            close_router(_ROUTER)
        _ROUTER, _ROUTER_ADDR = None, None
        _ROUTER = open_router(addr, timeout=timeout)
        _ROUTER_ADDR = addr
        return _ROUTER


def _drop_session_router(router: "DBusRouter") -> None:
    global _ROUTER, _ROUTER_ADDR
    with _LOCK:
        if _ROUTER is not router:
            return
        _ROUTER, _ROUTER_ADDR = None, None
    close_router(router)


def reset() -> None:
    """Fecha o roteador de sessão (encerramento e testes). O próximo uso reconecta."""
    global _ROUTER, _ROUTER_ADDR
    with _LOCK:
        router, _ROUTER, _ROUTER_ADDR = _ROUTER, None, None
    if router is not None:
        close_router(router)


def _send(msg: "Message", timeout: float, router: Optional["DBusRouter"]) -> Tuple[Any, ...]:
    from jeepney.io.common import RouterClosed
    from jeepney.wrappers import DBusErrorResponse, unwrap_msg

    inicio = time.monotonic()
    compartilhado = router is None
    if compartilhado:
        router = session_router(timeout=min(timeout, PROBE_TIMEOUT))
    restante = max(0.05, timeout - (time.monotonic() - inicio))
    try:
        reply = router.send_and_get_reply(msg, timeout=restante)
    except TimeoutError:
        raise
    except (RouterClosed, OSError) as e:
        if compartilhado:
            _drop_session_router(router)
        raise DBusError(f"conexão D-Bus caiu ({type(e).__name__}: {e})") from e
    try:
        return tuple(unwrap_msg(reply))
    except DBusErrorResponse as e:
        raise DBusError(str(e), name=e.name) from None


def call(
    dest: str,
    path: str,
    iface: str,
    method: str,
    signature: str = "",
    args: Sequence[Any] = (),
    timeout: float = CALL_TIMEOUT,
    *,
    router: Optional["DBusRouter"] = None,
) -> Tuple[Any, ...]:
    """Chamada de método; devolve o corpo da resposta (tupla).

    ``signature`` no formato D-Bus ("ss", "a{sv}"...); variante = (assinatura, valor).
    """
    from jeepney.wrappers import DBusAddress, new_method_call

    endereco = DBusAddress(path, bus_name=dest, interface=iface)
    msg = new_method_call(endereco, method, signature or None, tuple(args))
    return _send(msg, timeout, router)


def get_property(
    dest: str,
    path: str,
    iface: str,
    name: str,
    timeout: float = CALL_TIMEOUT,
    *,
    router: Optional["DBusRouter"] = None,
) -> Any:
    """Valor de uma propriedade (a variante já desembrulhada)."""
    (variante,) = call(dest, path, _PROPS_IFACE, "Get", "ss", (iface, name), timeout, router=router)
    return variante[1]


def name_has_owner(
    name: str, timeout: float = PROBE_TIMEOUT, *, router: Optional["DBusRouter"] = None
) -> bool:
    """Sonda barata: o nome tem dono no barramento? Qualquer falha dá False."""
    try:
        (tem,) = call(
            _BUS_NAME, _BUS_PATH, _BUS_NAME, "NameHasOwner", "s", (name,), timeout, router=router
        )
    except (DBusError, TimeoutError):
        return False
    return bool(tem)


def match_rule(
    *,
    type: str = "signal",
    sender: Optional[str] = None,
    interface: Optional[str] = None,
    member: Optional[str] = None,
    path: Optional[str] = None,
    path_namespace: Optional[str] = None,
) -> "MatchRule":
    """Regra de assinatura (jeepney.MatchRule) sem o chamador importar jeepney.

    Atenção: o filtro local do jeepney compara os campos do cabeçalho
    literalmente, e o barramento reescreve o remetente para o nome ÚNICO
    (":1.42"). ``sender`` com nome bem conhecido não casa: filtre por
    interface/member/path ou passe o nome único (GetNameOwner).
    """
    from jeepney.bus_messages import MatchRule

    return MatchRule(
        type=type,
        sender=sender,
        interface=interface,
        member=member,
        path=path,
        path_namespace=path_namespace,
    )


class SignalQueue:
    """Fila dos sinais de uma assinatura; ``get(timeout)`` devolve a Message ou None.

    Os sinais chegam pela thread receptora (daemon) do roteador. Fila cheia
    descarta o sinal novo. ``close()`` desfaz o filtro local e o AddMatch.
    """

    def __init__(self, router: "DBusRouter", rule: "MatchRule", handle):
        self._router = router
        self._rule = rule
        self._handle = handle
        self._fechada = False

    def get(self, timeout: Optional[float] = None) -> Optional["Message"]:
        try:
            return self._handle.queue.get(timeout=timeout)
        except _queue.Empty:
            return None

    def close(self) -> None:
        if self._fechada:
            return
        self._fechada = True
        try:
            self._handle.close()
        except Exception:
            pass
        try:
            from jeepney.bus_messages import message_bus

            self._router.send_and_get_reply(
                message_bus.RemoveMatch(self._rule), timeout=PROBE_TIMEOUT
            )
        except Exception:
            pass

    def __enter__(self) -> "SignalQueue":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


def subscribe(
    rule: "MatchRule",
    *,
    router: Optional["DBusRouter"] = None,
    bufsize: int = 64,
    timeout: float = CALL_TIMEOUT,
) -> SignalQueue:
    """Assina sinais. O filtro local entra ANTES do AddMatch, então nada se perde."""
    from jeepney.bus_messages import message_bus

    if router is None:
        router = session_router(timeout=min(timeout, PROBE_TIMEOUT))
    handle = router.filter(rule, queue=_queue.Queue(maxsize=bufsize))
    try:
        _send(message_bus.AddMatch(rule), timeout, router)
    except BaseException:
        handle.close()
        raise
    return SignalQueue(router, rule, handle)
