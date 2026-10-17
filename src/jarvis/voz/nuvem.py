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
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http.client import HTTPResponse
from typing import Any, Final
from urllib.parse import urlparse

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


@dataclass(slots=True)
class ClienteHttp:
    """Um POST (ou GET de catálogo) com prazo nosso, cabeçalho com a chave e corpo cancelável.

    Não guarda a `Chave`: recebe por chamada. É o que mantém o segredo com tempo de vida curto
    e fora do `repr` de qualquer objeto de longa duração.
    """

    base: str
    prazo_s: float = 10.0
    ambiente: Mapping[str, str] | None = None
    abrir: Any = field(default=urllib.request.urlopen, repr=False)
    """Injetável para o teste poder olhar o pedido sem subir servidor, quando é isso que se
    quer provar. Nos testes de caminho inteiro quem responde é um servidor de verdade."""

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
