"""Secret lookup. Order: OS keyring (if installed), then environment variable.

Nothing is ever read from config files or written to the log.
"""
from __future__ import annotations

import os

SERVICE = "freelance-agent"


class MissingSecret(RuntimeError):
    pass


def get_secret(name: str) -> str:
    try:
        import keyring  # optional; uses Windows Credential Manager on Windows
        val = keyring.get_password(SERVICE, name)
        if val:
            return val
    except Exception:
        pass
    val = os.environ.get(name)
    if not val:
        raise MissingSecret(f"Secret {name} not found in keyring or environment")
    return val
