"""Configuration loading helpers.

All YAML config lives under ``config/`` at the repository root. Paths in the
config that point at assets are resolved relative to the repo root so the app
works regardless of the current working directory.
"""

from __future__ import annotations

import os
import copy
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

import yaml

# Repository root = parent of the package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
CONFIG_LOCK = threading.RLock()


def load_yaml(name: str, config_dir=None) -> Dict[str, Any]:
    """Load a YAML file from the config directory (e.g. ``cameras.yaml``)."""
    path = Path(config_dir or CONFIG_DIR) / name
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def merge_config(base: dict, overrides: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_all(config_dir=None) -> Dict[str, Any]:
    """Load every config file into a single dictionary keyed by stem name."""
    with CONFIG_LOCK:
        values = {name: load_yaml(f"{name}.yaml", config_dir)
                  for name in ("cameras", "workspace", "drawing", "branding", "scenes")}
        runtime = Path(config_dir or CONFIG_DIR) / "runtime.yaml"
        if runtime.exists():
            values = merge_config(values, load_yaml("runtime.yaml", config_dir))
        return values


def save_overrides(values: dict, config_dir=None) -> None:
    """Atomically persist web settings without rewriting documented defaults."""
    directory = Path(config_dir or CONFIG_DIR)
    path = directory / "runtime.yaml"
    with CONFIG_LOCK:
        saved = load_yaml("runtime.yaml", directory) if path.exists() else {}
        merged = merge_config(saved, values)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                             prefix=".runtime-", suffix=".yaml", delete=False) as handle:
                temp_path = Path(handle.name)
                yaml.safe_dump(merged, handle, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def resolve_path(relative: str) -> Path:
    """Resolve a repo-relative path from config to an absolute path."""
    p = Path(relative)
    return p if p.is_absolute() else (REPO_ROOT / p)


def ensure_dir(path: os.PathLike | str) -> Path:
    """Create a directory (and parents) if needed and return it."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
