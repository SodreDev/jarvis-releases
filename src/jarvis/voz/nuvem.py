"""Encanamento comum dos motores de nuvem: prazo nosso, corpo cancelável, nada pendurado.

Por que o cliente HTTP é nosso e é a biblioteca padrão: os dois SDKs oficiais (Groq e
ElevenLabs) trazem árvore de dependência própria, cada uma com licença para verificar, e
nenhum dos dois entrega o que este produto precisa — abandonar o corpo da resposta no meio
porque o epoch morreu. `urllib.request` entrega, custa zero dependência e deixa o prazo nas
nossas mãos (regra 1 do `jarvis.rede`: "o prazo é nosso").

Três coisas que este módulo garante, e que são contrato do F1-09/F1-11 aplicado à rede:

1. **O pedido não sai se o epoch já morreu.** Cancelamento é consultado **antes** de abrir o
   socket: mandar áudio de epoch morto para a nuvem é pagar por trabalho que ninguém vai ouvir.
2. **O corpo em voo é descartado.** A leitura é por pedaços, com o cancelamento consultado
   entre eles; quando ele aparece, a resposta é fechada e o que já tinha chegado é **jogado
   fora**, não devolvido pela metade. O limite do descarte é o pedaço: uma leitura já
   bloqueada só termina pelo prazo do socket — e é por isso que o prazo é obrigatório.
3. **A suíte não tem como falar com a nuvem de verdade.** `proibir_nuvem_real_em_ci` recusa,
   sob `CI=1`, qualquer base que não seja a máquina local. É a mesma regra estrutural do
   `proibir_dispositivo_em_ci` (F1-01) e da `SondaDeSocket` (F1-14): a recusa mora no código
   de produção, não numa fixture.
"""

from __future__ import annotations

import io
import json
import select
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException, HTTPResponse, HTTPSConnection
from typing import Any, Final
from urllib.parse import urlparse, urlsplit

from jarvis import __version__
from jarvis.ambiente import VARIAVEL_CI, ambiente_ou_os, em_ci
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, CANAIS, TAXA_PADRAO
from jarvis.rede import ErroDeRede
from jarvis.voz.chaves import Chave, redigir
from jarvis.voz.interface import Cancelado, nunca_cancelado

AGENTE_DO_USUARIO: Final = f"jarvis/{__version__}"
"""Como o cliente se anuncia ao serviço: o `Python-urllib` padrão é barrado pelo Cloudflare."""

PEDACO_DE_LEITURA: Final = 8192
"""Bytes por leitura. Granularidade do descarte: quanto menor, mais rápido o `Cancel`
aparece; quanto maior, menos chamadas. 8 KiB é ~0,25 s de PCM16 16 kHz."""

LIMITE_DE_CORPO: Final = 32 * 1024 * 1024
"""Teto do corpo que aceitamos ler. Serviço que manda mais do que isso está errado, e ler sem
teto é deixar a memória do dono na mão de um terceiro."""

MAQUINAS_LOCAIS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
"""Onde o servidor falso dos testes mora. `0.0.0.0` não entra: é endereço de escuta, não de
destino — cliente que "conecta em 0.0.0.0" está pedindo outra coisa."""


class NuvemRealProibidaEmCI(ErroDeRede):
    """Sob `CI=1` ninguém fala com serviço de verdade, nem por descuido de configuração."""


class ErroDoServico(ErroDeRede):
    """Não deu para falar com o serviço, ou ele falhou do lado dele (5xx, 429, transporte).

    É `ErroDeRede` de propósito: o `AdaptadorRemoto` do F1-14 captura isso e **declara a
    degradação** — cai para PTT, avisa em uma frase e não refaz o pedido.
    """


