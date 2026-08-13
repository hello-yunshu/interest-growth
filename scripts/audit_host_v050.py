#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path

SKIP={".git","node_modules",".next",".venv","__pycache__",".pytest_cache"}
TEXT={".py",".js",".mjs",".cjs",".ts",".tsx",".jsx",".json",".yaml",".yml",".toml",".md",".sql"}
ACTIVE_ROOTS=(
    "apps/api",
    "adapters",
    "domains",
    "interest_growth_native",
    "plugins",
    "packages/artifacts",
    "packages/domain",
    "packages/engine-contracts",
    "packages/event-bus",
    "packages/native-execution-core/interest_growth_native",
    "packages/plugin-runtime",
    "packages/shared",
)

def files(root):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT and not any(x in SKIP for x in p.parts):
            yield p,p.read_text("utf-8",errors="ignore")

def active_files(root):
    for relative in ACTIVE_ROOTS:
        base=root/relative
        if base.exists():
            yield from files(base)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("root",type=Path);ap.add_argument("--strict",action="store_true");a=ap.parse_args();root=a.root.resolve()
    for marker in ("apps/api","apps/web","packages","docs"):
        if not (root/marker).exists():raise SystemExit(f"not Interest Growth source tree: missing {marker}")
    out=[]
    def add(sev,id,path,msg):out.append({"severity":sev,"id":id,"path":str(path),"message":msg})
    if not (root/"packages/native-execution-core").exists():add("P0","NATIVE_CORE_MISSING","packages/native-execution-core","RC2 package not copied")
    for rel in ("apps/web/package-lock.json","apps/desktop/package-lock.json","apps/desktop/src-tauri/Cargo.lock"):
        if not (root/rel).exists():add("P1","LOCKFILE_MISSING",rel,"reproducible-build lockfile missing")
    migration=any(
        "0011_native_execution_state" in t.lower()
        or ("native_tutor_checkpoint" in t.lower() and "migration" in str(p).lower())
        for p,t in files(root/"migrations")
    )
    for p,t in active_files(root):
        rel=p.relative_to(root);low=t.lower()
        if p.suffix==".py" and re.search(r"^\s*(from|import)\s+deeptutor\b",t,re.M):
            add("P0","DEEPTUTOR_DIRECT_IMPORT",rel,"active source imports deeptutor")
        if "pg_deeptutor" in t and "compat" not in low and "native-execution-core" not in rel.parts:
            add("P0","DEEPTUTOR_DIRECT_BRIDGE",rel,"active business source still references pg_deeptutor")
        if ("capability." in low or "plugin" in str(rel).lower()) and "integration.deeptutor" in low and any(x in low for x in ("depend","requires","dependency")):
            add("P0","PLUGIN_DEPENDS_ON_DEEPTUTOR",rel,"Capability Plugin depends on integration.deeptutor")
        if re.search(r"global_capability_ids\s*[:=].*\{\s*[\"']\*[\"']\s*\}",t):
            add("P0","GLOBAL_CAPABILITY_FAIL_OPEN",rel,"global capability lifecycle defaults to wildcard")
        if p.suffix==".py" and "session.get(" in t and not any(x in low for x in ("require_area","area_scoped","entityareabinding","current_area","area_id")):
            add("P1","AREA_DIRECT_ID_REVIEW",rel,"direct session.get lacks obvious Area guard")
    if not migration:add("P0","MIGRATION_11_NOT_REGISTERED","migrations","native migration 11 not detected")
    unique={ (x["severity"],x["id"],x["path"],x["message"]):x for x in out}
    out=sorted(unique.values(),key=lambda x:(x["severity"],x["id"],x["path"]))
    counts={s:sum(x["severity"]==s for x in out) for s in ("P0","P1")}
    result={"counts":counts,"findings":out,"ready_for_native_cutover":counts["P0"]==0 and (not a.strict or counts["P1"]==0)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if counts["P0"] else (1 if a.strict and counts["P1"] else 0)
if __name__=="__main__":raise SystemExit(main())
