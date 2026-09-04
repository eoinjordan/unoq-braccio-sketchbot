"""The ArmClient talks to the software simulator over a real socket (the same
protocol the real UNO Q arm agent speaks)."""

from __future__ import annotations

from sketch_artist.arm_client import ArmClient


def test_move_returns_ok(sim_agent):
    with ArmClient(host=sim_agent.host, port=sim_agent.port) as arm:
        assert arm.move((90, 90, 90, 90, 90, 90)) == "OK"


def test_status_line(sim_agent):
    with ArmClient(host=sim_agent.host, port=sim_agent.port) as arm:
        arm.move((90, 100, 80, 90, 90, 90))
        status = arm.status()
    assert status.startswith("S")


def test_bad_move_is_rejected(sim_agent):
    with ArmClient(host=sim_agent.host, port=sim_agent.port) as arm:
        reply = arm._send("M 1 2 3")  # too few joints
    assert reply.startswith("ERR")
