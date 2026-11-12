"""A cable tie has to pass through every tie tunnel, as exported.

The gripper-top holders and the saddle fit piece are tied to the gripper block
through a tunnel in the saddle pad. A tunnel that is in the source but closed
in the mesh is found only with a tie in hand, so the shipped STLs are probed:
lines spread over the cross section of a 3.6 x 1.4 mm tie must run the whole
length of the part without touching it, and the tunnel must have a floor, a
roof and a wall each side somewhere along it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts import check_tie_tunnels as ties
from scripts.mesh_check import load_stl

TABLE = json.loads(ties.PROBES.read_text(encoding="ascii"))
CASES = [(stl, index) for stl, tunnels in sorted(TABLE.items())
         for index in range(len(tunnels))]


def test_every_exported_saddle_has_a_probe():
    assert sorted(TABLE) == sorted(stl for stl, _, _ in ties.EXPORTS)
    assert all(TABLE[stl] for stl in TABLE), "a part lost its tie tunnel"
    for stl in TABLE:
        assert (ties.PARTS / stl).exists()


@pytest.mark.parametrize("stl, index", CASES,
                         ids=[f"{stl}:{index + 1}" for stl, index in CASES])
def test_tie_tunnel_is_open_from_mouth_to_mouth(stl, index):
    blocked, tried, enclosed = ties.probe(ties.PARTS / stl, TABLE[stl][index])
    assert blocked == 0, (
        f"{stl}: {blocked} of {tried} lines through the tie tunnel hit plastic")
    assert enclosed, f"{stl}: nothing walls the tie in; the tunnel is missing"


@pytest.mark.parametrize("stl, index", CASES,
                         ids=[f"{stl}:{index + 1}" for stl, index in CASES])
def test_tie_tunnel_takes_a_3_6_mm_tie_with_room(stl, index):
    width, thick = TABLE[stl][index]["tunnel_mm"]
    assert width >= ties.TIE_MM[0] + 1.2
    assert thick >= ties.TIE_MM[1] + 1.0


def test_the_probe_notices_a_blocked_tunnel():
    """Put a wall across the tunnel and the probe has to see it."""
    stl, index = CASES[0]
    tunnel = TABLE[stl][index]
    tris, _ = load_stl(ties.PARTS / stl)
    centre = np.array(tunnel["centre"], float)
    across = np.array(tunnel["across"], float)
    up = np.array(tunnel["up"], float)
    corners = [centre + a * 10 * across + b * 10 * up
               for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    wall = np.array([[corners[0], corners[1], corners[2]],
                     [corners[0], corners[2], corners[3]]])
    # a little off centre, so the line is clear of the wall's own diagonal
    point = centre + 0.5 * across
    start = point - ties.REACH_MM * np.array(tunnel["along"], float)
    end = point + ties.REACH_MM * np.array(tunnel["along"], float)
    assert ties.crossings(tris, start, end) == 0
    assert ties.crossings(np.concatenate([tris, wall]), start, end) == 1
