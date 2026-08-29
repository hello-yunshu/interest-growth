#!/usr/bin/env python3
"""Regression gate: the OLD APK patch may instrument, never transplant runtime."""

import os
import subprocess
import tempfile
import tarfile


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(ROOT, "scripts", "ci", "patch_release_test_source.sh")
ALLOWLIST = {
    "apps/desktop/src-tauri/Cargo.toml",
    "apps/desktop/src-tauri/gen/android/app/build.gradle.kts",
    "apps/desktop/src-tauri/gen/android/app/proguard-rules.pro",
    "apps/desktop/src-tauri/gen/android/app/src/main/java/app/psychologygrowth/desktop/CiFlags.kt",
    "apps/desktop/src-tauri/gen/android/app/src/main/java/app/psychologygrowth/desktop/MainActivity.kt",
    "apps/desktop/src-tauri/src/lib.rs",
    "apps/desktop/src-tauri/src/remote.rs",
}


def archive_ref():
    try:
        subprocess.run(["git", "rev-parse", "v1.0.0-rc.3"], cwd=ROOT,
                       check=True, capture_output=True)
        return "v1.0.0-rc.3"
    except subprocess.CalledProcessError:
        return "HEAD"


def snapshot(path):
    result = {}
    for base, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, path)
            with open(full, "rb") as fh:
                result[rel] = fh.read()
    return result


def test_static_forbidden_transplant_markers():
    text = open(SCRIPT).read()
    for forbidden in (
        "native_transplanted",
        "native_paths",
        "old_manifest",
        "old_lock",
        "repo_root",
        "source_fh",
        "transplanted current qualified native runtime",
        "CI historical Android plugin surface: desktop-only plugins",
        "CI old Android opener plugin omitted",
        "CI old Android SAF bridge omitted",
        "open(source",
    ):
        assert forbidden not in text, forbidden
    assert "preserved historical plugin surface" in text
    assert "android-ci-trust-root" in text


def test_fake_old_tree_changes_only_allowlisted_paths_and_is_idempotent():
    with tempfile.TemporaryDirectory(prefix="ig-patch-regression-") as td:
        with subprocess.Popen(["git", "archive", archive_ref()], cwd=ROOT,
                              stdout=subprocess.PIPE) as proc:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                archive.extractall(td)
            assert proc.wait() == 0
        before = snapshot(td)
        first = subprocess.run(["bash", SCRIPT, td], cwd=ROOT,
                               text=True, capture_output=True)
        assert first.returncode == 0, first.stderr
        after_first = snapshot(td)
        changed = {path for path in set(before) | set(after_first)
                   if before.get(path) != after_first.get(path)}
        assert changed <= ALLOWLIST, sorted(changed - ALLOWLIST)
        second = subprocess.run(["bash", SCRIPT, td], cwd=ROOT,
                                text=True, capture_output=True)
        assert second.returncode == 0, second.stderr
        assert snapshot(td) == after_first


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
