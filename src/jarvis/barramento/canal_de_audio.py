"""Canal de áudio entre `audio-io` e `agentd`: fora do barramento, com `epoch` no cabeçalho.

**Por que fora do barramento.** O diagrama da §2 manda "frames + PlaybackProgress" do `audio-io`
para o `agentd`, mas nenhum dos onze tipos da §3.2 carrega PCM — e não deveria carregar: o log
encadeado da F0-02 guarda **todo** evento, e gravar 50 quadros por segundo de áudio bruto num
log append-only seria encher o disco com o que a §9 chama de "nada de áudio bruto por padrão".
Então o áudio anda por um canal próprio, e o barramento continua carregando **decisões**.

**Por que `epoch` primeiro no cabeçalho.** Descartar quadro de epoch morto (§3.3 regra 6) tem de
custar uma leitura de 4 bytes, não a desserialização do quadro. O cabeçalho é
`epoch, seq, ts_mono_ns, amostras` — nessa ordem, e empacotado com `struct` para a leitura ser
barata e o formato ser o mesmo em qualquer linguagem (o `audio-io` pode virar Rust depois, como
a ADR-0014 previu).

**Três implementações, escolhidas por número** (ADR-0015):

- `CanalDeSocket` — *socket* de domínio Unix em modo datagrama: a fronteira do quadro é a do
  datagrama, então não existe enquadramento para errar. **Não existe no Windows** (o Python de
  lá não tem `AF_UNIX` em datagrama), e isso é uma falha de P11;
- `CanalDeAnel` — anel em memória compartilhada, um produtor e um consumidor, com número de
  sequência no **começo e no fim** de cada posição. Escrita em `memoryview` não é atômica em
  Python; a sequência repetida nas duas pontas é o que deixa o leitor **detectar** quadro
  escrito pela metade em vez de consumi-lo torto;
- `CanalDeConexao` — `multiprocessing.Connection`, que é o que o barramento já usa na F0-03:
  preserva fronteira de mensagem e é **portátil** (canal nomeado no Windows, socket no Unix).

**Áudio atrasado é áudio inútil:** nenhum dos três bloqueia o produtor quando enche — o anel
passa por cima do mais velho, o *socket* e a `Connection` recusam o quadro novo — e o descarte é
contado em `descartados`. Travar a captura para não perder quadro seria o oposto do que o SLO-1
quer. No Windows a `Connection` é canal nomeado e não existe pergunta de espaço (`select` só
aceita *socket* lá): o envio pode bloquear, e isso é a mesma lacuna de P11 que a ADR-0015 declara.
"""

from __future__ import annotations

import select
import socket
import struct
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from jarvis.audio_io.quadro import BYTES_POR_QUADRO, TAXA_PADRAO, Quadro

FORMATO_CABECALHO: Final = "<IIQI"
"""`epoch, seq, ts_mono_ns, amostras` — little endian, campos fixos, `epoch` primeiro."""
TAMANHO_CABECALHO: Final = struct.calcsize(FORMATO_CABECALHO)
FORMATO_SELO: Final = "<Q"
TAMANHO_SELO: Final = struct.calcsize(FORMATO_SELO)
ARQUIVO_DO_CANAL: Final = "audio.sock"
"""O canal de áudio tem endereço próprio ao lado do barramento, na mesma pasta de sessão."""
CAPACIDADE_PADRAO: Final = 64
"""Posições do anel: 64 quadros de 20 ms = 1,28 s de folga antes de começar a descartar."""
FORMATO_CONTADOR: Final = "<Q"
DESLOCAMENTO_DOS_DADOS: Final = 64
"""Cabeçalho do anel (contador e geometria) nos primeiros 64 bytes, para alinhar as posições."""


class ErroDeCanal(RuntimeError):
    """Canal mal configurado ou fechado."""


@dataclass(frozen=True, slots=True)
class Cabecalho:
    """O que vem antes das amostras. `epoch` primeiro: é a decisão mais barata do caminho."""

    epoch: int
    seq: int
    ts_mono_ns: int
    amostras: int

    def empacotar(self) -> bytes:
        return struct.pack(FORMATO_CABECALHO, self.epoch, self.seq, self.ts_mono_ns, self.amostras)

    @classmethod
    def desempacotar(cls, bruto: bytes) -> Cabecalho:
        epoch, seq, ts, amostras = struct.unpack(FORMATO_CABECALHO, bruto[:TAMANHO_CABECALHO])
        return cls(epoch=epoch, seq=seq, ts_mono_ns=ts, amostras=amostras)


