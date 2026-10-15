"""O lado do `audio-io` do controle de microfone (cartão F1-13).

Quem manda é o dono, pelo arquivo de pedido que a `ui` escreve (`jarvis.microfone`); quem
**relata** é este módulo, com o que a fonte está fazendo de verdade. A assimetria é o ponto do
cartão: a `ui` pede e observa, e nenhuma das duas pontas pode fingir estado.

Três coisas que o cartão cobra e estão aqui:

- **PTT abre e fecha a fonte**, não filtra depois de capturar: tecla solta é fonte fechada, e
  fonte fechada é zero amostra puxada do dispositivo. Filtrar amostra já capturada deixaria o
  áudio do dono passar pela nossa memória sem ele querer;
- **o *kill switch* corta captura e playback.** A fonte fica fechada e o playback silenciado;
- **sem dispositivo, o erro vira frase**, não exceção que derruba o processo: a `ui` precisa do
  motivo para oferecer o modo de arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.captura import Captura
from jarvis.audio_io.erros import ErroDeAudio
from jarvis.microfone import EstadoDaFonte, Modo, Pedido, escrever_estado, ler_pedido

TICKS_ENTRE_ESCRITAS: Final = 12
"""12 quadros de 20 ms ≈ 250 ms: a `ui` não precisa de contagem a 50 Hz, e escrever todo tick
seria 50 renomeações por segundo para nada. Mudança de estado **visível** escreve na hora."""


@dataclass(slots=True)
class ControleDoMicrofone:
    """Aplica o pedido do dono na fonte e publica o estado real. Um tick, uma decisão."""

    raiz: Path
    captura: Captura
    modo_inicial: Modo = Modo.ESCUTA
    """O que valer quando a `ui` ainda não pediu nada — é o que o `audio-io` recebeu na linha
    de comando. Sem `--capturar`, quem sobe a sessão não quer microfone aberto."""

    pedido: Pedido = field(init=False)
    indisponivel: str | None = None
    amostras_na_abertura: int = 0
    silenciar_playback: bool = False
    escritas: int = 0
    _ultimo_publicado: EstadoDaFonte | None = field(default=None, repr=False)
    _ticks: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self.pedido = Pedido(modo=self.modo_inicial)

    @property
    def estado(self) -> EstadoDaFonte:
        """O estado **observado**: `aberta` é a fonte, `amostras` é desta abertura."""
        aberta = self.captura.aberta
        return EstadoDaFonte(
            aberta=aberta,
            amostras=(self.captura.amostras_capturadas - self.amostras_na_abertura)
            if aberta
            else 0,
            amostras_totais=self.captura.amostras_capturadas,
            device_id=self.captura.fonte.device_id if aberta else None,
            indisponivel=self.indisponivel,
            modo=self.pedido.modo,
        )

    def tick(self) -> EstadoDaFonte:
        """Lê o pedido, aplica na fonte e publica o estado. Chamado uma vez por quadro."""
        pedido = ler_pedido(self.raiz)
        if pedido is not None:
            self.pedido = pedido
        self._aplicar()
        self.silenciar_playback = self.pedido.modo is Modo.DESLIGADO
        return self._publicar()

    def _aplicar(self) -> None:
        quer = self.pedido.quer_fonte_aberta
        if quer and not self.captura.aberta:
            self._abrir()
        elif not quer and self.captura.aberta:
            self.captura.fechar()

    def _abrir(self) -> None:
        try:
            self.captura.abrir()
        except ErroDeAudio as erro:
            # Sem dispositivo a `ui` tem de poder explicar e oferecer o modo de arquivo; um
            # traceback no `audio-io` deixaria a tela muda (aceite (d) do cartão).
            self.indisponivel = str(erro)
            return
        self.indisponivel = None
        self.amostras_na_abertura = self.captura.amostras_capturadas

    def _publicar(self) -> EstadoDaFonte:
        estado = self.estado
        self._ticks += 1
        visivel = (estado.aberta, estado.indisponivel, estado.modo)
        anterior = self._ultimo_publicado
        mudou = anterior is None or visivel != (
            anterior.aberta,
            anterior.indisponivel,
            anterior.modo,
        )
        if mudou or self._ticks >= TICKS_ENTRE_ESCRITAS:
            escrever_estado(self.raiz, estado)
            self._ultimo_publicado = estado
            self.escritas += 1
            self._ticks = 0
        return estado
