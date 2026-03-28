"""Lightweight .env loader for local development.

This avoids extra dependencies and keeps behavior simple:
- load key/value pairs from .env when present
- ignore comments and blank lines
- do not override values already set in the environment
"""

from pathlib import Path
import os


_ENV_PATH = Path(".env")


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env() -> None:
    """Load .env values into os.environ for local runs.

    Existing environment variables always win.
    """
    if not _ENV_PATH.is_file():
        return

    for raw_line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        os.environ[key] = _strip_wrapping_quotes(value.strip())
