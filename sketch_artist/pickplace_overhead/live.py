"""Hand-driven live moves behind the base, watched by the overhead camera.

This is the driver used to bring the floor rig up on 2026-11-12. Targets
are (base servo, reach mm, grasp z mm); the Studio's own gripper model and
inverse kinematics (``web.control.workspace_for_tool`` on the owner's
config) solve them in the forward frame and the result is mirrored to reach
behind the base (``sketch_artist.mirrored_arm``). Every move is checked
against the configured joint limits in both frames, ramped in small steps,
and followed by an overhead frame and an arm agent status read.

Joints move one at a time, in the order that keeps the claws highest, unless
the whole move is a few degrees. The base turns only with the arm folded.

    python -m sketch_artist.pickplace_overhead.live --config-dir DIR --state OUT \\
        hover 149 204 90           # fold, turn, go out to 90 mm over (base, reach)
    ... step 149 204 70 45 25 8    # descend at the same base and reach
    ... jaws 35 50 65              # close in steps
    ... step 149 204 25 45 70      # lift
    ... fold | park | axis

None of this is a pick-and-place program: it does exactly the moves it is
told and stops on the first failed check. See docs/pick-place-service.md.
"""

from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .. import config as cfg
from ..kinematics import BraccioKinematics
from ..mirrored_arm import mirror
from .geometry import REST_POSE, interpolate
from .rig import Halt
from .session import State

PITCHES = (-90, -85, -80, -75, -70, -65, -60, -55)


class Model:
    """The owner's gripper model and limits, from a Studio config directory."""

    def __init__(self, config_dir: Optional[str] = None):
        from web.control import DEFAULT_TOOLS, joint_limits

        self.conf = cfg.load_all(config_dir)
        self.tools = cfg.merge_config(DEFAULT_TOOLS, self.conf.get("tools", {}))
        self.tools["active"] = "gripper"
        self.gripper = self.tools["gripper"]
        self.limits = joint_limits(self.conf["workspace"])
        self.open = float(self.gripper["open_deg"])
        self.closed = float(self.gripper["closed_deg"])

    def check(self, angles: Sequence[float]) -> None:
        names = ("base", "shoulder", "elbow", "wrist", "roll", "jaws")
        for name, value, (lo, hi) in zip(names, angles, self.limits):
            if not lo - 1e-6 <= value <= hi + 1e-6:
                raise Halt("%s %.1f outside the configured limits %g-%g" % (name, value, lo, hi))

    def solve(self, base: float, reach: float, z: float, pitch: float,
              jaws: Optional[float] = None) -> Tuple[float, ...]:
        """Servo angles for a grasp point behind the base, at one tool pitch."""
        from web.control import workspace_for_tool

        tools = cfg.merge_config(self.tools, {"gripper": {"pitch_deg": float(pitch)}})
        kin = BraccioKinematics(workspace_for_tool(self.conf["workspace"], tools))
        yaw = math.radians(base - 90.0)
        forward = kin.solve(reach * math.cos(yaw), reach * math.sin(yaw), z, strict=True).as_tuple()
        behind = mirror(forward[:5] + (self.open if jaws is None else float(jaws),))
        self.check(behind)
        return tuple(round(a, 1) for a in behind)

    def solve_steepest(self, base, reach, z, jaws=None) -> Tuple[Tuple[float, ...], float]:
        last = None
        for pitch in PITCHES:
            try:
                return self.solve(base, reach, z, pitch, jaws), float(pitch)
            except Exception as exc:          # unreachable at this pitch
                last = exc
        raise Halt("no tool pitch reaches base %g reach %g z %g: %s" % (base, reach, z, last))


