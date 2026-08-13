from __future__ import annotations

import os
from pathlib import Path
import sys


def resource_root() -> Path:
    explicit = os.getenv("PG_RESOURCE_ROOT", "").strip()
    if explicit:
        return Path(explicit).resolve()
    frozen = getattr(sys, "_MEIPASS", "")
    if frozen:
        return Path(frozen).resolve()
    return Path(__file__).resolve().parents[3]
