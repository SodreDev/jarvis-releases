"""O cliente do Jarvis para o host nativo: métodos tipados sobre um transporte injetável.

O transporte de verdade (`TransporteUnix`) bate no socket Unix que o host abriu; os testes põem
um falso no lugar e nenhum navegador, socket ou dispositivo do dono é tocado. Tudo o que a
extensão devolve é conteúdo de terceiro — este módulo só o repassa, truncado, e nunca o interpreta.
"""

from __future__ import annotations

import itertools
import json
import os
import select
import socket
import stat
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, Final, Protocol

from jarvis.navegador.host import PRAZO_S, pasta_dos_sockets
from jarvis.navegador.protocolo import (
    ASSINAR,
    COM_CONTROLE,
    LIMITE_DA_RESPOSTA,
    LIMITE_DO_PEDIDO,
    MODO_AUTOMACAO_SOCIAL,
    PedidoDaPonte,
    PedidoInvalido,
    validar_evento,
    validar_pedido,
    validar_resposta,
)
from jarvis.navegador.quadro import CABECALHO, QuadroInvalido, escrever_quadro, ler_quadro


def familia_do_host(principal: str) -> str:
    """O navegador principal do dono (`firefox`, `chrome`, `brave`…) → a família do host: `firefox`
    ou `chromium` (todo derivado do Chromium usa a mesma extensão). Vazio = qualquer um."""
    nome = principal.strip().lower()
    if not nome:
        return ""
    return "firefox" if nome.startswith(("firefox", "librewolf", "zen")) else "chromium"


class NavegadorIndisponivel(RuntimeError):
    """Não há navegador com a extensão do Jarvis aberto (ou o host não respondeu)."""


SEM_ABA: Final = "sem_aba"
MENSAGEM_SEM_ABA: Final = (
    "essa aba não existe mais (foi fechada ou o id é de outra sessão): veja as abas abertas"
)
SEM_NAVEGADOR_ABERTO: Final = "com a extensão do Jarvis está aberto"
"""O pedaço da frase de `NavegadorIndisponivel` quando não há navegador com a extensão: o caminho
rápido a reconhece para abrir o navegador do dono pelo `sites.open` (ADR-0045)."""
ABA_QUE_NAO_EXISTE: Final = "no tab with id"
"""O texto do Chromium para um `tabId` que não existe (em minúsculas)."""


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

    def assinar(self, navegador: str = "") -> AssinaturaUnix:
        """Uma conexão que fica aberta recebendo os eventos da extensão (o PARAR do dono): no host
        mais recente daquela família, como os pedidos."""
        for caminho in self._soquetes(navegador):
            conexao = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                conexao.settimeout(self._prazo_s)
                conexao.connect(str(caminho))
                pedido = PedidoDaPonte(f"a{os.getpid()}", ASSINAR, {})
                with conexao.makefile("wb") as saida:
                    escrever_quadro(saida, pedido.como_objeto(), LIMITE_DO_PEDIDO)
                assinatura = AssinaturaUnix(conexao)
                resposta = validar_resposta(assinatura.quadro(self._prazo_s))
            except (ConnectionRefusedError, FileNotFoundError):
                conexao.close()
                continue
            except (OSError, QuadroInvalido, PedidoInvalido, NavegadorIndisponivel) as erro:
                conexao.close()
                raise NavegadorIndisponivel(f"o host não aceitou a assinatura: {erro}") from None
            if not resposta["ok"]:
                conexao.close()
                raise NavegadorIndisponivel(f"o host recusou a assinatura: {resposta['error']}")
            return assinatura
        raise NavegadorIndisponivel("nenhum navegador com a extensão do Jarvis está aberto")

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


