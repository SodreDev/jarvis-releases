"""Motores de voz atrás de uma interface, local por padrão (ADR-0017).

O pacote tem três camadas, e a ordem importa:

- `interface`: o que um motor é (um bloco entra, um bloco sai) e **de onde ele é** (`Onde`);
- `registro`: se ele pode rodar — licença do cliente, termos de serviço verificados na origem
  e o interruptor da nuvem, que é do dono;
- `chaves`, `groq`, `elevenlabs`, `edge`, `fonemizador`: as implementações.

Importar este pacote não carrega motor nenhum e não abre socket: os adaptadores de nuvem usam
só a biblioteca padrão e os locais importam o runtime deles **dentro** do método que precisa.
"""

from __future__ import annotations

from jarvis.voz.interface import (
    IDIOMA_PADRAO,
    Cancelado,
    Hipotese,
    MotorDeAsr,
    MotorDeTts,
    Onde,
    cancelado_por_epoch,
    nunca_cancelado,
)
from jarvis.voz.registro import (
    ARQUIVO_MOTORES,
    CAMPOS_DE_NUVEM,
    Falta,
    Motor,
    MotorRecusado,
    conferir,
    exigir_motor,
    ler_motores,
    motor_registrado,
    motores_de,
)

__all__ = [
    "ARQUIVO_MOTORES",
    "CAMPOS_DE_NUVEM",
    "IDIOMA_PADRAO",
    "Cancelado",
    "Falta",
    "Hipotese",
    "Motor",
    "MotorDeAsr",
    "MotorDeTts",
    "MotorRecusado",
    "Onde",
    "cancelado_por_epoch",
    "conferir",
    "exigir_motor",
    "ler_motores",
    "motor_registrado",
    "motores_de",
    "nunca_cancelado",
]
