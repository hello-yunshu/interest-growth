from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"

PYTHON_PATHS = [
    "apps/api", "packages/domain", "packages/plugin-runtime", "packages/engine-contracts",
    "packages/event-bus", "packages/artifacts", "packages/shared", "packages/native-execution-core",
    "adapters/deepseek",
]


def host_triple() -> str:
    explicit = os.getenv("TAURI_TARGET_TRIPLE", "").strip()
    if explicit:
        return explicit
    rustc = shutil.which("rustc")
    if rustc:
        out = subprocess.check_output([rustc, "-vV"], text=True)
        for line in out.splitlines():
            if line.startswith("host: "):
                return line.split(":", 1)[1].strip()
    system = platform.system().lower()
    machine = platform.machine().lower()
    mapping = {
        ("darwin", "arm64"): "aarch64-apple-darwin",
        ("windows", "amd64"): "x86_64-pc-windows-msvc",
        ("windows", "arm64"): "aarch64-pc-windows-msvc",
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    }
    try:
        return mapping[(system, machine)]
    except KeyError as exc:
        raise SystemExit(f"Unable to infer target triple for {system}/{machine}; set TAURI_TARGET_TRIPLE") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="")
    parser.add_argument("--skip-pyinstaller", action="store_true")
    args = parser.parse_args()
    triple = args.target or host_triple()
    exe = ".exe" if "windows" in triple else ""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    final = BIN_DIR / f"psychology-growth-core-{triple}{exe}"
    if args.skip_pyinstaller:
        print(final)
        return
    work = ROOT / "build" / "desktop-sidecar"
    dist = work / "dist"
    shutil.rmtree(work, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", "psychology-growth-core"]
    for rel in PYTHON_PATHS:
        cmd.extend(["--paths", str(ROOT / rel)])
    sep = ";" if os.name == "nt" else ":"
    for source, destination in (
        (ROOT / "plugins", "plugins"),
        (ROOT / "domains", "domains"),
    ):
        if source.exists():
            cmd.extend(["--add-data", f"{source}{sep}{destination}"])
    cmd.extend([
        "--add-data",
        f"{ROOT / 'packages' / 'native-execution-core' / 'interest_growth_native' / 'resources'}"
        f"{sep}interest_growth_native/resources",
    ])
    cmd.extend(["--distpath", str(dist), "--workpath", str(work / "work"), "--specpath", str(work / "spec"), str(ROOT / "scripts" / "desktop_core.py")])
    build_env = os.environ.copy()
    build_env.setdefault("PYINSTALLER_CONFIG_DIR", str(work / "cache"))
    subprocess.run(cmd, cwd=ROOT, env=build_env, check=True)
    built = dist / f"psychology-growth-core{exe}"
    if not built.exists():
        raise SystemExit(f"PyInstaller output missing: {built}")
    shutil.copy2(built, final)
    final.chmod(final.stat().st_mode | 0o111)
    print(final)


if __name__ == "__main__":
    main()
