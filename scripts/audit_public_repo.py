from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
# Keep the scripts directory importable so the SOURCE_MANIFEST scope check can
# reuse the manifest's own scope definition (single source of truth).
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
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
# Java keystore (JKS) magic bytes; checked against raw file bytes, not text.
JKS_MAGIC = b"\xfe\xed\xfe\xed"
# Credential/keystore/private-key files are never allowed in the public repo,
# regardless of extension (BLOCKER-1 / Gate F secret hygiene).
FORBIDDEN_CREDENTIAL_SUFFIXES = {".jks", ".keystore", ".p12", ".pfx", ".pem", ".key"}
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


def tracked_symlinks(root: Path = ROOT) -> list[str]:
    """Return the tracked paths whose git mode is a symlink (120000)."""
    proc = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git ls-files -s failed: {detail}")
    result = []
    for line in proc.stdout.decode("utf-8").splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        mode = meta.split(" ", 1)[0] if meta.split(" ", 1) else ""
        if mode == "120000":
            result.append(path)
    return sorted(result)


# BLOCKER-1 — tracked symlink / path integrity. A clean checkout must be fully
# readable and self-contained: no broken link, no link escaping the repository,
# no link into an absolute path / $HOME / node_modules, and no path that tries
# to escape the tree. Failing any of these fails the public-repo gate; the
# manifest and CI must never work around them by widening an ignore list.
def symlink_integrity_findings(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    root_resolved = root.resolve()
    for path in tracked_symlinks(root):
        full = root / path
        if not os.path.islink(full):
            failures.append(f"tracked symlink is not a link on disk: {path}")
            continue
        target = os.readlink(full)
        if os.path.isabs(target):
            failures.append(f"tracked symlink points to an absolute path: {path} -> {target}")
            continue
        target_parts = PurePosixPath(target).parts
        if "node_modules" in target_parts:
            failures.append(
                f"tracked symlink references node_modules (not self-contained): {path} -> {target}"
            )
            continue
        resolved = (full.parent / target).resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            failures.append(f"tracked symlink escapes the repository: {path} -> {target}")
            continue
        if str(resolved).startswith(str(Path.home())):
            failures.append(f"tracked symlink resolves under $HOME: {path} -> {target}")
            continue
        if not resolved.exists():
            failures.append(f"broken tracked symlink (clean checkout unreadable): {path} -> {target}")
    return failures


def tracked_path_escape_findings(paths: list[str]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        pure = PurePosixPath(path)
        if pure.is_absolute():
            failures.append(f"tracked path is absolute: {path}")
        if any(part == ".." for part in pure.parts):
            failures.append(f"tracked path escapes the tree via '..': {path}")
    return failures


def credential_file_findings(paths: list[str]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        if PurePosixPath(path).suffix.lower() in FORBIDDEN_CREDENTIAL_SUFFIXES:
            failures.append(f"credential/keystore file must never be tracked: {path}")
    return failures


def source_manifest_scope_findings(root: Path = ROOT) -> list[str]:
    """Prove SOURCE_MANIFEST covers exactly the current tracked scope.

    The manifest may only exclude itself and the standalone Native Core
    subtree (which owns its own package-scoped manifest). Any other drift
    (missing or extra tracked files) fails the repository gate so a clean
    checkout is auditable and no generated Android source is silently skipped.
    """
    failures: list[str] = []
    try:
        import generate_source_manifest  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return [f"cannot import generate_source_manifest for scope check: {exc}"]
    manifest_path = root / generate_source_manifest.MANIFEST_NAME
    if not manifest_path.exists():
        return [f"missing {generate_source_manifest.MANIFEST_NAME}"]
    tracked = set(tracked_paths(root))
    excluded = {
        p
        for p in tracked
        if p == generate_source_manifest.MANIFEST_NAME
        or p.startswith(generate_source_manifest.EXCLUDED_PREFIXES)
    }
    expected = tracked - excluded
    actual = set()
    for line in manifest_path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        if "  " in line:
            actual.add(line.split("  ", 1)[1].strip())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            failures.append(
                f"SOURCE_MANIFEST missing tracked files (clean checkout not auditable): {missing}"
            )
        if extra:
            failures.append(f"SOURCE_MANIFEST lists untracked/stale files: {extra}")
    return failures


# v0.7 §4 — Android FileProvider must be minimal and fail-closed. Only
# app-owned subdirectories genuinely meant for sharing/export may be exposed;
# the external storage root, cache/files roots and any wildcard path are never
# valid FileProvider namespaces. This is enforced statically so a broad
# `path="."` or an external-path root cannot be reintroduced in a later commit.
ANDROID_FILE_PATHS_XML = Path(
    "apps/desktop/src-tauri/gen/android/app/src/main/res/xml/file_paths.xml"
)
# Only these two app-controlled subdirectories may be exposed, matching the
# checked-in file_paths.xml. Any other entry, wildcard, or root exposure fails.
ALLOWED_FILE_PROVIDER_PATHS = {("cache-path", "export/"), ("files-path", "share/")}


def android_fileprovider_findings(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    target = root / ANDROID_FILE_PATHS_XML
    if not target.exists():
        return [f"missing Android file_paths.xml (expected at {ANDROID_FILE_PATHS_XML})"]
    try:
        import xml.etree.ElementTree as ET  # noqa: PLC0415

        tree = ET.parse(target)
    except Exception as exc:  # noqa: BLE001
        return [f"cannot parse Android file_paths.xml: {exc}"]
    root_el = tree.getroot()
    if root_el.tag != "paths":
        return [f"Android file_paths.xml root element must be <paths>, got <{root_el.tag}>"]
    found: set[tuple[str, str]] = set()
    for child in root_el:
        tag = child.tag
        path = child.get("path", "")
        if tag == "external-path":
            failures.append("Android FileProvider must not expose external-path (external storage root)")
            continue
        if tag not in {"cache-path", "files-path"}:
            failures.append(f"Android FileProvider unexpected path type <{tag}>")
            continue
        if path in {"", ".", "/"} or path.startswith("/") or ".." in path:
            failures.append(
                f"Android FileProvider {tag} path must be a scoped app subdirectory, got {path!r}"
            )
            continue
        found.add((tag, path))
    for entry in sorted(found - ALLOWED_FILE_PROVIDER_PATHS):
        failures.append(
            f"Android FileProvider exposes non-contract path {entry[0]} path={entry[1]!r}; "
            "only cache-path export/ and files-path share/ are allowed"
        )
    return failures


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
    # BLOCKER-1 — tracked symlink / path-escape / credential hygiene / manifest
    # scope are Required Gates of the repository integrity job. They must never
    # be bypassed by widening an ignore list.
    failures.extend(symlink_integrity_findings(root))
    failures.extend(tracked_path_escape_findings(paths))
    failures.extend(credential_file_findings(paths))
    failures.extend(source_manifest_scope_findings(root))
    failures.extend(android_fileprovider_findings(root))
    for path in paths:
        reason = forbidden_path_reason(path)
        if reason:
            failures.append(f"forbidden tracked path ({reason}): {path}")
            continue
        try:
            raw = (root / path).read_bytes()
        except OSError as exc:
            failures.append(f"tracked file unreadable in clean checkout ({exc}): {path}")
            continue
        if b"\0" in raw:
            continue
        if JKS_MAGIC in raw:
            failures.append(f"possible Java keystore binary: {path}")
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
