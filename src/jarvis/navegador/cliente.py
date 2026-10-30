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
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from jarvis.navegador.host import PRAZO_S, pasta_dos_sockets
from jarvis.navegador.protocolo import (
    ASSINAR,
    COM_CONTROLE,
    LIMITE_DA_RESPOSTA,
    LIMITE_DO_PEDIDO,
    MODO_AUTOMACAO_SOCIAL,
    PRAZOS_CURTOS,
    VERSAO,
    VERSAO_DA_PONTE,
    VERSAO_DO_HOST,
    PedidoDaPonte,
    PedidoInvalido,
    prazo_do_metodo,
    validar_evento,
    validar_pedido,
    validar_resposta,
)
from jarvis.navegador.quadro import CABECALHO, QuadroInvalido, escrever_quadro


def familia_do_host(principal: str) -> str:
    """O navegador principal do dono (`firefox`, `chrome`, `brave`…) → a família do host: `firefox`
    ou `chromium` (todo derivado do Chromium usa a mesma extensão). Vazio = qualquer um."""
    nome = principal.strip().lower()
    if not nome:
        return ""
    return "firefox" if nome.startswith(("firefox", "librewolf", "zen")) else "chromium"


class NavegadorIndisponivel(RuntimeError):
    """Não há navegador com a extensão do Jarvis aberto (ou o host não respondeu)."""


class ChamadaCancelada(NavegadorIndisponivel):
    """O turno (ou a tarefa) foi cancelado com o pedido em voo: o Jarvis largou a espera na hora,
    sem ficar preso no socket até o prazo — o que prendia o laço e a voz (dono, 2026-10-30)."""


class SemResposta(NavegadorIndisponivel):
    """A extensão não respondeu no prazo do método (`protocolo.prazo_do_metodo`)."""


MARGEM_DO_HOST_S: Final = 5.0
"""Nos pedidos longos o host tem o prazo dele (25 s) e responde `tempo_esgotado`: o Jarvis espera um
pouco mais que ele, para ouvir esse código em vez de desistir junto."""
FATIA_DA_ESPERA_S: Final = 0.1
"""De quanto em quanto a espera confere o cancelamento."""


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


METODO_DESCONHECIDO: Final = "metodo_invalido"
"""O código da extensão para método que ela não conhece (`background.js`, `default` do `switch`)."""
PEDIDO_INVALIDO: Final = "pedido_invalido"
"""O código do host para pedido fora do vocabulário dele (o host de antes de um método novo)."""
METODOS_DA_VERSAO_1: Final = frozenset(
    {
        "tabs.list",
        "tabs.current",
        "tabs.active",
        "tabs.navigate",
        "tabs.open",
        "tabs.show",
        "tabs.close",
        "windows.focused",
        "page.read",
        "page.map",
        "page.capture",
        "page.readUrl",
        "page.inspect",
        "page.click",
        "page.type",
        "page.act",
        "page.scroll",
        "controle.soltar",
        "controle.manter",
        "controle.parar",
        "controle.estado",
    }
)
"""O que a extensão de antes do CDP já sabia: método fora daqui que ela não conhece é sinal de que
o navegador está com a cópia velha carregada."""
RECARREGAR: Final = (
    "a extensão do Jarvis carregada no navegador é de uma versão anterior: abra a página de "
    "extensões (brave://extensions, chrome://extensions ou about:debugging no Firefox), clique em "
    "Recarregar no card do Jarvis e tente de novo"
)
"""A frase acionável para o dono e para o modelo (que não deve tentar o mesmo método de novo)."""


class ExtensaoDesatualizada(NavegadorFalhou):
    """A extensão no ar não conhece o método pedido: é a cópia de antes, sem recarregar."""

    def __init__(self, metodo: str) -> None:
        super().__init__("extensao_desatualizada", f"{metodo}: {RECARREGAR}")
        self.metodo = metodo


