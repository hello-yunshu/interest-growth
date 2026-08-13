from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

import uvicorn

from pg_api.main import app


def _version_tuple(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in value.split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def platform_supported() -> tuple[bool, str]:
    if os.getenv("PG_SKIP_PLATFORM_CHECK", "").lower() in {"1", "true", "yes"}:
        return True, "platform check bypassed for tests"
    if sys.platform == "darwin":
        version = platform.mac_ver()[0] or "0"
        machine = platform.machine().lower()
        ok = _version_tuple(version) >= (13, 0) and machine in {"arm64", "aarch64"}
        return ok, f"macOS {version} {machine}; requires macOS 13+ on Apple Silicon"
    if sys.platform == "win32":
        build = int(getattr(sys.getwindowsversion(), "build", 0))
        machine = platform.machine().lower()
        ok = build >= 26100 and machine in {"amd64", "x86_64"}
        return ok, f"Windows build {build} {machine}; requires Windows 11 24H2+ (26100+) x64"
    # Linux is a development/test host only; it is not a release target.
    return True, f"{sys.platform} development host"


def main() -> None:
    parser = argparse.ArgumentParser(prog="interest-growth-core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("desktop core only binds to loopback")
    supported, reason = platform_supported()
    if not supported:
        print(reason, file=sys.stderr)
        raise SystemExit(78)
    data_root = os.getenv("APP_DATA_ROOT", "").strip()
    if data_root:
        Path(data_root).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("APP_ENV", "desktop")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level=os.getenv("PG_CORE_LOG_LEVEL", "warning"),
    )


if __name__ == "__main__":
    main()
