#!/usr/bin/env python3
"""Resolve an upgrade baseline from published Releases, then a frozen fallback."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-tag", required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    releases = json.load(__import__("sys").stdin)
    stable = [
        release
        for release in releases
        if not release.get("draft")
        and not release.get("prerelease")
        and release.get("published_at")
        and release.get("tag_name") != args.current_tag
    ]
    if stable:
        # GitHub returns releases newest-first; sort by publication timestamp
        # so the decision is explicit and independent of tag spelling.
        baseline = max(stable, key=lambda release: release["published_at"])["tag_name"]
        print(f"{baseline}\tlatest-published-stable")
        return 0
    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    fallback = config.get("upgrade", {}).get("fallback_tag")
    if not isinstance(fallback, str) or not fallback or fallback == args.current_tag:
        raise SystemExit("no valid frozen upgrade baseline configured")
    if not any(release.get("tag_name") == fallback and not release.get("draft") for release in releases):
        raise SystemExit(f"frozen upgrade baseline is not a published release: {fallback}")
    print(f"{fallback}\tfrozen-last-distributed-rc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
