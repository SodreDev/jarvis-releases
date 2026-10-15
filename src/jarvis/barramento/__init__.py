"""Barramento de eventos: a fronteira entre os sete processos (SPEC §3, ADR-0007).

O contrato mora em `schemas/events.v1.json` e `schemas/event_log.sql` — dados, não código —
para que a decisão D1 (linguagem do núcleo, cartão F0-04) não implique reescrever o
contrato. Este pacote é a implementação de referência em Python.
"""

from jarvis.barramento.contrato import (
    ErroDeContrato,
    TipoDesconhecido,
    prioridade_canonica,
    validar,
    validar_bruto,
)
from jarvis.barramento.entrada import Fronteira, Recebido, receber
from jarvis.barramento.envelope import (
    Envelope,
    Fonte,
    Prioridade,
    Tipo,
    Trust,
    uuid7,
)
from jarvis.barramento.epoch import (
    DonoDoEpoch,
    EpochMorto,
    LivroDeFala,
    Veredito,
)
from jarvis.barramento.fila import FilaCheia, FilaDePrioridade, chave_de_coalescing
from jarvis.barramento.log import CadeiaRompida, LogDeEventos, Registro

__all__ = [
    "CadeiaRompida",
    "DonoDoEpoch",
    "Envelope",
    "EpochMorto",
    "ErroDeContrato",
    "FilaCheia",
    "FilaDePrioridade",
    "Fonte",
    "Fronteira",
    "LivroDeFala",
    "LogDeEventos",
    "Prioridade",
    "Recebido",
    "Registro",
    "Tipo",
    "TipoDesconhecido",
    "Trust",
    "Veredito",
    "chave_de_coalescing",
    "prioridade_canonica",
    "receber",
    "uuid7",
    "validar",
    "validar_bruto",
]
