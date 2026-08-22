#!/usr/bin/env python3
"""Append caller-side release identity evidence to a gate-generated report.

The reusable release-gates workflow generates the report before the publication
job knows the final tag and caller run ID. This small fail-closed helper adds
those caller-owned facts after the provisional asset checksum has been
verified and before the final checksum is regenerated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


IDENTITY_HEADER = "## Release Evidence Identity"


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