class AssinaturaUnix:
    """A conexão de eventos com o host: quadros lidos à mão do socket, com espera por `select` —
    um tempo esgotado no meio de um quadro bufferizado embaralharia o fluxo."""

    def __init__(self, conexao: socket.socket) -> None:
        self._conexao = conexao
        self._resto = bytearray()

    def _completo(self) -> dict[str, Any] | None:
        if len(self._resto) < CABECALHO.size:
            return None
        (tamanho,) = CABECALHO.unpack(self._resto[: CABECALHO.size])
        if tamanho > LIMITE_DA_RESPOSTA:
            raise NavegadorIndisponivel("quadro de evento grande demais")
        if len(self._resto) < CABECALHO.size + tamanho:
            return None
        corpo = bytes(self._resto[CABECALHO.size : CABECALHO.size + tamanho])
        del self._resto[: CABECALHO.size + tamanho]
        try:
            objeto = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NavegadorIndisponivel("evento que não é JSON") from None
        if not isinstance(objeto, dict):
            raise NavegadorIndisponivel("evento que não é objeto")
        return objeto

    def quadro(self, segundos: float) -> dict[str, Any] | None:
        """O próximo quadro em até `segundos`, ou `None`; conexão fechada: NavegadorIndisponivel."""
        pronto = self._completo()
        if pronto is not None:
            return pronto
        legiveis, _, _ = select.select([self._conexao], [], [], max(0.0, segundos))
        if not legiveis:
            return None
        pedaco = self._conexao.recv(65536)
        if not pedaco:
            raise NavegadorIndisponivel("o host fechou a conexão de eventos")
        self._resto.extend(pedaco)
        return self._completo()

    def esperar(self, segundos: float) -> list[dict[str, Any]]:
        """Os eventos válidos que chegaram em até `segundos`; inválidos são descartados."""
        eventos: list[dict[str, Any]] = []
        for bruto in self._quadros(segundos):
            try:
                eventos.append(validar_evento(bruto))
            except PedidoInvalido:
                continue
        return eventos

    def _quadros(self, segundos: float) -> Iterator[dict[str, Any]]:
        primeiro = self.quadro(segundos)
        while primeiro is not None:
            yield primeiro
            primeiro = self.quadro(0.0)

    def fechar(self) -> None:
        self._conexao.close()