@dataclass(frozen=True, slots=True)
class VersaoDaPonte:
    """O que `ClienteDoNavegador.versao` descobriu: `None` = não respondeu à pergunta de versão
    (é de antes dela)."""

    host: int | None
    extensao: int | None
    manifesto: str = ""
    pid_do_host: int | None = None
    host_iniciado_em: float | None = None
    permissoes: Mapping[str, bool] = field(default_factory=dict)
    host_conhece: bool = False
    extensao_conhece: bool = False

    @property
    def em_dia(self) -> bool:
        return self.host == VERSAO_DA_PONTE and self.extensao == VERSAO_DA_PONTE

    def o_que_fazer(self) -> str:
        """Vazio se está tudo em dia; senão, a frase do que o dono faz."""
        if self.em_dia and all(self.permissoes.get(p, False) for p in ("debugger", "scripting")):
            return ""
        if self.extensao is None or self.extensao < VERSAO_DA_PONTE:
            return RECARREGAR
        if self.host is None or self.host < VERSAO_DA_PONTE:
            return (
                "o host do navegador é de antes da atualização: recarregue a extensão do Jarvis "
                "(o navegador relança o host) ou feche e abra o navegador"
            )
        if self.extensao > VERSAO_DA_PONTE or self.host > VERSAO_DA_PONTE:
            return "a extensão é mais nova que este Jarvis: atualize o Jarvis e reinicie-o"
        return (
            "a extensão está sem a permissão de depuração (CDP): recarregue-a e aceite a permissão "
            "nova, ou o console, a rede e os gestos ficam desligados"
        )


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

    def prazo_de(self, metodo: str) -> float:
        """Quanto esperar a resposta deste método: curto para o que só consulta a extensão, o do
        host mais a margem para o que espera a página — nunca mais que o teto deste transporte."""
        prazo = prazo_do_metodo(metodo)
        if metodo not in PRAZOS_CURTOS:
            prazo += MARGEM_DO_HOST_S
        return min(prazo, self._prazo_s)

    def chamar(
        self,
        pedido: PedidoDaPonte,
        navegador: str = "",
        *,
        cancelado: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        for caminho in self._soquetes(navegador):
            try:
                return self._bater(caminho, pedido, cancelado)
            except (ConnectionRefusedError, FileNotFoundError):
                continue  # host morto que deixou o arquivo: tenta o próximo
            except NavegadorIndisponivel:
                raise
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

    def _bater(
        self, caminho: Path, pedido: PedidoDaPonte, cancelado: Callable[[], bool] | None = None
    ) -> dict[str, Any]:
        """Um pedido, uma conexão. A resposta é esperada em fatias de `FATIA_DA_ESPERA_S`, com o
        prazo do método e o cancelamento conferidos a cada uma: o laço nunca fica preso no socket
        por uma extensão travada, e o "para" do dono vale na hora."""
        prazo = self.prazo_de(pedido.method)
        limite = time.monotonic() + prazo
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexao:
            conexao.settimeout(min(prazo, 2.0))
            conexao.connect(str(caminho))
            conexao.settimeout(min(prazo, 2.0))
            with conexao.makefile("wb") as saida:
                escrever_quadro(saida, pedido.como_objeto(), LIMITE_DO_PEDIDO)
            espera = AssinaturaUnix(conexao)
            while True:
                if cancelado is not None and cancelado():
                    raise ChamadaCancelada(f"{pedido.method}: cancelado com o pedido em voo")
                falta = limite - time.monotonic()
                if falta <= 0:
                    raise SemResposta(
                        f"a extensão não respondeu a {pedido.method} em {prazo:.0f} s"
                    )
                try:
                    bruta = espera.quadro(min(FATIA_DA_ESPERA_S, falta))
                except NavegadorIndisponivel as erro:
                    raise NavegadorIndisponivel(f"o host fechou sem responder ({erro})") from None
                if bruta is not None:
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
        self.cancelado: Callable[[], bool] | None = None
        """O cancelamento de quem fala por este cliente (o turno, a tarefa): com ele, o pedido em
        voo é largado na hora em que o dono corta — sem ele, a espera vai até o prazo do método."""
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

    def sob(
        self, concessao: str | None, cancelado: Callable[[], bool] | None = None
    ) -> ClienteDoNavegador:
        """O mesmo cliente (transporte, navegador e ids) falando em nome de uma concessão de
        controle e com o cancelamento de quem pede: cada linha (o turno, cada tarefa) usa a sua
        cópia, sem disputar um atributo."""
        copia = ClienteDoNavegador(self._transporte, novo_id=self._novo_id)
        copia.navegador = self.navegador
        copia.concessao = concessao
        copia.cancelado = cancelado or self.cancelado
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
        if self.cancelado is not None and isinstance(self._transporte, TransporteUnix):
            # Só o transporte de verdade sabe largar a espera; os falsos respondem na hora.
            resposta = self._transporte.chamar(pedido, self.navegador, cancelado=self.cancelado)
        else:
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
            if erro["codigo"] == METODO_DESCONHECIDO and metodo not in METODOS_DA_VERSAO_1:
                # A extensão carregada no navegador é de antes deste método (não foi recarregada
                # depois da atualização): o modelo e o dono ouvem o que fazer, não "falhou".
                raise ExtensaoDesatualizada(metodo)
            raise NavegadorFalhou(erro["codigo"], erro["mensagem"])
        resultado: dict[str, Any] = resposta["result"]
        return resultado

    def versao(self) -> VersaoDaPonte:
        """A versão do host e a da extensão que estão no ar, sem tocar em aba nem página:
        `host.versao` (o host responde sozinho) e `ponte.versao` (a extensão). Quem é de antes
        responde que não conhece o método — e isso também é a resposta."""
        host = self._versao_de(VERSAO_DO_HOST)
        extensao = self._versao_de(VERSAO)
        return VersaoDaPonte(
            host=host.get("versao") if isinstance(host.get("versao"), int) else None,
            extensao=extensao.get("versao") if isinstance(extensao.get("versao"), int) else None,
            manifesto=str(extensao.get("manifesto", "")),
            pid_do_host=host.get("pid") if isinstance(host.get("pid"), int) else None,
            host_iniciado_em=float(host["iniciado_em"])
            if isinstance(host.get("iniciado_em"), (int, float))
            else None,
            permissoes={
                str(k): bool(v)
                for k, v in dict(extensao.get("permissoes") or {}).items()
                if isinstance(k, str)
            },
            host_conhece=bool(host),
            extensao_conhece=bool(extensao),
        )

    def _versao_de(self, metodo: str) -> dict[str, Any]:
        try:
            return self.chamar(metodo)
        except ExtensaoDesatualizada:
            return {}
        except NavegadorFalhou as erro:
            if erro.codigo in (METODO_DESCONHECIDO, PEDIDO_INVALIDO):
                return {}  # o host (ou a extensão) de antes: não conhece o método
            raise

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

    def console(self, tab_id: int) -> dict[str, Any]:
        """Os logs e erros do console da aba desde que o Jarvis anexou o depurador (ADR-0051)."""
        return self.chamar("page.console", tabId=tab_id)

    def rede(self, tab_id: int) -> dict[str, Any]:
        """Os pedidos de rede da aba desde que anexou: método, URL, status, tipo, tempo."""
        return self.chamar("page.network", tabId=tab_id)

    def avaliar(self, tab_id: int, codigo: str, *, mundo: str = "isolado") -> dict[str, Any]:
        """Roda um JavaScript no mundo isolado (padrão) ou principal e devolve o valor serializado,
        se der para serializar, mais `cdp` (foi por CDP) ou o recuo para `chrome.scripting`."""
        return self.chamar("page.eval", tabId=tab_id, codigo=codigo, mundo=mundo)

    def gesto(
        self,
        tab_id: int,
        gesto: str,
        *,
        alvo: str | None = None,
        ref: str | None = None,
        texto: str | None = None,
        pixels: int | None = None,
    ) -> dict[str, Any]:
        """Um gesto físico por `Input.*` do CDP (clicar, arrastar, digitar, rolar) quando o clique
        por `ref` não faz efeito (ADR-0051)."""
        params: dict[str, Any] = {"tabId": tab_id, "gesto": gesto}
        if alvo is not None:
            params["alvo"] = alvo
        if ref is not None:
            params["ref"] = ref
        if texto is not None:
            params["texto"] = texto
        if pixels is not None:
            params["pixels"] = pixels
        return self.chamar("page.gesture", **params)

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

    def fechar_aba(self, tab_id: int) -> dict[str, Any]:
        """Fecha a aba (ADR-0057). Quem decide se pode é o Jarvis — o escopo do pedido ou o sim do
        dono —; a extensão só recusa aba que não existe."""
        return self.chamar("tabs.close", tabId=tab_id)

    def janela_em_foco(self) -> dict[str, Any]:
        """A janela em foco e a aba ativa dela (`janelaId`, `abaAtivaId`), e a do Jarvis."""
        return self.chamar("windows.focused")
