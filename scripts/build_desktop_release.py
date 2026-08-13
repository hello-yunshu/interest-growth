from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a signed-updater desktop release on a native target host")
    parser.add_argument("--target", required=True)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    required = ["TAURI_UPDATER_ENDPOINT", "TAURI_UPDATER_PUBLIC_KEY", "TAURI_SIGNING_PRIVATE_KEY"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise SystemExit("missing release secrets/config: " + ", ".join(missing))

    env = os.environ.copy()
    env["PG_UPDATER_CONFIGURED"] = "1"
    run(sys.executable, "scripts/prepare_desktop_release_config.py", "--require-updater", env=env)
    if not args.skip_tests:
        run(sys.executable, "-m", "pytest", env=env)
        run(sys.executable, "scripts/self_audit.py", env=env)
    run(sys.executable, "scripts/build_desktop_sidecar.py", "--target", args.target, env=env)
    run("npm", "--prefix", "apps/web", "run", "build", env=env)
    run(
        "npm",
        "--prefix",
        "apps/desktop",
        "run",
        "build:release",
        "--",
        "--target",
        args.target,
        env=env,
    )


if __name__ == "__main__":
    main()
