#!/usr/bin/env python3
"""Generate the release verification report (prompt §28 / §30).

`Vx_y_RELEASE_VERIFICATION.md` is produced by GitHub Actions from THIS run's
real data. Nothing is hardcoded: every value is read from the environment /
the asset files actually produced. Items with no evidence are written as
"NOT RUN" (never as PASS).

Inputs come from the calling workflow via `--asset path`, `--field key=value`
(for tool versions / matrix facts) and environment variables that GitHub
Actions sets automatically (GITHUB_REPOSITORY, GITHUB_REF_NAME,
GITHUB_SHA, GITHUB_RUN_ID, RUNNER_OS).

Usage:
    python scripts/ci/generate_release_report.py \
        --out Vx_y_RELEASE_VERIFICATION.md \
        --asset dist/.../interest-growth-X.Y.Z-android-arm64.apk \
        --field "Android SDK=36" --field "NDK=27.1"
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def env(*names: str, default: str = "NOT SET") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="report file path")
    parser.add_argument("--asset", action="append", default=[], help="release asset (repeatable)")
    parser.add_argument("--field", action="append", default=[], help="key=value fact (repeatable)")
    parser.add_argument("--test-result", action="append", default=[],
                        help="job-name=status fact (repeatable)")
    parser.add_argument("--not-run", action="append", default=[],
                        help="explicitly NOT RUN item (repeatable)")
    args = parser.parse_args(argv)

    lines: list[str] = []
    add = lines.append
    tag = env('GITHUB_REF_NAME', default='unknown')
    add(f"# Interest Growth {tag} — Release Verification Report")
    add("")
    add(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    add("")

    add("## 1. Run identity")
    add("")
    add("| Field | Value |")
    add("| --- | --- |")
    add(f"| Repository | `{env('GITHUB_REPOSITORY')}` |")
    add(f"| Ref / tag | `{env('GITHUB_REF_NAME')}` |")
    add(f"| Commit SHA | `{env('GITHUB_SHA')}` |")
    add(f"| Workflow run ID | `{env('GITHUB_RUN_ID')}` |")
    add(f"| Runner OS | `{env('RUNNER_OS', default='NOT SET')}` |")
    add("")

    add("## 2. Toolchain")
    add("")
    add("| Tool | Value |")
    add("| --- | --- |")
    for fact in args.field:
        if "=" in fact:
            key, _, value = fact.partition("=")
            add(f"| {key.strip()} | {value.strip()} |")
    add("")

    add("## 3. Release assets")
    add("")
    add("| Artifact | Bytes | SHA-256 |")
    add("| --- | ---: | --- |")
    for raw in args.asset:
        asset = Path(raw)
        if not asset.is_file():
            print(f"REPORT FAIL: asset does not exist: {asset}", flush=True)
            return 1
        size = asset.stat().st_size
        add(f"| `{asset.name}` | {size} | `{sha256(asset)}` |")
    if not args.asset:
        add("| _(no assets supplied)_ | | |")
    add("")

    add("## 4. Gate results")
    add("")
    for item in args.test_result:
        if "=" in item:
            job, _, status = item.partition("=")
            add(f"- **{job.strip()}**: {status.strip()}")
    if not args.test_result:
        add("- _(no gate results supplied)_")
    add("")

    add("## 5. Explicitly NOT RUN / external boundaries")
    add("")
    if args.not_run:
        for item in args.not_run:
            add(f"- {item}")
    else:
        add("- _(none declared — the calling workflow must declare every "
            "hardware / external gate that was skipped)_")
    add("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"RELEASE REPORT: wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
