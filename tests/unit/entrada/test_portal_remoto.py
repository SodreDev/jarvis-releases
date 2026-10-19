"""O backend do portal `RemoteDesktop` contra um portal **falso** num barramento privado.

O portal de verdade abre um diálogo na tela do dono, então nunca é tocado: o teste sobe um
`dbus-daemon` próprio (sem ativação de serviços, ver `test_portal.py`) e publica nele um
`org.freedesktop.portal.Desktop` escrito com `jeepney`. Prova o protocolo que o cliente fala —
`CreateSession` → `SelectDevices` (teclado + ponteiro) → `Start` (o diálogo) → `Notify*` — e como
ele reage a cancelamento, a dispositivo negado e a sessão revogada. Não prova o comportamento do
xdg-desktop-portal-kde real (ver ADR-0027, «não verificado ao vivo»).
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from jarvis.entrada.porta import EntradaIndisponivel
from jarvis.entrada.portal_remoto import (
    CAMINHO,
    INTERFACE,
    INTERFACE_REQUEST,
    NOME,
    PONTEIRO,
    TECLADO,
    EntradaPorPortal,
)
from tests.unit.ui.test_portal import barramento  # noqa: F401 — fixture do dbus-daemon privado

_ABRIR_ORIGINAL = EntradaPorPortal.abrir  # antes de a trava do conftest entrar
jeepney = pytest.importorskip("jeepney")
pytestmark = pytest.mark.skipif(
    shutil.which("dbus-daemon") is None, reason="dbus-daemon não está instalado"
)


@dataclass
class PortalDeEntradaFalso:
    endereco: str
    codigo_do_start: int = 0
    dispositivos: int = TECLADO | PONTEIRO
    versao: int = 2
    revogar_apos_start: bool = False
    chamadas: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    sessoes_fechadas: int = 0
    _conexao: Any = None
    _trava: threading.Lock = field(default_factory=threading.Lock)
    _parar: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    sessao: str = ""

    def subir(self) -> None:
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection

        self._conexao = open_dbus_connection(self.endereco)
        resposta = self._conexao.send_and_get_reply(message_bus.RequestName(NOME), timeout=5)
        assert resposta.body[0] == 1
        self._thread = threading.Thread(target=self._atender, daemon=True)
        self._thread.start()

    def descer(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._conexao.close()

    def _enviar(self, mensagem: Any) -> None:
        with self._trava:
            self._conexao.send(mensagem)

    def _atender(self) -> None:
        from jeepney import HeaderFields, MessageType

        while not self._parar.is_set():
            try:
                mensagem = self._conexao.receive(timeout=0.1)
            except TimeoutError:
                continue
            except Exception:
                return
            if mensagem.header.message_type is not MessageType.method_call:
                continue
            campos = mensagem.header.fields
            self._chamada(
                mensagem,
                campos.get(HeaderFields.interface),
                campos.get(HeaderFields.member),
                str(campos.get(HeaderFields.sender)),
            )

    def _chamada(self, mensagem: Any, interface: str, membro: str, remetente: str) -> None:
        from jeepney import new_error, new_method_return

        quem = remetente.lstrip(":").replace(".", "_")
        corpo = tuple(mensagem.body)
        if interface == "org.freedesktop.DBus.Properties" and membro == "Get":
            if corpo[0] == INTERFACE:
                self._enviar(new_method_return(mensagem, "v", (("u", self.versao),)))
            else:
                self._enviar(
                    new_error(mensagem, "org.freedesktop.DBus.Error.UnknownInterface", "s", ("",))
                )
        elif membro in ("CreateSession", "SelectDevices", "Start"):
            opcoes = corpo[-1]
            token = opcoes["handle_token"][1]
            pedido = f"{CAMINHO}/request/{quem}/{token}"
            resultados: dict[str, Any] = {}
            codigo = 0
            if membro == "CreateSession":
                self.sessao = f"{CAMINHO}/session/{quem}/{opcoes['session_handle_token'][1]}"
                resultados = {"session_handle": ("s", self.sessao)}
            elif membro == "SelectDevices":
                self.chamadas.append((membro, (corpo[0], opcoes["types"][1])))
            else:
                codigo = self.codigo_do_start
                resultados = {"devices": ("u", self.dispositivos)}
                self.chamadas.append((membro, (corpo[0], corpo[1])))
            self._enviar(new_method_return(mensagem, "o", (pedido,)))
            self._responder(pedido, codigo, resultados)
        elif membro.startswith("Notify"):
            if self.revogar_apos_start:
                self._enviar(
                    new_error(
                        mensagem, "org.freedesktop.DBus.Error.AccessDenied", "s", ("revogada",)
                    )
                )
                return
            self.chamadas.append((membro, corpo))
            self._enviar(new_method_return(mensagem))
        elif membro == "Close":
            self.sessoes_fechadas += 1
            self._enviar(new_method_return(mensagem))
        else:
            self._enviar(new_method_return(mensagem))

    def _responder(self, pedido: str, codigo: int, resultados: dict[str, Any]) -> None:
        from jeepney import DBusAddress, new_signal

        emissor = DBusAddress(pedido, interface=INTERFACE_REQUEST)
        self._enviar(new_signal(emissor, "Response", "ua{sv}", (codigo, resultados)))

    def notificacoes(self) -> list[tuple[str, tuple[Any, ...]]]:
        return [c for c in self.chamadas if c[0].startswith("Notify")]


@pytest.fixture
def portal(barramento: str) -> Iterator[PortalDeEntradaFalso]:  # noqa: F811
    falso = PortalDeEntradaFalso(endereco=barramento)
    falso.subir()
    try:
        yield falso
    finally:
        falso.descer()


def _backend(barramento: str) -> EntradaPorPortal:  # noqa: F811
    return EntradaPorPortal(endereco=barramento, dormir=lambda _s: None)


def test_abre_a_sessao_pede_teclado_e_ponteiro_e_espera_o_dialogo(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.clicar("esquerdo", 1)
    finally:
        backend.fechar()
    nomes = [n for n, _ in portal.chamadas]
    assert nomes[:2] == ["SelectDevices", "Start"]
    assert dict(portal.chamadas)["SelectDevices"][1] == TECLADO | PONTEIRO
    assert portal.sessoes_fechadas == 1  # fechar revoga a sessão no portal


def test_clique_sai_como_apertar_e_soltar_do_botao_do_kernel(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.clicar("direito", 2)
    finally:
        backend.fechar()
    botoes = [(c[1][2], c[1][3]) for c in portal.notificacoes()]
    assert botoes == [(0x111, 1), (0x111, 0)] * 2


def test_mover_quebra_em_passos_e_soma_o_deslocamento_exato(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.mover(250, -120)
    finally:
        backend.fechar()
    passos = [c[1] for c in portal.notificacoes() if c[0] == "NotifyPointerMotion"]
    assert sum(p[2] for p in passos) == pytest.approx(250)
    assert sum(p[3] for p in passos) == pytest.approx(-120)
    assert max(abs(p[2]) for p in passos) <= 100


def test_digitar_manda_keysyms_independentes_do_layout(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.digitar("aç\n")
    finally:
        backend.fechar()
    teclas = [(c[1][2], c[1][3]) for c in portal.notificacoes()]
    assert teclas == [(0x61, 1), (0x61, 0), (0xE7, 1), (0xE7, 0), (0xFF0D, 1), (0xFF0D, 0)]


def test_atalho_aperta_modificadores_antes_e_solta_depois(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.pressionar(("ctrl", "shift"), "l")
    finally:
        backend.fechar()
    teclas = [(c[1][2], c[1][3]) for c in portal.notificacoes()]
    assert teclas == [(0xFFE3, 1), (0xFFE1, 1), (0x6C, 1), (0x6C, 0), (0xFFE1, 0), (0xFFE3, 0)]


def test_dono_cancelou_o_dialogo_vira_frase_e_nada_e_enviado(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    portal.codigo_do_start = 1
    backend = _backend(barramento)
    with pytest.raises(EntradaIndisponivel, match="cancelou o diálogo"):
        backend.mover(5, 5)
    assert portal.notificacoes() == []
    assert portal.sessoes_fechadas == 1  # não deixa sessão aberta pela metade


def test_dono_liberou_so_o_teclado_e_o_mouse_e_recusado(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    portal.dispositivos = TECLADO
    backend = _backend(barramento)
    try:
        backend.digitar("ok")
        with pytest.raises(EntradaIndisponivel, match="mouse"):
            backend.clicar("esquerdo", 1)
    finally:
        backend.fechar()


def test_dono_nao_liberou_nada_e_recusa(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    portal.dispositivos = 0
    with pytest.raises(EntradaIndisponivel, match="nem mouse"):
        _backend(barramento).digitar("x")


def test_sessao_revogada_pelo_dono_fecha_e_a_proxima_acao_reabre(
    portal: PortalDeEntradaFalso,
    barramento: str,  # noqa: F811
) -> None:
    backend = _backend(barramento)
    try:
        backend.digitar("a")
        portal.revogar_apos_start = True
        with pytest.raises(EntradaIndisponivel, match="recusou o evento"):
            backend.digitar("b")
        portal.revogar_apos_start = False
        backend.digitar("c")  # abriu outra sessão (outro diálogo, na vida real)
    finally:
        backend.fechar()
    assert [n for n, _ in portal.chamadas].count("Start") == 2


def test_sem_o_portal_de_controle_remoto_a_frase_diz_isso(barramento: str) -> None:  # noqa: F811
    with pytest.raises(EntradaIndisponivel, match="portal"):
        _backend(barramento).mover(1, 1)


def test_sob_ci_o_portal_do_sistema_nao_e_tocado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(EntradaPorPortal, "abrir", _ABRIR_ORIGINAL)  # tira a trava do conftest
    with pytest.raises(EntradaIndisponivel, match="sob CI"):
        EntradaPorPortal(ambiente={"CI": "true"}).mover(1, 1)
