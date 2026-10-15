-- Auditoria de política: decisão escrita ANTES do efeito, resultado anexado depois,
-- cada registro com o sha256 do anterior (SPEC §5.5 "Auditoria"; cartão F0-06).
--
-- Mesma técnica do event_log, campos diferentes: aqui o que importa é por que a decisão
-- foi tomada e sobre qual arquivo exatamente (identidade, não string).

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS audit_log (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT    NOT NULL UNIQUE,
    ts_wall         TEXT    NOT NULL,
    policy_epoch    INTEGER NOT NULL CHECK (policy_epoch >= 0),
    session_id      TEXT    NOT NULL,
    modo            TEXT    NOT NULL CHECK (modo IN ('jarvis', 'padrao', 'concedido', 'total')),
    tool_id         TEXT    NOT NULL,
    raiz            TEXT    NOT NULL,
    caminho         TEXT    NOT NULL,
    identidade      TEXT    NOT NULL,   -- device:inode (POSIX) ou volume:file_id (Windows)
    argv_json       TEXT    NOT NULL,   -- argumentos normalizados, não a frase do usuário
    elevacao        INTEGER NOT NULL CHECK (elevacao IN (0, 1)),
    grant_id        TEXT    NOT NULL,
    veredito        TEXT    NOT NULL CHECK (veredito IN ('allow', 'confirm', 'deny')),
    motivo          TEXT    NOT NULL,
    resultado       TEXT    NOT NULL,   -- vazio enquanto o efeito não terminou
    sessao_contaminada INTEGER NOT NULL CHECK (sessao_contaminada IN (0, 1)),
    prev_sha256     TEXT    NOT NULL CHECK (length(prev_sha256) = 64),
    sha256          TEXT    NOT NULL CHECK (length(sha256) = 64)
);

CREATE INDEX IF NOT EXISTS audit_log_por_sessao ON audit_log (session_id, seq);
CREATE INDEX IF NOT EXISTS audit_log_por_tool   ON audit_log (tool_id, seq);

-- Resultado é anexado depois da decisão, então UPDATE existe — mas só no campo `resultado`
-- e só enquanto ele está vazio, e o gatilho reescreve nada mais. A cadeia de hash cobre a
-- decisão (que é imutável); o resultado entra numa tabela própria, encadeada à parte.
CREATE TRIGGER IF NOT EXISTS audit_log_sem_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log é append-only: resultado vai em audit_result');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_sem_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log é append-only: DELETE proibido');
END;

CREATE TABLE IF NOT EXISTS audit_result (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id  TEXT    NOT NULL REFERENCES audit_log (decision_id),
    ts_wall      TEXT    NOT NULL,
    resultado    TEXT    NOT NULL,
    detalhe      TEXT    NOT NULL,
    prev_sha256  TEXT    NOT NULL CHECK (length(prev_sha256) = 64),
    sha256       TEXT    NOT NULL CHECK (length(sha256) = 64)
);

CREATE TRIGGER IF NOT EXISTS audit_result_sem_update
BEFORE UPDATE ON audit_result
BEGIN
    SELECT RAISE(ABORT, 'audit_result é append-only: UPDATE proibido');
END;

CREATE TRIGGER IF NOT EXISTS audit_result_sem_delete
BEFORE DELETE ON audit_result
BEGIN
    SELECT RAISE(ABORT, 'audit_result é append-only: DELETE proibido');
END;