@runtime_checkable
class CanalDeAudio(Protocol):
    """Quadros de 20 ms de um processo para outro, com descarte do mais velho."""

    nome: str
    descartados: int

    def enviar(self, quadro: Quadro, *, epoch: int) -> bool: ...

    def receber(self, *, epoch_minimo: int = 0) -> tuple[Cabecalho, Quadro] | None: ...

    def fechar(self) -> None: ...


def _quadro_de(cabecalho: Cabecalho, amostras: bytes, taxa: int) -> Quadro:
    return Quadro(
        indice=cabecalho.seq, amostras=amostras, ts_mono_ns=cabecalho.ts_mono_ns, taxa=taxa
    )


@dataclass(slots=True)
class CanalDeSocket:
    """Datagrama em *socket* de domínio Unix: a fronteira do quadro é a do datagrama.

    Em Windows não existe `AF_UNIX` em modo datagrama no Python, e a alternativa é *named pipe*
    (o que o `multiprocessing.Connection` já usa no barramento). Isso está **declarado** na
    ADR-0015 como lacuna de P11 desta implementação.
    """

    envio: socket.socket
    recepcao: socket.socket
    taxa: int = TAXA_PADRAO
    nome: str = "socket-unix-datagrama"
    descartados: int = 0
    _seq: int = 0

    @classmethod
    def par(cls, *, taxa: int = TAXA_PADRAO, folga: int = CAPACIDADE_PADRAO) -> CanalDeSocket:
        """Par conectado, para o produtor e o consumidor que já compartilham o processo pai."""
        esquerda, direita = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        tamanho = folga * (TAMANHO_CABECALHO + BYTES_POR_QUADRO)
        for lado in (esquerda, direita):
            lado.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, tamanho)
            lado.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, tamanho)
        esquerda.setblocking(False)
        direita.setblocking(False)
        return cls(envio=esquerda, recepcao=direita, taxa=taxa)

    def enviar(self, quadro: Quadro, *, epoch: int) -> bool:
        self._seq += 1
        cabecalho = Cabecalho(
            epoch=epoch, seq=self._seq, ts_mono_ns=quadro.ts_mono_ns, amostras=quadro.n_amostras
        )
        try:
            self.envio.send(cabecalho.empacotar() + quadro.amostras)
        except BlockingIOError:
            # Fila do socket cheia: o consumidor não acompanha. Descartar é a política.
            self.descartados += 1
            return False
        return True

    def receber(self, *, epoch_minimo: int = 0) -> tuple[Cabecalho, Quadro] | None:
        while True:
            try:
                bruto = self.recepcao.recv(TAMANHO_CABECALHO + BYTES_POR_QUADRO)
            except BlockingIOError:
                return None
            cabecalho = Cabecalho.desempacotar(bruto)
            if cabecalho.epoch < epoch_minimo:
                self.descartados += 1
                continue  # §3.3 regra 6: quadro de epoch morto não sobe a cadeia
            amostras = bruto[TAMANHO_CABECALHO:]
            return cabecalho, _quadro_de(cabecalho, amostras, self.taxa)

    def fechar(self) -> None:
        self.envio.close()
        self.recepcao.close()


