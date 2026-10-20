"""O cliente do Jarvis para o host nativo: métodos tipados sobre um transporte injetável.

O transporte de verdade (`TransporteUnix`) bate no socket Unix que o host abriu; os testes põem
um falso no lugar e nenhum navegador, socket ou dispositivo do dono é tocado. Tudo o que a
extensão devolve é conteúdo de terceiro — este módulo só o repassa, truncado, e nunca o interpreta.
"""

from __future__ import annotations

import os
import socket
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from jarvis.navegador.host import PRAZO_S, pasta_dos_sockets
from jarvis.navegador.protocolo import (
    LIMITE_DA_RESPOSTA,
    LIMITE_DO_PEDIDO,
    PedidoDaPonte,
    PedidoInvalido,
    validar_pedido,
    validar_resposta,
)
from jarvis.navegador.quadro import QuadroInvalido, escrever_quadro, ler_quadro


def familia_do_host(principal: str) -> str:
    """O navegador principal do dono (`firefox`, `chrome`, `brave`…) → a família do host: `firefox`
    ou `chromium` (todo derivado do Chromium usa a mesma extensão). Vazio = qualquer um."""
    nome = principal.strip().lower()
    if not nome:
        return ""
    return "firefox" if nome.startswith(("firefox", "librewolf", "zen")) else "chromium"


class NavegadorIndisponivel(RuntimeError):
    """Não há navegador com a extensão do Jarvis aberto (ou o host não respondeu)."""


