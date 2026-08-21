#!/usr/bin/env python3
"""Build the clean-extract self-hosted server deployment bundle."""

from __future__ import annotations

import argparse
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "docker-compose.yml",
    "docker-compose.remote.yml",
    ".env.remote.example",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "apps/api",
    "apps/web",
    "packages",
    "adapters",
    "plugins",
    "domains",
    "scripts",
    "deploy",
    "docs/operations/V0_7_BACKUP_RESTORE.md",
    "deployment/README.md",
)


def tracked_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    output = subprocess.check_output(["git", "ls-files", "--", str(path)], cwd=ROOT, text=True)
    return [ROOT / line for line in output.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    files: list[Path] = []
    for relative in FILES:
        target = ROOT / relative
        if not target.exists():
            raise SystemExit(f"missing bundle input: {relative}")
        files.extend(tracked_files(target))
    unique = sorted(set(files))
    prefix = f"interest-growth-server-{args.version}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ig-server-bundle-") as temp:
        stage = Path(temp) / prefix
        stage.mkdir()
        for source in unique:
            relative = source.relative_to(ROOT)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        (stage / "VERSION").write_text(f"{args.version}\n", encoding="utf-8")
        (stage / "SOURCE_SHA").write_text(f"{args.source_sha}\n", encoding="utf-8")
        with tarfile.open(args.out, "w:gz") as archive:
            for source in sorted(stage.rglob("*")):
                info = archive.gettarinfo(str(source), arcname=str(source.relative_to(stage.parent)))
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                if source.is_file():
                    with source.open("rb") as handle:
                        archive.addfile(info, handle)
                else:
                    archive.addfile(info)
    print(f"SERVER BUNDLE: {args.out} ({len(unique)} tracked source files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
