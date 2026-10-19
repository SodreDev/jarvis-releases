"""Entrada virtual pelo portal `org.freedesktop.portal.RemoteDesktop` — o caminho padrão no Wayland.

**Por que o portal.** No Wayland um aplicativo não injeta evento de entrada: quem pode é o
compositor, e a porta padronizada para pedir é o `RemoteDesktop` do xdg-desktop-portal. O
`Start` mostra um **diálogo ao dono** (o compositor pergunta o que pode ser controlado) e a
sessão é revogável; fechar a sessão devolve tudo. É o consentimento que a ADR-0027 pede. No
Plasma o backend é o `xdg-desktop-portal-kde`, que implementa `NotifyPointerMotion`,
`NotifyPointerButton` e `NotifyKeyboardKeysym` e **só existe em sessão Wayland** — em X11 ele
recusa, e o Jarvis cai para a reserva (`uinput`), se o dono a ligou.

Fontes (acesso em 2026-10-18): documentação do portal
(<https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html>)
e `remotedesktop.cpp` do xdg-desktop-portal-kde.

**Por que `jeepney`.** Já é do produto (MIT, ADR-0021): nenhuma biblioteca nova.

**Teclas por keysym.** O portal recebe o *keysym*, não a posição da tecla: digitar "ç" ou "é" não
depende do layout. **Mouse relativo:** `NotifyPointerMotionAbsolute` exige um stream de captura de
tela (ScreenCast), que esta fatia não abre; por isso `mover` é relativo.

Nada aqui roda sozinho nem sob CI: abrir a sessão **abre um diálogo na tela do dono**.
"""

from __future__ import annotations

import contextlib
import queue
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

from jarvis.ambiente import em_ci
from jarvis.entrada import teclas
from jarvis.entrada.porta import BOTOES, EntradaIndisponivel

NOME: Final = "org.freedesktop.portal.Desktop"
CAMINHO: Final = "/org/freedesktop/portal/desktop"
INTERFACE: Final = "org.freedesktop.portal.RemoteDesktop"
INTERFACE_REQUEST: Final = "org.freedesktop.portal.Request"
INTERFACE_SESSAO: Final = "org.freedesktop.portal.Session"
TECLADO: Final = 1
PONTEIRO: Final = 2
PRAZO_DA_CHAMADA_S: Final = 5.0
PRAZO_DO_DIALOGO_S: Final = 120.0
PASSO_DO_PONTEIRO: Final = 100
PAUSA_ENTRE_EVENTOS_S: Final = 0.008
BOTAO_DO_KERNEL: Final[dict[str, int]] = {"esquerdo": 0x110, "direito": 0x111, "meio": 0x112}
RESPOSTAS: Final[dict[int, str]] = {
    1: "você cancelou o diálogo do sistema",
    2: "o sistema recusou o controle remoto de entrada",
}


def _token() -> str:
    return f"jarvis_{secrets.token_hex(4)}"


def _remetente(nome_unico: str) -> str:
    return nome_unico.lstrip(":").replace(".", "_")


def _numero(valor: Any) -> int:
    if isinstance(valor, tuple) and len(valor) == 2:
        valor = valor[1]
    return int(valor)


