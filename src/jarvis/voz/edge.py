"""TTS pelo serviço de *read-aloud* do Edge — implementado, e barrado por falta de termos.

**Primeiro, o que o dono precisa saber: isto NÃO é local.** O `edge-tts` não roda modelo
nenhum na máquina; ele abre um WebSocket para `speech.platform.bing.com` com o token de
cliente do navegador Edge e recebe o áudio pronto. O texto que o Jarvis ia falar **sai da
máquina**, exatamente como na ElevenLabs — a diferença é que aqui não há conta, não há chave
e, principalmente, **não há contrato para ler**.

**Por que o portão o recusa por padrão.** A ADR-0017 fechou que campo de termo vazio barra o
motor ("no v0, 'não verificado' não liga nuvem"), e os quatro campos do `tts-edge` estão
vazios porque não existe página de termos para esse uso — o README do pacote nem declara
vínculo com a Microsoft. O caminho oficial com contrato é o Azure Speech, que é outro motor.
Para o dono poder testar assim mesmo, existe uma saída **explícita e por motor**:
`nuvem_sem_termos = ["tts-edge"]` na configuração dele. Com ela, o aviso passa a dizer, em
primeiro lugar, que não há termos verificados — e continua dizendo isso toda vez.

**O que este caminho custa em licença, medido aqui e não suposto:**

1. `edge-tts` declara **LGPL-3.0** (PyPI 7.3.1). Entra como **extra opcional**, instalado pelo
   dono (`uv sync --group edge`), nunca como dependência do produto e nunca distribuído junto;
2. o serviço devolve **MP3** e o pacote não deixa escolher formato (`MP3_BITRATE_BPS` é
   constante, não parâmetro). O caminho de áudio deste produto é PCM16 16 kHz (F1-01), então
   é preciso **decodificar** — e o decodificador é um programa externo (`ffmpeg`), chamado com
   `argv` explícito, em processo separado. O `ffmpeg` do projeto é LGPL-2.1+, mas **o build
   desta máquina pode ser GPL** (`--enable-gpl`), e isso muda a conversa de licença do produto.
   Por isso `abrir()` lê a licença do build local e a publica em `licenca_do_decodificador`,
   em vez de o registro afirmar o que não pode saber.

Dois custos de licença e zero contrato: é o que torna este motor uma opção de teste, não o
padrão. Escrever o protocolo do WebSocket à mão não melhoraria nada disso — tiraria a LGPL e
deixaria os outros dois problemas (sem contrato, e MP3 para decodificar) de pé, trocando-os
por manutenção de um protocolo não documentado que a Microsoft muda quando quer.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, CANAIS, TAXA_PADRAO
from jarvis.rede import AdaptadorRemoto, Sonda, SondaInjetada
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.nuvem import ErroDoServico
from jarvis.voz.registro import Motor, exigir_motor

REGISTRADO: Final = "tts-edge"
SERVICO: Final = "Microsoft (read-aloud do Edge)"
VOZ_PADRAO: Final = "pt-BR-AntonioNeural"
PRAZO_PADRAO_S: Final = 15.0
DECODIFICADOR: Final = "ffmpeg"
PRAZO_DO_DECODIFICADOR_S: Final = 10.0


class ExtraAusente(RuntimeError):
    """O extra opcional não está instalado. A mensagem diz o comando."""


class DecodificadorAusente(RuntimeError):
    """Não há `ffmpeg` para transformar o MP3 do serviço em PCM16."""


def licenca_do_ffmpeg(executavel: str = DECODIFICADOR) -> str:
    """O que o build **desta máquina** declara: LGPL por padrão, GPL com `--enable-gpl`.

    O registro não pode afirmar isso — ele descreve o projeto, não o pacote que o dono
    instalou. Ler a primeira linha e procurar as marcas de configuração é barato e é a
    diferença entre "o FFmpeg é LGPL" e "o seu FFmpeg é GPL".
    """
    try:
        saida = subprocess.run(  # noqa: S603 — argv explícito, sem shell (CONTRIBUTING 6)
            [executavel, "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PRAZO_DO_DECODIFICADOR_S,
        ).stdout
    except (OSError, subprocess.SubprocessError) as erro:
        raise DecodificadorAusente(
            f"{executavel} não respondeu: o caminho do Edge precisa dele para decodificar o "
            f"MP3 do serviço ({erro.__class__.__name__})"
        ) from None
    configuracao = next(
        (linha for linha in saida.splitlines() if linha.startswith("configuration:")), ""
    )
    if "--enable-gpl" in configuracao:
        versao3 = " e --enable-version3" if "--enable-version3" in configuracao else ""
        return f"GPL (build local com --enable-gpl{versao3})"
    return "LGPL-2.1-or-later (build local sem --enable-gpl)"


def mp3_para_pcm16(
    mp3: bytes,
    *,
    taxa: int = TAXA_PADRAO,
    executavel: str = DECODIFICADOR,
    prazo_s: float = PRAZO_DO_DECODIFICADOR_S,
) -> bytes:
    """MP3 → PCM16 mono na nossa taxa, por processo separado com `argv` explícito."""
    argumentos = [
        executavel,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(taxa),
        "-ac",
        str(CANAIS),
        "pipe:1",
    ]
    try:
        concluido = subprocess.run(  # noqa: S603 — argv explícito, sem shell
            argumentos, input=mp3, capture_output=True, check=False, timeout=prazo_s
        )
    except FileNotFoundError:
        raise DecodificadorAusente(
            f"{executavel} não está nesta máquina. O serviço do Edge só devolve MP3, e o "
            "caminho de áudio do Jarvis é PCM16 16 kHz: sem decodificador, este motor não "
            "fala. Instale o ffmpeg ou use o motor local (piper + epitran)"
        ) from None
    except subprocess.TimeoutExpired:
        raise ErroDoServico(f"{executavel} passou de {prazo_s}s decodificando") from None
    if concluido.returncode != 0:
        detalhe = concluido.stderr.decode("utf-8", "replace")[:200]
        raise ErroDoServico(f"{executavel} recusou o áudio do serviço: {detalhe}")
    if len(concluido.stdout) % BYTES_POR_AMOSTRA != 0:
        raise ErroDoServico("a saída do decodificador não é PCM16")
    return concluido.stdout


def _fluxo_do_edge_tts(texto: str, voz: str, prazo_s: float) -> Iterator[bytes]:  # pragma: no cover
    """Os pedaços de MP3 que o serviço manda. Só este trecho toca a rede.

    Fica isolado numa função de propósito: é o que os testes substituem para exercitar
    decodificação, cancelamento e portão **sem** falar com a Microsoft.
    """
    import asyncio

    try:
        import edge_tts
    except ImportError as erro:
        raise ExtraAusente(
            "edge-tts não está instalado: é extra opcional (LGPL-3.0), fora do produto. "
            "Rode `uv sync --group edge` se quiser testar este motor"
        ) from erro

    async def juntar() -> list[bytes]:
        pedacos: list[bytes] = []
        comunicacao = edge_tts.Communicate(texto, voz, receive_timeout=int(prazo_s))
        async for evento in comunicacao.stream():
            if evento.get("type") == "audio":
                pedacos.append(bytes(evento["data"]))
        return pedacos

    yield from asyncio.run(juntar())


@dataclass(slots=True)
class MotorTtsEdge:
    """Voz do read-aloud do Edge, atrás da mesma interface — e barrada por padrão."""

    raiz: Path
    voz: str = VOZ_PADRAO
    registrado: str = REGISTRADO
    nuvem_ligada: Collection[str] = ()
    sem_termos_aceitos: Collection[str] = ()
    """O que o dono escreveu em `nuvem_sem_termos` na configuração dele. Sem isto, o portão
    recusa — e com isto o aviso começa dizendo que não há termos verificados."""
    cancelado: Cancelado = nunca_cancelado
    prazo_s: float = PRAZO_PADRAO_S
    sonda: Sonda | None = None
    ambiente: Mapping[str, str] | None = None
    fluxo: Callable[[str, str, float], Iterator[bytes]] = _fluxo_do_edge_tts
    decodificar: Callable[[bytes], bytes] = mp3_para_pcm16

    nome: str = "edge-tts"
    licenca: str = ""
    licenca_do_decodificador: str = ""
    onde: Onde = Onde.NUVEM
    sinteses: int = 0
    caracteres_enviados: int = 0
    descartadas_por_cancelamento: int = 0
    bytes_descartados: int = 0
    _motor: Motor | None = field(default=None, repr=False)
    _adaptador: AdaptadorRemoto | None = field(default=None, repr=False)

    def abrir(self) -> Motor:
        motor = exigir_motor(
            self.registrado,
            nuvem_ligada=self.nuvem_ligada,
            sem_termos_aceitos=self.sem_termos_aceitos,
        )
        self.licenca = motor.licenca_do_cliente
        self._motor = motor
        self.licenca_do_decodificador = licenca_do_ffmpeg()
        self._adaptador = AdaptadorRemoto(
            servico=SERVICO,
            raiz=self.raiz,
            sonda=self.sonda if self.sonda is not None else SondaInjetada(ligada=True),
            prazo_s=self.prazo_s,
        )
        return motor

    @property
    def aviso(self) -> str:
        motor = self._motor or exigir_motor(
            self.registrado,
            nuvem_ligada=[self.registrado],
            sem_termos_aceitos=[self.registrado],
        )
        return motor.frase_de_aviso

    @property
    def degradado(self) -> bool:
        return self._adaptador is not None and self._adaptador.degradado

    def sintetizar(self, texto: str) -> bytes:
        if self._adaptador is None:
            self.abrir()
        adaptador = self._adaptador
        assert adaptador is not None

        if self.cancelado():
            self.descartadas_por_cancelamento += 1
            return b""

        self.sinteses += 1
        self.caracteres_enviados += len(texto)
        call_id = f"tts-edge-{self.sinteses}"

        def fazer(prazo: float) -> bytes | None:
            recebido = bytearray()
            for pedaco in self.fluxo(texto, self.voz, prazo):
                if self.cancelado():
                    # Mesmo contrato dos outros motores de nuvem: o que chegou é descartado,
                    # não decodificado e não tocado.
                    self.descartadas_por_cancelamento += 1
                    self.bytes_descartados += len(recebido)
                    return None
                recebido += pedaco
            if not recebido:
                return b""
            return self.decodificar(bytes(recebido))

        amostras = adaptador.chamar(fazer, call_id=call_id)
        return amostras if amostras is not None else b""
