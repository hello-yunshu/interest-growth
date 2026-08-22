#!/usr/bin/env python3
"""Append caller-side release identity evidence to a gate-generated report.

The reusable release-gates workflow generates the report before the publication
job knows the final tag and caller run ID. This small fail-closed helper adds
those caller-owned facts after the provisional asset checksum has been
verified and before the final checksum is regenerated.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


IDENTITY_HEADER = "## Release Evidence Identity"
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*")
TAG_RE = re.compile(
    r"v[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-(?:rc|beta|alpha|dev|pre)\.[0-9]+)?"
)


def _is_na(value: str) -> bool:
    return value == "NOT APPLICABLE"


def _validate_sha(name: str, value: str, *, allow_na: bool = False) -> None:
    if allow_na and _is_na(value):
        return
    if FULL_SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a full lowercase commit SHA")


def _validate_run_id(name: str, value: str, *, allow_na: bool = False) -> None:
    if allow_na and _is_na(value):
        return
    if POSITIVE_INTEGER_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a positive integer string")


def _validate_url(name: str, value: str, *, allow_na: bool = False) -> None:
    if allow_na and _is_na(value):
        return
    if not value.startswith("https://"):
        raise ValueError(f"{name} must start with https://")


def _validate_identity(args) -> None:
    if TAG_RE.fullmatch(args.tag) is None:
        raise ValueError("tag must match vX.Y.Z or a supported prerelease format")

    is_prerelease = "-" in args.tag
    _validate_sha("candidate SHA", args.candidate_sha, allow_na=is_prerelease)
    _validate_sha("tag SHA", args.tag_sha)
    _validate_run_id("candidate Run ID", args.candidate_run_id, allow_na=is_prerelease)
    _validate_run_id("release Run ID", args.release_run_id)
    _validate_url("candidate Run URL", args.candidate_run_url, allow_na=is_prerelease)
    _validate_url("release Run URL", args.release_run_url)

    expected_conclusion = "NOT APPLICABLE" if is_prerelease else "success"
    if args.candidate_conclusion != expected_conclusion:
        raise ValueError(
            f"candidate conclusion must be {expected_conclusion} for this tag"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="gate-generated Markdown report")
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--candidate-run-url", required=True)
    parser.add_argument("--candidate-conclusion", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tag-sha", required=True)
    parser.add_argument("--release-run-id", required=True)
    parser.add_argument("--release-run-url", required=True)
    parser.add_argument("--promotion-run-id", default="NOT AVAILABLE IN CALLER")
    args = parser.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        print(f"RELEASE REPORT FINALIZATION FAIL: missing report: {report}", file=sys.stderr)
        return 1

    content = report.read_text(encoding="utf-8")
    if IDENTITY_HEADER in content:
        print(
            f"RELEASE REPORT FINALIZATION FAIL: identity section already exists: {report}",
            file=sys.stderr,
        )
        return 1

    try:
        _validate_identity(args)
    except ValueError as exc:
        print(f"RELEASE REPORT FINALIZATION FAIL: {exc}", file=sys.stderr)
        return 1

    section = "\n".join(
        [
            IDENTITY_HEADER,
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Stable Candidate SHA | `{args.candidate_sha}` |",
            f"| Stable Candidate Run ID | `{args.candidate_run_id}` |",
            f"| Stable Candidate Run URL | {args.candidate_run_url} |",
            f"| Stable Candidate conclusion | `{args.candidate_conclusion}` |",
            f"| Final Tag | `{args.tag}` |",
            f"| Final Tag SHA | `{args.tag_sha}` |",
            f"| Final Release Run ID | `{args.release_run_id}` |",
            f"| Final Release Run URL | {args.release_run_url} |",
            f"| Promotion Run ID | `{args.promotion_run_id}` |",
            "",
        ]
    )
    report.write_text(content.rstrip() + "\n\n" + section, encoding="utf-8")
    print(f"RELEASE REPORT FINALIZATION: appended caller identity to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