class Live:
    def __init__(self, state_dir: str, model: Model, nominal: dict,
                 expected_spots: Sequence[Tuple[float, float, float]] = (),
                 check_sheet: bool = False):
        self.model = model
        self.state = State(state_dir)
        self.state.data.update({
            "nominal": nominal, "check_arm": False, "base_range": [0, 160],
            "roi": [250, 50, 1250, 800], "tool_mm": float(model.gripper["length_mm"]),
            "base_height_mm": float(model.conf["workspace"]["links"]["base_height_mm"])})
        self.state.save()
        self.rig = self.state.rig(floor_guard=-30.0, arm_mask_px=320)
        self.rig.cfg.max_step_deg = 2.0
        self.rig.cfg.dwell_s = 0.15
        # On the floor rig the sheet outline flipped with the camera's auto
        # exposure between identical frames, so it is off by default and the
        # base is compared by eye on the saved rest-pose frames.
        self.rig.cfg.check_sheet = check_sheet
        self.expected_spots = list(expected_spots)
        self.arm = self.rig.arm
        self.log = self.state.log

    def reference(self) -> None:
        self.rig.take_reference()
        self.rig.expected_spots = list(self.expected_spots)

    def pose(self) -> Tuple[float, ...]:
        return self.rig.link.pose()

    def tip_z(self, angles) -> float:
        return self.arm.chain(angles)["tip"][1]

    def folded(self) -> bool:
        pose = self.pose()
        return max(abs(pose[i] - REST_POSE[i]) for i in (1, 2, 3)) <= 0.6

    def _lowest(self, start, target) -> float:
        return min(self.tip_z(p) for p in [tuple(start)] + interpolate(start, target, 1.0))

    def go(self, target, label, floor_guard=None, together_deg=6.0):
        target = tuple(float(a) for a in target)
        self.model.check(target)
        cur = self.pose()
        if abs(cur[0] - target[0]) > 0.05:
            raise Halt("go() does not turn the base; fold and turn first")
        if max(abs(a - b) for a, b in zip(cur, target)) < 0.05:
            return self.rig.look(target, label)
        if max(abs(cur[i] - target[i]) for i in (1, 2, 3)) <= together_deg:
            plan: List[Tuple[float, ...]] = [target]
        else:
            best = None
            for order in itertools.permutations((1, 2, 3)):
                p, seq, low = list(cur), [], 1e9
                for j in order:
                    nxt = list(p)
                    nxt[j] = target[j]
                    low = min(low, self._lowest(tuple(p), tuple(nxt)))
                    seq.append(tuple(nxt))
                    p = nxt
                if best is None or low > best[0]:
                    best = (low, seq)
            plan = list(best[1])
            plan[-1] = target
        frame = None
        for i, p in enumerate(plan):
            frame = self.rig.move(p, "%s (%d/%d)" % (label, i + 1, len(plan)), floor_guard)
            self.pose()                      # the board is still answering
        return frame

    def turn(self, base: float, label="turn"):
        if not self.folded():
            raise Halt("the base turns only with the arm folded")
        cur = self.pose()
        return self.rig.move((float(base),) + tuple(cur[1:]), label)

    def jaws(self, value: float, label: str):
        cur = self.pose()
        return self.rig.move(cur[:5] + (float(value),), label, floor_guard_mm=-30.0)

    def fold(self):
        cur = self.pose()
        self.go((cur[0],) + REST_POSE[1:5] + (cur[5],), "fold", floor_guard=-30.0)

    def park(self, jaws: Optional[float] = None):
        if not self.folded():
            self.fold()
        cur = self.pose()
        self.rig.move((90.0,) + REST_POSE[1:5] + (cur[5] if jaws is None else float(jaws),), "park")

    def to_height(self, base, reach, z, label=None):
        jaws = self.pose()[5]
        target, pitch = self.model.solve_steepest(base, reach, z, jaws)
        guard = min(z, self.tip_z(self.pose()), 40.0) - 2.0
        self.go(target, label or "b%g r%g z%g p%d" % (base, reach, z, pitch), floor_guard=guard)
        self.log("  at z=%g: %s" % (z, target))
        return target


def display_px(frame) -> Optional[Tuple[float, float]]:
    """The gripper camera's round display: the brightest neutral blob near the arm."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] > 245) & (hsv[..., 1] < 60)).astype(np.uint8) * 255
    mask[:, :450] = 0
    mask[:, 950:] = 0
    mask[:300, :] = 0
    mask[650:, :] = 0
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    best = max(range(1, n), key=lambda i: stats[i, 4])
    return float(cent[best][0]), float(cent[best][1])


def fit_circle(points) -> Tuple[float, float, float]:
    p = np.asarray(points, float)
    a = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
    b = (p ** 2).sum(axis=1)
    cx, cy, c = np.linalg.lstsq(a, b, rcond=None)[0]
    return float(cx), float(cy), float(math.sqrt(c + cx * cx + cy * cy))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", required=True, help="the Studio config holding the gripper model")
    ap.add_argument("--state", required=True, help="directory for frames and the log")
    ap.add_argument("--nominal", default='{"base_px": [865, 545], "px_per_mm": 1.3, '
                    '"front_angle_deg": -2, "height_mm": 1000, "nadir_px": [930, 1050], "mirrored": true}',
                    help="rough overhead camera, JSON, used only for the arm silhouette")
    ap.add_argument("--check-sheet", action="store_true")
    ap.add_argument("command", choices=["hover", "step", "jaws", "fold", "park", "axis"])
    ap.add_argument("values", nargs="*", type=float)
    args = ap.parse_args(argv)
    import json

    live = Live(args.state, Model(args.config_dir), json.loads(args.nominal), check_sheet=args.check_sheet)
    v = args.values
    try:
        live.reference()
        if args.command == "hover":
            base, reach, z = v[:3]
            if abs(live.pose()[0] - base) > 0.05:
                if not live.folded():
                    live.fold()
                live.turn(base)
            live.to_height(base, reach, z)
        elif args.command == "step":
            base, reach = v[:2]
            for z in v[2:]:
                live.to_height(base, reach, z)
        elif args.command == "jaws":
            for value in v:
                live.jaws(value, "jaws %g" % value)
        elif args.command == "fold":
            live.fold()
        elif args.command == "park":
            live.park(v[0] if v else None)
        elif args.command == "axis":
            points = []
            for base in v or (90, 60, 30, 10, 30, 60, 90, 120, 90):
                found = display_px(live.turn(base, "base %g" % base))
                live.log("base %g display %s" % (base, found))
                if found:
                    points.append(found)
            if len(points) >= 3:
                live.log("display circle centre and radius: %.0f %.0f %.0f" % fit_circle(points))
    except Halt as exc:
        live.log("HALT: %s" % exc)
        return 3
    finally:
        live.rig.camera.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
