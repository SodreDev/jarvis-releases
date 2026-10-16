"""Atalho **global** de segurar-para-falar pelo portal `GlobalShortcuts` (ADR-0021).

**Por que o portal.** No Wayland um aplicativo não lê o teclado de ninguém: quem decide que uma
combinação é global é o compositor, e a porta para pedir isso é o
`org.freedesktop.portal.GlobalShortcuts` do xdg-desktop-portal. Nesta máquina ele existe na
versão 2 (Plasma, xdg-desktop-portal-kde). `Activated` e `Deactivated` são **apertar e
soltar** — exatamente o que segurar-para-falar precisa, sem `ydotool` e sem ler `/dev/input`.

**Por que `jeepney`.** Cliente D-Bus em Python puro, MIT, que já vem no produto por baixo do
`keyring` → `SecretStorage` e já está registrado em `licenses/bibliotecas-distribuidas.toml`.
Nenhuma biblioteca nova, nenhuma obrigação nova de distribuição.

**O que este módulo não faz por conta própria.** `BindShortcuts` abre um diálogo **na tela do
dono** (o compositor pergunta se ele aceita a combinação, ou qual quer). Por isso:

- nada aqui roda sozinho: quem chama `abrir` é o clique dele em "usar como atalho global";
- sob CI, `abrir` no barramento de sessão real **recusa** — nenhum teste, nem um futuro, abre
  diálogo na tela de alguém. Os testes usam um portal falso num barramento privado;
- sem portal (outra área de trabalho, sessão sem D-Bus), a recusa vira frase e a tela diz que
  o atalho vale **só com a janela em foco**.

O fluxo do portal: `CreateSession` → `BindShortcuts` → sinais. Cada chamada responde com o
caminho de um `Request`, e o resultado chega pelo sinal `Response` desse caminho — por isso o
filtro do sinal é registrado **antes** da chamada, senão uma resposta rápida se perderia.
"""

from __future__ import annotations

import contextlib
import queue
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.ambiente import em_ci
from jarvis.ui.atalhos import AtalhoIndisponivel
from jarvis.voz.escuta import gatilho_do_portal

NOME: Final = "org.freedesktop.portal.Desktop"
CAMINHO: Final = "/org/freedesktop/portal/desktop"
INTERFACE: Final = "org.freedesktop.portal.GlobalShortcuts"
INTERFACE_REQUEST: Final = "org.freedesktop.portal.Request"
INTERFACE_SESSAO: Final = "org.freedesktop.portal.Session"
INTERFACE_REGISTRO: Final = "org.freedesktop.host.portal.Registry"
ID_DO_APLICATIVO: Final = "dev.sodredev.Jarvis"
"""O mesmo id do `.desktop` dos pacotes (ADR-0020). Rodando da árvore, sem o `.desktop`
instalado, o registro pode ser recusado — e o portal segue com id vazio."""
ID_DO_ATALHO: Final = "falar"
DESCRICAO: Final = "Jarvis: segurar para falar"
PRAZO_DA_CHAMADA_S: Final = 5.0
PRAZO_DO_DIALOGO_S: Final = 120.0
"""O `BindShortcuts` espera o dono responder ao diálogo do compositor."""
RESPOSTAS: Final[dict[int, str]] = {
    1: "você cancelou o diálogo do sistema",
    2: "o sistema recusou o pedido de atalho",
}


def _token() -> str:
    return f"jarvis_{secrets.token_hex(4)}"


def _remetente(nome_unico: str) -> str:
    """`:1.42` → `1_42`, a forma que o portal usa nos caminhos de `Request` e `Session`."""
    return nome_unico.lstrip(":").replace(".", "_")


def _texto(valor: Any) -> str:
    """O valor de uma variante `(assinatura, valor)` como o jeepney entrega."""
    if isinstance(valor, tuple) and len(valor) == 2:
        return str(valor[1])
    return str(valor)