@dataclass(slots=True)
class CanalDeAnel:
    """Anel em memória compartilhada, um produtor e um consumidor.

    Cada posição guarda `selo | cabeçalho | amostras | selo`. O produtor escreve os dados e
    **depois** os dois selos com o número da posição; o consumidor só aceita a posição quando os
    dois selos batem com o que ele espera. Selo diferente significa uma de duas coisas, e as
    duas são descarte: o produtor está escrevendo ali agora, ou já passou por cima (o consumidor
    ficou para trás mais de uma volta).
    """

    memoria: shared_memory.SharedMemory
    capacidade: int = CAPACIDADE_PADRAO
    taxa: int = TAXA_PADRAO
    dono: bool = False
    nome: str = "anel-em-memoria-compartilhada"
    descartados: int = 0
    _lido: int = 0
    _visao: memoryview = field(init=False, repr=False)

    def __post_init__(self) -> None:
        visao = self.memoria.buf
        if visao is None:  # pragma: no cover — memória fechada antes do uso
            raise ErroDeCanal("memória compartilhada sem buffer: já foi fechada?")
        self._visao = visao

    # --- geometria -------------------------------------------------------------------
    @property
    def bytes_por_posicao(self) -> int:
        return TAMANHO_SELO + TAMANHO_CABECALHO + BYTES_POR_QUADRO + TAMANHO_SELO

    @classmethod
    def tamanho_necessario(cls, capacidade: int = CAPACIDADE_PADRAO) -> int:
        por_posicao = TAMANHO_SELO + TAMANHO_CABECALHO + BYTES_POR_QUADRO + TAMANHO_SELO
        return DESLOCAMENTO_DOS_DADOS + capacidade * por_posicao

    @classmethod
    def criar(cls, *, capacidade: int = CAPACIDADE_PADRAO, taxa: int = TAXA_PADRAO) -> CanalDeAnel:
        memoria = shared_memory.SharedMemory(create=True, size=cls.tamanho_necessario(capacidade))
        canal = cls(memoria=memoria, capacidade=capacidade, taxa=taxa, dono=True)
        canal._gravar_contador(0)
        return canal

    @classmethod
    def anexar(
        cls, nome_da_memoria: str, *, capacidade: int = CAPACIDADE_PADRAO, taxa: int = TAXA_PADRAO
    ) -> CanalDeAnel:
        memoria = shared_memory.SharedMemory(name=nome_da_memoria)
        return cls(memoria=memoria, capacidade=capacidade, taxa=taxa, dono=False)

    @property
    def nome_da_memoria(self) -> str:
        return str(self.memoria.name)

    # --- produtor --------------------------------------------------------------------
    def _contador(self) -> int:
        return int(struct.unpack_from(FORMATO_CONTADOR, self._visao, 0)[0])

    def _gravar_contador(self, valor: int) -> None:
        struct.pack_into(FORMATO_CONTADOR, self._visao, 0, valor)

    def _inicio(self, numero: int) -> int:
        return DESLOCAMENTO_DOS_DADOS + (numero % self.capacidade) * self.bytes_por_posicao

    def enviar(self, quadro: Quadro, *, epoch: int) -> bool:
        numero = self._contador() + 1
        inicio = self._inicio(numero)
        cabecalho = Cabecalho(
            epoch=epoch, seq=numero, ts_mono_ns=quadro.ts_mono_ns, amostras=quadro.n_amostras
        )
        meio = inicio + TAMANHO_SELO
        fim = meio + TAMANHO_CABECALHO
        self._visao[meio:fim] = cabecalho.empacotar()
        self._visao[fim : fim + BYTES_POR_QUADRO] = quadro.amostras
        # Os selos vão por último: antes deles, a posição é "em escrita" para o consumidor.
        struct.pack_into(FORMATO_SELO, self._visao, inicio, numero)
        struct.pack_into(FORMATO_SELO, self._visao, fim + BYTES_POR_QUADRO, numero)
        self._gravar_contador(numero)
        return True

    # --- consumidor ------------------------------------------------------------------
    def receber(self, *, epoch_minimo: int = 0) -> tuple[Cabecalho, Quadro] | None:
        while True:
            escrito = self._contador()
            if self._lido >= escrito:
                return None
            atrasado = escrito - self._lido
            if atrasado > self.capacidade:
                # Ficou mais de uma volta atrás: o que havia já foi sobrescrito.
                perdidos = atrasado - self.capacidade
                self.descartados += perdidos
                self._lido = escrito - self.capacidade
            proximo = self._lido + 1
            inicio = self._inicio(proximo)
            meio = inicio + TAMANHO_SELO
            fim = meio + TAMANHO_CABECALHO
            selo_inicial = int(struct.unpack_from(FORMATO_SELO, self._visao, inicio)[0])
            dados = bytes(self._visao[fim : fim + BYTES_POR_QUADRO])
            bruto_cabecalho = bytes(self._visao[meio:fim])
            selo_final = int(
                struct.unpack_from(FORMATO_SELO, self._visao, fim + BYTES_POR_QUADRO)[0]
            )
            if selo_inicial != proximo or selo_final != proximo:
                # Em escrita agora, ou já sobrescrito: nos dois casos, este quadro se perdeu.
                self.descartados += 1
                self._lido = proximo
                continue
            self._lido = proximo
            cabecalho = Cabecalho.desempacotar(bruto_cabecalho)
            if cabecalho.epoch < epoch_minimo:
                self.descartados += 1
                continue
            return cabecalho, _quadro_de(cabecalho, dados, self.taxa)

    def fechar(self) -> None:
        self._visao.release()
        self.memoria.close()
        if self.dono:
            self.memoria.unlink()


