"""Histórico de turno: só o que o dono **ouviu** (regra 4 da §3.3, cartões F1-11 e F1-12).

"Texto enfileirado e não tocado não existe para o modelo." Então a entrada de histórico não sai
do texto que mandamos sintetizar: sai do `PlaybackProgress`, que conta amostras **consumidas
pelo sumidouro**, passado pelo mapa texto ↔ amostras do F1-09.

Cada entrada carrega `epoch` e `played_ms`, porque é isso que torna o histórico auditável: dá
para cruzar com o log encadeado (F0-02) e ver que o que o modelo lembra é o que saiu no
alto-falante.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from jarvis.agentd.tts import Fala
from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.barramento.envelope import Envelope, Tipo
from jarvis.barramento.log import LogDeEventos


@dataclass(frozen=True, slots=True)
class EntradaDeHistorico:
    """Uma fala nossa, do jeito que o dono ouviu."""

    epoch: int
    chunk_id: str
    played_ms: int
    texto: str
    truncada: bool

    @property
    def amostras(self) -> int:
        return int(self.played_ms * TAXA_PADRAO / 1000)


@dataclass(slots=True)
class Historico:
    """O histórico do turno, construído a partir de `PlaybackProgress`."""

    entradas: list[EntradaDeHistorico] = field(default_factory=list)

    def registrar(
        self, progresso: Envelope, fala: Fala, *, amostras_tocadas: int
    ) -> EntradaDeHistorico:
        """Anota o que tocou. `amostras_tocadas` é o total consumido pelo sumidouro no turno."""
        if progresso.type is not Tipo.PLAYBACK_PROGRESS:
            raise ValueError(f"histórico só registra PlaybackProgress, não {progresso.type}")
        texto = fala.texto_ate(amostras_tocadas)
        entrada = EntradaDeHistorico(
            epoch=int(progresso.payload["epoch"]),
            chunk_id=str(progresso.payload["chunk_id"]),
            played_ms=int(progresso.payload["played_ms"]),
            texto=texto,
            truncada=texto != fala.texto,
        )
        self.entradas.append(entrada)
        return entrada

    @property
    def texto_ouvido(self) -> str:
        """O que o dono ouviu no turno: o prefixo mais longo registrado."""
        return max((e.texto for e in self.entradas), key=len, default="")

    @property
    def played_ms_total(self) -> int:
        return max((e.played_ms for e in self.entradas), default=0)

    def contem(self, trecho: str) -> bool:
        """`True` se algum texto registrado contém o trecho — usado para provar ausência."""
        alvo = trecho.strip()
        return bool(alvo) and any(alvo in e.texto for e in self.entradas)

    def entradas_do_epoch(self, epoch: int) -> list[EntradaDeHistorico]:
        return [e for e in self.entradas if e.epoch == epoch]

    def para_log(self) -> list[dict[str, object]]:
        """O que vai para o log encadeado (F0-02): texto, epoch e played_ms."""
        return [
            {
                "epoch": e.epoch,
                "chunk_id": e.chunk_id,
                "played_ms": e.played_ms,
                "texto": e.texto,
                "truncada": e.truncada,
            }
            for e in self.entradas
        ]


def texto_nao_tocado(fala: Fala, amostras_tocadas: int) -> str:
    """O sufixo que foi sintetizado e **não** saiu: é o que não pode existir no histórico."""
    return fala.texto[len(fala.texto_ate(amostras_tocadas)) :]


def falas_truncadas(entradas: Sequence[EntradaDeHistorico]) -> list[EntradaDeHistorico]:
    return [e for e in entradas if e.truncada]


@dataclass(frozen=True, slots=True)
class Retomada:
    """O que o `s2` recebe quando o dono diz "continua" (regra 5 da §3.3).

    **Só o trecho tocado.** O plano antigo não volta: o que foi enfileirado e não saiu não
    existe para o modelo, então ele não pode ser "retomado" — o modelo decide o que dizer agora
    a partir do que o dono ouviu. É por isso que esta estrutura **não tem** campo para o sufixo
    não tocado: a ausência é a garantia.
    """

    ouvido: str
    epoch: int
    played_ms: int

    @property
    def contexto(self) -> str:
        """O texto que vai para o `s2` decidir a retomada."""
        return self.ouvido

    def ressuscita(self, texto_antigo: str) -> bool:
        """`True` se o contexto traria de volta algo que o dono não ouviu — tem de ser falso."""
        faltante = texto_antigo[len(self.ouvido) :].strip()
        return bool(faltante) and faltante in self.contexto


def retomar(historico: Historico, *, epoch: int) -> Retomada:
    """Monta a retomada a partir do histórico: o prefixo tocado e mais nada."""
    return Retomada(
        ouvido=historico.texto_ouvido,
        epoch=epoch,
        played_ms=historico.played_ms_total,
    )


def anexar_ao_log(log: LogDeEventos, progressos: Sequence[Envelope]) -> list[int]:
    """Grava os `PlaybackProgress` no log encadeado (F0-02) e devolve os `seq` gravados.

    O histórico **é** o log, não uma cópia: cada entrada vem de um `PlaybackProgress`, que já
    carrega `epoch`, `chunk_id` e `played_ms`. Gravar ali é o que torna o histórico auditável —
    mexer num `played_ms` depois quebra a cadeia de hash, e o `verificar_cadeia` acusa. Guardar
    o histórico num arquivo à parte permitiria editar o que o modelo "lembra" sem deixar rastro.
    """
    seqs: list[int] = []
    for progresso in progressos:
        if progresso.type is not Tipo.PLAYBACK_PROGRESS:
            raise ValueError(f"o histórico só grava PlaybackProgress, não {progresso.type}")
        seqs.append(log.anexar(progresso).seq)
    return seqs


def do_log(log: LogDeEventos, fala: Fala, *, session_id: str | None = None) -> Historico:
    """Reconstrói o histórico **a partir do log** — a prova de que ele não vive em outro lugar.

    **`played_ms` é por pedaço, não do turno.** O `PlaybackProgress` da §3.2 conta o que saiu
    **daquele** pedaço (F1-03), então o total tocado no turno é a soma dos pedaços — e, quando o
    mesmo pedaço aparece mais de uma vez (progresso periódico), vale o maior valor dele. A
    primeira versão desta função tratava `played_ms` como total do turno e devolvia um histórico
    **mais curto** do que o dono ouviu: o teste de reconstrução pegou.
    """
    historico = Historico()
    por_pedaco: dict[str, int] = {}
    for registro in log.ler(session_id=session_id):
        if registro.envelope.type is not Tipo.PLAYBACK_PROGRESS:
            continue
        chunk = str(registro.envelope.payload["chunk_id"])
        played_ms = int(registro.envelope.payload["played_ms"])
        por_pedaco[chunk] = max(por_pedaco.get(chunk, 0), played_ms)
        total_ms = sum(por_pedaco.values())
        historico.registrar(
            registro.envelope,
            fala,
            amostras_tocadas=int(total_ms * TAXA_PADRAO / 1000),
        )
    return historico
