from __future__ import annotations

import os
from pathlib import Path


FALSE_VALUES = {"0", "false", "no", "off"}


def load_local_env(env_path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries from the project .env without overriding shell env."""
    if os.environ.get("AI_SCIENTIST_LOAD_DOTENV", "1").strip().lower() in FALSE_VALUES:
        return

    path = env_path or Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
