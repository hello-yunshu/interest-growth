from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "desktop" / "src-tauri" / "tauri.release.conf.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-updater", action="store_true")
    args = parser.parse_args()
    endpoint = os.getenv("TAURI_UPDATER_ENDPOINT", "").strip()
    pubkey = os.getenv("TAURI_UPDATER_PUBLIC_KEY", "").strip()
    if args.require_updater and (not endpoint or not pubkey):
        raise SystemExit(
            "TAURI_UPDATER_ENDPOINT and TAURI_UPDATER_PUBLIC_KEY are required for updater releases"
        )

    # This file is intentionally an extension/delta, not a copy of tauri.conf.json.
    # Tauri merges --config values with the base and platform-specific configs.
    cfg: dict[str, object] = {}
    if endpoint and pubkey:
        cfg = {
            "plugins": {"updater": {"endpoints": [endpoint], "pubkey": pubkey}},
            "bundle": {"createUpdaterArtifacts": True},
        }
    OUT.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
