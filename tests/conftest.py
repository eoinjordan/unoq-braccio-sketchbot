"""Shared pytest fixtures for the sketchbot test suite."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sketch_artist import config as cfg
from sketch_artist.sim import SimArmAgent

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def conf():
    return cfg.load_all()


@pytest.fixture
def workspace_cfg(conf):
    # Deep-copied so a test may tweak geometry without affecting others.
    return copy.deepcopy(conf["workspace"])


@pytest.fixture(scope="session")
def sample_image():
    p = REPO_ROOT / "examples" / "sample_face_eoin.png"
    assert p.exists(), "examples/sample_face_eoin.png is missing"
    return str(p)


@pytest.fixture
def sim_agent(workspace_cfg):
    """A running software arm agent on an ephemeral port (M/S protocol)."""
    agent = SimArmAgent(workspace_cfg).start()
    try:
        yield agent
    finally:
        agent.stop()
