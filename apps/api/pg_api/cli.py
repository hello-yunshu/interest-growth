from __future__ import annotations

import argparse

from .db import init_db
from .features import seed_feature_flags
from .plugins import get_plugin_runtime


def main() -> None:
    parser = argparse.ArgumentParser(prog="interest-growth")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        seed_feature_flags()
        runtime = get_plugin_runtime(refresh=True)
        print(f"Database initialized. Plugins: {len(runtime.manifests)}")


if __name__ == "__main__":
    main()
