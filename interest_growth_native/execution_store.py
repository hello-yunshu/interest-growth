from __future__ import annotations

import json
import sqlite3
import uuid
from importlib import resources
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from .errors import AreaIsolationError, InvalidStateTransition, ValidationError
from .events import RuntimeEvent

RUNNING = "running"
WAITING = "waiting_input"
COMPLETED = "completed"
CANCELLED = "cancelled"
ERROR = "error"
TERMINAL = {COMPLETED, CANCELLED, ERROR}

REQUIRED_TABLES = {
    "native_tutor_checkpoint",
    "native_run_event",
    "native_aux_memory",
}

@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    area_id: str
    session_id: str
    state: str
    version: int
    user_message: str
    assistant_text: str = ""
    selected_capability: str | None = None
    wait_payload: dict[str, Any] | None = None
    execution_snapshot: dict[str, Any] | None = None
    parent_run_id: str | None = None
    host_session_id: str | None = None
    host_turn_id: str | None = None

class SQLiteExecutionStore:
    """Execution-only state.

    Persistent stores NEVER create schema implicitly. In-memory schema
    initialization exists only for tests/local ephemeral sessions.
    """

    def __init__(self, path: str | Path = ":memory:", *, initialize_memory: bool = True):
        self.path = str(path)
        self._memory = self.path == ":memory:"
        self._lock = RLock()
        self._conn: sqlite3.Connection | None = None
        if self._memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            if initialize_memory:
                self.initialize_schema_for_tests()
        else:
            self.verify_schema()

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def loads(value: str | None, default: Any = None) -> Any:
        return default if value is None else json.loads(value)

    def initialize_schema_for_tests(self) -> None:
        assert self._conn is not None
        sql = (
            resources.files("interest_growth_native")
            .joinpath("resources", "0011_native_execution_state.sql")
            .read_text(encoding="utf-8")
        )
        self._conn.executescript(sql)

    def verify_schema(self) -> None:
        p = Path(self.path)
        if not p.is_file():
            raise ValidationError(f"execution DB missing: {p}; run host migration first")
        conn = sqlite3.connect(p)
        try:
            names = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        missing = REQUIRED_TABLES - names
        if missing:
            raise ValidationError(
                f"native execution migration missing tables: {sorted(missing)}"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._memory:
                assert self._conn is not None
                try:
                    yield self._conn
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise
            else:
                conn = sqlite3.connect(self.path, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

    def create_run(
        self,
        *,
        area_id: str,
        session_id: str,
        user_message: str,
        selected_capability: str | None = None,
        parent_run_id: str | None = None,
        host_session_id: str | None = None,
        host_turn_id: str | None = None,
        execution_snapshot: dict[str, Any] | None = None,
    ) -> RunRecord:
        rid = uuid.uuid4().hex
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO native_tutor_checkpoint(
                        id, area_id, session_id, state, version, user_message,
                        assistant_text, selected_capability, execution_snapshot_json,
                        parent_run_id, host_session_id, host_turn_id
                    ) VALUES (?, ?, ?, ?, 0, ?, '', ?, ?, ?, ?, ?)
                    """,
                    (
                        rid, area_id, session_id, RUNNING, user_message,
                        selected_capability,
                        self.dumps(execution_snapshot) if execution_snapshot else None,
                        parent_run_id, host_session_id, host_turn_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise InvalidStateTransition(
                f"session already has an active native turn: {area_id}/{session_id}"
            ) from exc
        return self.load(rid, area_id=area_id)

    def load(self, run_id: str, *, area_id: str | None = None) -> RunRecord:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM native_tutor_checkpoint WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        if area_id is not None and row["area_id"] != area_id:
            raise AreaIsolationError("run belongs to another Interest Area")
        return RunRecord(
            id=row["id"],
            area_id=row["area_id"],
            session_id=row["session_id"],
            state=row["state"],
            version=row["version"],
            user_message=row["user_message"],
            assistant_text=row["assistant_text"],
            selected_capability=row["selected_capability"],
            wait_payload=self.loads(row["wait_payload_json"]),
            execution_snapshot=self.loads(row["execution_snapshot_json"]),
            parent_run_id=row["parent_run_id"],
            host_session_id=row["host_session_id"],
            host_turn_id=row["host_turn_id"],
        )

    def transition(
        self,
        run_id: str,
        *,
        area_id: str,
        from_states: set[str],
        to_state: str,
        expected_version: int,
        assistant_text: str | None = None,
        wait_payload: dict[str, Any] | None = None,
        execution_snapshot: dict[str, Any] | None = None,
    ) -> RunRecord:
        sets = ["state=?", "version=version+1", "updated_at=CURRENT_TIMESTAMP"]
        values: list[Any] = [to_state]
        if assistant_text is not None:
            sets.append("assistant_text=?")
            values.append(assistant_text)
        if wait_payload is not None or to_state != WAITING:
            sets.append("wait_payload_json=?")
            values.append(self.dumps(wait_payload) if wait_payload is not None else None)
        if execution_snapshot is not None:
            sets.append("execution_snapshot_json=?")
            values.append(self.dumps(execution_snapshot))

        placeholders = ",".join("?" for _ in from_states)
        values += [run_id, area_id, expected_version, *sorted(from_states)]
        with self.connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE native_tutor_checkpoint
                SET {",".join(sets)}
                WHERE id=? AND area_id=? AND version=?
                  AND state IN ({placeholders})
                """,
                values,
            )
            changed = cur.rowcount
        current = self.load(run_id, area_id=area_id)
        if not changed:
            raise InvalidStateTransition(
                f"CAS transition rejected; current={current.state}@v{current.version}"
            )
        return current

    def update_snapshot(
        self,
        run_id: str,
        *,
        area_id: str,
        expected_version: int,
        execution_snapshot: dict[str, Any],
        assistant_text: str | None = None,
    ) -> RunRecord:
        sets = ["execution_snapshot_json=?", "version=version+1", "updated_at=CURRENT_TIMESTAMP"]
        values: list[Any] = [self.dumps(execution_snapshot)]
        if assistant_text is not None:
            sets.append("assistant_text=?")
            values.append(assistant_text)
        values += [run_id, area_id, expected_version, RUNNING]
        with self.connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE native_tutor_checkpoint
                SET {",".join(sets)}
                WHERE id=? AND area_id=? AND version=? AND state=?
                """,
                values,
            )
            changed = cur.rowcount
        current = self.load(run_id, area_id=area_id)
        if not changed:
            raise InvalidStateTransition(
                f"snapshot CAS rejected; current={current.state}@v{current.version}"
            )
        return current

    def append_event(self, event: RuntimeEvent) -> RuntimeEvent:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO native_run_event(
                    run_id, area_id, session_id, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id, event.area_id, event.session_id, event.type,
                    self.dumps(event.payload), event.created_at,
                ),
            )
            seq = int(cur.lastrowid)
        return RuntimeEvent(
            event.type, event.run_id, event.area_id, event.session_id,
            dict(event.payload), seq, event.created_at,
        )

    def events(
        self,
        run_id: str,
        *,
        area_id: str,
        after_seq: int = 0,
        limit: int = 1000,
    ) -> list[sqlite3.Row]:
        self.load(run_id, area_id=area_id)
        limit = max(1, min(int(limit), 5000))
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM native_run_event
                WHERE run_id=? AND area_id=? AND seq>?
                ORDER BY seq LIMIT ?
                """,
                (run_id, area_id, max(0, int(after_seq)), limit),
            ).fetchall()

    def write_aux_memory(
        self,
        *,
        area_id: str,
        session_id: str,
        layer: str,
        kind: str,
        content: str,
        source_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        mid = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO native_aux_memory(
                    id, area_id, session_id, layer, kind, content,
                    source_run_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid, area_id, session_id, layer, kind, content,
                    source_run_id, self.dumps(metadata or {}),
                ),
            )
        return mid

    def read_aux_memory(
        self,
        *,
        area_id: str,
        session_id: str,
        limit: int = 30,
    ):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM native_aux_memory
                WHERE area_id=? AND session_id=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (area_id, session_id, max(1, min(limit, 500))),
            ).fetchall()

    def stale_running(self) -> list[RunRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, area_id FROM native_tutor_checkpoint WHERE state=?",
                (RUNNING,),
            ).fetchall()
        return [self.load(r["id"], area_id=r["area_id"]) for r in rows]

    def recover_stale_running(self, *, to_state: str = ERROR) -> tuple[RunRecord, ...]:
        if to_state not in {ERROR, CANCELLED}:
            raise ValueError("stale runs must become error or cancelled")
        recovered = []
        for row in self.stale_running():
            try:
                recovered.append(
                    self.transition(
                        row.id,
                        area_id=row.area_id,
                        from_states={RUNNING},
                        to_state=to_state,
                        expected_version=row.version,
                        assistant_text=row.assistant_text,
                    )
                )
            except InvalidStateTransition:
                pass
        return tuple(recovered)
