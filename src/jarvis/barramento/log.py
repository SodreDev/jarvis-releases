"""Log de eventos append-only encadeado por hash (§3, §5.5; esquema em `schemas/event_log.sql`).

Cada registro carrega o sha256 do anterior, e o próprio sha256 cobre o registro inteiro mais
esse elo. Consequência prática: adulterar ou remover um registro quebra a verificação da
cadeia a partir dali — edição silenciosa deixa de existir.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

from jarvis.barramento.envelope import Envelope

GENESE: Final = "0" * 64
ARQUIVO_ESQUEMA: Final = Path(__file__).resolve().parents[3] / "schemas" / "event_log.sql"

CAMPOS_ASSINADOS: Final = (
    "seq",
    "event_id",
    "session_id",
    "epoch",
    "ts_mono_ns",
    "ts_wall",
    "source",
    "trust",
    "priority",
    "type",
    "payload_json",
    "prev_sha256",
)


class CadeiaRompida(RuntimeError):
    """A verificação achou registro adulterado, faltando ou fora de ordem."""


def _canonico(registro: dict[str, Any]) -> bytes:
    """Serialização determinística do que entra no hash — mesma em qualquer linguagem."""
    return json.dumps(
        {campo: registro[campo] for campo in CAMPOS_ASSINADOS},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def hash_do_registro(registro: dict[str, Any]) -> str:
    return hashlib.sha256(_canonico(registro)).hexdigest()


@dataclass(frozen=True, slots=True)
class Registro:
    seq: int
    envelope: Envelope
    prev_sha256: str
    sha256: str


class LogDeEventos:
    """Escrita só por `anexar`; leitura por `ler`; integridade por `verificar_cadeia`."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self._con = sqlite3.connect(caminho, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(ARQUIVO_ESQUEMA.read_text(encoding="utf-8"))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self._con.close()

    @property
    def ultimo_hash(self) -> str:
        linha = self._con.execute(
            "SELECT sha256 FROM event_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return GENESE if linha is None else str(linha["sha256"])

    def anexar(self, envelope: Envelope) -> Registro:
        """Grava um evento. O `seq` é do banco; o elo é o hash do último registro."""
        bruto = envelope.para_dict()
        with self._con:  # transação: o seq reservado e o hash gravado não se separam
            cursor = self._con.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS proximo FROM event_log")
            seq = int(cursor.fetchone()["proximo"])
            anterior = self.ultimo_hash
            registro = {
                "seq": seq,
                "event_id": bruto["event_id"],
                "session_id": bruto["session_id"],
                "epoch": bruto["epoch"],
                "ts_mono_ns": bruto["ts_mono_ns"],
                "ts_wall": bruto["ts_wall"],
                "source": bruto["source"],
                "trust": bruto["trust"],
                "priority": bruto["priority"],
                "type": bruto["type"],
                "payload_json": json.dumps(
                    bruto["payload"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                "prev_sha256": anterior,
            }
            digest = hash_do_registro(registro)
            self._con.execute(
                """
                INSERT INTO event_log (
                    seq, event_id, session_id, epoch, ts_mono_ns, ts_wall, source, trust,
                    priority, type, payload_json, prev_sha256, sha256
                ) VALUES (
                    :seq, :event_id, :session_id, :epoch, :ts_mono_ns, :ts_wall, :source, :trust,
                    :priority, :type, :payload_json, :prev_sha256, :sha256
                )
                """,
                {**registro, "sha256": digest},
            )
        return Registro(seq=seq, envelope=envelope, prev_sha256=anterior, sha256=digest)

    def maior_seq(self, *, session_id: str | None = None) -> int:
        """Maior `seq` persistido (da sessão, se pedida); 0 quando não há registro.

        É o teto da reposição: cursor acima disto é cursor que não existe, e o corretor
        trata como pedido do começo em vez de entregar nada (achado 6 da revisão F0+F1).
        """
        sql = "SELECT COALESCE(MAX(seq), 0) AS maior FROM event_log"
        parametros: tuple[str, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            parametros = (session_id,)
        return int(self._con.execute(sql, parametros).fetchone()["maior"])

    def ler(self, *, session_id: str | None = None) -> Iterator[Registro]:
        sql = "SELECT * FROM event_log"
        parametros: tuple[str, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            parametros = (session_id,)
        sql += " ORDER BY seq"
        for linha in self._con.execute(sql, parametros):
            yield Registro(
                seq=int(linha["seq"]),
                envelope=Envelope.de_dict(
                    {
                        "schema_version": "1",
                        "event_id": linha["event_id"],
                        "session_id": linha["session_id"],
                        "epoch": linha["epoch"],
                        "ts_mono_ns": linha["ts_mono_ns"],
                        "ts_wall": linha["ts_wall"],
                        "source": linha["source"],
                        "trust": linha["trust"],
                        "priority": linha["priority"],
                        "type": linha["type"],
                        "payload": json.loads(linha["payload_json"]),
                    }
                ),
                prev_sha256=str(linha["prev_sha256"]),
                sha256=str(linha["sha256"]),
            )

    def verificar_cadeia(self) -> int:
        """Recalcula a cadeia inteira. Devolve quantos registros conferem; levanta se não.

        Detecta as três formas de mexer no log: mudar um campo (hash do registro muda),
        remover um registro (elo não bate e o `seq` salta) e reordenar (o `seq` esperado
        não corresponde).
        """
        esperado_prev = GENESE
        conferidos = 0
        for esperado_seq, linha in enumerate(
            self._con.execute("SELECT * FROM event_log ORDER BY seq"), start=1
        ):
            seq = int(linha["seq"])
            if seq != esperado_seq:
                raise CadeiaRompida(f"seq {seq} fora de ordem (esperado {esperado_seq})")
            if str(linha["prev_sha256"]) != esperado_prev:
                raise CadeiaRompida(f"elo quebrado no seq {seq}")
            registro = {campo: linha[campo] for campo in CAMPOS_ASSINADOS}
            recalculado = hash_do_registro(registro)
            if recalculado != str(linha["sha256"]):
                raise CadeiaRompida(f"registro adulterado no seq {seq}")
            esperado_prev = recalculado
            conferidos += 1
        return conferidos
