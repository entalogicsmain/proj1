"""Prompt loader with content hash, so every run can be tied to a prompt version."""
from __future__ import annotations

import hashlib
from pathlib import Path


class Prompts:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def get(self, name: str) -> str:
        return (self.dir / f"{name}.md").read_text()

    def version(self, name: str) -> str:
        return hashlib.sha256(self.get(name).encode()).hexdigest()[:8]
