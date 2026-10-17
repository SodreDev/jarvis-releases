-- Livro-razão da memória (SPEC §6.2) mais o grafo pessoal (§6.7), no mesmo SQLite.
-- Dado, não código: a migração é este arquivo (cartão F0-05).
--
-- Integridade da §6.2: (a) todo fato aponta para ≥1 episódio; (b) contradição encerra
-- valid_to e cria assertiva nova, não apaga; (c) observed_at ≠ valid_from/to; (d) vetor é
-- índice descartável, reconstituível por content_hash + embedding_version.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- --- §6.2 livro-razão -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS episode (
    id              TEXT PRIMARY KEY,
    occurred_at     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    source          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    raw_cipher_ref  TEXT,
    sha256          TEXT NOT NULL,
    trust           TEXT NOT NULL CHECK (
                        trust IN ('system', 'user_voice', 'user_ui', 'tool_result', 'third_party')
                    ),
    pii_class       TEXT NOT NULL DEFAULT 'none',
    retention_until TEXT
);

CREATE TABLE IF NOT EXISTS entity (
    id             TEXT PRIMARY KEY,
    type           TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases_json   TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS assertion (
    id                TEXT PRIMARY KEY,
    subject_entity    TEXT NOT NULL REFERENCES entity (id),
    predicate         TEXT NOT NULL,
    value_json        TEXT NOT NULL,
    scope             TEXT NOT NULL DEFAULT 'pessoal',
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    observed_at       TEXT NOT NULL,
    valid_from        TEXT NOT NULL,
    valid_to          TEXT,
    status            TEXT NOT NULL CHECK (
                          status IN ('proposed', 'active', 'superseded', 'retracted', 'quarantined')
                      ),
    source_episode_id TEXT NOT NULL REFERENCES episode (id),
    supersedes_id     TEXT REFERENCES assertion (id),
    approved_by       TEXT
);

CREATE TABLE IF NOT EXISTS memory_unit (
    id                TEXT PRIMARY KEY,
    episode_id        TEXT NOT NULL REFERENCES episode (id),
    assertion_id      TEXT REFERENCES assertion (id),
    text_redacted     TEXT NOT NULL,
    embedding_version TEXT NOT NULL DEFAULT 'v0',
    content_hash      TEXT NOT NULL,
    importance        REAL NOT NULL DEFAULT 0.5,
    access_count      INTEGER NOT NULL DEFAULT 0,
    last_accessed_at  TEXT
);

CREATE TABLE IF NOT EXISTS procedure (
    id           TEXT PRIMARY KEY,
    trigger      TEXT NOT NULL,
    instruction  TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    state        TEXT NOT NULL CHECK (state IN ('draft', 'approved', 'disabled')),
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    approver     TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    id              TEXT PRIMARY KEY,
    memory_unit_id  TEXT NOT NULL REFERENCES memory_unit (id),
    op              TEXT NOT NULL CHECK (op IN ('upsert', 'delete')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    content_hash    TEXT NOT NULL
);

-- --- §6.7 grafo pessoal -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_edge (
    id                TEXT PRIMARY KEY,
    src               TEXT NOT NULL REFERENCES entity (id),
    relation          TEXT NOT NULL,
    dst               TEXT NOT NULL REFERENCES entity (id),
    source_episode_id TEXT NOT NULL REFERENCES episode (id),
    valid_from        TEXT NOT NULL,
    valid_to          TEXT,
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status            TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'retracted')),
    weight            REAL NOT NULL DEFAULT 0.5,
    support_count     INTEGER NOT NULL DEFAULT 1,
    last_seen_at      TEXT,
    extractor         TEXT NOT NULL DEFAULT 'deterministico-v0',
    extractor_version TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS entity_mention (
    id                TEXT PRIMARY KEY,
    episode_id        TEXT NOT NULL REFERENCES episode (id),
    memory_unit_id    TEXT REFERENCES memory_unit (id),
    entity_id         TEXT NOT NULL REFERENCES entity (id),
    span_json         TEXT NOT NULL DEFAULT '{}',
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    extractor         TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'rejected'))
);

CREATE TABLE IF NOT EXISTS entity_resolution (
    alias_norm TEXT NOT NULL,
    entity_id  TEXT NOT NULL REFERENCES entity (id),
    score      REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    method     TEXT NOT NULL,
    PRIMARY KEY (alias_norm, entity_id)
);

CREATE TABLE IF NOT EXISTS graph_node_stats (
    entity_id  TEXT PRIMARY KEY REFERENCES entity (id),
    degree     INTEGER NOT NULL DEFAULT 0,
    hubness    REAL NOT NULL DEFAULT 0,
    updated_at TEXT
);

-- --- índices obrigatórios da §6.7 -------------------------------------------------
CREATE INDEX IF NOT EXISTS entity_edge_src ON entity_edge (src, relation, status);
CREATE INDEX IF NOT EXISTS entity_edge_dst ON entity_edge (dst, relation, status);
CREATE INDEX IF NOT EXISTS assertion_sujeito
    ON assertion (subject_entity, predicate, status, valid_from);
CREATE INDEX IF NOT EXISTS memory_unit_assertion ON memory_unit (assertion_id);
CREATE INDEX IF NOT EXISTS entity_mention_entidade ON entity_mention (entity_id);
CREATE INDEX IF NOT EXISTS entity_resolution_alias ON entity_resolution (alias_norm);
-- Usados pela travessia: validade temporal junto da direção.
CREATE INDEX IF NOT EXISTS entity_edge_src_valido ON entity_edge (src, status, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS entity_edge_dst_valido ON entity_edge (dst, status, valid_from, valid_to);

-- --- busca léxica (§6.8, lista 2 de 3) --------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS memory_unit_fts USING fts5 (
    text_redacted,
    content = 'memory_unit',
    content_rowid = 'rowid',
    tokenize = "unicode61 remove_diacritics 2"
);

-- --- bruto cifrado e turnos de conversa (ADR-0026, fatia M1) -------------------------
-- O texto de cada episódio de conversa vai cifrado aqui; `episode.raw_cipher_ref` aponta para
-- `raw_blob.ref`. O índice e a busca só veem `memory_unit.text_redacted` (§6.2 e).
CREATE TABLE IF NOT EXISTS raw_blob (
    ref       TEXT PRIMARY KEY,
    cifrado   BLOB NOT NULL,
    criado_em TEXT NOT NULL
);

-- Um turno estável da conversa. Do Jarvis, só o que tocou (P4): `played_ms` e `interrompida`
-- dizem quanto o dono ouviu.
CREATE TABLE IF NOT EXISTS turno (
    episode_id   TEXT PRIMARY KEY REFERENCES episode (id),
    session_id   TEXT NOT NULL,
    ordem        INTEGER NOT NULL,
    papel        TEXT NOT NULL CHECK (papel IN ('dono', 'jarvis')),
    played_ms    INTEGER,
    interrompida INTEGER NOT NULL DEFAULT 0 CHECK (interrompida IN (0, 1))
);
CREATE INDEX IF NOT EXISTS turno_sessao ON turno (session_id, ordem);
CREATE INDEX IF NOT EXISTS episode_tipo_tempo ON episode (kind, occurred_at);
CREATE INDEX IF NOT EXISTS episode_retencao ON episode (retention_until);