@dataclass(slots=True)
class AtalhoPortal:
    """`BackendDeAtalho` de verdade: o compositor avisa quando a combinação aperta e solta."""

    combinacao: str = "Ctrl+Space"
    """Na grafia do Qt. Vai para o portal como **preferência**: quem decide é o compositor,
    e o dono pode trocar no diálogo — o que valeu volta em `gatilho`."""
    endereco: str = "SESSION"
    """`SESSION` (o barramento do dono) ou o endereço de um barramento privado (teste)."""
    ambiente: Mapping[str, str] | None = None
    ao_mudar: Callable[[bool], None] | None = None
    """Chamada a cada apertar (`True`) e soltar (`False`), **da thread do portal**."""
    nome: str = "portal"
    gatilho: str = ""
    """O que o compositor diz que ficou valendo (`trigger_description`), para a tela."""
    registrado: bool = False
    """Se o id do aplicativo foi aceito pelo `Registry` do portal."""
    _apertado: bool = field(default=False, repr=False)
    _conexao: Any = field(default=None, repr=False)
    _roteador: Any = field(default=None, repr=False)
    _sessao: str = field(default="", repr=False)
    _filtro: Any = field(default=None, repr=False)
    _fila: queue.Queue[Any] = field(default_factory=lambda: queue.Queue(maxsize=256), repr=False)
    _parar: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    # --- BackendDeAtalho ------------------------------------------------------------------
    def abrir(self) -> None:
        if self.endereco == "SESSION" and em_ci(self.ambiente):
            raise AtalhoIndisponivel(
                "sob CI o portal do sistema não é tocado: ele abriria um diálogo na tela"
            )
        try:
            from jeepney.io.threading import DBusRouter, open_dbus_connection
        except ImportError:  # pragma: no cover — jeepney vem com o grupo `gui`
            raise AtalhoIndisponivel("jeepney não está instalado (grupo `gui`)") from None
        try:
            self._conexao = open_dbus_connection(self.endereco)
        except Exception as erro:
            raise AtalhoIndisponivel(f"sem barramento de sessão D-Bus: {erro}") from None
        self._roteador = DBusRouter(self._conexao)
        try:
            self._conferir_portal()
            self._registrar()
            self._sessao = self._criar_sessao()
            self.gatilho = self._ligar_atalho()
            self._escutar()
        except AtalhoIndisponivel:
            self.fechar()
            raise
        except Exception as erro:
            self.fechar()
            raise AtalhoIndisponivel(f"o portal de atalhos falhou: {erro}") from None

    def pressionado(self) -> bool:
        return self._apertado

    def fechar(self) -> None:
        self._parar.set()
        if self._roteador is not None and self._sessao:
            from jeepney import DBusAddress, new_method_call

            sessao = DBusAddress(self._sessao, bus_name=NOME, interface=INTERFACE_SESSAO)
            # Fechar é melhor-esforço: a sessão do portal morre com a conexão de qualquer jeito.
            with contextlib.suppress(Exception):
                self._roteador.send_and_get_reply(
                    new_method_call(sessao, "Close"), timeout=PRAZO_DA_CHAMADA_S
                )
        if self._filtro is not None:
            self._filtro.close()
            self._filtro = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._roteador is not None:
            self._roteador.close()
            self._roteador = None
        if self._conexao is not None:
            self._conexao.close()
            self._conexao = None
        self._sessao = ""
        self._mudar(apertado=False)

    # --- as etapas ------------------------------------------------------------------------
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
            raise AtalhoIndisponivel(
                f"esta sessão não tem o portal de atalhos globais ({erro.name})"
            ) from None
        if int(_texto(versao)) < 1:
            raise AtalhoIndisponivel(f"portal de atalhos em versão {versao} desconhecida")

    def _registrar(self) -> None:
        """Diz ao portal quem somos. Recusado (sem `.desktop` instalado) não é fatal."""
        from jeepney import DBusErrorResponse, new_method_call

        try:
            self._chamar(
                new_method_call(
                    self._portal(INTERFACE_REGISTRO),
                    "Register",
                    "sa{sv}",
                    (ID_DO_APLICATIVO, {}),
                )
            )
        except DBusErrorResponse:
            self.registrado = False
        else:
            self.registrado = True

    def _pedir(
        self, metodo: str, assinatura: str, corpo: tuple[Any, ...], token: str, prazo: float
    ) -> dict[str, Any]:
        """Chama um método que responde por `Request` e espera o `Response` dele."""
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
                raise AtalhoIndisponivel(
                    f"o portal não respondeu a {metodo} em {prazo:.0f} s"
                ) from None
        codigo, resultados = sinal.body
        if codigo != 0:
            raise AtalhoIndisponivel(RESPOSTAS.get(int(codigo), f"{metodo} respondeu {codigo}"))
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
        sessao = _texto(resultados.get("session_handle", ""))
        if not sessao:
            raise AtalhoIndisponivel("o portal criou a sessão sem dizer qual")
        return sessao

    def _ligar_atalho(self) -> str:
        token = _token()
        dados: dict[str, Any] = {"description": ("s", DESCRICAO)}
        preferido = gatilho_do_portal(self.combinacao)
        if preferido:
            dados["preferred_trigger"] = ("s", preferido)
        resultados = self._pedir(
            "BindShortcuts",
            "oa(sa{sv})sa{sv}",
            (self._sessao, [(ID_DO_ATALHO, dados)], "", {"handle_token": ("s", token)}),
            token,
            PRAZO_DO_DIALOGO_S,
        )
        ligados = resultados.get("shortcuts", ("", []))[1]
        for identificador, propriedades in ligados:
            if identificador == ID_DO_ATALHO:
                return _texto(propriedades.get("trigger_description", "")) or self.combinacao
        raise AtalhoIndisponivel("o sistema não ligou o atalho (nenhuma combinação aceita)")

    def _escutar(self) -> None:
        from jeepney import MatchRule, message_bus
        from jeepney.io.threading import Proxy

        regra = MatchRule(type="signal", interface=INTERFACE, path=CAMINHO)
        Proxy(message_bus, self._roteador, timeout=PRAZO_DA_CHAMADA_S).AddMatch(regra)
        self._filtro = self._roteador.filter(regra, queue=self._fila)
        self._parar.clear()
        self._thread = threading.Thread(target=self._receber, name="jarvis-portal", daemon=True)
        self._thread.start()

    def _receber(self) -> None:
        while not self._parar.is_set():
            try:
                sinal = self._fila.get(timeout=0.2)
            except queue.Empty:
                continue
            membro = sinal.header.fields.get(_campo_membro())
            if membro not in {"Activated", "Deactivated"}:
                continue
            sessao, identificador = sinal.body[0], sinal.body[1]
            if sessao == self._sessao and identificador == ID_DO_ATALHO:
                self._mudar(apertado=membro == "Activated")

    def _mudar(self, *, apertado: bool) -> None:
        if apertado == self._apertado:
            return
        self._apertado = apertado
        if self.ao_mudar is not None:
            self.ao_mudar(apertado)