class ServicoRecusou(RuntimeError):
    """O serviço entendeu e recusou: chave inválida, sem crédito, pedido malformado (4xx).

    **Não** é `ErroDeRede`, e a diferença é o dono: "a sua chave não serve" não pode chegar a
    ele como "estou sem internet". Este erro atravessa o adaptador e sobe para o aplicativo,
    que desliga o motor de nuvem e diz o que aconteceu. A mensagem já passou por `redigir`.
    """


STATUS_QUE_VIRAM_DEGRADACAO: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
"""4xx que são "tente mais tarde" (prazo, cedo demais, limite de taxa) e 5xx do serviço: isso
é indisponibilidade, e indisponibilidade é o caminho do F1-14. O resto do 4xx é recusa."""


@dataclass(frozen=True, slots=True)
class Resposta:
    """O que voltou — ou o que foi descartado por cancelamento."""

    corpo: bytes = b""
    status: int = 0
    cancelada: bool = False
    bytes_descartados: int = 0

    def json(self) -> dict[str, Any]:
        if not self.corpo:
            return {}
        dados = json.loads(self.corpo.decode("utf-8", "replace"))
        return dados if isinstance(dados, dict) else {}


def proibir_nuvem_real_em_ci(base: str, ambiente: Mapping[str, str] | None = None) -> None:
    """Recusa, sob CI, qualquer base que não seja local. Chamada na abertura do motor."""
    if not em_ci(ambiente):
        return
    maquina = (urlparse(base).hostname or "").lower()
    if maquina not in MAQUINAS_LOCAIS:
        raise NuvemRealProibidaEmCI(
            f"{VARIAVEL_CI} está ligado e a base {base!r} não é local: a suíte não fala com "
            "serviço de nuvem de verdade (aponte para um servidor falso em porta efêmera)"
        )


def envelope_wav(amostras: bytes, *, taxa: int = TAXA_PADRAO) -> bytes:
    """PCM16 mono do nosso caminho de áudio dentro de um WAV, em memória.

    Os dois serviços querem arquivo, não amostras cruas, e a página da Groq recomenda
    justamente 16 kHz mono — então não há reamostragem nem conversão com perda aqui: só o
    cabeçalho de 44 bytes que falta.
    """
    memoria = io.BytesIO()
    with wave.open(memoria, "wb") as arquivo:
        arquivo.setnchannels(CANAIS)
        arquivo.setsampwidth(BYTES_POR_AMOSTRA)
        arquivo.setframerate(taxa)
        arquivo.writeframes(amostras)
    return memoria.getvalue()


def corpo_multipart(
    campos: Mapping[str, str],
    *,
    nome_do_arquivo: str,
    conteudo: bytes,
    tipo: str = "audio/wav",
    campo_do_arquivo: str = "file",
) -> tuple[bytes, str]:
    """Monta `multipart/form-data` à mão. Devolve (corpo, content-type).

    Feito aqui porque é pequeno e porque a alternativa — um SDK — traria dependência e
    esconderia o único detalhe que importa: nada neste corpo é segredo. A chave vai no
    cabeçalho, nunca no corpo e nunca na URL.
    """
    limite = f"----jarvis{uuid.uuid4().hex}"
    partes: list[bytes] = []
    for nome, valor in campos.items():
        cabecalho = f'Content-Disposition: form-data; name="{nome}"'
        partes.append(f"--{limite}\r\n{cabecalho}\r\n\r\n{valor}\r\n".encode())
    partes.append(
        f'--{limite}\r\nContent-Disposition: form-data; name="{campo_do_arquivo}"; '
        f'filename="{nome_do_arquivo}"\r\nContent-Type: {tipo}\r\n\r\n'.encode()
    )
    partes.append(conteudo)
    partes.append(f"\r\n--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def _ler_cancelavel(
    resposta: HTTPResponse,
    *,
    cancelado: Cancelado,
    limite: int = LIMITE_DE_CORPO,
) -> Resposta:
    """Lê o corpo por pedaços, abandonando no primeiro cancelamento visto.

    O que já chegou é **descartado**: devolver corpo pela metade seria entregar ao `agentd`
    uma transcrição truncada de um turno que o dono já interrompeu — pior do que não entregar.
    """
    recebido = bytearray()
    while True:
        if cancelado():
            resposta.close()
            return Resposta(status=resposta.status, cancelada=True, bytes_descartados=len(recebido))
        pedaco = resposta.read(PEDACO_DE_LEITURA)
        if not pedaco:
            return Resposta(corpo=bytes(recebido), status=resposta.status)
        recebido += pedaco
        if len(recebido) > limite:
            resposta.close()
            raise ErroDoServico(
                f"o serviço mandou mais de {limite} bytes de corpo: leitura abandonada"
            )


