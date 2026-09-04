"""Validate the Gazebo bridge package without a ROS/Gazebo install:
package.xml well-formedness, the bridge's joint order, and Python syntax."""

from __future__ import annotations

import py_compile
import xml.etree.ElementTree as ET
from pathlib import Path

GAZEBO = Path(__file__).resolve().parent.parent / "sim" / "gazebo"

# The real controller/model joint order (unoq_braccio_sim / braccio_model).
EXPECTED_JOINTS = [
    "base", "shoulder", "elbow", "wrist_vertical", "wrist_rotation", "gripper",
]


def test_package_xml_is_well_formed():
    root = ET.parse(GAZEBO / "package.xml").getroot()
    assert root.find("name").text == "braccio_sim"
    deps = {d.text for d in root.findall("exec_depend")}
    # Builds on the real Braccio model + driver from the unoq-braccio repo.
    assert {"unoq_braccio_sim", "unoq_braccio_driver"} <= deps


def test_bridge_joint_order_matches_controller():
    bridge = (GAZEBO / "braccio_sim" / "braccio_bridge.py").read_text(encoding="utf-8")
    for joint in EXPECTED_JOINTS:
        assert f'"{joint}"' in bridge


def test_python_assets_compile():
    for rel in ("launch/sketchbot_gazebo.launch.py",
                "braccio_sim/braccio_bridge.py",
                "setup.py"):
        py_compile.compile(str(GAZEBO / rel), doraise=True)
