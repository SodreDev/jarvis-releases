"""O processo `audio-io` (SPEC §2): captura em quadros de 20 ms e playback cancelável.

O que este processo faz, e o que ele **não** faz:

- captura pela fonte escolhida em `JARVIS_AUDIO_BACKEND` (cartão F1-01) e publica
  `AudioActivity` com `device_id` e `energy_db`;
- toca pedaços de TTS com `epoch` e, ao receber `Cancel`, **esvazia a fila no mesmo tick**
  (§3.3 regra 2), publicando o `PlaybackProgress` com o `played_ms` que saiu de verdade;
- passa a captura pela cadeia AEC → NR → AGC (cartão F1-04), alimentada pelo **loopback do
  nosso próprio playback**, e relata `aec_ok`. Enquanto `aec_ok` é falso o playback fica
  **pausado**: falar sem referência é se interromper sozinho;
- não decide turno, não fala com LLM e **não emite `Cancel`** — quem emite é o `agentd`
  (§3.2, origem canônica). Este processo reage.

Sem placa de som: o sumidouro padrão é memória (cartão F1-03). O backend de dispositivo real
entra com o hardware do dono (F1-13/F1-16).
"""

from __future__ import annotations

import sys
import time

from jarvis.audio_io.aec import CadeiaDeAec
from jarvis.audio_io.backend import fonte_do_ambiente
from jarvis.audio_io.captura import SEGUNDOS_POR_QUADRO, Captura
from jarvis.audio_io.playback import FilaDePlayback, em_pedacos
from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import gerar
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.processo import Processo, Reacao, analisador
from jarvis.relogio import RelogioDoSistema

DISPOSITIVO_SINTETICO = "sintetico:0"


def atividade(processo: Processo, *, fala: bool) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=processo.epoch,
        source="audio-io",
        trust=Trust.USER_VOICE,
        priority=Prioridade.P0 if fala else Prioridade.P1,
        type=Tipo.AUDIO_ACTIVITY,
        payload={
            "speech": fala,
            "device_id": DISPOSITIVO_SINTETICO,
            "energy_db": -18.0 if fala else -60.0,
            "aec_ok": True,
        },
    )


def reacao_com_playback(fila: FilaDePlayback) -> Reacao:
    """Fecha a reação sobre a fila de playback deste processo."""

    def reagir(_processo: Processo, envelope: Envelope, _veredito: str) -> list[Envelope]:
        if envelope.type is not Tipo.CANCEL:
            return []
        # §3.3 regra 2: esvaziar no mesmo tick, e dizer quanto tocou de verdade.
        cancelamento = fila.cancelar(
            reason=str(envelope.payload["reason"]), epoch_novo=envelope.epoch
        )
        return cancelamento.eventos

    return reagir


def laco_de_20_ms(
    processo: Processo,
    captura: Captura,
    fila: FilaDePlayback,
    relogio: RelogioDoSistema,
    *,
    timeout: float | None,
) -> None:
    """O laço do processo que fica perto do dispositivo: captura, playback e barramento.

    A ordem importa. Primeiro o que é do mundo (captura), depois o que sai para o mundo
    (playback), e só então o barramento — e o barramento é lido **sem bloquear**, porque um
    `Cancel` que chega enquanto esperamos evento não pode esperar o próximo quadro para
    esvaziar a fila (§3.3 regra 2). O ritmo de 20 ms vem da fonte, que dorme no relógio.
    """
    limite = None if timeout is None else relogio.mono_ns() + int(timeout * 1e9)
    while limite is None or relogio.mono_ns() < limite:
        quadros_antes = captura.quadros
        for envelope in captura.tick():
            processo.publicar(envelope)
        # Playback pausado enquanto a referência não vale (cartão F1-04).
        fila.pausado = not captura.aec_ok
        for envelope in fila.tick():
            processo.publicar(envelope)
        for envelope, veredito in processo.recebidos(timeout=0.0):
            for resposta in processo.reacao(processo, envelope, veredito):
                processo.publicar(resposta)
        if captura.quadros == quadros_antes and not captura.privacidade:
            # Fonte esgotada (arquivo acabou): sem isto o laço vira espera ativa.
            relogio.dormir(SEGUNDOS_POR_QUADRO)


def main(argv: list[str] | None = None) -> int:
    analisa = analisador("audio-io")
    analisa.add_argument(
        "--emitir-fala",
        action="store_true",
        help="publica um AudioActivity(speech=True) sintético ao conectar (cartão F0-03)",
    )
    analisa.add_argument(
        "--capturar",
        action="store_true",
        help=(
            "liga a captura de verdade (quadros de 20 ms pela fonte de JARVIS_AUDIO_BACKEND). "
            "No v0 o esqueleto não captura por padrão: quem liga é quem sobe a sessão, e o "
            "botão de privacidade e o PTT são o cartão F1-13"
        ),
    )
    analisa.add_argument(
        "--sem-aec",
        action="store_true",
        help="desliga a cadeia AEC/NR/AGC (serve para o A/B do cartão F1-04)",
    )
    analisa.add_argument(
        "--enfileirar-ms",
        type=float,
        default=0.0,
        help="enfileira este tanto de playback sintético ao conectar (cartão F1-03)",
    )
    args = analisa.parse_args(argv)

    relogio = RelogioDoSistema()
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id="")
    processo = Processo(
        nome="audio-io",
        raiz=args.raiz,
        reacao=reacao_com_playback(fila),
    )
    processo.abrir()
    fila.session_id = processo.session_id
    fila.epoch_atual = processo.epoch
    cadeia = None if args.sem_aec else CadeiaDeAec()
    captura = Captura(
        fonte=fonte_do_ambiente(relogio=relogio),
        relogio=relogio,
        session_id=processo.session_id,
        epoch=processo.epoch,
        cadeia=cadeia,
        tocando=lambda: fila.tocando is not None,
    )
    if cadeia is not None:
        fila.escuta = cadeia.referencia
    try:
        if args.enfileirar_ms > 0:
            audio = gerar(semente=0)
            alvo = int(TAXA_PADRAO * args.enfileirar_ms / 1000) * 2
            fatia = (audio * (alvo // len(audio) + 1))[:alvo]
            for pedaco in em_pedacos(fatia, chunk_id="tts", epoch=processo.epoch):
                fila.enfileirar(pedaco)
        if args.emitir_fala:
            time.sleep(0.2)  # dá tempo de os outros seis se registrarem
            processo.publicar(atividade(processo, fala=True))
        if args.capturar or args.enfileirar_ms > 0:
            captura.abrir()
            laco_de_20_ms(processo, captura, fila, relogio, timeout=args.timeout)
        else:
            processo.rodar(timeout=args.timeout)
    finally:
        captura.fechar()
        processo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
