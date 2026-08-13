from importlib import resources
from pathlib import Path
from interest_growth_native.execution_store import SQLiteExecutionStore

def test_packaged_migration_resource_matches_release_sql():
    root=Path(__file__).resolve().parents[1]
    a=(root/"migrations/0011_native_execution_state.sql").read_text("utf-8")
    b=resources.files("interest_growth_native").joinpath("resources","0011_native_execution_state.sql").read_text(encoding="utf-8")
    assert a==b

def test_ephemeral_store_initializes_from_packaged_resource():
    s=SQLiteExecutionStore(":memory:")
    with s.connect() as conn:
        names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"native_tutor_checkpoint","native_run_event","native_aux_memory"} <= names