MAXIMO_DE_OCIOSAS: Final = 4
"""Conexões paradas guardadas por servidor: o TTS sintetiza até três lotes à frente."""
OCIOSA_ATE_S: Final = 30.0
"""Conexão parada há mais que isto é fechada em vez de reaproveitada: o servidor (o Cloudflare na
frente da Groq e da ElevenLabs) derruba a ociosa por conta dele."""
LIMITE_DO_CORPO_DE_ERRO: Final = 64 * 1024


class _RespostaPersistente:
    """A resposta de `ConexoesPersistentes`: lê como a do `urlopen` e, no fim, devolve a conexão
    ao pool — só se o corpo foi lido inteiro e o servidor não pediu para fechar. A leitura
    abandonada (o cancelamento do epoch, o corpo grande demais) fecha a conexão: sobraria corpo
    em voo nela."""

    def __init__(self, resposta: HTTPResponse, devolver: Callable[[bool], None]) -> None:
        self._resposta = resposta
        self._devolver = devolver
        self._abandonada = False
        self._feita = False

    @property
    def status(self) -> int:
        return self._resposta.status

    def read(self, quantos: int = -1) -> bytes:
        return self._resposta.read(quantos)

    def close(self) -> None:
        if not self._resposta.isclosed():
            self._abandonada = True
        self._terminar()

    def __enter__(self) -> _RespostaPersistente:
        return self

    def __exit__(self, *_: object) -> None:
        self._terminar()

    def _terminar(self) -> None:
        if self._feita:
            return
        self._feita = True
        inteira = self._resposta.isclosed() and not self._abandonada
        self._devolver(inteira and not self._resposta.will_close)