def canal_do_ambiente(*, capacidade: int = CAPACIDADE_PADRAO) -> CanalDeAudio:
    """O canal escolhido pela ADR-0015: `multiprocessing.Connection`.

    Trocar de implementação é trocar esta linha. A escolha **não** foi por latência (os três
    candidatos ficam ~1 000× abaixo do período de 20 ms do quadro): foi por **P11** — a
    `Connection` é a única das três que roda nos dois sistemas sem código separado, e é o mesmo
    transporte que o barramento já usa desde a F0-03. O anel fica no repositório como
    alternativa **medida**, para quando o `audio-io` virar Rust (ADR-0014) e quiser cópia zero.
    """
    _ = capacidade  # a Connection usa o buffer do sistema; a folga é dele
    return CanalDeConexao.par()


def endereco_do_audio(raiz: Path) -> tuple[str, str]:
    """Endereço do canal de áudio: o mesmo esquema do barramento, arquivo próprio.

    Reaproveita `jarvis.barramento.ipc.endereco` em tudo — pasta 0700, limite de `sun_path`,
    *named pipe* no Windows — trocando só o nome, porque dois ouvintes não cabem num endereço.
    """
    from jarvis.barramento.ipc import endereco

    alvo, familia = endereco(raiz)
    if familia == "AF_PIPE":
        return alvo + "-audio", familia
    return str(Path(alvo).with_name(ARQUIVO_DO_CANAL)), familia


def descrever_formato(destino: Path | None = None) -> str:
    """O formato do quadro no canal, em texto — para quem reimplementar em outra linguagem."""
    texto = (
        f"cabeçalho: {FORMATO_CABECALHO} (epoch u32, seq u32, ts_mono_ns u64, amostras u32) "
        f"= {TAMANHO_CABECALHO} bytes; amostras: PCM16 little endian, "
        f"{BYTES_POR_QUADRO} bytes por quadro de 20 ms a {TAXA_PADRAO} Hz; "
        f"anel: selo u64 antes e depois de cada posição, contador u64 no deslocamento 0."
    )
    if destino is not None:
        destino.write_text(texto + "\n", encoding="utf-8")
    return texto