class NavegadorFalhou(RuntimeError):
    """A extensão respondeu com erro: o `codigo` é o dela (`alvo_ausente`, `campo_sensivel`…)."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(f"{codigo}: {mensagem}" if mensagem else codigo)
        self.codigo = codigo
        self.mensagem = mensagem


class Transporte(Protocol):
    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        """A resposta `{id, ok, result|error}` já validada, ou `NavegadorIndisponivel`."""
        ...


class TransporteUnix:
    """Fala com o host pelo socket Unix, um pedido por conexão."""

    def __init__(
        self,
        pasta: Path | None = None,
        *,
        uid: int | None = None,
        prazo_s: float = PRAZO_S + 5,
    ) -> None:
        self._uid = os.getuid() if uid is None else uid
        self._pasta = pasta or pasta_dos_sockets(os.environ, self._uid)
        self._prazo_s = prazo_s

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> TransporteUnix:
        """O socket em `$XDG_RUNTIME_DIR` **deste** ambiente, não do `os.environ`: o do teste é uma
        pasta temporária, e o teste nunca fala com o navegador de verdade do dono."""
        uid = os.getuid()
        return cls(pasta_dos_sockets(ambiente, uid), uid=uid)

    @property
    def pasta(self) -> Path:
        return self._pasta

    def _soquetes(self, navegador: str) -> list[Path]:
        try:
            estado = self._pasta.lstat()
        except OSError:
            return []
        if not stat.S_ISDIR(estado.st_mode) or estado.st_uid != self._uid or estado.st_mode & 0o077:
            return []  # pasta que não é só nossa: não se confia no que houver dentro
        achados: list[tuple[float, Path]] = []
        for caminho in self._pasta.glob("*.sock"):
            if navegador and not caminho.name.startswith(f"{navegador}-"):
                continue
            try:
                info = caminho.lstat()
            except OSError:
                continue
            if stat.S_ISSOCK(info.st_mode) and info.st_uid == self._uid:
                achados.append((info.st_mtime, caminho))
        return [c for _, c in sorted(achados, reverse=True)]

    def vivos(self, navegador: str = "") -> tuple[str, ...]:
        """As famílias (`chromium`, `firefox`) com host que **aceita** conexão agora.

        Conecta e solta sem mandar quadro: o host lê o fim do fluxo e fecha aquela conexão — nada
        chega à extensão nem à página. O host só existe enquanto a extensão mantém a porta do
        Native Messaging aberta (o navegador o encerra quando ela fecha), então socket que aceita
        é extensão conectada; arquivo que sobrou de host morto recusa e não conta."""
        familias: list[str] = []
        for caminho in self._soquetes(navegador):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexao:
                    conexao.settimeout(1.0)
                    conexao.connect(str(caminho))
            except OSError:
                continue
            familia = caminho.name.split("-", 1)[0]
            if familia not in familias:
                familias.append(familia)
        return tuple(familias)

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        for caminho in self._soquetes(navegador):
            try:
                return self._bater(caminho, pedido)
            except (ConnectionRefusedError, FileNotFoundError):
                continue  # host morto que deixou o arquivo: tenta o próximo
            except (OSError, QuadroInvalido, PedidoInvalido) as erro:
                raise NavegadorIndisponivel(f"o host do navegador falhou: {erro}") from None
        quem = f" ({navegador})" if navegador else ""
        raise NavegadorIndisponivel(
            f"nenhum navegador{quem} com a extensão do Jarvis está aberto; abra o navegador e "
            "confira se a extensão está instalada"
        )

    def _bater(self, caminho: Path, pedido: PedidoDaPonte) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexao:
            conexao.settimeout(self._prazo_s)
            conexao.connect(str(caminho))
            with conexao.makefile("rwb") as fluxo:
                escrever_quadro(fluxo, pedido.como_objeto(), LIMITE_DO_PEDIDO)
                bruta = ler_quadro(fluxo, LIMITE_DA_RESPOSTA)
        if bruta is None:
            raise NavegadorIndisponivel("o host fechou sem responder")
        return validar_resposta(bruta)


class ClienteDoNavegador:
    """Um método por comando da extensão, com o contrato do `protocolo`."""

    def __init__(
        self,
        transporte: Transporte,
        *,
        novo_id: Callable[[], str] | None = None,
    ) -> None:
        self._transporte = transporte
        self._contador = 0
        self._novo_id = novo_id or self._sequencial
        self.navegador = ""
        """Para falar com um só (`firefox` | `chromium`); vazio = o que abriu por último."""

    def _sequencial(self) -> str:
        self._contador += 1
        return f"j{os.getpid()}-{self._contador}"

    def chamar(self, metodo: str, **params: Any) -> dict[str, Any]:
        pedido = validar_pedido(
            {
                "id": self._novo_id(),
                "method": metodo,
                "params": {k: v for k, v in params.items() if v is not None},
            }
        )
        resposta = self._transporte.chamar(pedido, self.navegador)
        if resposta.get("id") not in (None, pedido.id):
            raise NavegadorIndisponivel("a resposta veio com outro id")
        if not resposta["ok"]:
            erro = resposta["error"]
            raise NavegadorFalhou(erro["codigo"], erro["mensagem"])
        resultado: dict[str, Any] = resposta["result"]
        return resultado

    # --- comandos -----------------------------------------------------------------------
    def abas(self) -> list[dict[str, Any]]:
        return list(self.chamar("tabs.list").get("abas", []))

    def aba(self, tab_id: int | None = None) -> dict[str, Any]:
        """A aba pedida, ou a ativa da janela em foco: o código resolve o id **antes** de agir."""
        return dict(self.chamar("tabs.current", tabId=tab_id).get("aba", {}))

    def ler(self, tab_id: int) -> dict[str, Any]:
        return self.chamar("page.read", tabId=tab_id)

    def inspecionar(self, tab_id: int, alvo: str) -> dict[str, Any]:
        return self.chamar("page.inspect", tabId=tab_id, alvo=alvo)

    def clicar(self, tab_id: int, alvo: str) -> dict[str, Any]:
        return self.chamar("page.click", tabId=tab_id, alvo=alvo)

    def digitar(
        self, tab_id: int, alvo: str, texto: str, *, limpar: bool = False
    ) -> dict[str, Any]:
        return self.chamar("page.type", tabId=tab_id, alvo=alvo, texto=texto, limpar=limpar)

    def rolar(self, tab_id: int, pixels: int) -> dict[str, Any]:
        return self.chamar("page.scroll", tabId=tab_id, pixels=pixels)

    def navegar(self, tab_id: int, url: str) -> dict[str, Any]:
        return self.chamar("tabs.navigate", tabId=tab_id, url=url)

    def abrir(self, url: str) -> dict[str, Any]:
        """Uma aba **nova**, ativa — só quando o dono pediu nova aba; o padrão é `navegar`."""
        return self.chamar("tabs.open", url=url)
