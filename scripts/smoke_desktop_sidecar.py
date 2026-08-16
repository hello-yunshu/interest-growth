from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def binary_for_target(target: str) -> Path:
    suffix = ".exe" if "windows" in target else ""
    return BIN_DIR / f"psychology-growth-core-{target}{suffix}"


def get_json(url: str, token: str = "") -> tuple[int, dict]:
    headers = {"X-PG-Desktop-Token": token} if token else {}
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"detail": body}
        return int(exc.code), payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the packaged Interest Growth Core and probe desktop boundaries")
    parser.add_argument("--target", required=True)
    parser.add_argument("--binary", default="")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    binary = Path(args.binary).resolve() if args.binary else binary_for_target(args.target)
    if not binary.exists():
        raise SystemExit(f"sidecar binary missing: {binary}")

    port = free_loopback_port()
    token = "native-sidecar-smoke-token"
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="interest-growth-sidecar-smoke-") as data_dir:
        env = os.environ.copy()
        env.update(
            {
                "APP_ENV": "desktop",
                "APP_DATA_ROOT": data_dir,
                "PG_DESKTOP_TOKEN": token,
                "DEEPSEEK_API_KEY": "",
                "PG_CORE_LOG_LEVEL": "warning",
            }
        )
        proc = subprocess.Popen(
            [str(binary), "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + args.timeout
            health = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    status, payload = get_json(f"{base}/api/health")
                    if status == 200 and payload.get("service") == "interest-growth-api":
                        health = payload
                        break
                except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
                    pass
                time.sleep(0.2)
            if health is None:
                stdout, stderr = proc.communicate(timeout=2) if proc.poll() is not None else ("", "")
                raise SystemExit(
                    "packaged sidecar failed health smoke\n"
                    f"returncode={proc.poll()}\nstdout={stdout[-2000:]}\nstderr={stderr[-4000:]}"
                )

            denied_status, _ = get_json(f"{base}/api/system/desktop-runtime")
            if denied_status != 401:
                raise SystemExit(f"desktop token smoke expected 401 without token, got {denied_status}")
            allowed_status, runtime = get_json(f"{base}/api/system/desktop-runtime", token)
            if allowed_status != 200 or not runtime.get("desktop_mode") or not runtime.get("token_required"):
                raise SystemExit(f"desktop protected runtime smoke failed: {allowed_status} {runtime}")
            print(
                json.dumps(
                    {
                        "sidecar": str(binary),
                        "health": health,
                        "protected_runtime": runtime,
                        "result": "PASS",
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            # PyInstaller one-file bootloaders fork a child process that owns
            # the app's DB handle. Terminating only the parent leaves the child
            # alive holding psychology_growth.db, so Windows temp-dir cleanup
            # fails with WinError 32. Kill the whole process tree instead.
            if proc.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    main()
