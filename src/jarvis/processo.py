"""Base dos processos clientes do barramento (SPEC §2): conecta, reage, persiste cursor.

Cada um dos seis processos fora do `agentd` é um laço pequeno e determinístico: recebe um
envelope, devolve zero ou mais envelopes. Nenhum deles decide política nem executa shell; o
que cada um pode fazer está na docstring do pacote correspondente.

O cursor (último `seq` visto) fica em arquivo na pasta de execução: quem reinicia pede do
cursor e o corretor repõe o que passou — é o que faz "matar e reabrir" não perder log.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.barramento.envelope import Envelope
from jarvis.barramento.ipc import Canal, conectar

Reacao = Callable[["Processo", Envelope, str], list[Envelope]]


@dataclass(slots=True)
class Processo:
    """Um processo cliente ligado ao barramento."""

    nome: str
    raiz: Path
    reacao: Reacao
    session_id: str = ""
    epoch: int = 0
    canal: Canal | None = field(default=None, init=False)
    publicados: int = field(default=0, init=False)

    @property
    def arquivo_cursor(self) -> Path:
        return self.raiz / f"cursor-{self.nome}"

    @property
    def cursor(self) -> int:
        if not self.arquivo_cursor.exists():
            return 0
        texto = self.arquivo_cursor.read_text(encoding="utf-8").strip()
        return int(texto) if texto else 0

    def gravar_cursor(self, seq: int) -> None:
        self.arquivo_cursor.write_text(str(seq), encoding="utf-8")

    def abrir(self) -> None:
        canal = conectar(self.raiz, self.nome)
        canal.enviar({"registro": self.nome, "desde_seq": self.cursor})
        ack = canal.receber(timeout=10.0)
        if ack is None or ack.get("ack") != self.nome:
            raise RuntimeError(f"{self.nome}: barramento não confirmou o registro")
        self.session_id = str(ack["session_id"])
        self.epoch = int(ack["epoch"])
        self.canal = canal

    def fechar(self) -> None:
        if self.canal is not None:
            self.canal.fechar()
            self.canal = None

    def publicar(self, envelope: Envelope) -> None:
        if self.canal is None:
            raise RuntimeError(f"{self.nome} não está conectado")
        self.canal.enviar({"publicar": envelope.para_dict()})
        self.publicados += 1

    def recebidos(self, *, timeout: float | None = None) -> Iterator[tuple[Envelope, str]]:
        """Envelopes entregues pelo corretor, com o veredito de epoch."""
        if self.canal is None:
            raise RuntimeError(f"{self.nome} não está conectado")
        while True:
            quadro: dict[str, Any] | None = self.canal.receber(timeout=timeout)
            if quadro is None:
                return
            evento = quadro.get("evento")
            if not isinstance(evento, dict):
                continue
            envelope = Envelope.de_dict(evento)
            self.epoch = max(self.epoch, envelope.epoch)
            yield envelope, str(quadro.get("veredito", "aceitar"))
            self.gravar_cursor(int(quadro.get("seq", 0)))

    def rodar(self, *, timeout: float | None = None) -> None:
        """Laço de trabalho: cada evento recebido vira zero ou mais eventos publicados."""
        for envelope, veredito in self.recebidos(timeout=timeout):
            for resposta in self.reacao(self, envelope, veredito):
                self.publicar(resposta)


def analisador(nome: str) -> argparse.ArgumentParser:
    analisa = argparse.ArgumentParser(prog=f"jarvis.{nome}")
    analisa.add_argument("--raiz", type=Path, required=True, help="pasta de execução da sessão")
    analisa.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="segundos sem evento antes de encerrar (padrão: nunca)",
    )
    return analisa


def rodar_processo(nome: str, reacao: Reacao, argv: list[str] | None = None) -> int:
    """Ponto de entrada comum dos seis processos clientes."""
    args = analisador(nome).parse_args(argv)
    processo = Processo(nome=nome, raiz=args.raiz, reacao=reacao)
    processo.abrir()
    try:
        processo.rodar(timeout=args.timeout)
    finally:
        processo.fechar()
    return 0
