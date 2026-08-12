import json,sqlite3,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def host(tmp_path):
    h=tmp_path/"host"
    for rel in ("apps/api","apps/web","apps/desktop","apps/desktop/src-tauri","packages","docs","migrations"):
        (h/rel).mkdir(parents=True,exist_ok=True)
    (h/"apps/web/package-lock.json").write_text("{}","utf-8")
    (h/"apps/desktop/package-lock.json").write_text("{}","utf-8")
    (h/"apps/desktop/src-tauri/Cargo.lock").write_text("#lock","utf-8")
    (h/"migrations/0011_native_execution_state.sql").write_text((ROOT/"migrations/0011_native_execution_state.sql").read_text("utf-8"),"utf-8")
    return h

def test_apply_copies_rc2_but_does_not_claim_host_wiring(tmp_path):
    h=host(tmp_path)
    p=subprocess.run([sys.executable,str(ROOT/"scripts/apply_to_interest_growth_v050.py"),str(h)],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    m=json.loads((h/"NATIVE_EXECUTION_APPLY_MANIFEST.json").read_text("utf-8"))
    assert m["status"]=="package_copied_host_wiring_not_claimed"
    assert (h/"packages/native-execution-core/HOST_INTEGRATION_SPEC.json").exists()

def test_host_audit_detects_deeptutor_bridge_and_fail_open_global_default(tmp_path):
    h=host(tmp_path);(h/"packages/native-execution-core").mkdir()
    (h/"apps/api/bad.py").write_text(
        "import deeptutor\npg_deeptutor = object()\nglobal_capability_ids={'*'}\n",
        "utf-8",
    )
    p=subprocess.run([sys.executable,str(ROOT/"scripts/audit_host_v050.py"),str(h),"--strict"],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==2
    ids={x["id"] for x in json.loads(p.stdout)["findings"]}
    assert {"DEEPTUTOR_DIRECT_IMPORT","DEEPTUTOR_DIRECT_BRIDGE","GLOBAL_CAPABILITY_FAIL_OPEN"} <= ids

def test_synthetic_clean_host_can_pass_strict_audit(tmp_path):
    h=host(tmp_path);(h/"packages/native-execution-core").mkdir()
    p=subprocess.run([sys.executable,str(ROOT/"scripts/audit_host_v050.py"),str(h),"--strict"],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr
    assert json.loads(p.stdout)["ready_for_native_cutover"] is True

def test_migration_runner_preserves_legacy_sentinel(tmp_path):
    db=tmp_path/"host.db";conn=sqlite3.connect(db)
    conn.execute("CREATE TABLE legacy(id INTEGER PRIMARY KEY,value TEXT)")
    conn.execute("INSERT INTO legacy(value) VALUES ('keep')");conn.commit();conn.close()
    p=subprocess.run([sys.executable,str(ROOT/"scripts/migrate_host_db_v11.py"),str(db),"--no-backup"],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr
    conn=sqlite3.connect(db)
    assert conn.execute("SELECT value FROM legacy").fetchone()[0]=="keep"
    names={x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"native_tutor_checkpoint","native_run_event","native_aux_memory"} <= names