class EntradaPorPortal:
    nome = "portal"

    def __init__(
        self,
        *,
        endereco: str = "SESSION",
        ambiente: Mapping[str, str] | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._endereco = endereco
        self._ambiente = ambiente
        self._dormir = dormir
        self._trava = threading.RLock()
        self._conexao: Any = None
        self._roteador: Any = None
        self._sessao = ""
        self.dispositivos = 0
        """O que o dono deixou controlar no diálogo (bits: 1 teclado, 2 ponteiro)."""

    # --- sessão ---------------------------------------------------------------------------
    def abrir(self) -> None:
        """Cria a sessão e espera o dono no diálogo. Idempotente."""
        with self._trava:
            if self._sessao:
                return
            if self._endereco == "SESSION" and em_ci(self._ambiente):
                raise EntradaIndisponivel(
                    "sob CI o portal do sistema não é tocado: ele abriria um diálogo na tela"
                )
            try:
                from jeepney.io.threading import DBusRouter, open_dbus_connection
            except ImportError:  # pragma: no cover — jeepney vem com o produto no Linux
                raise EntradaIndisponivel("jeepney não está instalado") from None
            try:
                self._conexao = open_dbus_connection(self._endereco)
            except Exception as erro:
                raise EntradaIndisponivel(f"sem barramento de sessão D-Bus: {erro}") from None
            self._roteador = DBusRouter(self._conexao)
            try:
                self._conferir_portal()
                self._sessao = self._criar_sessao()
                self._escolher_dispositivos()
                self.dispositivos = self._iniciar()
            except EntradaIndisponivel:
                self.fechar()
                raise
            except Exception as erro:
                self.fechar()
                raise EntradaIndisponivel(f"o portal de entrada falhou: {erro}") from None

    def fechar(self) -> None:
        with self._trava:
            if self._roteador is not None and self._sessao:
                from jeepney import DBusAddress, new_method_call

                sessao = DBusAddress(self._sessao, bus_name=NOME, interface=INTERFACE_SESSAO)
                with contextlib.suppress(Exception):  # melhor-esforço: morre com a conexão
                    self._roteador.send_and_get_reply(
                        new_method_call(sessao, "Close"), timeout=PRAZO_DA_CHAMADA_S
                    )
            if self._roteador is not None:
                self._roteador.close()
                self._roteador = None
            if self._conexao is not None:
                self._conexao.close()
                self._conexao = None
            self._sessao = ""
            self.dispositivos = 0

    # --- as chamadas do portal -------------------------------------------------------------
    def _portal(self, interface: str = INTERFACE) -> Any:
        from jeepney import DBusAddress

        return DBusAddress(CAMINHO, bus_name=NOME, interface=interface)

    def _chamar(self, mensagem: Any) -> tuple[Any, ...]:
        from jeepney import DBusErrorResponse, MessageType

        resposta = self._roteador.send_and_get_reply(mensagem, timeout=PRAZO_DA_CHAMADA_S)
        if resposta.header.message_type is MessageType.error:
            raise DBusErrorResponse(resposta)
        return tuple(resposta.body)

    def _conferir_portal(self) -> None:
        from jeepney import DBusErrorResponse, Properties

        try:
            (versao,) = self._chamar(Properties(self._portal()).get("version"))
        except DBusErrorResponse as erro:
            raise EntradaIndisponivel(
                f"esta sessão não tem o portal de controle remoto ({erro.name})"
            ) from None
        if _numero(versao) < 1:
            raise EntradaIndisponivel(f"portal RemoteDesktop em versão {versao} desconhecida")

    def _pedir(
        self, metodo: str, assinatura: str, corpo: tuple[Any, ...], token: str, prazo: float
    ) -> dict[str, Any]:
        """Chama o que responde por `Request` e espera o `Response` — filtro registrado antes."""
        from jeepney import MatchRule, message_bus, new_method_call
        from jeepney.io.threading import Proxy

        caminho = f"{CAMINHO}/request/{_remetente(self._conexao.unique_name)}/{token}"
        regra = MatchRule(
            type="signal", interface=INTERFACE_REQUEST, member="Response", path=caminho
        )
        Proxy(message_bus, self._roteador, timeout=PRAZO_DA_CHAMADA_S).AddMatch(regra)
        with self._roteador.filter(regra) as fila:
            self._chamar(new_method_call(self._portal(), metodo, assinatura, corpo))
            try:
                sinal = fila.get(timeout=prazo)
            except queue.Empty:
                raise EntradaIndisponivel(
                    f"o portal não respondeu a {metodo} em {prazo:.0f} s"
                ) from None
        codigo, resultados = sinal.body
        if codigo != 0:
            raise EntradaIndisponivel(RESPOSTAS.get(int(codigo), f"{metodo} respondeu {codigo}"))
        return dict(resultados)

    def _criar_sessao(self) -> str:
        token = _token()
        resultados = self._pedir(
            "CreateSession",
            "a{sv}",
            ({"handle_token": ("s", token), "session_handle_token": ("s", _token())},),
            token,
            PRAZO_DA_CHAMADA_S,
        )
        sessao = resultados.get("session_handle", "")
        sessao = sessao[1] if isinstance(sessao, tuple) else sessao
        if not sessao:
            raise EntradaIndisponivel("o portal criou a sessão sem dizer qual")
        return str(sessao)

    def _escolher_dispositivos(self) -> None:
        token = _token()
        # `persist_mode` fica em 0 (o padrão): cada execução do Jarvis pede o consentimento de novo.
        self._pedir(
            "SelectDevices",
            "oa{sv}",
            (self._sessao, {"handle_token": ("s", token), "types": ("u", TECLADO | PONTEIRO)}),
            token,
            PRAZO_DA_CHAMADA_S,
        )

    def _iniciar(self) -> int:
        token = _token()
        resultados = self._pedir(
            "Start",
            "osa{sv}",
            (self._sessao, "", {"handle_token": ("s", token)}),
            token,
            PRAZO_DO_DIALOGO_S,
        )
        dispositivos = _numero(resultados.get("devices", ("u", 0)))
        if not dispositivos & (TECLADO | PONTEIRO):
            raise EntradaIndisponivel("você não liberou teclado nem mouse no diálogo do sistema")
        return dispositivos

    def _notificar(self, metodo: str, assinatura: str, *corpo: Any) -> None:
        from jeepney import DBusErrorResponse, new_method_call

        if not self._sessao:
            raise EntradaIndisponivel("a sessão de entrada não está aberta")
        try:
            self._chamar(
                new_method_call(self._portal(), metodo, assinatura, (self._sessao, {}, *corpo))
            )
        except DBusErrorResponse as erro:
            self.fechar()  # sessão revogada pelo dono ou pelo sistema: a próxima ação reabre
            raise EntradaIndisponivel(f"o sistema recusou o evento ({erro.name})") from None

    # --- BackendDeEntrada ---------------------------------------------------------------------
    def _precisa(self, bit: int, nome: str) -> None:
        self.abrir()
        if not self.dispositivos & bit:
            raise EntradaIndisponivel(f"você não liberou o {nome} no diálogo do sistema")

    def mover(self, dx: int, dy: int) -> None:
        with self._trava:
            self._precisa(PONTEIRO, "mouse")
            passos = max(1, -(-max(abs(dx), abs(dy)) // PASSO_DO_PONTEIRO))
            for i in range(passos):
                parte_x = dx * (i + 1) // passos - dx * i // passos
                parte_y = dy * (i + 1) // passos - dy * i // passos
                self._notificar("NotifyPointerMotion", "oa{sv}dd", float(parte_x), float(parte_y))
                self._dormir(PAUSA_ENTRE_EVENTOS_S)

    def clicar(self, botao: str, vezes: int) -> None:
        if botao not in BOTOES:
            raise ValueError(f"botão {botao!r} desconhecido")
        codigo = BOTAO_DO_KERNEL[botao]
        with self._trava:
            self._precisa(PONTEIRO, "mouse")
            for _ in range(vezes):
                self._notificar("NotifyPointerButton", "oa{sv}iu", codigo, 1)
                self._dormir(PAUSA_ENTRE_EVENTOS_S)
                self._notificar("NotifyPointerButton", "oa{sv}iu", codigo, 0)
                self._dormir(PAUSA_ENTRE_EVENTOS_S * 4)

    def _tecla(self, keysym: int) -> None:
        self._notificar("NotifyKeyboardKeysym", "oa{sv}iu", keysym, 1)
        self._dormir(PAUSA_ENTRE_EVENTOS_S)
        self._notificar("NotifyKeyboardKeysym", "oa{sv}iu", keysym, 0)
        self._dormir(PAUSA_ENTRE_EVENTOS_S)

    def digitar(self, texto: str) -> None:
        with self._trava:
            self._precisa(TECLADO, "teclado")
            for c in teclas.validar_texto(texto):
                self._tecla(teclas.keysym_do_caractere(c))

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None:
        with self._trava:
            self._precisa(TECLADO, "teclado")
            apertados: list[int] = []
            try:
                for m in modificadores:
                    simbolo = teclas.KEYSYM_DO_MODIFICADOR[m]
                    self._notificar("NotifyKeyboardKeysym", "oa{sv}iu", simbolo, 1)
                    apertados.append(simbolo)
                self._tecla(teclas.keysym_da_tecla(tecla))
            finally:  # nunca deixa modificador preso, nem se a tecla falhar
                for simbolo in reversed(apertados):
                    with contextlib.suppress(EntradaIndisponivel):
                        self._notificar("NotifyKeyboardKeysym", "oa{sv}iu", simbolo, 0)
