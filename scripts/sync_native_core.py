from __future__ import annotations

"""One-way mirror: root Native Core -> standalone package.

The Host is the canonical product owner and the root `interest_growth_native`
tree is the authoritative Native Core source. `packages/native-execution-core`
is the standalone packaging mirror and must stay byte-for-byte identical.

This script copies the authoritative tree into the package mirror and also
mirrors the native-core-relevant test files so the standalone package test
suite exercises the same code.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "native-execution-core"
SRC = ROOT / "interest_growth_native"
DST = PKG / "interest_growth_native"
ROOT_TESTS = ROOT / "tests"
PKG_TESTS = PKG / "tests"

NATIVE_TEST_FILES = [
    "test_api_and_host_contract.py",
    "test_architecture_and_capabilities.py",
    "test_exact_rag_adapter_contract.py",
    "test_host_merge_tooling.py",
    "test_llm_protocol_and_web_security.py",
    "test_migration_and_reconnect_api.py",
    "test_package_resources.py",
    "test_parser_security_and_locations.py",
    "test_public_repo_audit.py",
    "test_provider_transport_errors.py",
    "test_research_citation_grounding.py",
    "test_research_network_optin.py",
    "test_research_solve_and_activity.py",
    "test_reviewed_exact_rag_adapters.py",
    "test_safewebfetcher_pinned_transport.py",
    "test_server_owned_questions_and_public_trace.py",
    "test_skill_persona_memory_visual.py",
    "test_stream_continuation_and_usage.py",
    "test_tool_permission_discovery.py",
    "test_tutor_resume_permission_revocation.py",
    "test_v03_indexing_contract.py",
    "test_v03_rag_skill_writing_invariants.py",
    "test_v03_tutor_invariants.py",
]

# Pure-logic tooling that the standalone package must keep byte-for-byte identical.
# verify.py is intentionally excluded: it pins the package's own version (0.6.0rc2).
SHARED_SCRIPTS = [
    "audit_host_v050.py",
    "audit_public_repo.py",
]


def sync_tree(src: Path, dst: Path) -> int:
    copied = 0
    for path in src.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if not target.exists() or target.read_bytes() != path.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    for path in dst.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(dst)
        if not (src / rel).exists():
            path.unlink()
    return copied


def main() -> int:
    copied = sync_tree(SRC, DST)
    for name in NATIVE_TEST_FILES:
        source = ROOT_TESTS / name
        if source.exists():
            target = PKG_TESTS / name
            if not target.exists() or target.read_bytes() != source.read_bytes():
                shutil.copy2(source, target)
                copied += 1
    for name in SHARED_SCRIPTS:
        source = ROOT / "scripts" / name
        target = PKG / "scripts" / name
        if source.exists() and (not target.exists() or target.read_bytes() != source.read_bytes()):
            shutil.copy2(source, target)
            copied += 1
    print(f"native core mirror synced: {copied} files updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
