from __future__ import annotations
import ast,compileall,json,re,subprocess,sys,tomllib
from importlib import resources
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PKG=ROOT/"interest_growth_native"
EXPECTED_EVENTS={
    "answer_delta","thinking","activity","sources",
    "wait_for_input","result","done","error",
}
FORBIDDEN_TABLES={
    "native_kb","native_document","native_source","native_skill","native_persona",
    "native_mastery","native_practice","native_note","native_book","native_writing",
    "native_claim","native_evidence","native_growth_memory",
}
def fail(msg):
    print("VERIFY FAIL:",msg);return 1
def main():
    for path in (PKG,ROOT/"scripts",ROOT/"tests"):
        if not compileall.compile_dir(str(path),quiet=1):return fail(f"compileall: {path}")
    for p in PKG.rglob("*.py"):
        text=p.read_text("utf-8")
        ast.parse(text,filename=str(p))
        if re.search(r"^\s*(from|import)\s+deeptutor\b",text,re.M):return fail(f"deeptutor import: {p}")
        if re.search(r"\bPsychology\b|心理学",text,re.I):return fail(f"domain leak: {p}")
        if re.search(r"\b(eval|exec|os\.system|subprocess\.)\s*\(",text):return fail(f"unsafe execution surface: {p}")
    migration=(ROOT/"migrations/0011_native_execution_state.sql").read_text("utf-8")
    for table in FORBIDDEN_TABLES:
        if re.search(rf"\b{re.escape(table)}\b",migration.lower()):return fail(f"forbidden native canonical table: {table}")
    packaged=(PKG/"resources/0011_native_execution_state.sql").read_text("utf-8")
    if migration!=packaged:return fail("migration package resource drift")
    from interest_growth_native.events import PUBLIC_EVENT_TYPES
    if set(PUBLIC_EVENT_TYPES)!=EXPECTED_EVENTS:return fail("public Tutor event contract drift")
    spec=json.loads((ROOT/"HOST_INTEGRATION_SPEC.json").read_text("utf-8"))
    if spec["global_lifecycle"]["wildcard_default_allowed_in_production"] is not False:return fail("global lifecycle fail-open")
    if set(spec["allowed_native_tables"])!={"native_tutor_checkpoint","native_run_event","native_aux_memory"}:return fail("allowed native tables drift")
    with (ROOT/"pyproject.toml").open("rb") as f:project=tomllib.load(f)
    if project["project"]["version"]!="0.6.0rc2":return fail("version mismatch")
    migrate=(ROOT/"scripts/migrate_host_db_v11.py").read_text("utf-8")
    if ".executescript(" in migrate:return fail("production migration runner uses executescript")
    proc=subprocess.run([sys.executable,"-m","pytest","-q","-p","no:cacheprovider"],cwd=ROOT,text=True)
    if proc.returncode:return proc.returncode
    print("native execution core RC2 verification: PASS")
    return 0
if __name__=="__main__":raise SystemExit(main())
