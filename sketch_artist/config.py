"""Configuration loading helpers.

All YAML config lives under ``config/`` at the repository root. Paths in the
config that point at assets are resolved relative to the repo root so the app
works regardless of the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

# Repository root = parent of the package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def load_yaml(name: str) -> Dict[str, Any]:
    """Load a YAML file from the config directory (e.g. ``cameras.yaml``)."""
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_all() -> Dict[str, Any]:
    """Load every config file into a single dictionary keyed by stem name."""
    return {
        "cameras": load_yaml("cameras.yaml"),
        "workspace": load_yaml("workspace.yaml"),
        "drawing": load_yaml("drawing.yaml"),
        "branding": load_yaml("branding.yaml"),
    }


def resolve_path(relative: str) -> Path:
    """Resolve a repo-relative path from config to an absolute path."""
    p = Path(relative)
    return p if p.is_absolute() else (REPO_ROOT / p)


def ensure_dir(path: os.PathLike | str) -> Path:
    """Create a directory (and parents) if needed and return it."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
