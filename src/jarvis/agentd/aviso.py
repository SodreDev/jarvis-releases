"""O aviso de degradação dito em voz alta — **uma** vez (cartão F1-14, aceite (e)).

Quem fala é o `agentd`, porque é ele que tem o TTS e o epoch (§3.2). A garantia de "uma vez"
não está aqui: está em `jarvis.rede.reservar_aviso_por_voz`, que **grava a reserva antes** de
alguém sintetizar. Então mesmo que o `agentd` morra no meio da síntese, o dono perde um aviso
em vez de ouvir o mesmo aviso em loop — e perder um aviso é o lado certo para errar.

O que fica declarado como lacuna: aqui o aviso é sintetizado e **registrado**, não entregue ao
dispositivo. A ponte de pedaços de TTS do `agentd` para o playback do `audio-io` é a mesma que
o F1-11 exercita em processo, e o caminho até a placa de som é o F1-16.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.agentd.tts import MotorDeTts, MotorParametrico, SintetizadorEmStreaming
from jarvis.rede import reservar_aviso_por_voz

ARQUIVO_AVISO: Final = "aviso-por-voz.jsonl"


@dataclass(frozen=True, slots=True)
class AvisoFalado:
    frase: str
    amostras: int
    epoch: int


def falar_aviso(
    raiz: Path,
    *,
    motor: MotorDeTts | None = None,
    session_id: str = "",
    epoch: int = 0,
) -> AvisoFalado | None:
    """Sintetiza o aviso reservado, ou devolve `None` quando não há o que dizer."""
    frase = reservar_aviso_por_voz(raiz)
    if frase is None:
        return None
    sintetizador = SintetizadorEmStreaming(
        motor=motor or MotorParametrico(), session_id=session_id, epoch=epoch
    )
    fala = sintetizador.falar(frase, chunk_id=f"aviso-{epoch}")
    aviso = AvisoFalado(frase=frase, amostras=fala.amostras_sintetizadas, epoch=epoch)
    with (raiz / ARQUIVO_AVISO).open("a", encoding="utf-8") as arquivo:
        arquivo.write(
            json.dumps(
                {"frase": aviso.frase, "amostras": aviso.amostras, "epoch": aviso.epoch},
                ensure_ascii=False,
            )
            + "\n"
        )
    return aviso


def avisos_falados(raiz: Path) -> list[AvisoFalado]:
    """O que já foi dito em voz alta. É em cima disto que o teste prova que não repete."""
    caminho = raiz / ARQUIVO_AVISO
    if not caminho.exists():
        return []
    avisos: list[AvisoFalado] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        dados = json.loads(linha)
        avisos.append(
            AvisoFalado(
                frase=str(dados["frase"]),
                amostras=int(dados["amostras"]),
                epoch=int(dados["epoch"]),
            )
        )
    return avisos
