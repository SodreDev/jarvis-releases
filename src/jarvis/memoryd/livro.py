"""O livro-razão da memória do cérebro: turnos, memórias e grafo, com proveniência (ADR-0026).

É a camada de dados das tools `memoria.*` sobre o esquema da SPEC §6.2/§6.7
(`schemas/memoria.sql`). Quem decide **se** uma escrita acontece e **em que estado** é a
política (`jarvis.politica.memoria`) e o PDP; este módulo grava o que foi decidido e garante as
invariantes do livro:

- **todo turno é episódio** (§6.4), com o texto **cifrado** no `raw_blob` (regra 6) e a redação
  em `memory_unit`; o turno do Jarvis é o **tocado** (P4), e quem chama passa o `played_ms`;
- **retenção D19**: turno nasce com `retention_until` = +90 dias; quando uma memória ou aresta
  passa a citá-lo, a retenção cai (`NULL`) e ele fica até o dono apagar;
- **nada se edita no lugar** (P7): corrigir encerra a validade e cria a nova; retratar muda o
  status; só `apagar` remove — e remove em cascata (gate 2): bruto, FTS, índice, outbox,
  menção, assertiva, aresta e a entidade que ficou sem nenhum suporte;
- **caminho crítico só grava episódio + outbox** (§6.4); o índice é alimentado por
  `processar_outbox`, fora da voz.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from jarvis.barramento.envelope import uuid7
from jarvis.memoryd.cofre import Cofre
from jarvis.memoryd.esquema import abrir
from jarvis.memoryd.fusao import recuperar, rrf, termos
from jarvis.memoryd.importacao import classe_de_pii, redigir
from jarvis.memoryd.indice import ItemDoIndice, MemoryIndex
from jarvis.politica.memoria import Estado, normalizar

RETENCAO_DO_TURNO: Final = timedelta(days=90)
"""D19 (diretor, 2026-10-16): turno que nenhuma memória cita fica 90 dias."""
ENTIDADE_DO_DONO: Final = "ent-dono"
LOTE_DA_OUTBOX: Final = 64
PREDICADO_PADRAO: Final = "nota"
Papel = Literal["dono", "jarvis"]
Escopo = Literal["turno", "sessao", "memoria"]


class AlvoInexistente(LookupError):
    """O id não existe no livro (ou já foi apagado)."""


class BancoSemCofre(RuntimeError):
    """Banco em disco sem cofre: conversa não é gravada em claro (ADR-0026, regra 6)."""


def _agora() -> datetime:
    return datetime.now(UTC)


def _iso(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class LivroDeMemoria:
    con: sqlite3.Connection
    cofre: Cofre | None
    indice: MemoryIndex
    agora: Callable[[], datetime] = _agora
    _ordem: dict[str, int] = field(default_factory=dict)

    @classmethod
    def abrir(
        cls,
        caminho: Path | str,
        *,
        cofre: Cofre | None,
        indice: MemoryIndex,
        agora: Callable[[], datetime] = _agora,
    ) -> LivroDeMemoria:
        """Abre o livro. Em disco, **só com cofre**: sem cifra, a conversa não é gravada."""
        if str(caminho) != ":memory:" and cofre is None:
            raise BancoSemCofre(
                f"{caminho}: sem cofre não há histórico em disco — cifrar antes da primeira "
                "gravação (ADR-0026, regra 6)"
            )
        return cls(con=abrir(caminho), cofre=cofre, indice=indice, agora=agora)

    # --- turnos (M1) --------------------------------------------------------------------
    def gravar_turno(
        self,
        *,
        session_id: str,
        papel: Papel,
        texto: str,
        trust: str,
        played_ms: int | None = None,
        interrompida: bool = False,
    ) -> str:
        """Grava um turno estável. Do Jarvis, `texto` é o **tocado** e vem com `played_ms`."""
        if papel == "jarvis" and played_ms is None:
            raise ValueError("turno do Jarvis sem played_ms: só entra o que tocou (P4)")
        momento = self.agora()
        episodio = f"ep-{uuid7()}"
        redacao = redigir(texto)
        ref = self._guardar_bruto(texto, momento)
        ordem = self._proxima_ordem(session_id)
        self.con.execute(
            "INSERT INTO episode (id, occurred_at, ingested_at, session_id, actor, source, kind,"
            " raw_cipher_ref, sha256, trust, pii_class, retention_until)"
            " VALUES (?, ?, ?, ?, ?, 'conversa', 'turno', ?, ?, ?, ?, ?)",
            (
                episodio,
                _iso(momento),
                _iso(momento),
                session_id,
                papel,
                ref,
                _hash(texto),
                trust,
                classe_de_pii(redacao.texto),
                _iso(momento + RETENCAO_DO_TURNO),
            ),
        )
        self.con.execute(
            "INSERT INTO turno (episode_id, session_id, ordem, papel, played_ms, interrompida)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (episodio, session_id, ordem, papel, played_ms, int(interrompida)),
        )
        self._unidade(episodio, None, redacao.texto)
        return episodio

    def texto_bruto(self, episode_id: str) -> str:
        """O texto original, decifrado — para a tela do dono, não para o modelo."""
        linha = self.con.execute(
            "SELECT b.cifrado FROM episode e JOIN raw_blob b ON b.ref = e.raw_cipher_ref"
            " WHERE e.id = ?",
            (episode_id,),
        ).fetchone()
        if linha is None:
            raise AlvoInexistente(episode_id)
        bruto = bytes(linha["cifrado"])
        return (self.cofre.decifrar(bruto) if self.cofre is not None else bruto).decode("utf-8")

    def buscar_historico(
        self, consulta: str, *, desde: str | None = None, ate: str | None = None, k: int = 5
    ) -> list[dict[str, Any]]:
        """Turnos que casam com a consulta, léxico (FTS5) + índice, fundidos por RRF."""
        expressao = " OR ".join(f'"{t}"' for t in termos(consulta))
        if not expressao:
            return []
        lexicos = [
            str(linha["id"])
            for linha in self.con.execute(
                "SELECT m.id FROM memory_unit_fts f JOIN memory_unit m ON m.rowid = f.rowid"
                " JOIN episode e ON e.id = m.episode_id"
                " WHERE memory_unit_fts MATCH ? AND e.kind = 'turno' AND m.assertion_id IS NULL"
                " AND (? IS NULL OR e.occurred_at >= ?) AND (? IS NULL OR e.occurred_at <= ?)"
                " ORDER BY bm25(memory_unit_fts) LIMIT ?",
                (expressao, desde, desde, ate, ate, k * 2),
            )
        ]
        densos = [a.id for a in self.indice.search(consulta, k * 2, onde={"tipo": "turno"})]
        achados: list[dict[str, Any]] = []
        for unidade, _escore, fontes in rrf([("lexico", lexicos), ("denso", densos)]):
            linha = self.con.execute(
                "SELECT m.text_redacted, e.id AS episodio, e.session_id, e.occurred_at,"
                " e.pii_class, t.papel, t.interrompida FROM memory_unit m"
                " JOIN episode e ON e.id = m.episode_id JOIN turno t ON t.episode_id = e.id"
                " WHERE m.id = ? AND (? IS NULL OR e.occurred_at >= ?)"
                " AND (? IS NULL OR e.occurred_at <= ?)",
                (unidade, desde, desde, ate, ate),
            ).fetchone()
            if linha is None:
                continue
            achados.append(
                {
                    "episode_id": linha["episodio"],
                    "session_id": linha["session_id"],
                    "occurred_at": linha["occurred_at"],
                    "papel": linha["papel"],
                    "texto": linha["text_redacted"],
                    "interrompida": bool(linha["interrompida"]),
                    "pii_class": linha["pii_class"],
                    "caminho": f"acerto {'+'.join(fontes)} direto no turno {linha['episodio']}",
                }
            )
            if len(achados) == k:
                break
        return achados

    def ler_mensagem(self, episode_id: str, *, vizinhos: int = 2) -> list[dict[str, Any]]:
        alvo = self.con.execute(
            "SELECT session_id, ordem FROM turno WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if alvo is None:
            raise AlvoInexistente(episode_id)
        linhas = self.con.execute(
            "SELECT t.episode_id, t.papel, t.ordem, t.interrompida, m.text_redacted,"
            " e.occurred_at, e.pii_class FROM turno t JOIN episode e ON e.id = t.episode_id"
            " JOIN memory_unit m ON m.episode_id = e.id AND m.assertion_id IS NULL"
            " WHERE t.session_id = ? AND t.ordem BETWEEN ? AND ? ORDER BY t.ordem",
            (alvo["session_id"], alvo["ordem"] - vizinhos, alvo["ordem"] + vizinhos),
        )
        return [
            {
                "episode_id": linha["episode_id"],
                "papel": linha["papel"],
                "texto": linha["text_redacted"],
                "interrompida": bool(linha["interrompida"]),
                "occurred_at": linha["occurred_at"],
                "pii_class": linha["pii_class"],
                "alvo": linha["episode_id"] == episode_id,
            }
            for linha in linhas
        ]

    # --- memórias e grafo (M2) ----------------------------------------------------------
    def lembrar(
        self,
        texto: str,
        *,
        estado: Estado,
        fonte: str,
        extrator: str,
        sujeito: str | None = None,
        predicado: str | None = None,
    ) -> dict[str, Any]:
        self._exigir_episodio(fonte)
        momento = _iso(self.agora())
        entidade = self._entidade_do_sujeito(sujeito, estado=estado, fonte=fonte, extrator=extrator)
        redacao = redigir(texto)
        assertiva = f"ast-{uuid7()}"
        self.con.execute(
            "INSERT INTO assertion (id, subject_entity, predicate, value_json, confidence,"
            " observed_at, valid_from, status, source_episode_id, approved_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assertiva,
                entidade,
                predicado or PREDICADO_PADRAO,
                json.dumps({"texto": redacao.texto}, ensure_ascii=False),
                1.0 if estado is Estado.ATIVA else 0.5,
                momento,
                momento,
                str(estado),
                fonte,
                "dono" if estado is Estado.ATIVA else None,
            ),
        )
        self._unidade(fonte, assertiva, redacao.texto)
        self._citar(fonte)
        return {"assertion_id": assertiva, "estado": str(estado), "redigidos": redacao.total}

    def atualizar(
        self, assertion_id: str, texto: str, *, motivo: str, fonte: str
    ) -> dict[str, Any]:
        """Encerra a validade da antiga e grava a nova no lugar (P7). Já vem confirmada."""
        self._exigir_episodio(fonte)
        antiga = self.con.execute(
            "SELECT subject_entity, predicate FROM assertion WHERE id = ? AND status = 'active'",
            (assertion_id,),
        ).fetchone()
        if antiga is None:
            raise AlvoInexistente(f"{assertion_id} não é uma memória ativa")
        momento = _iso(self.agora())
        self.con.execute(
            "UPDATE assertion SET status = 'superseded', valid_to = ? WHERE id = ?",
            (momento, assertion_id),
        )
        self._tirar_do_indice_as_unidades_de(assertion_id)
        redacao = redigir(texto)
        nova = f"ast-{uuid7()}"
        self.con.execute(
            "INSERT INTO assertion (id, subject_entity, predicate, value_json, confidence,"
            " observed_at, valid_from, status, source_episode_id, supersedes_id, approved_by)"
            " VALUES (?, ?, ?, ?, 1.0, ?, ?, 'active', ?, ?, 'dono')",
            (
                nova,
                antiga["subject_entity"],
                antiga["predicate"],
                json.dumps({"texto": redacao.texto, "motivo": motivo}, ensure_ascii=False),
                momento,
                momento,
                fonte,
                assertion_id,
            ),
        )
        self._unidade(fonte, nova, redacao.texto)
        self._citar(fonte)
        return {"assertion_id": nova, "substituida": assertion_id}

    def criar_no(
        self,
        tipo: str,
        nome: str,
        *,
        apelidos: Sequence[str] = (),
        estado: Estado,
        fonte: str,
        extrator: str,
    ) -> dict[str, Any]:
        self._exigir_episodio(fonte)
        existente = self.resolver(nome)
        if existente is not None:
            return {
                "entity_id": existente,
                "estado": self._status_da_entidade(existente),
                "existente": True,
            }
        entidade = f"ent-{uuid7()}"
        self.con.execute(
            "INSERT INTO entity (id, type, canonical_name, aliases_json, created_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                entidade,
                tipo,
                nome,
                json.dumps(list(apelidos), ensure_ascii=False),
                _iso(self.agora()),
                str(estado),
            ),
        )
        metodo = "dono" if estado is Estado.ATIVA else "jarvis"
        for apelido in {nome, *apelidos}:
            self.con.execute(
                "INSERT OR IGNORE INTO entity_resolution (alias_norm, entity_id, score, method)"
                " VALUES (?, ?, 1.0, ?)",
                (normalizar(apelido), entidade, metodo),
            )
        self._mencao(fonte, entidade, estado, extrator)
        self._citar(fonte)
        return {"entity_id": entidade, "estado": str(estado), "existente": False}

    def criar_aresta(
        self,
        origem: str,
        relacao: str,
        destino: str,
        *,
        estado: Estado,
        fonte: str,
        extrator: str,
        desde: str | None = None,
        ate: str | None = None,
    ) -> dict[str, Any]:
        self._exigir_episodio(fonte)
        src, dst = self._exigir_entidade(origem), self._exigir_entidade(destino)
        momento = _iso(self.agora())
        aresta = f"edge-{uuid7()}"
        self.con.execute(
            "INSERT INTO entity_edge (id, src, relation, dst, source_episode_id, valid_from,"
            " valid_to, confidence, status, last_seen_at, extractor, extractor_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '1')",
            (
                aresta,
                src,
                relacao,
                dst,
                fonte,
                desde or momento,
                ate,
                1.0 if estado is Estado.ATIVA else 0.5,
                str(estado),
                momento,
                extrator,
            ),
        )
        self._citar(fonte)
        return {"edge_id": aresta, "estado": str(estado)}

    def retratar(self, alvo_id: str) -> dict[str, Any]:
        """Deixa de usar, sem apagar: status `retracted` e validade encerrada."""
        momento = _iso(self.agora())
        if alvo_id.startswith("ast-"):
            mudou = self.con.execute(
                "UPDATE assertion SET status = 'retracted', valid_to = ? WHERE id = ?",
                (momento, alvo_id),
            ).rowcount
            self._tirar_do_indice_as_unidades_de(alvo_id)
        elif alvo_id.startswith("edge-"):
            mudou = self.con.execute(
                "UPDATE entity_edge SET status = 'retracted', valid_to = ? WHERE id = ?",
                (momento, alvo_id),
            ).rowcount
        elif alvo_id.startswith("ent-"):
            mudou = self.con.execute(
                "UPDATE entity SET status = 'retracted' WHERE id = ?", (alvo_id,)
            ).rowcount
        else:
            mudou = 0
        if not mudou:
            raise AlvoInexistente(alvo_id)
        return {"alvo_id": alvo_id, "estado": "retracted"}

    def buscar(
        self, consulta: str, *, instante: str | None = None, k: int = 8
    ) -> list[dict[str, Any]]:
        """Recuperação da §6.8 restrita a memória **ativa e vigente**, com o caminho (gate 6)."""
        quando = instante or _iso(self.agora())
        achados: list[dict[str, Any]] = []
        for achado in recuperar(self.con, consulta, k=k * 3, evidencias=k * 3).achados:
            linha = self.con.execute(
                "SELECT a.id AS assertiva, e.pii_class FROM memory_unit m"
                " JOIN assertion a ON a.id = m.assertion_id JOIN episode e ON e.id = m.episode_id"
                " WHERE m.id = ? AND a.status = 'active' AND a.valid_from <= ?"
                " AND (a.valid_to IS NULL OR a.valid_to > ?)",
                (achado.memory_unit_id, quando, quando),
            ).fetchone()
            if linha is None:
                continue
            achados.append(
                {
                    "memory_unit_id": achado.memory_unit_id,
                    "assertion_id": linha["assertiva"],
                    "texto": achado.texto,
                    "caminho": achado.caminho
                    or f"acerto {'+'.join(achado.fontes)} direto na memória {linha['assertiva']}",
                    "fontes": list(achado.fontes),
                    "pii_class": linha["pii_class"],
                }
            )
            if len(achados) == k:
                break
        return achados

    # --- esquecer de vez (gate 2) e retenção (D19) --------------------------------------
    def apagar(self, alvo_id: str, escopo: Escopo) -> dict[str, int]:
        if escopo == "turno":
            removidos = self._apagar_episodio(alvo_id)
        elif escopo == "sessao":
            episodios = [
                str(r["id"])
                for r in self.con.execute("SELECT id FROM episode WHERE session_id = ?", (alvo_id,))
            ]
            if not episodios:
                raise AlvoInexistente(alvo_id)
            removidos = {}
            for episodio in episodios:
                for chave, n in self._apagar_episodio(episodio).items():
                    removidos[chave] = removidos.get(chave, 0) + n
        else:
            removidos = self._apagar_assertivas([alvo_id], exigir=True)
        self._expurgar()
        return removidos

    def expirar(self) -> int:
        """D19: apaga turno vencido que nenhuma memória cita (citado tem retenção `NULL`)."""
        vencidos = [
            str(r["id"])
            for r in self.con.execute(
                "SELECT id FROM episode WHERE kind = 'turno' AND retention_until IS NOT NULL"
                " AND retention_until < ?",
                (_iso(self.agora()),),
            )
        ]
        for episodio in vencidos:
            self._apagar_episodio(episodio)
        if vencidos:
            self._expurgar()
        return len(vencidos)

    def processar_outbox(self, *, lote: int = LOTE_DA_OUTBOX) -> int:
        """O worker da §6.4: leva ao índice o que o caminho crítico deixou na outbox.

        Em lotes: o embedding de um lote custa quase o de um item, e o índice grava uma versão
        por chamada. No índice vão `tipo` (`turno`/`memoria`) e o `status` da assertiva, para o
        filtro descer para dentro dele. Aqui também roda a ligação de menções (§6.7: extração é
        trabalho de segundo plano, nunca da voz).
        """
        linhas = self.con.execute(
            "SELECT o.id, o.op, m.id AS unidade, m.text_redacted, m.content_hash,"
            " a.status FROM outbox o"
            " JOIN memory_unit m ON m.id = o.memory_unit_id"
            " LEFT JOIN assertion a ON a.id = m.assertion_id"
        ).fetchall()
        for inicio in range(0, len(linhas), lote):
            pedaco = linhas[inicio : inicio + lote]
            novos = [linha for linha in pedaco if linha["op"] == "upsert"]
            self.indice.upsert(
                [
                    ItemDoIndice(
                        id=linha["unidade"],
                        text_redacted=linha["text_redacted"],
                        content_hash=linha["content_hash"],
                        metadata={
                            "tipo": "turno" if linha["status"] is None else "memoria",
                            "status": "turno" if linha["status"] is None else str(linha["status"]),
                        },
                    )
                    for linha in novos
                ]
            )
            self.indice.delete([linha["unidade"] for linha in pedaco if linha["op"] != "upsert"])
            for linha in novos:
                if linha["status"] is not None:
                    self.ligar_mencoes(linha["unidade"])
            self.con.executemany(
                "DELETE FROM outbox WHERE id = ?", [(linha["id"],) for linha in pedaco]
            )
        return len(linhas)

    def ligar_mencoes(self, unidade: str) -> int:
        """Extrator determinístico (§6.7 b): nome ou apelido **exato** de entidade no texto.

        Liga a `memory_unit` às entidades que ela cita — é o que deixa o passo 1b da §6.8
        (acerto denso → entidade) e a volta do grafo para a evidência funcionarem. A menção
        herda o status da assertiva: memória só proposta não puxa nada para a recuperação.
        """
        linha = self.con.execute(
            "SELECT m.text_redacted, m.episode_id, a.status FROM memory_unit m"
            " JOIN assertion a ON a.id = m.assertion_id WHERE m.id = ?",
            (unidade,),
        ).fetchone()
        if linha is None:
            return 0
        texto = f" {normalizar(str(linha['text_redacted']))} "
        ligadas = 0
        for apelido in self.con.execute(
            "SELECT r.alias_norm, r.entity_id FROM entity_resolution r"
            " JOIN entity e ON e.id = r.entity_id WHERE e.status = 'active'"
        ).fetchall():
            if f" {apelido['alias_norm']} " not in texto:
                continue
            if self.con.execute(
                "SELECT 1 FROM entity_mention WHERE memory_unit_id = ? AND entity_id = ?",
                (unidade, apelido["entity_id"]),
            ).fetchone():
                continue
            self.con.execute(
                "INSERT INTO entity_mention (id, episode_id, memory_unit_id, entity_id,"
                " confidence, extractor, extractor_version, status)"
                " VALUES (?, ?, ?, ?, 1.0, 'apelido-exato', '1', ?)",
                (
                    f"men-{uuid7()}",
                    linha["episode_id"],
                    unidade,
                    apelido["entity_id"],
                    "active" if linha["status"] == "active" else "proposed",
                ),
            )
            ligadas += 1
        return ligadas

    def varrer(self, trecho: str) -> dict[str, int]:
        """Onde este trecho ainda aparece — o teste de exclusão em cascata (gate 2) usa."""
        alvo = f"%{trecho}%"
        brutos = 0
        for linha in self.con.execute("SELECT cifrado FROM raw_blob"):
            bruto = bytes(linha["cifrado"])
            claro = self.cofre.decifrar(bruto) if self.cofre is not None else bruto
            brutos += trecho in claro.decode("utf-8")
        consulta = " OR ".join(f'"{t}"' for t in termos(trecho)) or '""'
        return {
            "bruto": brutos,
            "memory_unit": self._contar(
                "SELECT COUNT(*) FROM memory_unit WHERE text_redacted LIKE ?", alvo
            ),
            "fts": self._contar(
                "SELECT COUNT(*) FROM memory_unit_fts WHERE memory_unit_fts MATCH ?", consulta
            )
            if trecho.strip()
            else 0,
            "assertion": self._contar(
                "SELECT COUNT(*) FROM assertion WHERE value_json LIKE ?", alvo
            ),
            "indice": int(getattr(self.indice, "contem_texto", lambda _t: False)(trecho)),
        }

    # --- internos -----------------------------------------------------------------------
    def _contar(self, sql: str, parametro: str) -> int:
        return int(self.con.execute(sql, (parametro,)).fetchone()[0])

    def _guardar_bruto(self, texto: str, momento: datetime) -> str:
        claro = texto.encode("utf-8")
        cifrado = self.cofre.cifrar(claro) if self.cofre is not None else claro
        ref = f"raw-{uuid7()}"
        self.con.execute(
            "INSERT INTO raw_blob (ref, cifrado, criado_em) VALUES (?, ?, ?)",
            (ref, cifrado, _iso(momento)),
        )
        return ref

    def _proxima_ordem(self, session_id: str) -> int:
        if session_id not in self._ordem:
            linha = self.con.execute(
                "SELECT COALESCE(MAX(ordem), -1) FROM turno WHERE session_id = ?", (session_id,)
            ).fetchone()
            self._ordem[session_id] = int(linha[0])
        self._ordem[session_id] += 1
        return self._ordem[session_id]

    def _unidade(self, episodio: str, assertiva: str | None, texto: str) -> str:
        unidade = f"mu-{uuid7()}"
        cursor = self.con.execute(
            "INSERT INTO memory_unit (id, episode_id, assertion_id, text_redacted, content_hash)"
            " VALUES (?, ?, ?, ?, ?)",
            (unidade, episodio, assertiva, texto, _hash(texto)),
        )
        self.con.execute(
            "INSERT INTO memory_unit_fts (rowid, text_redacted) VALUES (?, ?)",
            (cursor.lastrowid, texto),
        )
        self.con.execute(
            "INSERT INTO outbox (id, memory_unit_id, op, content_hash) VALUES (?, ?, 'upsert', ?)",
            (f"ob-{uuid7()}", unidade, _hash(texto)),
        )
        return unidade

    def _citar(self, episodio: str) -> None:
        """D19: turno citado por memória fica até o dono apagar."""
        self.con.execute("UPDATE episode SET retention_until = NULL WHERE id = ?", (episodio,))

    def _exigir_episodio(self, episodio: str) -> None:
        if self.con.execute("SELECT 1 FROM episode WHERE id = ?", (episodio,)).fetchone() is None:
            raise AlvoInexistente(f"episódio de origem {episodio} não existe (ADR-0026, regra 2)")

    def resolver(self, nome_ou_id: str) -> str | None:
        if nome_ou_id.startswith("ent-"):
            linha = self.con.execute("SELECT id FROM entity WHERE id = ?", (nome_ou_id,)).fetchone()
        else:
            linha = self.con.execute(
                "SELECT entity_id AS id FROM entity_resolution WHERE alias_norm = ?"
                " ORDER BY score DESC LIMIT 1",
                (normalizar(nome_ou_id),),
            ).fetchone()
        return None if linha is None else str(linha["id"])

    def _exigir_entidade(self, nome_ou_id: str) -> str:
        entidade = self.resolver(nome_ou_id)
        if entidade is None:
            raise AlvoInexistente(f"entidade {nome_ou_id!r} não existe no grafo")
        return entidade

    def _status_da_entidade(self, entidade: str) -> str:
        linha = self.con.execute("SELECT status FROM entity WHERE id = ?", (entidade,)).fetchone()
        return str(linha["status"])

    def _entidade_do_sujeito(
        self, sujeito: str | None, *, estado: Estado, fonte: str, extrator: str
    ) -> str:
        if sujeito:
            existente = self.resolver(sujeito)
            if existente is not None:
                return existente
            return str(
                self.criar_no("coisa", sujeito, estado=estado, fonte=fonte, extrator=extrator)[
                    "entity_id"
                ]
            )
        if self.con.execute("SELECT 1 FROM entity WHERE id = ?", (ENTIDADE_DO_DONO,)).fetchone():
            return ENTIDADE_DO_DONO
        self.con.execute(
            "INSERT INTO entity (id, type, canonical_name, created_at, status)"
            " VALUES (?, 'pessoa', 'dono', ?, 'active')",
            (ENTIDADE_DO_DONO, _iso(self.agora())),
        )
        return ENTIDADE_DO_DONO

    def _mencao(self, episodio: str, entidade: str, estado: Estado, extrator: str) -> None:
        self.con.execute(
            "INSERT INTO entity_mention (id, episode_id, entity_id, confidence, extractor,"
            " extractor_version, status) VALUES (?, ?, ?, ?, ?, '1', ?)",
            (
                f"men-{uuid7()}",
                episodio,
                entidade,
                1.0 if estado is Estado.ATIVA else 0.5,
                extrator,
                str(estado),
            ),
        )

    def _expurgar(self) -> None:
        """Gate 2 no disco, não só na consulta: o FTS5 guarda os termos apagados nos segmentos
        até a fusão (`optimize`); o WAL guarda as versões antigas das páginas até o checkpoint
        (`TRUNCATE` zera o arquivo); o índice vetorial guarda o vetor até reescrever. As páginas
        liberadas do SQLite são zeradas pelo `secure_delete` (`jarvis.memoryd.esquema`)."""
        self.con.execute("INSERT INTO memory_unit_fts (memory_unit_fts) VALUES ('optimize')")
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        expurgar = getattr(self.indice, "expurgar", None)
        if callable(expurgar):
            expurgar()

    def _tirar_do_indice_as_unidades_de(self, assertiva: str) -> None:
        ids = [
            str(r["id"])
            for r in self.con.execute(
                "SELECT id FROM memory_unit WHERE assertion_id = ?", (assertiva,)
            )
        ]
        self.indice.delete(ids)

    def _apagar_unidades(self, ids: Sequence[str]) -> int:
        for unidade in ids:
            linha = self.con.execute(
                "SELECT rowid, text_redacted FROM memory_unit WHERE id = ?", (unidade,)
            ).fetchone()
            if linha is None:
                continue
            self.con.execute(
                "INSERT INTO memory_unit_fts (memory_unit_fts, rowid, text_redacted)"
                " VALUES ('delete', ?, ?)",
                (linha["rowid"], linha["text_redacted"]),
            )
            self.con.execute("DELETE FROM outbox WHERE memory_unit_id = ?", (unidade,))
            self.con.execute("DELETE FROM entity_mention WHERE memory_unit_id = ?", (unidade,))
            self.con.execute("DELETE FROM memory_unit WHERE id = ?", (unidade,))
        self.indice.delete(list(ids))
        return len(ids)

    def _apagar_assertivas(self, ids: Sequence[str], *, exigir: bool = False) -> dict[str, int]:
        existentes = [
            i
            for i in ids
            if self.con.execute("SELECT 1 FROM assertion WHERE id = ?", (i,)).fetchone()
        ]
        if exigir and not existentes:
            raise AlvoInexistente(", ".join(ids))
        unidades = [
            str(r["id"])
            for i in existentes
            for r in self.con.execute("SELECT id FROM memory_unit WHERE assertion_id = ?", (i,))
        ]
        removidas = self._apagar_unidades(unidades)
        for assertiva in existentes:
            self.con.execute(
                "UPDATE assertion SET supersedes_id = NULL WHERE supersedes_id = ?", (assertiva,)
            )
            self.con.execute("DELETE FROM assertion WHERE id = ?", (assertiva,))
        return {"assertion": len(existentes), "memory_unit": removidas}

    def _apagar_episodio(self, episodio: str) -> dict[str, int]:
        linha = self.con.execute(
            "SELECT raw_cipher_ref FROM episode WHERE id = ?", (episodio,)
        ).fetchone()
        if linha is None:
            raise AlvoInexistente(episodio)
        contagem = self._apagar_assertivas(
            [
                str(r["id"])
                for r in self.con.execute(
                    "SELECT id FROM assertion WHERE source_episode_id = ?", (episodio,)
                )
            ]
        )
        unidades = [
            str(r["id"])
            for r in self.con.execute(
                "SELECT id FROM memory_unit WHERE episode_id = ?", (episodio,)
            )
        ]
        contagem["memory_unit"] += self._apagar_unidades(unidades)
        entidades = {
            str(r["entity_id"])
            for r in self.con.execute(
                "SELECT entity_id FROM entity_mention WHERE episode_id = ?", (episodio,)
            )
        }
        contagem["entity_mention"] = self.con.execute(
            "DELETE FROM entity_mention WHERE episode_id = ?", (episodio,)
        ).rowcount
        contagem["entity_edge"] = self.con.execute(
            "DELETE FROM entity_edge WHERE source_episode_id = ?", (episodio,)
        ).rowcount
        contagem["entity"] = sum(self._apagar_entidade_sem_suporte(e) for e in entidades)
        self.con.execute("DELETE FROM turno WHERE episode_id = ?", (episodio,))
        self.con.execute("DELETE FROM episode WHERE id = ?", (episodio,))
        if linha["raw_cipher_ref"]:
            contagem["bruto"] = self.con.execute(
                "DELETE FROM raw_blob WHERE ref = ?", (linha["raw_cipher_ref"],)
            ).rowcount
        contagem["episode"] = 1
        return contagem

    def _apagar_entidade_sem_suporte(self, entidade: str) -> int:
        suporte = self.con.execute(
            "SELECT (SELECT COUNT(*) FROM entity_mention WHERE entity_id = :e)"
            " + (SELECT COUNT(*) FROM entity_edge WHERE src = :e OR dst = :e)"
            " + (SELECT COUNT(*) FROM assertion WHERE subject_entity = :e)",
            {"e": entidade},
        ).fetchone()[0]
        if suporte:
            return 0
        self.con.execute("DELETE FROM entity_resolution WHERE entity_id = ?", (entidade,))
        self.con.execute("DELETE FROM graph_node_stats WHERE entity_id = ?", (entidade,))
        return self.con.execute("DELETE FROM entity WHERE id = ?", (entidade,)).rowcount
