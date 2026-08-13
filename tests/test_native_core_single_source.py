import subprocess
import sys

from pathlib import Path


def test_root_and_standalone_native_core_are_byte_identical(project_root):
    proc = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "verify_native_core_sync.py")],
        capture_output=True, text=True, cwd=project_root,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_sync_script_detects_drift_in_standalone_mirror(tmp_path, project_root):
    from scripts.verify_native_core_sync import main as verify_main

    pkg_mirror = project_root / "packages" / "native-execution-core" / "interest_growth_native"
    victim = pkg_mirror / "version.py"
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"# injected drift")
        assert verify_main() != 0
    finally:
        victim.write_bytes(original)
