"""PTT global no Wayland pelo portal ``org.freedesktop.portal.GlobalShortcuts`` (F2-01).

- Sonda: ``org.freedesktop.portal.Desktop`` tem dono e a propriedade ``version`` de
  GlobalShortcuts é ≥ 1.
- Conexão D-Bus DEDICADA. Nela, ``org.freedesktop.host.portal.Registry.Register(app_id,
  {})`` vem antes de qualquer outra chamada de portal (o app_id casa com o .desktop,
  que ``ensure_desktop_entry`` grava no primeiro ``ensure_session``, nunca no __init__).
- Cada pedido assina o ``Response`` no caminho de request PREVISTO
  (``/org/freedesktop/portal/desktop/request/<remetente>/<token>``) ANTES da chamada.
  ``CreateSession`` traz ``session_handle`` no Response; ``BindShortcuts`` espera até
  120 s (o KDE mostra um diálogo). Resposta 0 = ok; 1 = usuário recusou →
  ``CapabilityUnavailable`` e o pedido não se repete neste processo; 2 ou falha → o
  próximo da cadeia (KGlobalAccel), se existir.
- ``Activated``/``Deactivated`` ``(o sessão, s id, t ts, a{sv})`` só da sessão criada
  viram ``on_press``/``on_release`` do atalho.
- ``stop()`` chama ``Close`` na ``org.freedesktop.portal.Session``. ``listen_keys`` → False.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, List, Optional, Sequence, Tuple

from ..capabilities import Cap
from ..common.base import BackendBase, Probe
from ..errors import CapabilityUnavailable
from ..linux import dbus as _dbus
from ..linux.app_id import APP_ID

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
IFACE_GLOBAL_SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"
IFACE_REQUEST = "org.freedesktop.portal.Request"
IFACE_SESSION = "org.freedesktop.portal.Session"
IFACE_REGISTRY = "org.freedesktop.host.portal.Registry"

SESSION_TIMEOUT = 30.0
BIND_TIMEOUT = 120.0

_MODIFICADORES_PORTAL = {
    "shift": "SHIFT", "ctrl": "CTRL", "control": "CTRL", "alt": "ALT",
    "cmd": "LOGO", "super": "LOGO", "meta": "LOGO",
}


def convert_trigger_to_portal(trigger: str) -> str:
    """Gatilho pynput ("<cmd>+<shift>+g") → formato do portal ("LOGO+SHIFT+g")."""
    partes = []
    for bruto in trigger.split("+"):
        parte = bruto.strip()
        nome = parte[1:-1] if parte.startswith("<") and parte.endswith(">") else parte
        partes.append(_MODIFICADORES_PORTAL.get(nome.lower(), nome))
    return "+".join(partes)


def _variante(valor):
    if isinstance(valor, tuple) and len(valor) == 2 and isinstance(valor[0], str):
        return valor[1]
    return valor


def _token() -> str:
    return "jarvis_" + uuid.uuid4().hex[:12]


class PortalGlobalShortcuts(BackendBase):
    def __init__(self, ctx=None, *, app_id: str = APP_ID):
        self.ctx = ctx
        self._app_id = app_id
        self._lock = threading.RLock()
        self._router = None
        self._session: Optional[str] = None
        self._recusado = False
        self._desktop_garantido = False
        self._handlers: Dict[str, Tuple] = {}
        self._filas_sinais: List = []
        self._despachante = None
        self._parar = threading.Event()
        self._fallback = None

    @property
    def name(self) -> str:
        return self._fallback.name if self._fallback is not None else "portal"

    @classmethod
    def probe(cls, ctx) -> Probe:
        if not _dbus.name_has_owner(PORTAL_BUS):
            return Probe(False, f"{PORTAL_BUS} sem dono no D-Bus de sessão")
        try:
            versao = int(_dbus.get_property(PORTAL_BUS, PORTAL_PATH, IFACE_GLOBAL_SHORTCUTS, "version",
                                            _dbus.PROBE_TIMEOUT))
        except Exception as e:
            return Probe(False, f"GlobalShortcuts indisponível no portal ({type(e).__name__})")
        if versao < 1:
            return Probe(False, f"GlobalShortcuts versão {versao}")
        return Probe(True)

    def listen_keys(self, on_press, on_release) -> bool:
        return False

    # ── sessão ─────────────────────────────────────────────────────────────────
    def _indisponivel(self, motivo: str) -> CapabilityUnavailable:
        return CapabilityUnavailable(Cap.HOTKEYS, [(IFACE_GLOBAL_SHORTCUTS, motivo)])

    def _conectar(self) -> None:
        if self._router is not None:
            return
        self._router = _dbus.open_dedicated_router()
        try:
            _dbus.call(PORTAL_BUS, PORTAL_PATH, IFACE_REGISTRY, "Register", "sa{sv}", (self._app_id, {}),
                       _dbus.CALL_TIMEOUT, router=self._router)
        except _dbus.DBusError as e:
            # portal sem Registry ou app já identificado pela conexão: segue sem ele
            print(f"[HOTKEYS] portal: Registry.Register não aplicado ({e.name or e})")

    def _remetente(self) -> str:
        return self._router.unique_name.lstrip(":").replace(".", "_")

    def _pedir(self, metodo: str, assinatura: str, args: tuple, opcoes: dict, timeout: float):
        token = _token()
        previsto = f"{PORTAL_PATH}/request/{self._remetente()}/{token}"
        opcoes = dict(opcoes)
        opcoes["handle_token"] = ("s", token)
        filas = [_dbus.subscribe(_dbus.match_rule(interface=IFACE_REQUEST, member="Response", path=previsto),
                                 router=self._router)]
        try:
            (handle,) = _dbus.call(PORTAL_BUS, PORTAL_PATH, IFACE_GLOBAL_SHORTCUTS, metodo, assinatura,
                                   (*args, opcoes), _dbus.CALL_TIMEOUT, router=self._router)
            if str(handle) != previsto:  # portal antigo: request em outro caminho
                filas.append(_dbus.subscribe(
                    _dbus.match_rule(interface=IFACE_REQUEST, member="Response", path=str(handle)),
                    router=self._router))
            fim = time.monotonic() + timeout
            while time.monotonic() < fim:
                for fila in filas:
                    msg = fila.get(timeout=0.1)
                    if msg is not None:
                        codigo, resultados = msg.body
                        return int(codigo), {k: _variante(v) for k, v in resultados.items()}
            raise TimeoutError(f"portal: sem Response de {metodo} em {timeout:.0f} s")
        finally:
            for fila in filas:
                fila.close()

    def _garantir_desktop_entry(self) -> None:
        if not self._desktop_garantido:
            self._desktop_garantido = True
            from ..linux.desktop_entry import ensure_desktop_entry

            ensure_desktop_entry(self._app_id)

    def ensure_session(self) -> str:
        """Cria (uma vez) a sessão GlobalShortcuts; devolve o session_handle."""
        with self._lock:
            if self._session is not None:
                return self._session
            if self._recusado:
                raise self._indisponivel("usuário recusou")
            self._garantir_desktop_entry()
            self._conectar()
            codigo, resultados = self._pedir("CreateSession", "a{sv}", (),
                                             {"session_handle_token": ("s", _token())}, SESSION_TIMEOUT)
            if codigo == 1:
                self._recusado = True
                raise self._indisponivel("usuário recusou")
            if codigo != 0 or not resultados.get("session_handle"):
                raise _dbus.DBusError(f"portal: CreateSession respondeu {codigo}")
            self._session = str(resultados["session_handle"])
            self._assinar_ativacoes()
            return self._session

    # ── atalhos ────────────────────────────────────────────────────────────────
    def bind(self, bindings: Sequence) -> Dict[str, str]:
        with self._lock:
            if self._fallback is not None:
                return self._fallback.bind(bindings)
            if self._recusado:
                raise self._indisponivel("usuário recusou")
            for b in bindings:
                self._handlers[b.id] = (b.on_press, b.on_release)
            try:
                sessao = self.ensure_session()
                atalhos = [
                    (b.id, {"description": ("s", b.description),
                            "preferred_trigger": ("s", convert_trigger_to_portal(b.trigger))})
                    for b in bindings
                ]
                codigo, resultados = self._pedir("BindShortcuts", "oa(sa{sv})sa{sv}", (sessao, atalhos, ""),
                                                 {}, BIND_TIMEOUT)
            except CapabilityUnavailable:
                raise
            except Exception as e:
                return self._cair_para_kglobalaccel(bindings, f"{type(e).__name__}: {e}")
            if codigo == 0:
                efetivos = {b.id: convert_trigger_to_portal(b.trigger) for b in bindings}
                for atalho_id, props in resultados.get("shortcuts") or []:
                    descricao = _variante((props or {}).get("trigger_description"))
                    if descricao:
                        efetivos[atalho_id] = str(descricao)
                return efetivos
            if codigo == 1:
                self._recusado = True
                raise self._indisponivel("usuário recusou")
            return self._cair_para_kglobalaccel(bindings, f"BindShortcuts respondeu {codigo}")

    def _cair_para_kglobalaccel(self, bindings: Sequence, motivo: str) -> Dict[str, str]:
        from ..linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

        if not KGlobalAccelHotkeys.probe(self.ctx).ok:
            raise self._indisponivel(f"{motivo}; KGlobalAccel também indisponível")
        print(f"[HOTKEYS] portal GlobalShortcuts falhou ({motivo}); usando o KGlobalAccel.")
        self._fallback = KGlobalAccelHotkeys(self.ctx)
        return self._fallback.bind(bindings)

    # ── sinais ─────────────────────────────────────────────────────────────────
    def _assinar_ativacoes(self) -> None:
        if self._despachante is not None:
            return
        self._parar.clear()
        self._filas_sinais = [
            _dbus.subscribe(_dbus.match_rule(interface=IFACE_GLOBAL_SHORTCUTS, member=membro, path=PORTAL_PATH),
                            router=self._router, bufsize=128)
            for membro in ("Activated", "Deactivated")
        ]
        self._despachante = threading.Thread(target=self._despachar, args=(list(self._filas_sinais),),
                                             daemon=True, name="PortalHotkeys-sinais")
        self._despachante.start()

    def _despachar(self, filas) -> None:
        ativado, desativado = filas
        while not self._parar.is_set():
            for pressionado, fila in ((True, ativado), (False, desativado)):
                msg = fila.get(timeout=0.1)
                if msg is None:
                    continue
                try:
                    sessao, atalho = str(msg.body[0]), msg.body[1]
                except (IndexError, TypeError):
                    continue
                if sessao != self._session:
                    continue
                par = self._handlers.get(atalho)
                callback = (par[0] if pressionado else par[1]) if par else None
                if callback is None:
                    continue
                try:
                    callback()
                except Exception as e:
                    print(f"[HOTKEYS] handler de {atalho!r} falhou: {e}")

    def stop(self) -> None:
        self._parar.set()
        if self._fallback is not None:
            self._fallback.stop()
        with self._lock:
            for fila in self._filas_sinais:
                fila.close()
            self._filas_sinais = []
            self._despachante = None
            if self._session is not None and self._router is not None:
                try:
                    _dbus.call(PORTAL_BUS, self._session, IFACE_SESSION, "Close",
                               timeout=_dbus.PROBE_TIMEOUT, router=self._router)
                except Exception:
                    pass
            self._session = None
            if self._router is not None:
                _dbus.close_router(self._router)
                self._router = None
