"""Configuration loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict when it is missing."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_config(config_dir: str | Path) -> dict[str, Any]:
    """Load settings, companies, and profile config from a directory."""

    root = Path(config_dir)
    return {
        "settings": load_yaml(root / "settings.yaml"),
        "companies": load_yaml(root / "companies.yaml"),
        "profile": load_yaml(root / "profile.yaml"),
        "config_dir": str(root),
    }
