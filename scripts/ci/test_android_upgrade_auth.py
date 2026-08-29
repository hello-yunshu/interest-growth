#!/usr/bin/env python3
"""Unit tests for authenticated Android upgrade preflight and evidence."""

import os
import tempfile

import android_upgrade_auth as a
import android_upgrade_provenance as p
import write_android_upgrade_continuity as c


def test_password_exchange_evidence_is_redacted():
    evidence = a.canonical_auth_evidence(
        "password_exchange", owner_password="super-secret",
        bearer_token="bearer-secret",
    )
    assert evidence["owner_password_present"] is True
    assert evidence["owner_password_length"] == 12
    assert evidence["bearer_token_sha256_prefix"] == a.token_fingerprint("bearer-secret")
    assert "super-secret" not in str(evidence)
    assert "bearer-secret" not in str(evidence)


def test_legacy_session_requires_proven_session():
    evidence = a.canonical_auth_evidence("legacy_session", session_present=True)
    assert evidence["session_present"] is True
    try:
        a.canonical_auth_evidence("legacy_session")
    except a.AuthPreflightError:
        pass
    else:
        raise AssertionError("missing credential/session must fail closed")


def test_preflight_only_accepts_2xx():
    assert a.classify_preflight_status(200)["result"] == "PASS"
    for code in (401, 403, 500):
        try:
            a.classify_preflight_status(code)
        except a.AuthPreflightError:
            pass
        else:
            raise AssertionError(f"HTTP {code} must fail closed")


def test_session_status_is_secret_free():
    out = a.sanitize_session_status({
        "enrolled": True, "connected": True, "authExpired": False,
        "accessToken": "must-not-leak", "deviceId": "device-1",
    })
    assert out == {"enrolled": True, "connected": True, "authExpired": False,
                   "deviceId": "device-1"}


def test_provenance_rejects_synthetic_current_native():
    base = {
        "old_baseline_tag": "v1.0.0-rc.3", "old_source_sha": "oldsha",
        "new_source_sha": "newsha", "web_provenance": "patched",
        "old_apk_sha256": "oldapk", "new_apk_sha256": "newapk",
        "instrumentation": ["cdp"], "native_runtime_preserved": True,
    }
    for value in ("synthetic-current-native", "unknown"):
        try:
            p.validate_historical_upgrade({**base, "runtime_provenance": value})
        except p.ProvenanceError:
            pass
        else:
            raise AssertionError("forbidden provenance passed")


def test_provenance_hashes_real_apk_pair():
    with tempfile.TemporaryDirectory() as td:
        old = os.path.join(td, "old.apk")
        new = os.path.join(td, "new.apk")
        open(old, "wb").write(b"old")
        open(new, "wb").write(b"new")
        old_sha = p.sha256_file(old)
        new_sha = p.sha256_file(new)
        out = p.build_provenance(
            old_baseline_tag="v1.0.0-rc.3", old_source_sha="oldsha",
            old_apk=old, new_apk=new, new_source_sha="newsha",
            runtime_provenance="historical-instrumented",
            web_provenance="patched", instrumentation=["cdp", "tls"],
        )
    assert out["old_apk_sha256"] == old_sha
    assert out["new_apk_sha256"] == new_sha
    assert out["native_runtime_preserved"] is True


def test_continuity_parser_reads_package_install_facts():
    facts = c.package_facts(
        "versionCode=3 minSdk=24\n"
        "  dataDir=/data/user/0/app.psychologygrowth.desktop\n"
        "  firstInstallTime=2026-08-30 01:00:00\n"
        "  lastUpdateTime=2026-08-30 02:00:00\n"
    )
    assert facts["data_dir"].endswith("app.psychologygrowth.desktop")
    assert facts["first_install_time"] == "2026-08-30"
    assert facts["version_code"] == "3"


def run_all():
    failed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())
