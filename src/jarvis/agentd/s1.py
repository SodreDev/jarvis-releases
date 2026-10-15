"""S1: a reação de 20–100 ms como tabela auditável (cartão F1-08).

**A reação rápida não é efeito colateral do LLM.** Ela é uma tabela de decisão em arquivo de
dados (`tabelas/s1.v1.json`), avaliada de cima para baixo: a primeira linha cujas condições
batem decide. Cada linha tem `porque` escrito e um teste no repositório — é isso que faz dela
algo que o dono pode auditar, em vez de um emaranhado de `if`.

As cinco ações são as da §2: `ouvir | backchannel | ceder | falar | cancelar`. Só **uma** linha
leva a `falar`, e só **uma** produz som sem ser nossa vez (`backchannel`).

**Três garantias duras, cada uma numa linha da tabela:**

- **orçamento** — estourou o teto de 100 ms? Cai em `ouvir`, nunca em `falar`. Decidir com
  orçamento vencido é decidir com informação velha;
- **epoch morto** — evento de epoch menor que o atual não produz fala (§3.3 regra 6);
- **`unknown` não vira fala** — a mesma regra do detector de turno (F1-07): sem confiança, não
  interrompe e não toma o turno.

O S1 **não escolhe o que dizer** — isso é o `s2` (F2). Ele escolhe entre as cinco reações.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.audio_io.trilha import EventoDeTrilha

ARQUIVO_TABELA: Final = Path(__file__).resolve().parents[3] / "tabelas" / "s1.v1.json"
TETO_MS: Final = 100.0
"""Teto do orçamento da §2 (20–100 ms). Passar daqui cai em `ouvir`."""
SUFIXOS_NUMERICOS: Final[tuple[str, ...]] = ("_min", "_max")


class Acao(StrEnum):
    """As cinco reações da §2."""

    OUVIR = "ouvir"
    BACKCHANNEL = "backchannel"
    CEDER = "ceder"
    FALAR = "falar"
    CANCELAR = "cancelar"


class ErroDeTabela(ValueError):
    """Tabela inválida: condição desconhecida, ação fora das cinco, linha sem `porque`."""


@dataclass(frozen=True, slots=True)
class EstadoS1:
    """O que o S1 sabe no instante da decisão. Tudo vem de evento, nada de adivinhação."""

    epoch_atual: int = 0
    epoch_do_evento: int = 0
    aec_ok: bool = True
    fala_do_dono: bool = False
    tocando: bool = False
    decisao_de_turno: str = "ausente"
    p_eot: float = 0.0
    duracao_fala_ms: float = 0.0
    orcamento_estourado: bool = False

    @property
    def epoch_morto(self) -> bool:
        return self.epoch_do_evento < self.epoch_atual

    def valor(self, chave: str) -> Any:
        if chave == "epoch_morto":
            return self.epoch_morto
        return getattr(self, chave)


@dataclass(frozen=True, slots=True)
class Linha:
    """Uma linha da tabela: condições, ação e o porquê (que vai para a auditoria)."""

    id: str
    quando: dict[str, Any]
    entao: Acao
    porque: str

    def bate(self, estado: EstadoS1) -> bool:
        for chave, esperado in self.quando.items():
            if chave.endswith("_min"):
                if float(estado.valor(chave.removesuffix("_min"))) < float(esperado):
                    return False
            elif chave.endswith("_max"):
                if float(estado.valor(chave.removesuffix("_max"))) > float(esperado):
                    return False
            elif estado.valor(chave) != esperado:
                return False
        return True


@dataclass(frozen=True, slots=True)
class Decisao:
    """A ação escolhida e **qual linha** a escolheu — sem isso não há auditoria."""

    acao: Acao
    linha: str
    porque: str

    @property
    def produz_som(self) -> bool:
        return self.acao in (Acao.FALAR, Acao.BACKCHANNEL)


@dataclass(frozen=True, slots=True)
class Tabela:
    """A tabela carregada do arquivo de dados, validada na carga."""

    versao: int
    linhas: tuple[Linha, ...]
    condicoes_aceitas: frozenset[str]

    @classmethod
    def do_arquivo(cls, caminho: Path = ARQUIVO_TABELA) -> Tabela:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        aceitas = frozenset(dados["condicoes_aceitas"])
        linhas: list[Linha] = []
        for bruto in dados["linhas"]:
            quando = dict(bruto["quando"])
            for chave in quando:
                base = chave
                for sufixo in SUFIXOS_NUMERICOS:
                    base = base.removesuffix(sufixo)
                if chave not in aceitas and base not in {
                    c.removesuffix("_min").removesuffix("_max") for c in aceitas
                }:
                    raise ErroDeTabela(
                        f"{bruto['id']}: condição {chave!r} não está em condicoes_aceitas"
                    )
            if not str(bruto.get("porque", "")).strip():
                raise ErroDeTabela(f"{bruto['id']}: linha sem `porque` não é auditável")
            try:
                acao = Acao(bruto["entao"])
            except ValueError as erro:
                raise ErroDeTabela(
                    f"{bruto['id']}: ação {bruto['entao']!r} não é uma das cinco da §2"
                ) from erro
            linhas.append(
                Linha(id=str(bruto["id"]), quando=quando, entao=acao, porque=str(bruto["porque"]))
            )
        if not linhas:
            raise ErroDeTabela("tabela vazia")
        if linhas[-1].quando:
            raise ErroDeTabela(
                "a última linha tem condição: sem saída padrão, um estado não previsto deixaria "
                "o S1 sem decisão"
            )
        return cls(versao=int(dados["versao"]), linhas=tuple(linhas), condicoes_aceitas=aceitas)

    def decidir(self, estado: EstadoS1) -> Decisao:
        """Primeira linha que bate. A última não tem condição, então sempre há decisão."""
        for linha in self.linhas:
            if linha.bate(estado):
                return Decisao(acao=linha.entao, linha=linha.id, porque=linha.porque)
        raise ErroDeTabela("nenhuma linha bateu — a tabela perdeu a saída padrão")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(linha.id for linha in self.linhas)


@dataclass(slots=True)
class S1:
    """O S1 com o orçamento aplicado. Determinístico: mesmo estado, mesma decisão."""

    tabela: Tabela = field(default_factory=Tabela.do_arquivo)
    teto_ms: float = TETO_MS
    decisoes: int = 0

    def decidir(self, estado: EstadoS1, *, gasto_ms: float = 0.0) -> Decisao:
        """Decide. `gasto_ms` é o tempo já gasto desde a chegada do evento."""
        if gasto_ms > self.teto_ms:
            estado = replace(estado, orcamento_estourado=True)
        self.decisoes += 1
        return self.tabela.decidir(estado)

    def decidir_cronometrando(self, estado: EstadoS1, *, inicio_ns: int) -> tuple[Decisao, float]:
        """Mede o próprio gasto antes de decidir — é assim que o orçamento vale de verdade."""
        gasto_ms = (time.perf_counter_ns() - inicio_ns) / 1e6
        return self.decidir(estado, gasto_ms=gasto_ms), gasto_ms


def estado_da_trilha(
    eventos: Sequence[EventoDeTrilha], *, epoch_atual: int = 0
) -> list[tuple[EventoDeTrilha, EstadoS1]]:
    """Reconstrói o estado do S1 a partir de uma trilha do F1-01, evento por evento.

    É o aceite (e) do cartão: a mesma trilha produz a mesma sequência de decisões. O estado é
    acumulado — `AudioActivity` diz fala e `aec_ok`, `PlaybackProgress` diz que há playback,
    `TurnPrediction` diz a decisão de turno, `Cancel` sobe o epoch.
    """
    fala = False
    aec_ok = True
    tocando = False
    turno = "ausente"
    p_eot = 0.0
    inicio_da_fala_ns: int | None = None
    atual = epoch_atual
    saida: list[tuple[EventoDeTrilha, EstadoS1]] = []
    for evento in eventos:
        if evento.type == "AudioActivity":
            fala = bool(evento.payload.get("speech", False))
            aec_ok = bool(evento.payload.get("aec_ok", True))
            if fala and inicio_da_fala_ns is None:
                inicio_da_fala_ns = evento.ts_mono_ns
            if not fala:
                inicio_da_fala_ns = None
        elif evento.type == "PlaybackProgress":
            tocando = True
        elif evento.type == "TurnPrediction":
            turno = str(evento.payload.get("decision", "ausente"))
            p_eot = float(evento.payload.get("p_eot", 0.0))
        elif evento.type == "Cancel":
            atual = max(atual, evento.epoch)
            tocando = False
        duracao = (
            0.0 if inicio_da_fala_ns is None else (evento.ts_mono_ns - inicio_da_fala_ns) / 1e6
        )
        saida.append(
            (
                evento,
                EstadoS1(
                    epoch_atual=atual,
                    epoch_do_evento=evento.epoch,
                    aec_ok=aec_ok,
                    fala_do_dono=fala,
                    tocando=tocando,
                    decisao_de_turno=turno,
                    p_eot=p_eot,
                    duracao_fala_ms=duracao,
                ),
            )
        )
    return saida


def decisoes_da_trilha(
    eventos: Sequence[EventoDeTrilha], *, s1: S1 | None = None, epoch_atual: int = 0
) -> list[Decisao]:
    motor = s1 if s1 is not None else S1()
    return [
        motor.decidir(estado) for _, estado in estado_da_trilha(eventos, epoch_atual=epoch_atual)
    ]
