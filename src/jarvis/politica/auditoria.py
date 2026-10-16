"""Auditoria de política: decisão antes do efeito, encadeada por hash (SPEC §5.5).

Duas tabelas, duas cadeias: a decisão é imutável (`audit_log`) e o resultado chega depois
(`audit_result`), em vez de o resultado reescrever a decisão. Assim "decisão registrada antes
do efeito" não é uma promessa — é a única forma que o banco aceita.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

from jarvis.barramento.envelope import agora_wall, uuid7
from jarvis.dados import caminho

GENESE: Final = "0" * 64
ARQUIVO_ESQUEMA: Final = caminho("schemas/audit_log.sql")

CAMPOS_DA_DECISAO: Final = (
    "seq",
    "decision_id",
    "ts_wall",
    "policy_epoch",
    "session_id",
    "modo",
    "tool_id",
    "raiz",
    "caminho",
    "identidade",
    "argv_json",
    "elevacao",
    "grant_id",
    "veredito",
    "motivo",
    "resultado",
    "sessao_contaminada",
    "prev_sha256",
)
CAMPOS_DO_RESULTADO: Final = (
    "seq",
    "decision_id",
    "ts_wall",
    "resultado",
    "detalhe",
    "prev_sha256",
)


class CadeiaDeAuditoriaRompida(RuntimeError):
    """Registro de auditoria adulterado, faltando ou fora de ordem."""


def _hash(registro: dict[str, Any], campos: tuple[str, ...]) -> str:
    bruto = json.dumps(
        {campo: registro[campo] for campo in campos},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RegistroDeAuditoria:
    seq: int
    decision_id: str
    veredito: str
    motivo: str
    tool_id: str
    modo: str
    identidade: str
    sha256: str


class LogDeAuditoria:
    """Escreve a decisão antes do efeito e anexa o resultado depois."""

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
        with contextlib.suppress(sqlite3.Error):
            self._con.close()

    def _ultimo(self, tabela: str) -> str:
        consulta = (
            "SELECT sha256 FROM audit_log ORDER BY seq DESC LIMIT 1"
            if tabela == "audit_log"
            else "SELECT sha256 FROM audit_result ORDER BY seq DESC LIMIT 1"
        )
        linha = self._con.execute(consulta).fetchone()
        return GENESE if linha is None else str(linha["sha256"])

    def registrar_decisao(
        self,
        *,
        session_id: str,
        policy_epoch: int,
        modo: str,
        tool_id: str,
        raiz: str,
        caminho: str,
        identidade: str,
        argv: dict[str, Any],
        elevacao: bool,
        grant_id: str,
        veredito: str,
        motivo: str,
        sessao_contaminada: bool = False,
    ) -> RegistroDeAuditoria:
        """Grava a decisão. Chamada **antes** de qualquer efeito acontecer."""
        with self._con:
            proximo = int(
                self._con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM audit_log"
                ).fetchone()["n"]
            )
            registro: dict[str, Any] = {
                "seq": proximo,
                "decision_id": uuid7(),
                "ts_wall": agora_wall(),
                "policy_epoch": policy_epoch,
                "session_id": session_id,
                "modo": modo,
                "tool_id": tool_id,
                "raiz": raiz,
                "caminho": caminho,
                "identidade": identidade,
                "argv_json": json.dumps(argv, ensure_ascii=False, sort_keys=True),
                "elevacao": int(elevacao),
                "grant_id": grant_id,
                "veredito": veredito,
                "motivo": motivo,
                "resultado": "",
                "sessao_contaminada": int(sessao_contaminada),
                "prev_sha256": self._ultimo("audit_log"),
            }
            digest = _hash(registro, CAMPOS_DA_DECISAO)
            colunas = ", ".join([*CAMPOS_DA_DECISAO, "sha256"])
            valores = ", ".join(f":{c}" for c in [*CAMPOS_DA_DECISAO, "sha256"])
            self._con.execute(
                f"INSERT INTO audit_log ({colunas}) VALUES ({valores})",  # noqa: S608
                {**registro, "sha256": digest},
            )
        return RegistroDeAuditoria(
            seq=proximo,
            decision_id=str(registro["decision_id"]),
            veredito=veredito,
            motivo=motivo,
            tool_id=tool_id,
            modo=modo,
            identidade=identidade,
            sha256=digest,
        )

    def anexar_resultado(self, decision_id: str, resultado: str, detalhe: str = "") -> str:
        """Anexa o resultado numa cadeia própria — a decisão permanece imutável."""
        with self._con:
            proximo = int(
                self._con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM audit_result"
                ).fetchone()["n"]
            )
            registro: dict[str, Any] = {
                "seq": proximo,
                "decision_id": decision_id,
                "ts_wall": agora_wall(),
                "resultado": resultado,
                "detalhe": detalhe,
                "prev_sha256": self._ultimo("audit_result"),
            }
            digest = _hash(registro, CAMPOS_DO_RESULTADO)
            self._con.execute(
                "INSERT INTO audit_result (seq, decision_id, ts_wall, resultado, detalhe,"
                " prev_sha256, sha256) VALUES (:seq, :decision_id, :ts_wall, :resultado,"
                " :detalhe, :prev_sha256, :sha256)",
                {**registro, "sha256": digest},
            )
        return digest

    def decisoes(self) -> Iterator[RegistroDeAuditoria]:
        for linha in self._con.execute("SELECT * FROM audit_log ORDER BY seq"):
            yield RegistroDeAuditoria(
                seq=int(linha["seq"]),
                decision_id=str(linha["decision_id"]),
                veredito=str(linha["veredito"]),
                motivo=str(linha["motivo"]),
                tool_id=str(linha["tool_id"]),
                modo=str(linha["modo"]),
                identidade=str(linha["identidade"]),
                sha256=str(linha["sha256"]),
            )

    def verificar_cadeia(self) -> int:
        conferidos = 0
        # Consultas literais, uma por tabela: nenhum nome de tabela ou coluna sai de dado.
        tabelas = (
            ("audit_log", CAMPOS_DA_DECISAO, "SELECT * FROM audit_log ORDER BY seq"),
            ("audit_result", CAMPOS_DO_RESULTADO, "SELECT * FROM audit_result ORDER BY seq"),
        )
        for tabela, campos, consulta in tabelas:
            esperado = GENESE
            for esperado_seq, linha in enumerate(self._con.execute(consulta), start=1):
                if int(linha["seq"]) != esperado_seq:
                    raise CadeiaDeAuditoriaRompida(
                        f"{tabela}: seq {linha['seq']} fora de ordem (esperado {esperado_seq})"
                    )
                if str(linha["prev_sha256"]) != esperado:
                    raise CadeiaDeAuditoriaRompida(f"{tabela}: elo quebrado no seq {linha['seq']}")
                recalculado = _hash({c: linha[c] for c in campos}, campos)
                if recalculado != str(linha["sha256"]):
                    raise CadeiaDeAuditoriaRompida(
                        f"{tabela}: registro adulterado no seq {linha['seq']}"
                    )
                esperado = recalculado
                conferidos += 1
        return conferidos
