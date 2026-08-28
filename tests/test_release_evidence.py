from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / "ci" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finalize_release_report_appends_exact_identity(tmp_path):
    module = load_script("finalize_release_report.py")
    report = tmp_path / "V1_0_20_RELEASE_VERIFICATION.md"
    report.write_text("# Interest Growth v1.0.20 — Release Verification Report\n", encoding="utf-8")

    result = module.main(
        [
            "--report",
            str(report),
            "--candidate-sha",
            "a" * 40,
            "--candidate-run-id",
            "123456789",
            "--candidate-run-url",
            "https://github.com/hello-yunshu/interest-growth/actions/runs/123456789",
            "--candidate-conclusion",
            "success",
            "--tag",
            "v1.0.20",
            "--tag-sha",
            "b" * 40,
            "--release-run-id",
            "987654321",
            "--release-run-url",
            "https://github.com/hello-yunshu/interest-growth/actions/runs/987654321",
        ]
    )

    assert result == 0
    content = report.read_text(encoding="utf-8")
    assert "## Release Evidence Identity" in content
    assert "| Stable Candidate SHA | `" + "a" * 40 + "` |" in content
    assert "| Stable Candidate Run ID | `123456789` |" in content
    assert "| Final Tag SHA | `" + "b" * 40 + "` |" in content
    assert "| Final Release Run ID | `987654321` |" in content

    assert module.main(
        [
            "--report",
            str(report),
            "--candidate-sha",
            "NOT APPLICABLE",
            "--candidate-run-id",
            "NOT APPLICABLE",
            "--candidate-run-url",
            "NOT APPLICABLE",
            "--candidate-conclusion",
            "NOT APPLICABLE",
            "--tag",
            "v1.0.20",
            "--tag-sha",
            "b" * 40,
            "--release-run-id",
            "987654321",
            "--release-run-url",
            "NOT APPLICABLE",
        ]
    ) == 1


def test_finalize_release_report_rejects_invalid_identity_fields(tmp_path):
    module = load_script("finalize_release_report.py")

    def invoke(**overrides):
        report = tmp_path / "report.md"
        report.write_text("# report\n", encoding="utf-8")
        values = {
            "candidate_sha": "a" * 40,
            "candidate_run_id": "123456789",
            "candidate_run_url": "https://github.com/example/run/123456789",
            "candidate_conclusion": "success",
            "tag": "v1.0.20",
            "tag_sha": "b" * 40,
            "release_run_id": "987654321",
            "release_run_url": "https://github.com/example/run/987654321",
        }
        values.update(overrides)
        argv = ["--report", str(report)]
        for key, value in values.items():
            argv.extend([f"--{key.replace('_', '-')}", value])
        return module.main(argv)

    assert invoke(candidate_sha="not-a-sha") == 1
    assert invoke(tag_sha="B" * 40) == 1
    assert invoke(candidate_conclusion="failure") == 1
    assert invoke(candidate_run_id="0") == 1
    assert invoke(tag="release-1.0.20") == 1
    assert invoke(release_run_url="http://github.com/example/run/987654321") == 1


def test_finalize_release_report_accepts_prerelease_not_applicable_candidate(tmp_path):
    module = load_script("finalize_release_report.py")
    report = tmp_path / "V1_0_20_RELEASE_VERIFICATION.md"
    report.write_text("# report\n", encoding="utf-8")

    assert module.main(
        [
            "--report",
            str(report),
            "--candidate-sha",
            "NOT APPLICABLE",
            "--candidate-run-id",
            "NOT APPLICABLE",
            "--candidate-run-url",
            "NOT APPLICABLE",
            "--candidate-conclusion",
            "NOT APPLICABLE",
            "--tag",
            "v1.0.20-rc.1",
            "--tag-sha",
            "b" * 40,
            "--release-run-id",
            "987654321",
            "--release-run-url",
            "https://github.com/example/run/987654321",
        ]
    ) == 0


