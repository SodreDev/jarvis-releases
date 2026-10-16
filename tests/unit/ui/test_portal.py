"""O atalho global pelo portal, contra um portal **falso** num barramento privado (ADR-0021).

O portal de verdade abre um diálogo na tela do dono, então ele nunca é tocado aqui: o teste
sobe um `dbus-daemon` próprio (o processo é deste teste e é encerrado pelo objeto que o abriu,
nunca por nome), publica nele um `org.freedesktop.portal.Desktop` escrito com `jeepney` e
conversa com ele como o Plasma conversaria — `CreateSession`, `BindShortcuts`, `Response` e os
sinais `Activated`/`Deactivated`.

O que isto prova: o protocolo que o cliente fala (caminhos de `Request`, ordem filtro →
chamada, variantes, sessão) e o apertar/soltar. O que não prova: o comportamento do
xdg-desktop-portal-kde de verdade — que fica como "não verificado" na ADR-0021.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.ui.atalhos import AtalhoIndisponivel, atalho_do_ambiente
from jarvis.ui.portal import (
    CAMINHO,
    ID_DO_ATALHO,
    INTERFACE,
    INTERFACE_REQUEST,
    NOME,
    AtalhoPortal,
    portal_disponivel,
)

jeepney = pytest.importorskip("jeepney")
pytestmark = pytest.mark.skipif(
    shutil.which("dbus-daemon") is None, reason="dbus-daemon não está instalado"
)


CONFIG_SEM_ATIVACAO = """<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={pasta}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""
"""Barramento **sem** `<servicedir>`: nome que ninguém publicou não é ativado.

A configuração padrão de sessão ativa serviços sob demanda — e foi assim que a primeira versão
deste teste subiu o xdg-desktop-portal-kde **de verdade** dentro do barramento privado, que
pode abrir diálogo na tela do dono. Aqui o que não existe continua não existindo."""


