import sqlite3,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from migrate_host_db_v11 import apply_atomic

def test_migration_failure_is_atomic(tmp_path):
    sql=(ROOT/"migrations/0011_native_execution_state.sql").read_text("utf-8")
    conn=sqlite3.connect(tmp_path/"x.db")
    conn.execute("CREATE TABLE sentinel(id INTEGER)");conn.commit()
    with pytest.raises(RuntimeError):apply_atomic(conn,sql,fail_after=1)
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert tables=={"sentinel"}

def test_production_migration_runner_does_not_use_executescript():
    text=(ROOT/"scripts/migrate_host_db_v11.py").read_text("utf-8")
    assert ".executescript(" not in text
