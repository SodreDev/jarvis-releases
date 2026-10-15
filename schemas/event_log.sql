-- Log de eventos append-only encadeado por hash (SPEC §3, §5.5 "Auditoria"; cartão F0-02).
--
-- Este arquivo é dado, não código: a implementação de qualquer linguagem (decisão D1,
-- cartão F0-04) cria o mesmo esquema. O encadeamento é o que torna edição silenciosa
-- detectável: cada registro carrega o sha256 do anterior, e `sha256` cobre o registro
-- inteiro mais esse elo.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS event_log (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT    NOT NULL UNIQUE,
    session_id     TEXT    NOT NULL,
    epoch          INTEGER NOT NULL CHECK (epoch >= 0),
    ts_mono_ns     INTEGER NOT NULL CHECK (ts_mono_ns >= 0),
    ts_wall        TEXT    NOT NULL,
    source         TEXT    NOT NULL,
    trust          TEXT    NOT NULL CHECK (
                       trust IN ('system', 'user_voice', 'user_ui', 'tool_result', 'third_party')
                   ),
    priority       TEXT    NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3', 'P4')),
    type           TEXT    NOT NULL,
    payload_json   TEXT    NOT NULL,
    -- Elo: sha256 do registro anterior; 64 zeros no primeiro (gênese).
    prev_sha256    TEXT    NOT NULL CHECK (length(prev_sha256) = 64),
    sha256         TEXT    NOT NULL CHECK (length(sha256) = 64)
);

CREATE INDEX IF NOT EXISTS event_log_por_sessao ON event_log (session_id, seq);
CREATE INDEX IF NOT EXISTS event_log_por_epoch   ON event_log (session_id, epoch, seq);
CREATE INDEX IF NOT EXISTS event_log_por_tipo    ON event_log (type, seq);

-- Append-only no próprio banco: nem a nossa aplicação consegue editar sem derrubar o
-- gatilho primeiro, e derrubar o gatilho não reescreve os hashes (a verificação acusa).
CREATE TRIGGER IF NOT EXISTS event_log_sem_update
BEFORE UPDATE ON event_log
BEGIN
    SELECT RAISE(ABORT, 'event_log é append-only: UPDATE proibido');
END;

CREATE TRIGGER IF NOT EXISTS event_log_sem_delete
BEFORE DELETE ON event_log
BEGIN
    SELECT RAISE(ABORT, 'event_log é append-only: DELETE proibido');
END;
