from __future__ import annotations

import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/verify_android_apk.sh"


def _apk(path: Path, marker: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        native = b"ELF\x00interest-growth"
        if marker:
            native += marker.encode("utf-8")
        archive.writestr("lib/arm64-v8a/libinterest_growth_desktop_lib.so", native)
        archive.writestr("res/xml/network_security_config.xml", "<network-security-config/>")
    return path


def _tool_path(tmp_path: Path, *, with_aapt: bool) -> tuple[Path, dict[str, str]]:
    tools = tmp_path / ("tools-with-aapt" if with_aapt else "tools-without-aapt")
    tools.mkdir()
    for name in (
        "bash",
        "dirname",
        "basename",
        "unzip",
        "strings",
        "grep",
        "sed",
        "sort",
        "wc",
        "head",
        "tr",
    ):
        source = shutil.which(name)
        assert source, f"test host is missing required utility: {name}"
        (tools / name).symlink_to(source)
    if with_aapt:
        aapt = tools / "aapt"
        aapt.write_text(
            "#!/bin/sh\n"
            "test \"$1\" = dump && test \"$2\" = badging || exit 2\n"
            "printf '%s\\n' \"package: name='app.psychologygrowth.desktop' versionCode='1000021' versionName='1.0.20'\"\n"
            "printf '%s\\n' \"application-label:'Interest Growth'\"\n"
            "printf '%s\\n' \"sdkVersion:'24'\"\n"
            "printf '%s\\n' \"targetSdkVersion:'36'\"\n"
            "printf '%s\\n' \"native-code: 'arm64-v8a'\"\n",
            encoding="utf-8",
        )
        aapt.chmod(aapt.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = str(tools)
    return tools, env


def _run(profile: str, apk: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--profile", profile, "--require-aapt", str(apk)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_debug_profile_allows_expected_debug_marker_without_filename_inference(tmp_path: Path) -> None:
    _, env = _tool_path(tmp_path, with_aapt=True)
    apk = _apk(tmp_path / "interest-growth-arm64-debug.apk", "setWebContentsDebuggingEnabled")

    result = _run("debug", apk, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "profile: debug" in result.stdout


def test_release_profile_rejects_debug_marker_even_when_filename_looks_test_like(tmp_path: Path) -> None:
    _, env = _tool_path(tmp_path, with_aapt=True)
    apk = _apk(tmp_path / "interest-growth-release-test.apk", "setWebContentsDebuggingEnabled")

    result = _run("release", apk, env)

    assert result.returncode == 1
    assert "setWebContentsDebuggingEnabled" in result.stderr


def test_release_test_profile_allows_declared_ci_marker(tmp_path: Path) -> None:
    _, env = _tool_path(tmp_path, with_aapt=True)
    apk = _apk(tmp_path / "interest-growth-arm64-release.apk", "android-ci-trust-root")

    result = _run("release-test", apk, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "release-test" in result.stdout


def test_unknown_profile_and_missing_apk_fail_closed(tmp_path: Path) -> None:
    _, env = _tool_path(tmp_path, with_aapt=True)
    unknown = subprocess.run(
        ["bash", str(SCRIPT), "--profile", "staging", str(tmp_path / "missing.apk")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    missing = subprocess.run(
        ["bash", str(SCRIPT), "--profile", "debug", str(tmp_path / "missing.apk")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert unknown.returncode == 2
    assert "--profile must be one of" in unknown.stderr
    assert missing.returncode == 2
    assert "missing APK" in missing.stderr


def test_release_requires_aapt_even_when_require_flag_is_not_supplied(tmp_path: Path) -> None:
    _, env = _tool_path(tmp_path, with_aapt=False)
    apk = _apk(tmp_path / "interest-growth-arm64.apk")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--profile", "release", str(apk)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "aapt/aapt2 not on PATH" in result.stderr