def _campo_membro() -> Any:
    from jeepney import HeaderFields

    return HeaderFields.member


def portal_disponivel(
    endereco: str = "SESSION", ambiente: Mapping[str, str] | None = None
) -> tuple[bool, str]:
    """Só **lê** se o portal existe (propriedade `version`): não abre sessão, não abre diálogo.

    É o que a tela pergunta antes de oferecer o botão de atalho global.
    """
    if endereco == "SESSION" and em_ci(ambiente):
        return False, "sob CI o portal do sistema não é consultado"
    try:
        from jeepney import DBusErrorResponse, Properties
        from jeepney.io.blocking import open_dbus_connection
    except ImportError:  # pragma: no cover
        return False, "jeepney não está instalado"
    try:
        conexao = open_dbus_connection(endereco)
    except Exception as erro:
        return False, f"sem barramento de sessão D-Bus: {erro}"
    try:
        endereco_portal = AtalhoPortal()._portal()
        resposta = conexao.send_and_get_reply(
            Properties(endereco_portal).get("version"), timeout=PRAZO_DA_CHAMADA_S
        )
        from jeepney import MessageType

        if resposta.header.message_type is MessageType.error:
            raise DBusErrorResponse(resposta)
        versao = _texto(resposta.body[0])
    except Exception as erro:
        return False, f"esta sessão não tem o portal de atalhos globais ({erro})"
    finally:
        conexao.close()
    return True, f"portal de atalhos globais disponível (versão {versao})"