@pytest.fixture
def barramento(tmp_path: Path) -> Iterator[str]:
    """Um barramento só deste teste. O endereço vem da primeira linha da saída."""
    config = tmp_path / "barramento.conf"
    config.write_text(CONFIG_SEM_ATIVACAO.format(pasta=tmp_path), encoding="utf-8")
    # Sem sessão gráfica no ambiente do daemon: nada que ele faça alcança a tela do dono.
    ambiente = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": str(tmp_path)}
    processo = subprocess.Popen(
        ["dbus-daemon", f"--config-file={config}", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
        env=ambiente,
    )
    try:
        assert processo.stdout is not None
        endereco = processo.stdout.readline().strip()
        assert endereco, "o dbus-daemon não disse o endereço"
        yield endereco
    finally:
        processo.terminate()
        processo.wait(timeout=5)


@dataclass
class PortalFalso:
    """Responde como o portal responderia. `codigo_do_bind` simula o dono cancelando."""

    endereco: str
    codigo_do_bind: int = 0
    gatilho_ligado: str = "Ctrl+Espaço"
    com_global_shortcuts: bool = True
    preferido: str = ""
    sessoes_fechadas: list[str] = field(default_factory=list)
    registros: list[str] = field(default_factory=list)
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
        assert resposta.body[0] == 1, "o portal falso não ficou com o nome"
        self._thread = threading.Thread(target=self._atender, daemon=True)
        self._thread.start()

    def descer(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._conexao.close()

    # --- o que o teste aciona ---------------------------------------------------------------
    def apertar(self, *, identificador: str = ID_DO_ATALHO, sessao: str = "") -> None:
        self._sinal_do_atalho("Activated", identificador, sessao or self.sessao)

    def soltar(self) -> None:
        self._sinal_do_atalho("Deactivated", ID_DO_ATALHO, self.sessao)

    def _sinal_do_atalho(self, membro: str, identificador: str, sessao: str) -> None:
        from jeepney import DBusAddress, new_signal

        emissor = DBusAddress(CAMINHO, interface=INTERFACE)
        self._enviar(new_signal(emissor, membro, "osta{sv}", (sessao, identificador, 1, {})))

    # --- o portal ---------------------------------------------------------------------------
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
            self._atender_chamada(
                mensagem,
                campos.get(HeaderFields.interface),
                campos.get(HeaderFields.member),
                str(campos.get(HeaderFields.sender)),
            )

    def _atender_chamada(self, mensagem: Any, interface: str, membro: str, remetente: str) -> None:
        from jeepney import new_error, new_method_return

        quem = remetente.lstrip(":").replace(".", "_")
        if interface == "org.freedesktop.DBus.Properties" and membro == "Get":
            if mensagem.body[0] == INTERFACE and self.com_global_shortcuts:
                self._enviar(new_method_return(mensagem, "v", (("u", 2),)))
            else:
                self._enviar(
                    new_error(mensagem, "org.freedesktop.DBus.Error.UnknownInterface", "s", ("",))
                )
        elif membro == "Register":
            self.registros.append(mensagem.body[0])
            self._enviar(new_method_return(mensagem))
        elif membro == "CreateSession":
            token = mensagem.body[0]["handle_token"][1]
            fichinha = mensagem.body[0]["session_handle_token"][1]
            pedido = f"{CAMINHO}/request/{quem}/{token}"
            self.sessao = f"{CAMINHO}/session/{quem}/{fichinha}"
            self._enviar(new_method_return(mensagem, "o", (pedido,)))
            self._responder(pedido, 0, {"session_handle": ("s", self.sessao)})
        elif membro == "BindShortcuts":
            _sessao, atalhos, _janela, opcoes = mensagem.body
            token = opcoes["handle_token"][1]
            self.preferido = atalhos[0][1].get("preferred_trigger", ("s", ""))[1]
            pedido = f"{CAMINHO}/request/{quem}/{token}"
            self._enviar(new_method_return(mensagem, "o", (pedido,)))
            ligados = [
                (
                    ID_DO_ATALHO,
                    {
                        "description": ("s", atalhos[0][1]["description"][1]),
                        "trigger_description": ("s", self.gatilho_ligado),
                    },
                )
            ]
            self._responder(pedido, self.codigo_do_bind, {"shortcuts": ("a(sa{sv})", ligados)})
        elif membro == "Close":
            self.sessoes_fechadas.append(str(mensagem.header.fields.get(1)))
            self._enviar(new_method_return(mensagem))
        else:
            self._enviar(new_method_return(mensagem))

    def _responder(self, pedido: str, codigo: int, resultados: dict[str, Any]) -> None:
        from jeepney import DBusAddress, new_signal

        emissor = DBusAddress(pedido, interface=INTERFACE_REQUEST)
        self._enviar(new_signal(emissor, "Response", "ua{sv}", (codigo, resultados)))


@pytest.fixture
def portal(barramento: str) -> Iterator[PortalFalso]:
    falso = PortalFalso(endereco=barramento)
    falso.subir()
    try:
        yield falso
    finally:
        falso.descer()


def esperar(condicao: Any, limite: float = 3.0) -> bool:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


# --- o caminho feliz ------------------------------------------------------------------------
def test_liga_o_atalho_e_segue_apertar_e_soltar(portal: PortalFalso, barramento: str) -> None:
    mudancas: list[bool] = []
    atalho = AtalhoPortal(combinacao="Ctrl+Space", endereco=barramento, ao_mudar=mudancas.append)
    atalho.abrir()
    try:
        assert atalho.gatilho == "Ctrl+Espaço", "a tela tem de mostrar o que o sistema ligou"
        assert portal.preferido == "CTRL+space", "a preferência vai na grafia da spec"
        assert portal.registros == ["dev.sodredev.Jarvis"] and atalho.registrado
        assert not atalho.pressionado()

        portal.apertar()
        assert esperar(atalho.pressionado)
        portal.soltar()
        assert esperar(lambda: not atalho.pressionado())
        assert mudancas == [True, False]
    finally:
        atalho.fechar()
    assert portal.sessoes_fechadas, "fechar não encerrou a sessão do portal"


def test_sinal_de_outra_sessao_ou_outro_atalho_e_ignorado(
    portal: PortalFalso, barramento: str
) -> None:
    atalho = AtalhoPortal(endereco=barramento)
    atalho.abrir()
    try:
        portal.apertar(identificador="outro")
        portal.apertar(sessao=f"{CAMINHO}/session/alguem/x")
        assert not esperar(atalho.pressionado, limite=0.5)
    finally:
        atalho.fechar()


# --- as recusas -----------------------------------------------------------------------------
def test_dono_cancelou_o_dialogo_vira_frase(portal: PortalFalso, barramento: str) -> None:
    portal.codigo_do_bind = 1
    with pytest.raises(AtalhoIndisponivel, match="você cancelou"):
        AtalhoPortal(endereco=barramento).abrir()


def test_sem_global_shortcuts_vira_frase(portal: PortalFalso, barramento: str) -> None:
    portal.com_global_shortcuts = False
    with pytest.raises(AtalhoIndisponivel, match="não tem o portal"):
        AtalhoPortal(endereco=barramento).abrir()
    disponivel, frase = portal_disponivel(barramento)
    assert not disponivel and "não tem o portal" in frase


def test_sem_portal_nenhum_no_barramento(barramento: str) -> None:
    with pytest.raises(AtalhoIndisponivel, match="não tem o portal"):
        AtalhoPortal(endereco=barramento).abrir()


def test_portal_disponivel_so_le_a_versao(portal: PortalFalso, barramento: str) -> None:
    disponivel, frase = portal_disponivel(barramento)
    assert disponivel and "versão 2" in frase
    assert portal.sessao == "", "consultar não pode abrir sessão"


def test_sob_ci_o_portal_do_sistema_nao_e_tocado() -> None:
    # O conftest liga CI=1: nenhum teste abre diálogo na tela de ninguém.
    with pytest.raises(AtalhoIndisponivel, match="sob CI"):
        AtalhoPortal().abrir()
    assert portal_disponivel() == (False, "sob CI o portal do sistema não é consultado")


def test_o_backend_portal_do_ambiente_e_o_de_verdade() -> None:
    atalho = atalho_do_ambiente(ambiente={"JARVIS_HOTKEYS_BACKEND": "portal"})
    assert isinstance(atalho, AtalhoPortal)
