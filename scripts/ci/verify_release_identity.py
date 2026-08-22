#!/usr/bin/env python3
"""Fail closed unless a release tag's base version matches project.version."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


SUPPORTED_TAG = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+)(?:-(?:rc\.\d+|beta\.\d+|alpha\.\d+|dev\.\d+|pre\.\d+))?$"
)


def verify(tag: str, source: Path) -> tuple[str, str]:
    match = SUPPORTED_TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"unsupported release tag: {tag}")
    with source.open("rb") as handle:
        source_version = tomllib.load(handle)["project"]["version"]
    tag_version = match.group("version")
    if tag_version != source_version:
        raise ValueError(f"tag version {tag_version} != source version {source_version}")
    return tag_version, source_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)
    try:
        tag_version, source_version = verify(args.tag, args.source)
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL: release identity check: {exc}", file=sys.stderr)
        return 1
    print(f"release identity: tag version {tag_version} == source version {source_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