@dataclass(slots=True)
class CanalDeConexao:
    """`multiprocessing.Connection`: a fronteira de mensagem já vem feita, e é portátil.

    É o mesmo transporte do barramento (F0-03), então não há tecnologia nova para manter, e
    funciona no Windows (canal nomeado) sem código separado — o que nem o `AF_UNIX` em
    datagrama nem o nome da memória compartilhada entregam de graça.

    O preço: a `Connection` **bloqueia** quando o buffer do sistema enche, e áudio atrasado é
    áudio inútil. Por isso o envio só acontece quando `ha_espaco_para_enviar` diz que há espaço,
    e o resto é descarte contado — a mesma política dos outros dois. No Windows essa pergunta
    não tem resposta (ver `ha_espaco_para_enviar`) e o envio volta a poder bloquear: lacuna de
    P11 da ADR-0015, não política.
    """

    envio: Any
    recepcao: Any
    taxa: int = TAXA_PADRAO
    nome: str = "multiprocessing-connection"
    descartados: int = 0
    ouvinte: Any = None
    recebidos: int = 0
    _seq: int = 0

    @classmethod
    def par(cls, *, taxa: int = TAXA_PADRAO) -> CanalDeConexao:
        """Par no mesmo processo (ou em filho por `fork`): é o que a medição usa."""
        from multiprocessing import Pipe

        recepcao, envio = Pipe(duplex=False)
        return cls(envio=envio, recepcao=recepcao, taxa=taxa)

    @classmethod
    def escutar(cls, raiz: Path, *, taxa: int = TAXA_PADRAO) -> CanalDeConexao:
        """O **consumidor** escuta (é o `agentd`, que também é o corretor do barramento).

        O `accept` bloqueia, e o `agentd` não pode parar o laço de 20 ms esperando conexão —
        então ele acontece numa linha de execução de fundo, e `receber` devolve `None` até o
        produtor aparecer. Endereço e chave são os mesmos do barramento (`AF_UNIX` no Linux,
        `AF_PIPE` no Windows, HMAC por sessão): canal de áudio novo não inventa autenticação.
        """
        from multiprocessing.connection import Listener

        from jarvis.barramento.ipc import ler_chave

        alvo, familia = endereco_do_audio(raiz)
        if familia == "AF_UNIX":
            Path(alvo).unlink(missing_ok=True)
        ouvinte = Listener(alvo, family=familia, authkey=ler_chave(raiz))
        canal = cls(envio=None, recepcao=None, taxa=taxa, ouvinte=ouvinte)
        linha = threading.Thread(target=canal._aceitar, name="canal-de-audio", daemon=True)
        linha.start()
        return canal

    @classmethod
    def conectar(
        cls, raiz: Path, *, taxa: int = TAXA_PADRAO, tentativas: int = 50, espera: float = 0.1
    ) -> CanalDeConexao:
        """O **produtor** conecta (é o `audio-io`), com a mesma espera do barramento."""
        from multiprocessing.connection import Client

        from jarvis.barramento.ipc import ErroDeIPC, ler_chave

        alvo, familia = endereco_do_audio(raiz)
        chave = ler_chave(raiz)
        for _ in range(tentativas):
            try:
                return cls(
                    envio=Client(alvo, family=familia, authkey=chave), recepcao=None, taxa=taxa
                )
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                time.sleep(espera)
        raise ErroDeIPC(f"canal de áudio não respondeu em {alvo}")

    def _aceitar(self) -> None:
        try:
            self.recepcao = self.ouvinte.accept() if self.ouvinte is not None else None
        except OSError:  # pragma: no cover — ouvinte fechado antes de alguém conectar
            self.recepcao = None

    def ha_espaco_para_enviar(self) -> bool:
        """Cabe um quadro inteiro agora, sem o envio ficar pendurado?

        No Linux a pergunta é `select` de escrita no descritor, e ela também é o que impede
        mensagem partida pela metade: o pipe só aparece pronto quando cabem `PIPE_BUF` bytes
        (4 KiB) e o `AF_UNIX` em fluxo só quando três quartos do buffer estão livres — os dois
        com folga sobre os 664 bytes de um quadro. No Windows a `Connection` é canal nomeado e
        o `select` de lá só aceita *socket*: sem resposta, respondemos `True` e o envio pode
        bloquear (lacuna de P11, declarada na ADR-0015 e no docstring da classe).
        """
        if sys.platform == "win32":  # pragma: no cover — P11: o CI do Windows ainda não rodou
            return True
        try:
            descritor = self.envio.fileno()
        except (OSError, ValueError):  # pragma: no cover — ponta já fechada
            return True
        return bool(select.select([], [descritor], [], 0)[1])

    def enviar(self, quadro: Quadro, *, epoch: int) -> bool:
        if self.envio is None:
            self.descartados += 1
            return False
        self._seq += 1
        if not self.ha_espaco_para_enviar():
            # Buffer do sistema cheio: o consumidor não acompanha. Bloquear aqui seria travar o
            # laço de 20 ms da captura e queimar o SLO-1 em silêncio; descartar e contar é a
            # política. O `seq` já foi gasto de propósito: o buraco na contagem é o que deixa
            # o consumidor ver que houve perda (é o que o `CanalDeSocket` já fazia).
            self.descartados += 1
            return False
        cabecalho = Cabecalho(
            epoch=epoch, seq=self._seq, ts_mono_ns=quadro.ts_mono_ns, amostras=quadro.n_amostras
        )
        try:
            self.envio.send_bytes(cabecalho.empacotar() + quadro.amostras)
        except BlockingIOError:  # pragma: no cover — corrida: encheu entre a pergunta e o envio
            self.descartados += 1
            return False
        except (BrokenPipeError, OSError):
            self.descartados += 1
            return False
        return True

    def receber(self, *, epoch_minimo: int = 0) -> tuple[Cabecalho, Quadro] | None:
        while True:
            if self.recepcao is None:
                return None  # o produtor ainda não conectou
            if not self.recepcao.poll():
                return None
            try:
                bruto = self.recepcao.recv_bytes()
            except (EOFError, OSError):
                return None
            cabecalho = Cabecalho.desempacotar(bruto)
            if cabecalho.epoch < epoch_minimo:
                self.descartados += 1
                continue
            self.recebidos += 1
            return cabecalho, _quadro_de(cabecalho, bruto[TAMANHO_CABECALHO:], self.taxa)

    def fechar(self) -> None:
        for ponta in (self.envio, self.recepcao, self.ouvinte):
            if ponta is not None:
                with suppress(OSError):
                    ponta.close()
