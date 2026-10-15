"""audio-io — captura e playback, perto do dispositivo (SPEC §2).

Responsabilidade: AEC, redução de ruído, AGC, VAD barato, captura em frames de
20 ms, playback cancelável, `PlaybackProgress` com `played_ms` real.

Proibições: não decide turno, não fala com LLM.

O banco de teste (cartão F1-01) é o que faz tudo isto ser verificável sem microfone:
`FonteDeAudio` e `SumidouroDeAudio` têm implementação de arquivo, sintética e de
dispositivo real, a escolha vem de `JARVIS_AUDIO_BACKEND`, e o tempo vem de um
`Relogio` injetado.
"""

from __future__ import annotations

from jarvis.audio_io.ambiente import (
    VARIAVEL_BACKEND,
    VARIAVEL_CI,
    Backend,
    backend_escolhido,
    em_ci,
    proibir_dispositivo_em_ci,
)
from jarvis.audio_io.backend import fonte_do_ambiente, sumidouro_do_ambiente
from jarvis.audio_io.energia import LIMIAR_PADRAO_DB, DetectorDeEnergia
from jarvis.audio_io.erros import (
    DispositivoIndisponivel,
    DispositivoProibidoEmCI,
    ErroDeAudio,
    FormatoNaoSuportado,
)
from jarvis.audio_io.fontes import (
    FonteDeArquivo,
    FonteDeAudio,
    FonteDeDispositivo,
    FonteSintetica,
)
from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_QUADRO,
    MS_POR_QUADRO,
    PISO_DB,
    TAXA_PADRAO,
    Quadro,
    como_int16,
    de_int16,
    em_quadros,
    energia_db,
)
from jarvis.audio_io.replay import Reproducao, atividade, reproduzir
from jarvis.audio_io.sintese import (
    ROTEIRO_PADRAO,
    TipoDeTrecho,
    Trecho,
    aplicar_ganho_db,
    atrasar,
    eco,
    fala_simulada,
    gerar,
    misturar,
    ruido_rosa,
    silencio,
)
from jarvis.audio_io.sumidouros import (
    SumidouroDeArquivo,
    SumidouroDeAudio,
    SumidouroDeDispositivo,
    SumidouroEmMemoria,
)
from jarvis.audio_io.trilha import Divergencia, EventoDeTrilha

__all__ = [
    "AMOSTRAS_POR_QUADRO",
    "BYTES_POR_QUADRO",
    "LIMIAR_PADRAO_DB",
    "MS_POR_QUADRO",
    "PISO_DB",
    "ROTEIRO_PADRAO",
    "TAXA_PADRAO",
    "VARIAVEL_BACKEND",
    "VARIAVEL_CI",
    "Backend",
    "DetectorDeEnergia",
    "DispositivoIndisponivel",
    "DispositivoProibidoEmCI",
    "Divergencia",
    "ErroDeAudio",
    "EventoDeTrilha",
    "FonteDeArquivo",
    "FonteDeAudio",
    "FonteDeDispositivo",
    "FonteSintetica",
    "FormatoNaoSuportado",
    "Quadro",
    "Reproducao",
    "SumidouroDeArquivo",
    "SumidouroDeAudio",
    "SumidouroDeDispositivo",
    "SumidouroEmMemoria",
    "TipoDeTrecho",
    "Trecho",
    "aplicar_ganho_db",
    "atividade",
    "atrasar",
    "backend_escolhido",
    "como_int16",
    "de_int16",
    "eco",
    "em_ci",
    "em_quadros",
    "energia_db",
    "fala_simulada",
    "fonte_do_ambiente",
    "gerar",
    "misturar",
    "proibir_dispositivo_em_ci",
    "reproduzir",
    "ruido_rosa",
    "silencio",
    "sumidouro_do_ambiente",
]
