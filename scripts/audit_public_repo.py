from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = {
    "THIRD_PARTY_NOTICES.md",
    "HOST_INTEGRATION_SPEC.json",
    "docs/FINAL_RC2_AUDIT.md",
    "docs/V03_CROSS_VALIDATION_RC2.md",
}
FORBIDDEN_NATIVE_TABLES = {
    "native_kb",
    "native_document",
    "native_source",
    "native_skill",
    "native_persona",
    "native_mastery",
    "native_practice",
    "native_note",
    "native_book",
    "native_writing",
    "native_claim",
    "native_evidence",
    "native_growth_memory",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
}
PROMPT_FILENAME_PATTERN = re.compile(r"(?:^|[_-])prompts?(?:[_-]|\.|$)|提示词", re.IGNORECASE)
RUNTIME_ROOTS = ("interest_growth_native/",)
RELEASE_CRITICAL_ROOTS = ("interest_growth_native/", "migrations/")


def tracked_paths(root: Path = ROOT) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail}")
    return sorted(p for p in proc.stdout.decode("utf-8").split("\0") if p)


def forbidden_path_reason(path: str) -> str | None:
    pure = PurePosixPath(path)
    lower = path.lower()
    parts = {part.lower() for part in pure.parts}
    name = pure.name.lower()
    if any(part.lower() == "local_only" or "do_not_commit" in part.lower() for part in pure.parts):
        return "local-only or AI coding prompt material"
    if PROMPT_FILENAME_PATTERN.search(name) and not path.startswith("docs/ai-coding/"):
        return "local-only or AI coding prompt material"
    if name == ".env" or (
        name.startswith(".env.") and name not in {".env.example", ".env.remote.example"}
    ):
        return "environment file"
    if pure.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return "credential file"
    if pure.suffix.lower() in {".zip", ".whl"}:
        return "release/build archive"
    if {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"} & parts:
        return "cache or local environment"
    if {"build", "dist"} & parts or name.endswith(".egg-info"):
        return "build output"
    if lower.endswith((".pyc", ".pyo")):
        return "compiled Python output"
    return None


def _python_findings(path: str, text: str) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [f"invalid Python syntax: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "deeptutor" or alias.name.startswith("deeptutor.") for alias in node.names):
            findings.append("direct DeepTutor runtime import")
        if isinstance(node, ast.ImportFrom) and node.module and (node.module == "deeptutor" or node.module.startswith("deeptutor.")):
            findings.append("direct DeepTutor runtime import")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec"}:
                findings.append(f"arbitrary code execution call: {func.id}")
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr == "system"
            ):
                findings.append("arbitrary code execution call: os.system")
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                findings.append(f"runtime subprocess call: subprocess.{func.attr}")
    return sorted(set(findings))


def content_findings(path: str, text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(f"possible {label}")
    if path.startswith(RUNTIME_ROOTS):
        if re.search(r"\bPsychology\b|心理学", text, re.IGNORECASE):
            findings.append("hard-coded Psychology policy in runtime")
        if path.endswith(".py"):
            findings.extend(_python_findings(path, text))
    if path.startswith(RELEASE_CRITICAL_ROOTS) and re.search(
        r"\b(?:TODO|FIXME|NotImplemented)\b", text
    ):
        findings.append("release-critical placeholder")
    if path.startswith("migrations/") and path.endswith(".sql"):
        lowered = text.lower()
        for table in sorted(FORBIDDEN_NATIVE_TABLES):
            if re.search(rf"\b{re.escape(table)}\b", lowered):
                findings.append(f"duplicate canonical native table: {table}")
    return sorted(set(findings))


def audit(root: Path = ROOT) -> list[str]:
    paths = tracked_paths(root)
    failures: list[str] = []
    tracked = set(paths)
    for required in sorted(REQUIRED_PATHS - tracked):
        failures.append(f"missing required tracked file: {required}")
    for path in paths:
        reason = forbidden_path_reason(path)
        if reason:
            failures.append(f"forbidden tracked path ({reason}): {path}")
            continue
        raw = (root / path).read_bytes()
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", "replace")
        for finding in content_findings(path, text):
            failures.append(f"{finding}: {path}")
    spec_path = root / "HOST_INTEGRATION_SPEC.json"
    if spec_path.exists():
        try:
            spec = json.loads(spec_path.read_text("utf-8"))
            if spec["global_lifecycle"]["wildcard_default_allowed_in_production"] is not False:
                failures.append("production global Capability lifecycle is not fail-closed")
            allowed = set(spec["allowed_native_tables"])
            expected = {"native_tutor_checkpoint", "native_run_event", "native_aux_memory"}
            if allowed != expected:
                failures.append("allowed native execution tables drifted")
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"invalid HOST_INTEGRATION_SPEC.json: {exc}")
    return failures


def main() -> int:
    try:
        failures = audit()
    except (OSError, RuntimeError) as exc:
        print(f"PUBLIC REPO AUDIT FAIL: {exc}")
        return 1
    if failures:
        for failure in failures:
            print(f"PUBLIC REPO AUDIT FAIL: {failure}")
        return 1
    print(f"public repository hygiene: PASS ({len(tracked_paths())} tracked paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
