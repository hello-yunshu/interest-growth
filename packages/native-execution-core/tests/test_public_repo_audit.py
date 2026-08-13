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
    findings = audit_public_repo.content_findings("interest_growth_native/bad.py", runtime)
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