class ClienteDoNavegador:
    """Um método por comando da extensão, com o contrato do `protocolo`."""

    def __init__(
        self,
        transporte: Transporte,
        *,
        novo_id: Callable[[], str] | None = None,
    ) -> None:
        self._transporte = transporte
        self._contador = itertools.count(1)
        self._novo_id = novo_id or self._sequencial
        self.navegador = ""
        """Para falar com um só (`firefox` | `chromium`); vazio = o que abriu por último."""
        self.concessao: str | None = None
        """O controle do objetivo que pediu (`sob`): vai em todo pedido que mexe numa aba."""
        self.automacao_social = False
        """O gancho da automação de redes sociais, e-mail e agenda (com digitação humanizada, que
        ainda não existe): o **único** caminho para a janela própria do Jarvis (ADR-0036, emenda de
        2026-10-21). Desligado — o padrão, e sem chave na configuração por enquanto —, o trabalho de
        fundo é uma aba em segundo plano na janela do dono, e nada abre janela nem instância."""

    def _sequencial(self) -> str:
        return f"j{os.getpid()}-{next(self._contador)}"

    @property
    def transporte(self) -> Transporte:
        return self._transporte

    def sob(self, concessao: str | None) -> ClienteDoNavegador:
        """O mesmo cliente (transporte, navegador e ids) falando em nome de uma concessão de
        controle: cada linha (o turno, cada tarefa) usa a sua cópia, sem disputar um atributo."""
        copia = ClienteDoNavegador(self._transporte, novo_id=self._novo_id)
        copia.navegador = self.navegador
        copia.concessao = concessao
        copia.automacao_social = self.automacao_social
        return copia

    def _modo(self) -> str | None:
        return MODO_AUTOMACAO_SOCIAL if self.automacao_social else None

    def chamar(self, metodo: str, **params: Any) -> dict[str, Any]:
        if metodo in COM_CONTROLE and self.concessao is not None and "controle" not in params:
            params["controle"] = self.concessao
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
            if erro["codigo"] == "falha" and ABA_QUE_NAO_EXISTE in erro["mensagem"].casefold():
                # A extensão de antes do `1565698` (não recarregada) devolve o «No tab with id» do
                # navegador como "falha" crua: é a aba que não existe mais (trilha do dono,
                # 2026-10-21, 21:13: duas navegações com um id velho, 2–3 ms cada).
                raise NavegadorFalhou(SEM_ABA, MENSAGEM_SEM_ABA)
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

    def mapear(self, tab_id: int) -> dict[str, Any]:
        """O mapa da página (ADR-0032): elementos interativos com `ref`, e os scripts."""
        return self.chamar("page.map", tabId=tab_id)

    def capturar(self, tab_id: int) -> dict[str, Any]:
        """A tela da aba (`imagem`, URL de dados JPEG) e o mapa do mesmo instante (`mapa`)."""
        return self.chamar("page.capture", tabId=tab_id)

    def ler_em_segundo_plano(self, url: str) -> dict[str, Any]:
        """A leitura (`pagina`) de um endereço numa aba de fundo da janela do dono (sem `active`,
        sem foco), fechada no fim."""
        return self.chamar("page.readUrl", url=url, modo=self._modo())

    def inspecionar(
        self, tab_id: int, alvo: str | None = None, *, ref: str | None = None
    ) -> dict[str, Any]:
        return self.chamar("page.inspect", tabId=tab_id, alvo=alvo, ref=ref)

    def clicar(
        self, tab_id: int, alvo: str | None = None, *, ref: str | None = None
    ) -> dict[str, Any]:
        return self.chamar("page.click", tabId=tab_id, alvo=alvo, ref=ref)

    def digitar(
        self,
        tab_id: int,
        alvo: str | None,
        texto: str,
        *,
        limpar: bool = False,
        ref: str | None = None,
    ) -> dict[str, Any]:
        return self.chamar(
            "page.type", tabId=tab_id, alvo=alvo, ref=ref, texto=texto, limpar=limpar
        )

    def acionar(
        self,
        tab_id: int,
        acao: str,
        alvo: str | None = None,
        *,
        ref: str | None = None,
        tecla: str | None = None,
        valor: str | None = None,
    ) -> dict[str, Any]:
        """Uma ação da lista fechada no elemento — equivale a clicá-lo (ADR-0027, ADR-0032)."""
        return self.chamar(
            "page.act", tabId=tab_id, acao=acao, alvo=alvo, ref=ref, tecla=tecla, valor=valor
        )

    def rolar(self, tab_id: int, pixels: int) -> dict[str, Any]:
        return self.chamar("page.scroll", tabId=tab_id, pixels=pixels)

    def navegar(self, tab_id: int, url: str) -> dict[str, Any]:
        """Leva a aba ao endereço e volta **depois** de conferir: `comecou` (a aba saiu do lugar),
        `carregou`, `pagina` (o conteúdo da extensão respondeu na página nova: `{url, titulo}`, ou
        nulo na página de erro do navegador), `janela` (`dono` | `jarvis`) e `visivel`."""
        return self.chamar("tabs.navigate", tabId=tab_id, url=url)

    def abrir(self, url: str, *, segundo_plano: bool = False) -> dict[str, Any]:
        """Uma aba **nova** na janela do dono: ativa (ele vai ver), ou — `segundo_plano` — em
        segundo plano, sem `active` e sem tirar o foco (ADR-0036, emenda de 2026-10-21; na
        automação social, na janela própria do Jarvis). Conferida como em `navegar`."""
        if not segundo_plano:
            return self.chamar("tabs.open", url=url)
        if self.automacao_social:
            return self.chamar("tabs.open", url=url, modo=MODO_AUTOMACAO_SOCIAL)
        return self.chamar("tabs.open", url=url, fundo=True)

    def mostrar(self, tab_id: int) -> dict[str, Any]:
        """Põe a aba à vista do dono (ativa, com a janela dela na frente; a da janela do Jarvis vai
        para a do dono). `visivel` diz se ficou — o sistema pode negar o foco ao navegador."""
        return self.chamar("tabs.show", tabId=tab_id)

    def janela_em_foco(self) -> dict[str, Any]:
        """A janela em foco e a aba ativa dela (`janelaId`, `abaAtivaId`), e a do Jarvis."""
        return self.chamar("windows.focused")
