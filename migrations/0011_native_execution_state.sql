PRAGMA foreign_keys=ON;

CREATE TABLE native_tutor_checkpoint (
    id TEXT PRIMARY KEY,
    area_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    state TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    user_message TEXT NOT NULL,
    assistant_text TEXT NOT NULL DEFAULT '',
    selected_capability TEXT,
    wait_payload_json TEXT,
    execution_snapshot_json TEXT,
    parent_run_id TEXT,
    host_session_id TEXT,
    host_turn_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_native_checkpoint_area_session
ON native_tutor_checkpoint(area_id, session_id);

CREATE UNIQUE INDEX uq_native_active_turn_per_session
ON native_tutor_checkpoint(area_id, session_id)
WHERE state IN ('running', 'waiting_input');

CREATE TABLE native_run_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES native_tutor_checkpoint(id) ON DELETE CASCADE,
    area_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_native_event_run
ON native_run_event(run_id, seq);

CREATE TABLE native_aux_memory (
    id TEXT PRIMARY KEY,
    area_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source_run_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_native_aux_memory_area_session
ON native_aux_memory(area_id, session_id, created_at);