@dataclass
class ConexoesPersistentes:
    """O `urlopen` com conexão que fica aberta entre um pedido e outro (keep-alive), por servidor.

    Pedido do dono (2026-10-21, «precisa ser muito rápido»): o `urlopen` abre uma conexão nova —
    DNS, TCP e TLS — a **cada** pedido: cada lote de fala da ElevenLabs e cada transcrição da Groq.
    Medido desta rede em 2026-10-21 (sem chave, GET sem autenticação): conexão nova à ElevenLabs
    ~70 ms acima da reaproveitada (213–230 ms × 147–155 ms), à Groq ~25 ms, e o DNS frio mais
    120–200 ms. Aqui a conexão fica guardada e volta para o próximo pedido; `aquecer` a abre antes
    do primeiro (sem mandar dado nenhum: só o aperto de mão do TLS).

    Nada muda no contrato do `ClienteHttp`: erro 4xx/5xx sobe como `HTTPError`, falha de rede como
    `URLError`, e a leitura cancelada fecha a conexão. Conexão que o servidor já fechou (a ociosa
    derrubada) é conferida **antes** de reaproveitar — nunca se repete um POST."""

    maximo: int = MAXIMO_DE_OCIOSAS
    ociosa_ate_s: float = OCIOSA_ATE_S
    relogio: Callable[[], float] = time.monotonic
    abertas: int = 0
    """Conexões novas abertas (para o teste e a medição)."""
    reaproveitadas: int = 0
    _ociosas: dict[tuple[str, str, int], list[tuple[HTTPConnection, float]]] = field(
        default_factory=dict, repr=False
    )
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __call__(self, pedido: urllib.request.Request, timeout: float) -> _RespostaPersistente:
        partes = urlsplit(pedido.full_url)
        chave = _chave_do_servidor(partes.scheme, partes.hostname or "", partes.port)
        caminho = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
        conexao = self._tomar(chave, timeout)
        try:
            conexao.request(
                pedido.get_method(),
                caminho,
                body=pedido.data if isinstance(pedido.data, bytes) else None,
                headers=dict(pedido.header_items()),
            )
            resposta = conexao.getresponse()
        except OSError as erro:
            conexao.close()
            raise urllib.error.URLError(erro) from None
        except HTTPException as erro:
            conexao.close()
            raise urllib.error.URLError(str(erro) or type(erro).__name__) from None
        if resposta.status >= 400:
            corpo = resposta.read(LIMITE_DO_CORPO_DE_ERRO)
            conexao.close()
            raise urllib.error.HTTPError(
                pedido.full_url,
                resposta.status,
                resposta.reason,
                resposta.headers,
                io.BytesIO(corpo),
            )

        def devolver(reaproveitavel: bool) -> None:
            if reaproveitavel:
                self._guardar(chave, conexao)
            else:
                conexao.close()

        return _RespostaPersistente(resposta, devolver)

    def aquecer(self, url: str, timeout: float = 5.0) -> bool:
        """Abre (DNS, TCP, TLS) e guarda uma conexão com o servidor de `url`, sem pedido nenhum:
        o primeiro lote de fala e a primeira transcrição não pagam o aperto de mão."""
        partes = urlsplit(url)
        chave = _chave_do_servidor(partes.scheme, partes.hostname or "", partes.port)
        with self._trava:
            if self._ociosas.get(chave):
                return True
        conexao = _nova_conexao(chave, timeout)
        try:
            conexao.connect()
        except OSError:
            conexao.close()
            return False
        self.abertas += 1
        self._guardar(chave, conexao)
        return True

    def fechar(self) -> None:
        with self._trava:
            todas = [c for lista in self._ociosas.values() for c, _ in lista]
            self._ociosas.clear()
        for conexao in todas:
            conexao.close()

    def _tomar(self, chave: tuple[str, str, int], timeout: float) -> HTTPConnection:
        agora = self.relogio()
        with self._trava:
            lista = self._ociosas.get(chave, [])
            while lista:
                conexao, desde = lista.pop()
                if agora - desde <= self.ociosa_ate_s and _viva(conexao):
                    self.reaproveitadas += 1
                    if conexao.sock is not None:
                        conexao.sock.settimeout(timeout)
                    conexao.timeout = timeout
                    return conexao
                conexao.close()
        self.abertas += 1
        return _nova_conexao(chave, timeout)

    def _guardar(self, chave: tuple[str, str, int], conexao: HTTPConnection) -> None:
        with self._trava:
            lista = self._ociosas.setdefault(chave, [])
            if len(lista) < self.maximo:
                lista.append((conexao, self.relogio()))
                return
        conexao.close()


def _chave_do_servidor(esquema: str, host: str, porta: int | None) -> tuple[str, str, int]:
    if esquema not in ("http", "https") or not host:
        raise urllib.error.URLError(f"esquema {esquema!r} ou servidor vazio")
    return esquema, host, porta or (443 if esquema == "https" else 80)


def _nova_conexao(chave: tuple[str, str, int], timeout: float) -> HTTPConnection:
    esquema, host, porta = chave
    if esquema == "https":
        return HTTPSConnection(host, porta, timeout=timeout, context=ssl.create_default_context())
    return HTTPConnection(host, porta, timeout=timeout)