def test_release_workflow_verifies_and_regenerates_downloaded_checksums():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    reusable = (ROOT / ".github/workflows/_release-gates.yml").read_text(encoding="utf-8")
    assert "sha256sum -c SHA256SUMS.txt" in workflow
    assert "verify_release_identity.py --tag" in workflow
    assert "verify_release_identity.py --tag" in reusable
    assert "id: candidate-proof" in workflow
    assert "candidate_run_id=" in workflow
    assert "finalize_release_report.py" in workflow
    assert "generate_release_checksums.py" in workflow
    assert "adb shell am start -W -n app.psychologygrowth.desktop/.MainActivity" in reusable
    assert "adb shell pidof app.psychologygrowth.desktop" in reusable
    assert "adb_root_ok=false" in reusable
    assert "adb_root_ok=false; for _ in $(seq 1 3); do if adb root;" in reusable
    assert "done; if [ \"$adb_root_ok\" != true ]; then" in reusable
    assert "for _ in $(seq 1 60); do if adb shell pidof app.psychologygrowth.desktop" in reusable
    assert "for attempt in 1 2 3; do if npm run tauri -- android build --apk --target x86_64" in reusable
    assert ":app:assembleUniversalRelease -x rustBuildUniversalRelease" in reusable
    assert "ci-old-java-oncreate.txt" in reusable
    assert "create-stage crash buffer" in reusable
    assert "verify-stage crash buffer" in reusable
    assert "create-stage app startup logcat" in reusable
    assert "verify-stage app startup logcat" in reusable
    assert "Final Release Run ID" in (ROOT / "scripts/ci/finalize_release_report.py").read_text(
        encoding="utf-8"
    )
    patcher = (ROOT / "scripts/ci/patch_release_test_source.sh").read_text(encoding="utf-8")
    webview_patcher = (ROOT / "scripts/ci/enable_release_test_webview.sh").read_text(
        encoding="utf-8"
    )
    assert "super_anchor =" in patcher
    assert "super_anchor =" in webview_patcher
    assert "must not race broker initialization" in webview_patcher
    assert "ci-old-startup-error.txt" in patcher
    assert "CI historical Android plugin surface" in patcher
    assert "IG_REPO_ROOT" in patcher
    assert "current qualified native runtime" in patcher
    assert "native_transplanted" in patcher
    assert "--features android-ci-trust-root" in reusable
    diagnostics = (ROOT / "scripts/ci/print_android_startup_diagnostics.sh").read_text(
        encoding="utf-8"
    )
    assert "separate shell command" in diagnostics
    assert "ci-old-startup-panic.txt" in diagnostics


def test_tracked_workflows_use_readable_action_refs():
    workflow_dir = ROOT / ".github/workflows"
    bad = []
    for path in workflow_dir.glob("*.yml"):
        # This user-owned untracked scratch workflow is intentionally outside
        # the product workflow set and must remain untouched.
        if path.name == "release 2.yml":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"uses:.*@[0-9a-f]{40}\b|uses:.*@sha256:", text):
            bad.append(path.name)
    assert not bad, f"workflow Action refs must be readable tags/named refs: {bad}"


def test_release_identity_accepts_stable_and_rc_tags_and_rejects_mismatch(tmp_path):
    module = load_script("verify_release_identity.py")
    source = tmp_path / "pyproject.toml"
    source.write_text('[project]\nversion = "1.0.20"\n', encoding="utf-8")

    assert module.verify("v1.0.20", source) == ("1.0.20", "1.0.20")
    assert module.verify("v1.0.20-rc.1", source) == ("1.0.20", "1.0.20")

    try:
        module.verify("v1.1.0-rc.1", source)
    except ValueError as exc:
        assert "tag version 1.1.0 != source version 1.0.20" in str(exc)
    else:
        raise AssertionError("mismatched release identity must fail")


def test_checksum_fixture_matches_sha256(tmp_path):
    module = load_script("generate_release_checksums.py")
    asset = tmp_path / "asset.txt"
    asset.write_bytes(b"release evidence\n")
    sums = tmp_path / "SHA256SUMS.txt"

    assert module.main(["--out", str(sums), str(asset)]) == 0
    expected = hashlib.sha256(asset.read_bytes()).hexdigest()
    assert sums.read_text(encoding="utf-8") == f"{expected}  asset.txt\n"
