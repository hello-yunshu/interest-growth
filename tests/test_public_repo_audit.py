from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_public_repo.py"
SPEC = importlib.util.spec_from_file_location("audit_public_repo", SCRIPT)
assert SPEC and SPEC.loader
audit_public_repo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_public_repo)


def test_forbidden_public_paths_fail_closed():
    cases = {
        "LOCAL_ONLY_DO_NOT_COMMIT/notes.md",
        "docs/internal_prompt.md",
        "总执行提示词.md",
        ".env",
        ".env.local",
        "release/package.whl",
        "dist/source.zip",
        "src/__pycache__/module.pyc",
    }
    for path in cases:
        assert audit_public_repo.forbidden_path_reason(path), path
    assert audit_public_repo.forbidden_path_reason(".env.example") is None
    assert audit_public_repo.forbidden_path_reason(".env.remote.example") is None
    assert audit_public_repo.forbidden_path_reason(
        "domains/general/skills/image-prompt/SKILL.md"
    ) is None
    assert audit_public_repo.forbidden_path_reason(
        "docs/ai-coding/12_CODING_AGENT_MASTER_PROMPT.md"
    ) is None
    assert audit_public_repo.forbidden_path_reason("docs/product_prompts.md") is not None


def test_runtime_content_guards_detect_architecture_and_security_regressions():
    runtime = """\
import deeptutor
import os

def run(payload):
    # Psychology must stay in a Domain Pack.
    return eval(payload), os.system(payload)  # TODO
"""
    findings = audit_public_repo.content_findings("packages/native-execution-core/interest_growth_native/bad.py", runtime)
    assert "direct DeepTutor runtime import" in findings
    assert "hard-coded Psychology policy in runtime" in findings
    assert "arbitrary code execution call: eval" in findings
    assert "arbitrary code execution call: os.system" in findings
    assert "release-critical placeholder" in findings


def test_migration_and_secret_guards_detect_forbidden_truth_and_tokens():
    migration = "CREATE TABLE native_mastery (id TEXT);"
    assert "duplicate canonical native table: native_mastery" in audit_public_repo.content_findings(
        "migrations/0012_bad.sql", migration
    )
    fake_token = "ghp_" + "x" * 24
    assert "possible GitHub token" in audit_public_repo.content_findings(
        "config.txt", fake_token
    )


def _write_capability(root: Path, rel: Path, data: dict) -> None:
    target = root / rel
    target.write_text(__import__("json").dumps(data, indent=2))


def test_android_capability_gate_rejects_non_minimal_permissions(tmp_path):
    # Baseline: the minimal Android capability passes cleanly.
    root = tmp_path
    root.mkdir(exist_ok=True)
    desktop = root / audit_public_repo.DESKTOP_CAPABILITY
    desktop.parent.mkdir(parents=True, exist_ok=True)
    _write_capability(
        root,
        audit_public_repo.ANDROID_CAPABILITY,
        {
            "identifier": audit_public_repo.ANDROID_CAPABILITY_IDENTIFIER,
            "platforms": ["android"],
            "permissions": ["core:default", "opener:allow-default-urls"],
        },
    )
    _write_capability(
        root,
        audit_public_repo.DESKTOP_CAPABILITY,
        {"identifier": "main-capability", "platforms": ["macOS", "windows", "linux"], "permissions": []},
    )
    assert audit_public_repo.android_capability_findings(root) == []

    # Any permission beyond the minimal allowlist fails the denylist gate.
    _write_capability(
        root,
        audit_public_repo.ANDROID_CAPABILITY,
        {
            "identifier": audit_public_repo.ANDROID_CAPABILITY_IDENTIFIER,
            "platforms": ["android"],
            "permissions": [
                "core:default",
                "opener:allow-default-urls",
                "dialog:allow-save",
                "window-state:default",
                "fs:allow-write-file",
            ],
        },
    )
    findings = audit_public_repo.android_capability_findings(root)
    assert any("denylist" in f for f in findings), findings
    assert any("dialog:allow-save" in f and "window-state:default" in f and "fs:allow-write-file" in f for f in findings)


def test_android_capability_gate_enforces_platform_isolation(tmp_path):
    root = tmp_path
    root.mkdir(exist_ok=True)
    desktop = root / audit_public_repo.DESKTOP_CAPABILITY
    desktop.parent.mkdir(parents=True, exist_ok=True)
    android = root / audit_public_repo.ANDROID_CAPABILITY
    # Android scoped to more than android fails.
    _write_capability(
        root,
        audit_public_repo.ANDROID_CAPABILITY,
        {
            "identifier": audit_public_repo.ANDROID_CAPABILITY_IDENTIFIER,
            "platforms": ["android", "iOS"],
            "permissions": ["core:default", "opener:allow-default-urls"],
        },
    )
    _write_capability(
        root,
        audit_public_repo.DESKTOP_CAPABILITY,
        {"identifier": "main-capability", "platforms": ["macOS", "windows", "linux"], "permissions": []},
    )
    findings = audit_public_repo.android_capability_findings(root)
    assert any("scoped to exactly" in f for f in findings), findings

    # Desktop capability with no explicit platforms leaks into Android and fails.
    _write_capability(
        root,
        audit_public_repo.ANDROID_CAPABILITY,
        {
            "identifier": audit_public_repo.ANDROID_CAPABILITY_IDENTIFIER,
            "platforms": ["android"],
            "permissions": ["core:default", "opener:allow-default-urls"],
        },
    )
    _write_capability(
        root,
        audit_public_repo.DESKTOP_CAPABILITY,
        {"identifier": "main-capability", "permissions": []},
    )
    findings = audit_public_repo.android_capability_findings(root)
    assert any("capability isolation" in f for f in findings), findings


def test_android_capability_gate_requires_android_file(tmp_path):
    root = tmp_path
    root.mkdir(exist_ok=True)
    findings = audit_public_repo.android_capability_findings(root)
    assert any("missing Android capability" in f for f in findings), findings
