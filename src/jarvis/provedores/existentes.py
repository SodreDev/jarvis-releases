"""Os dois motores de conversa que já existiam, atrás da interface de provedor (ADR-0056).

- **eco** (local): repete o que o dono disse, sem rede e sem conta — o padrão (ADR-0025, D18);
- **CLI do Claude** (nuvem): o `claude -p` em stream (ADR-0018, ADR-0025), agora com o esforço do
  preset (`--effort`). A CLI não tem comando oficial de listar modelos, então a lista é a do
  registro: os apelidos que a referência da CLI documenta e os ids dos modelos atuais.

Nenhum dos dois mudou de comportamento: o motor é o mesmo objeto de antes, só que montado aqui.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.provedores.interface import Capacidades, ListagemIndisponivel, Modelo
from jarvis.s2.motor import MotorDeConversa
from jarvis.s2.motor_claude_cli import COMANDO_PADRAO, MotorClaudeCli
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.registro import Motor
from jarvis.voz.s2_provisorio import RespostaDeEco

NOME_DO_ECO = "eco (repete o que você disse)"


@dataclass(slots=True)
class ProvedorEco:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return Onde.LOCAL

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        return (
            Modelo(
                "eco",
                "repete o que você disse",
                Capacidades(visao=False, ferramentas=False, esforcos=()),
            ),
        )

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        eco = RespostaDeEco()
        return MotorRoteirizado(
            resposta=lambda contexto: eco.responder(contexto.turno), nome=NOME_DO_ECO
        )


@dataclass(slots=True)
class ProvedorClaudeCli:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)
    comando: Sequence[str] = COMANDO_PADRAO

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return Onde.NUVEM

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        raise ListagemIndisponivel("a CLI do Claude não tem comando oficial de listar modelos")

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        self.pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
        return MotorClaudeCli(
            pasta_de_trabalho=self.pasta_de_trabalho,
            comando=self.comando,
            modelo=modelo,
            esforco=esforco,
            ambiente=self.ambiente,
        )


__all__ = ["NOME_DO_ECO", "ProvedorClaudeCli", "ProvedorEco"]
