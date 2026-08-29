#!/usr/bin/env python3
"""Provenance contract for historical Android upgrade evidence."""

import hashlib
import json
import os


ALLOWED_RUNTIME_PROVENANCE = {"historical", "historical-instrumented"}


class ProvenanceError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_historical_upgrade(provenance):
    if not isinstance(provenance, dict):
        raise ProvenanceError("provenance must be an object")
    if provenance.get("runtime_provenance") not in ALLOWED_RUNTIME_PROVENANCE:
        raise ProvenanceError("synthetic-current-native or unknown runtime provenance is forbidden")
    if not provenance.get("old_source_sha"):
        raise ProvenanceError("old_source_sha is required")
    if not provenance.get("new_source_sha"):
        raise ProvenanceError("new_source_sha is required")
    if not provenance.get("old_baseline_tag"):
        raise ProvenanceError("old_baseline_tag is required")
    if not provenance.get("old_apk_sha256") or not provenance.get("new_apk_sha256"):
        raise ProvenanceError("old_apk_sha256 and new_apk_sha256 are required")
    if not provenance.get("instrumentation"):
        raise ProvenanceError("historical instrumentation list is required")
    if not provenance.get("web_provenance"):
        raise ProvenanceError("web_provenance is required")
    if provenance.get("runtime_provenance") == "historical-instrumented" and not provenance.get("native_runtime_preserved"):
        raise ProvenanceError("historical-instrumented evidence must state native runtime preservation")
    return provenance


def build_provenance(*, old_baseline_tag, old_source_sha, old_apk, new_apk,
                     new_source_sha, runtime_provenance, web_provenance,
                     instrumentation, auth_evidence_path=None):
    payload = {
        "schema": "android-upgrade-provenance-v1",
        "old_baseline_tag": old_baseline_tag,
        "old_source_sha": old_source_sha,
        "new_source_sha": new_source_sha,
        "old_apk_sha256": sha256_file(old_apk),
        "new_apk_sha256": sha256_file(new_apk),
        "runtime_provenance": runtime_provenance,
        "native_runtime_preserved": runtime_provenance in ALLOWED_RUNTIME_PROVENANCE,
        "web_provenance": web_provenance,
        "instrumentation": list(instrumentation),
        "auth_evidence_file": auth_evidence_path,
    }
    return validate_historical_upgrade(payload)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-baseline-tag", required=True)
    ap.add_argument("--old-source-sha", required=True)
    ap.add_argument("--old-apk", required=True)
    ap.add_argument("--new-apk", required=True)
    ap.add_argument("--new-source-sha", required=True)
    ap.add_argument("--runtime-provenance", required=True)
    ap.add_argument("--web-provenance", required=True)
    ap.add_argument("--instrumentation", action="append", required=True)
    ap.add_argument("--auth-evidence-path")
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    for path in (args.old_apk, args.new_apk):
        if not os.path.isfile(path):
            raise ProvenanceError(f"APK does not exist: {path}")
    payload = build_provenance(
        old_baseline_tag=args.old_baseline_tag,
        old_source_sha=args.old_source_sha,
        old_apk=args.old_apk,
        new_apk=args.new_apk,
        new_source_sha=args.new_source_sha,
        runtime_provenance=args.runtime_provenance,
        web_provenance=args.web_provenance,
        instrumentation=args.instrumentation,
        auth_evidence_path=args.auth_evidence_path,
    )
    with open(args.output, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
