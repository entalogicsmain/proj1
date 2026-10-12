"""Config loading. Plain TOML, no secrets."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelSpec:
    provider: str
    model: str


@dataclass
class Config:
    root: Path
    paths: dict
    caps: dict
    models: dict[str, ModelSpec]
    pricing: dict[str, dict]
    raw: dict = field(default_factory=dict)

    def path(self, key: str) -> Path:
        p = Path(self.paths[key])
        return p if p.is_absolute() else self.root / p

    def model(self, role: str) -> ModelSpec:
        return self.models[role]


def load_config(path: str | Path = "config/config.toml", root: str | Path | None = None) -> Config:
    path = Path(path)
    root = Path(root) if root else path.resolve().parent.parent
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    models = {k: ModelSpec(**v) for k, v in raw["models"].items()}
    return Config(root=root, paths=raw["paths"], caps=raw["caps"], models=models,
                  pricing=raw.get("pricing", {}), raw=raw)
