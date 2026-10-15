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

from jarvis.audio_io.aec import CadeiaDeAec, MotivoDeFalha, Processado, quadros_de
from jarvis.audio_io.ambiente import (
    VARIAVEL_BACKEND,
    VARIAVEL_CI,
    Backend,
    backend_escolhido,
    em_ci,
    proibir_dispositivo_em_ci,
)
from jarvis.audio_io.backend import fonte_do_ambiente, sumidouro_do_ambiente
from jarvis.audio_io.captura import Captura
from jarvis.audio_io.dsp import (
    CanceladorDeEco,
    ControleDeGanho,
    SupressorDeRuido,
    erle_db,
    para_bytes,
    para_float,
)
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
from jarvis.audio_io.playback import (
    Cancelamento,
    FilaDePlayback,
    Pedaco,
    em_pedacos,
)
from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_AMOSTRA,
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
    "BYTES_POR_AMOSTRA",
    "BYTES_POR_QUADRO",
    "LIMIAR_PADRAO_DB",
    "MS_POR_QUADRO",
    "PISO_DB",
    "ROTEIRO_PADRAO",
    "TAXA_PADRAO",
    "VARIAVEL_BACKEND",
    "VARIAVEL_CI",
    "Backend",
    "CadeiaDeAec",
    "CanceladorDeEco",
    "Cancelamento",
    "Captura",
    "ControleDeGanho",
    "DetectorDeEnergia",
    "DispositivoIndisponivel",
    "DispositivoProibidoEmCI",
    "Divergencia",
    "ErroDeAudio",
    "EventoDeTrilha",
    "FilaDePlayback",
    "FonteDeArquivo",
    "FonteDeAudio",
    "FonteDeDispositivo",
    "FonteSintetica",
    "FormatoNaoSuportado",
    "MotivoDeFalha",
    "Pedaco",
    "Processado",
    "Quadro",
    "Reproducao",
    "SumidouroDeArquivo",
    "SumidouroDeAudio",
    "SumidouroDeDispositivo",
    "SumidouroEmMemoria",
    "SupressorDeRuido",
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
    "em_pedacos",
    "em_quadros",
    "energia_db",
    "erle_db",
    "fala_simulada",
    "fonte_do_ambiente",
    "gerar",
    "misturar",
    "para_bytes",
    "para_float",
    "proibir_dispositivo_em_ci",
    "quadros_de",
    "reproduzir",
    "ruido_rosa",
    "silencio",
    "sumidouro_do_ambiente",
]