def _viva(conexao: HTTPConnection) -> bool:
    """A conexão parada continua de pé? Se o servidor a fechou, o soquete fica "legível" (EOF):
    reaproveitá-la mandaria o pedido para o vazio."""
    soquete = conexao.sock
    if soquete is None:
        return False
    try:
        legivel, _, _ = select.select([soquete], [], [], 0)
    except (OSError, ValueError):
        return False
    return not legivel


CONEXOES: Final = ConexoesPersistentes()
"""O pool do processo: a Groq e a ElevenLabs (e o servidor falso dos testes) por servidor."""


@dataclass(slots=True)
class ClienteHttp:
    """Um POST (ou GET de catálogo) com prazo nosso, cabeçalho com a chave e corpo cancelável.

    Não guarda a `Chave`: recebe por chamada. É o que mantém o segredo com tempo de vida curto
    e fora do `repr` de qualquer objeto de longa duração.
    """

    base: str
    prazo_s: float = 10.0
    ambiente: Mapping[str, str] | None = None
    abrir: Any = field(default_factory=lambda: CONEXOES, repr=False)
    """Quem faz o pedido: o pool de conexões persistentes (2026-10-21). Injetável para o teste
    poder olhar o pedido sem subir servidor, quando é isso que se quer provar (o `urlopen` de
    antes também serve). Nos testes de caminho inteiro quem responde é um servidor de verdade."""

    def aquecer(self) -> bool:
        """A conexão com o serviço aberta antes do primeiro pedido (sem dado nenhum). Sob CI, a
        nuvem de verdade continua proibida."""
        proibir_nuvem_real_em_ci(self.base, self.ambiente)
        aquecer = getattr(self.abrir, "aquecer", None)
        return bool(aquecer(self.base, min(self.prazo_s, 5.0))) if callable(aquecer) else False

    chamadas: int = 0
    bytes_descartados: int = 0
    nao_enviadas_por_cancelamento: int = 0

    def postar(
        self,
        caminho: str,
        *,
        corpo: bytes,
        tipo_do_corpo: str,
        chave: Chave,
        cabecalho_da_chave: str = "Authorization",
        prefixo_da_chave: str = "Bearer ",
        cabecalhos: Mapping[str, str] | None = None,
        cancelado: Cancelado = nunca_cancelado,
        prazo_s: float | None = None,
    ) -> Resposta:
        """POST em `base + caminho`. Devolve `Resposta`, ou levanta `ErroDoServico`."""
        return self._pedir(
            "POST",
            caminho,
            corpo=corpo,
            tipo_do_corpo=tipo_do_corpo,
            chave=chave,
            cabecalho_da_chave=cabecalho_da_chave,
            prefixo_da_chave=prefixo_da_chave,
            cabecalhos=cabecalhos,
            cancelado=cancelado,
            prazo_s=prazo_s,
        )

    def obter(
        self,
        caminho: str,
        *,
        chave: Chave,
        cabecalho_da_chave: str = "Authorization",
        prefixo_da_chave: str = "Bearer ",
        prazo_s: float | None = None,
    ) -> Resposta:
        """GET em `base + caminho` — consulta de catálogo (vozes), nunca dado do dono."""
        return self._pedir(
            "GET",
            caminho,
            corpo=None,
            tipo_do_corpo="",
            chave=chave,
            cabecalho_da_chave=cabecalho_da_chave,
            prefixo_da_chave=prefixo_da_chave,
            cabecalhos=None,
            cancelado=nunca_cancelado,
            prazo_s=prazo_s,
        )

    def _pedir(
        self,
        metodo: str,
        caminho: str,
        *,
        corpo: bytes | None,
        tipo_do_corpo: str,
        chave: Chave,
        cabecalho_da_chave: str,
        prefixo_da_chave: str,
        cabecalhos: Mapping[str, str] | None,
        cancelado: Cancelado,
        prazo_s: float | None,
    ) -> Resposta:
        if cancelado():
            # Antes do socket: epoch morto não paga requisição (regra 6 da §3.3).
            self.nao_enviadas_por_cancelamento += 1
            return Resposta(cancelada=True)
        proibir_nuvem_real_em_ci(self.base, self.ambiente)
        pedido = urllib.request.Request(  # noqa: S310 — esquema conferido abaixo
            url=self.base.rstrip("/") + caminho,
            data=corpo,
            method=metodo,
        )
        if pedido.type not in {"http", "https"}:
            raise ErroDoServico(f"esquema {pedido.type!r} não é http(s)")
        if corpo is not None:
            pedido.add_header("Content-Type", tipo_do_corpo)
            pedido.add_header("Content-Length", str(len(corpo)))
        # A chave vai **no cabeçalho**: nunca na URL (fica em log de proxy), nunca no corpo.
        pedido.add_header(cabecalho_da_chave, f"{prefixo_da_chave}{chave.usar()}")
        # Sem isto o urllib se anuncia `Python-urllib/3.x`, e o Cloudflare da Groq responde
        # `403 error code: 1010` (assinatura de cliente barrada) antes de olhar a chave —
        # provado ao vivo em 2026-10-17 com o turbo. Um UA próprio resolve e diz quem somos.
        pedido.add_header("User-Agent", AGENTE_DO_USUARIO)
        for nome, valor in (cabecalhos or {}).items():
            pedido.add_header(nome, valor)
        self.chamadas += 1
        prazo = self.prazo_s if prazo_s is None else prazo_s
        try:
            with self.abrir(pedido, timeout=prazo) as resposta:
                lida = _ler_cancelavel(resposta, cancelado=cancelado)
        except urllib.error.HTTPError as erro:
            detalhe = redigir(erro.read().decode("utf-8", "replace")[:500], [chave])
            if erro.code in STATUS_QUE_VIRAM_DEGRADACAO or erro.code >= 500:
                raise ErroDoServico(f"{erro.code} do serviço: {detalhe}") from None
            if erro.code == 403 and "1010" in detalhe:
                raise ServicoRecusou(
                    f"o serviço barrou este cliente antes de olhar a chave (403, "
                    f"{detalhe.strip()}): "
                    "é a proteção do Cloudflare contra assinatura de cliente desconhecida, não "
                    "problema de chave nem de modelo. Atualize o Jarvis; se persistir, tente "
                    "outra rede ou VPN"
                ) from None
            raise ServicoRecusou(
                f"o serviço recusou o pedido ({erro.code}): {detalhe}. Isto não é falta de "
                "rede — confira a chave, o plano, o modelo e o motor escolhido"
            ) from None
        except urllib.error.URLError as erro:
            # `URLError` carrega o motivo do sistema (DNS, recusa de conexão). Não carrega
            # chave, mas passa por `redigir` de qualquer forma: é barato e fecha a porta.
            raise ErroDoServico(
                redigir(f"não deu para falar com o serviço: {erro.reason}", [chave])
            ) from None
        if lida.cancelada:
            self.bytes_descartados += lida.bytes_descartados
        return lida


def campos_sem_segredo(campos: Mapping[str, str], chaves: Sequence[Chave] = ()) -> None:
    """Confere que nenhum campo do corpo contém chave. Chamado antes de montar o pedido.

    Parece paranoia e é barato: o corpo vai para disco em log de serviço de terceiro, e um
    refactor que passe a chave para o lugar errado não pode falhar silenciosamente.
    """
    for nome, valor in campos.items():
        for chave in chaves:
            if chave.valor and chave.valor in str(valor):
                raise ErroDoServico(
                    f"o campo {nome!r} do corpo contém o valor de {chave.variavel}: a chave vai "
                    "no cabeçalho, não no corpo"
                )


def ambiente_tem(variavel: str, ambiente: Mapping[str, str] | None = None) -> bool:
    return bool(ambiente_ou_os(ambiente).get(variavel, "").strip())
