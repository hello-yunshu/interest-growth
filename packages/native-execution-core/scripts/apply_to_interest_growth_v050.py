#!/usr/bin/env python3
"""Fail-closed package copier; never blind-rewrites unknown host orchestration."""
from __future__ import annotations
import argparse,hashlib,json,shutil
from pathlib import Path

def tree_hash(root):
    h=hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        if any(x in p.parts for x in ("__pycache__",".pytest_cache","build","dist")) or p.suffix in {".pyc",".whl",".zip"}:continue
        h.update(p.relative_to(root).as_posix().encode());h.update(p.read_bytes())
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("target",type=Path);ap.add_argument("--force-copy",action="store_true");a=ap.parse_args();target=a.target.resolve()
    missing=[x for x in ("apps/api","apps/web","packages","docs") if not (target/x).exists()]
    if missing:raise SystemExit(f"not Interest Growth source tree: missing {missing}")
    src=Path(__file__).resolve().parents[1];dest=target/"packages/native-execution-core"
    if dest.exists() and not a.force_copy:raise SystemExit(f"{dest} exists; review before --force-copy")
    if dest.exists():shutil.rmtree(dest)
    shutil.copytree(src,dest,ignore=shutil.ignore_patterns("__pycache__",".pytest_cache","*.pyc","*.zip","*.whl","build","dist","*.egg-info"))
    spec=json.loads((src/"HOST_INTEGRATION_SPEC.json").read_text("utf-8"))
    manifest={
        "package":"native-execution-core","version":"0.6.0rc2",
        "tree_sha256":tree_hash(dest),
        "expected_host_baseline":spec["target_host_baseline"],
        "v03_invariant_reference":spec["v03_reference"],
        "status":"package_copied_host_wiring_not_claimed",
        "required_next_steps":spec["host_merge_gates"],
    }
    (target/"NATIVE_EXECUTION_APPLY_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__":raise SystemExit(main())
