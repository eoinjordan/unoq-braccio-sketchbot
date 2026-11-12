"""Command line for the overhead pick-and-place rig.

    python -m sketch_artist.pickplace_overhead.session <stage> --state DIR ...

Stages, in the order a new rig needs them:

    detect      one frame, detections drawn on it; no motion
    level       hold the arm level and high so tool length and jaws can be
                read off the picture
    calibrate   fit the camera (and the tool length) from fingertip sightings
    column      lower the closed gripper over bare floor in small steps
    plan        dry run: which bricks are reachable, and the waypoints
    pick        run the plan on the arm, checking a frame after every move
    park        fold the arm back to the rest pose

Everything the stages learn is kept in DIR/state.json, and every frame they
take is saved under DIR/frames.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from . import calibrate, detect, overlay, plan as planning, watch
from .geometry import (ArmGeometry, Envelope, KeepOut, REST_POSE, back_project, nominal_camera,
                       project)
from .rig import ArmLink, Halt, OverheadCamera, Rig, RigConfig

DEFAULTS = {
    "camera_usb_id": "vid_1532&pid_0e03",
    "camera_focus": 55.0,
    "arm_host": "192.168.1.63",
    "arm_port": 8765,
    "base_height_mm": 92.0,
    "tool_mm": 190.0,
    "base_range": [60.0, 172.0],
    "max_front_reach_mm": 140.0,
    # Provisional camera, read off a frame; replaced by "P" after calibrate.
    "nominal": {"base_px": [882, 657], "px_per_mm": 1.3, "front_angle_deg": 20.0,
                "height_mm": 1000.0, "nadir_px": [930, 1050], "mirrored": True},
    "roi": [250, 150, 1150, 950],
    "pick": {},
    "keep_out_px": [],          # polygons in pixels that the tool must stay out of
}


class State:
    def __init__(self, directory: str):
        self.dir = directory
        self.frames = os.path.join(directory, "frames")
        os.makedirs(self.frames, exist_ok=True)
        self.path = os.path.join(directory, "state.json")
        self.data = json.loads(json.dumps(DEFAULTS))
        if os.path.exists(self.path):
            with open(self.path, encoding="ascii") as fh:
                self.data.update(json.load(fh))
        self.logfile = os.path.join(directory, "session.log")

    def save(self) -> None:
        with open(self.path, "w", encoding="ascii") as fh:
            json.dump(self.data, fh, indent=1)

    def log(self, message: str) -> None:
        line = time.strftime("%H:%M:%S ") + message
        print(line, flush=True)
        with open(self.logfile, "a", encoding="ascii", errors="replace") as fh:
            fh.write(line + "\n")

    # -- pieces built from the state -------------------------------------
    def arm(self) -> ArmGeometry:
        return ArmGeometry(base_height_mm=self.data["base_height_mm"], tool_mm=self.data["tool_mm"])

    def P(self) -> np.ndarray:
        if "P" in self.data:
            return np.asarray(self.data["P"], float)
        n = self.data["nominal"]
        return nominal_camera(n["base_px"], n["px_per_mm"], n["front_angle_deg"], n["height_mm"],
                              n["nadir_px"], n["mirrored"])

    def pick_config(self) -> planning.PickConfig:
        return planning.PickConfig(**self.data["pick"])

    def detector(self, P: np.ndarray) -> detect.ColourDetector:
        bx, by = project(P, (0.0, 0.0, 0.0))
        cfg = detect.ColourDetectorConfig(
            roi=tuple(self.data["roi"]), ignore_circles=[(bx, by, 185.0)],
            ignore_polygons=self.data.get("ignore_px", []))
        return detect.ColourDetector(cfg)

    def envelope(self, arm: ArmGeometry, floor_guard: float) -> Envelope:
        return Envelope(arm, floor_clearance_mm=floor_guard,
                        base_range=tuple(self.data["base_range"]),
                        max_front_reach_mm=self.data["max_front_reach_mm"])

    def rig(self, floor_guard: float = 100.0, arm_mask_px: int = 150) -> Rig:
        arm = self.arm()
        P = self.P()
        camera = OverheadCamera(usb_id=self.data["camera_usb_id"], focus=self.data["camera_focus"])
        cfg = RigConfig(sharpness_roi=tuple(self.data["roi"]), arm_mask_px=arm_mask_px,
                        check_arm=bool(self.data.get("check_arm", True)))
        return Rig(camera, ArmLink(self.data["arm_host"], self.data["arm_port"]), arm,
                   self.envelope(arm, floor_guard), P, cfg, self.log, self.frames)


def carry(base: float, jaws: float):
    return planning.carry_pose(base, jaws)


def require_rest(rig: Rig) -> None:
    pose = rig.link.pose()
    if max(abs(a - b) for a, b in zip(pose[:4], REST_POSE[:4])) > 0.6:
        raise Halt("arm is not parked (pose %s); run the park stage first" % (pose,))


# -- stages -------------------------------------------------------------------

def stage_detect(state: State, args) -> int:
    camera = OverheadCamera(usb_id=state.data["camera_usb_id"], focus=state.data["camera_focus"])
    try:
        frame = camera.frame()
    finally:
        camera.close()
    P = state.P()
    dets = state.detector(P).detect(frame)
    for i, d in enumerate(dets):
        state.log("det %d %-13s px=(%.0f, %.0f) conf=%.2f box=%.0fx%.0f angle=%.0f"
                  % (i, d.label, d.x_px, d.y_px, d.confidence, d.length_px, d.width_px, d.angle_deg))
    cv2.imwrite(os.path.join(state.dir, "detect.jpg"), detect.annotate(frame, dets))
    cv2.imwrite(os.path.join(state.dir, "detect_raw.jpg"), frame)
    state.log("sharpness %.0f" % watch.sharpness(frame, tuple(state.data["roi"])))
    return 0


def stage_park(state: State, args) -> int:
    rig = state.rig(floor_guard=20.0)
    try:
        pose = rig.link.pose()
        rig.move(carry(pose[0], pose[5]), "fold up", check=False)
        rig.move(REST_POSE[:5] + (10.0,), "park", check=False)
    finally:
        rig.camera.close()
    return 0


def stage_level(state: State, args) -> int:
    """Arm level and high; frames with the jaws at several angles and rolls."""
    rig = state.rig(arm_mask_px=260)
    try:
        require_rest(rig)
        rig.take_reference()
        base = args.base
        rig.move(carry(base, 10.0), "turn")
        level = (base, 90.0, 180.0, 90.0, 90.0, 10.0)
        rig.move(level, "level jaws 10")
        for jaws in args.jaws:
            rig.move(level[:5] + (jaws,), "level jaws %g" % jaws)
        for wrist in args.wrists:
            rig.move(level[:3] + (wrist, 90.0, 10.0), "level wrist %g" % wrist)
        if args.wrists:
            level = level[:3] + (args.wrists[-1],) + level[4:]
        for roll in args.rolls:
            rig.move(level[:4] + (roll, 10.0), "level roll %g" % roll)
        rig.move(level[:5] + (10.0,), "level roll 90")
        rig.move(carry(base, 10.0), "fold up")
        rig.move(REST_POSE[:5] + (10.0,), "park")
    finally:
        rig.camera.close()
    return 0


def stage_calibrate(state: State, args) -> int:
    rig = state.rig(arm_mask_px=260)
    arm = rig.arm
    samples: List[calibrate.Sample] = []
    try:
        require_rest(rig)
        ref = rig.take_reference()
        base_px = rig.base_px()
        poses = calibrate.calibration_poses(arm, args.bases, args.reaches, args.heights,
                                            args.pitches, jaws=args.jaws)
        state.log("calibrating over %d poses, lowest fingertip %.0f mm"
                  % (len(poses), min(arm.chain(p)["tip"][1] for p in poses)))
        last_base = None
        for i, pose in enumerate(poses):
            if last_base is not None and pose[0] != last_base:
                rig.move(carry(last_base, args.jaws), "fold up")
            if pose[0] != last_base:
                rig.move(carry(pose[0], args.jaws), "turn")
                last_base = pose[0]
            frame = rig.move(pose, "cal %d" % i)
            tip_px = project(rig.P, arm.point_xyz(pose, "tip"))
            heading = math.degrees(math.atan2(-(tip_px[1] - base_px[1]), tip_px[0] - base_px[0]))
            found = calibrate.find_fingertip(ref, frame, base_px, heading, expected_px=tip_px,
                                             search_px=args.search_px)
            if found is None:
                state.log("  no fingertip seen in cal %d" % i)
                continue
            samples.append(calibrate.Sample(pose, found))
            state.log("  fingertip at (%.0f, %.0f)" % found)
        rig.move(carry(last_base, args.jaws), "fold up")
        rig.move(REST_POSE[:5] + (10.0,), "park")
    finally:
        rig.camera.close()
        with open(os.path.join(state.dir, "samples.json"), "w", encoding="ascii") as fh:
            json.dump([{"angles": s.angles, "pixel": s.pixel} for s in samples], fh)
    return fit_samples(state, args.tool_range)


def fit_samples(state: State, tool_range: Sequence[float]) -> int:
    with open(os.path.join(state.dir, "samples.json"), encoding="ascii") as fh:
        samples = [calibrate.Sample(tuple(s["angles"]), tuple(s["pixel"])) for s in json.load(fh)]
    arm = state.arm()
    lo, hi = tool_range
    candidates = [lo + i for i in range(int(hi - lo) + 1)] if hi > lo else [lo]
    cal = calibrate.fit(samples, arm, candidates)
    arm.tool_mm = cal.tool_mm
    loo = calibrate.leave_one_out_mm(samples, arm)
    state.log("camera fitted: tool %.0f mm, rms %.1f px (%.1f mm), worst %.1f px, %d samples, "
              "%d rejected, leave-one-out %.1f mm"
              % (cal.tool_mm, cal.rms_px, cal.rms_mm, cal.max_px, cal.samples, cal.rejected, loo))
    state.data.update({"P": cal.P.tolist(), "tool_mm": cal.tool_mm,
                       "calibration": {"rms_px": cal.rms_px, "rms_mm": cal.rms_mm,
                                       "max_px": cal.max_px, "samples": cal.samples,
                                       "rejected": cal.rejected, "leave_one_out_mm": loo}})
    state.save()
    return 0


def stage_column(state: State, args) -> int:
    """Lower the gripper over one floor point in small steps, a frame at each."""
    cfg = state.pick_config()
    rig = state.rig(floor_guard=cfg.floor_guard_mm)
    arm = rig.arm
    try:
        require_rest(rig)
        rig.take_reference()
        x, y = back_project(rig.P, args.pixel, 0.0) if args.pixel else args.xy
        state.log("column at base-frame (%.0f, %.0f) mm" % (x, y))
        z = args.top
        pose, pitch = planning.steepest(arm, x, y, z, 90.0, args.jaws, cfg)
        rig.move(carry(pose[0], args.jaws), "turn")
        rig.move(pose, "column z=%g" % z)
        while z > args.bottom + 1e-6:
            z = max(args.bottom, z - args.step)
            pose, pitch = planning.steepest(arm, x, y, z, 90.0, args.jaws, cfg, pitch)
            rig.move(pose, "column z=%g" % z, floor_guard_mm=args.bottom - 0.5)
        while z < args.top - 1e-6:
            z = min(args.top, z + 3 * args.step)
            pose, pitch = planning.steepest(arm, x, y, z, 90.0, args.jaws, cfg, pitch)
            rig.move(pose, "column up z=%g" % z, floor_guard_mm=args.bottom - 0.5)
        rig.move(carry(pose[0], args.jaws), "fold up")
        rig.move(REST_POSE[:5] + (10.0,), "park")
    finally:
        rig.camera.close()
    return 0


def _plan(state: State, frame: np.ndarray):
    P = state.P()
    arm = state.arm()
    cfg = state.pick_config()
    dets = state.detector(P).detect(frame)
    extra = []
    for i, poly in enumerate(state.data.get("keep_out_px", [])):
        extra.append(KeepOut("zone %d" % i, [back_project(P, p, 0.0) for p in poly], 400.0, 10.0))
    plans, env = planning.plan_all(dets, P, arm, cfg, tuple(state.data["base_range"]), extra,
                                   state.data["max_front_reach_mm"])
    return dets, plans, env, P, arm, cfg


def stage_plan(state: State, args) -> int:
    if args.frame:
        frame = cv2.imread(args.frame)
    else:
        camera = OverheadCamera(usb_id=state.data["camera_usb_id"], focus=state.data["camera_focus"])
        try:
            frame = camera.frame()
        finally:
            camera.close()
    dets, plans, env, P, arm, cfg = _plan(state, frame)
    state.log("\n" + planning.describe(plans))
    for p in plans:
        if p.reachable:
            for w in p.waypoints:
                state.log("  brick %d  %-18s %s" % (p.index, w.label, w.angles))
    title = "dry run" + ("" if "P" in state.data else ", provisional camera (not calibrated)")
    cv2.imwrite(os.path.join(state.dir, "plan.jpg"),
                overlay.draw_plan(frame, dets, plans, P, arm, env, cfg, title))
    return 0


def _brick_still_there(dets: Sequence[detect.Detection], target: detect.Detection,
                       radius_px: float = 28.0) -> bool:
    return any(d.label == target.label and math.hypot(d.x_px - target.x_px, d.y_px - target.y_px)
               <= radius_px for d in dets)


def _colour_in_box(frame: np.ndarray, det: detect.Detection, labels: Sequence[str]) -> int:
    """Brick-coloured pixels inside a detection's box (used on the bin)."""
    masks = detect.class_masks(frame, detect.ColourDetectorConfig())
    box = np.zeros(frame.shape[:2], np.uint8)
    cv2.fillPoly(box, [detect.box_corners(det).astype(np.int32)], 255)
    box = cv2.erode(box, np.ones((15, 15), np.uint8))
    total = 0
    for label in labels:
        total += int(np.count_nonzero(masks[label] & (box > 0)))
    return total


def stage_pick(state: State, args) -> int:
    cfg0 = state.pick_config()
    rig = state.rig(floor_guard=cfg0.floor_guard_mm)
    results = []
    try:
        require_rest(rig)
        first = rig.take_reference()
        cv2.imwrite(os.path.join(state.dir, "before.jpg"), first)
        dets, plans, env, P, arm, cfg = _plan(state, first)
        rig.env = env
        cv2.imwrite(os.path.join(state.dir, "before_annotated.jpg"),
                    overlay.draw_plan(first, dets, plans, P, arm, env, cfg, "before"))
        state.log("\n" + planning.describe(plans))
        bin_det = next((d for d in dets if d.label == detect.BIN), None)
        done = 0
        for p in plans:
            row = {"index": p.index, "label": p.detection.label, "reach_mm": p.reach_mm,
                   "px": [round(p.detection.x_px), round(p.detection.y_px)]}
            results.append(row)
            if not p.reachable:
                row["result"] = "not attempted: " + p.reason
                continue
            if args.only is not None and p.index not in args.only:
                row["result"] = "not attempted: not selected"
                continue
            if args.limit is not None and done >= args.limit:
                row["result"] = "not attempted: limit reached"
                continue
            done += 1
            row["result"] = _pick_one(state, rig, p, bin_det, cfg, args)
            state.log("brick %d: %s" % (p.index, row["result"]))
        after = rig.camera.frame()
        cv2.imwrite(os.path.join(state.dir, "after.jpg"), after)
        dets2, plans2, env2, _, _, _ = _plan(state, after)
        cv2.imwrite(os.path.join(state.dir, "after_annotated.jpg"),
                    overlay.draw_plan(after, dets2, plans2, P, arm, env2, cfg, "after"))
    except Halt as exc:
        state.log("HALT: %s" % exc)
        results.append({"result": "HALT: %s" % exc})
        return 3
    finally:
        rig.camera.close()
        with open(os.path.join(state.dir, "results.json"), "w", encoding="ascii") as fh:
            json.dump(results, fh, indent=1)
    return 0


def _pick_one(state: State, rig: Rig, p: planning.BrickPlan, bin_det, cfg, args) -> str:
    det = p.detection
    for attempt in range(3):
        rig.take_reference()
        rig.expected_spots = [(det.x_px, det.y_px, 0.9 * max(det.length_px, 40.0))]
        if bin_det is not None:
            rig.expected_spots.append((bin_det.x_px, bin_det.y_px, 0.75 * bin_det.length_px))
        in_bin_before = _colour_in_box(rig.reference, bin_det, detect.BRICK_LABELS)
        plan_now = p
        if attempt:
            # A failed grasp is retried a little lower, twice at most.
            lower = planning.PickConfig(**{**state.data["pick"],
                                           "grasp_z_mm": cfg.grasp_z_mm - args.retry_lower * attempt})
            if lower.grasp_z_mm < args.lowest_grasp:
                return "skipped after %d attempts: would go below %.0f mm" % (attempt, args.lowest_grasp)
            plan_now = planning.plan_brick(p.index, det, rig.P, rig.arm, rig.env, lower, bin_det)
            if not plan_now.reachable:
                return "skipped after %d attempts: %s" % (attempt, plan_now.reason)
        gripped = None
        for wp in plan_now.waypoints:
            frame = rig.move(wp.angles, "b%d %s" % (p.index, wp.label), wp.floor_guard_mm)
            if wp.label == "turn to bin":
                # The arm now points away from where the brick lay, so the
                # floor there is in plain view.
                dets = state.detector(rig.P).detect(frame)
                gripped = not _brick_still_there(dets, det)
                state.log("  after lift: brick %s the floor" % ("left" if gripped else "is still on"))
                if not gripped:
                    # Never hold closed jaws on nothing or on a jammed brick.
                    rig.move(wp.angles[:5] + (cfg.jaws_open,), "b%d open (no brick)" % p.index)
                    rig.move(REST_POSE[:5] + (cfg.jaws_open,), "b%d park" % p.index)
                    break
        final = rig.camera.frame()
        if not gripped:
            continue
        in_bin_after = _colour_in_box(final, bin_det, detect.BRICK_LABELS)
        gained = in_bin_after - in_bin_before
        if gained > args.min_bin_gain:
            return "picked and placed in the bin (attempt %d, +%d px of brick colour in the bin)" \
                % (attempt + 1, gained)
        return "left the floor but not seen in the bin (attempt %d, %+d px)" % (attempt + 1, gained)
    return "grasp failed 3 times, skipped"


# -- entry --------------------------------------------------------------------

def _floats(text: str) -> List[float]:
    return [float(v) for v in text.split(",") if v != ""]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["detect", "level", "calibrate", "fit", "column", "plan", "pick", "park"])
    ap.add_argument("--state", required=True, help="directory for state.json, frames and logs")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON",
                    help="set a state value first, e.g. --set tool_mm=190 or --set pick.bin_rim_mm=80")
    ap.add_argument("--base", type=float, default=140.0)
    ap.add_argument("--jaws", type=_floats, default=None)
    ap.add_argument("--rolls", type=_floats, default=[])
    ap.add_argument("--wrists", type=_floats, default=[],
                    help="level stage: wrist servo angles to step through")
    ap.add_argument("--bases", type=_floats, default=[70, 95, 120, 145, 170])
    ap.add_argument("--reaches", type=_floats, default=[250, 290, 330])
    ap.add_argument("--heights", type=_floats, default=[150, 195, 240])
    ap.add_argument("--pitches", type=_floats, default=[0, -25, -50])
    ap.add_argument("--tool-range", type=_floats, default=[150, 230])
    ap.add_argument("--search-px", type=float, default=170.0)
    ap.add_argument("--pixel", type=_floats, default=None)
    ap.add_argument("--xy", type=_floats, default=None)
    ap.add_argument("--top", type=float, default=70.0)
    ap.add_argument("--bottom", type=float, default=40.0)
    ap.add_argument("--step", type=float, default=3.0)
    ap.add_argument("--frame", default=None)
    ap.add_argument("--only", type=lambda s: [int(v) for v in s.split(",")], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--retry-lower", type=float, default=4.0)
    ap.add_argument("--lowest-grasp", type=float, default=2.0)
    ap.add_argument("--min-bin-gain", type=int, default=250)
    args = ap.parse_args(argv)

    state = State(args.state)
    for item in args.set:
        key, value = item.split("=", 1)
        target = state.data
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = json.loads(value)
    if args.set:
        state.save()
    if args.stage in ("level",) and args.jaws is None:
        args.jaws = [35.0, 60.0]
    if args.stage in ("calibrate", "column"):
        args.jaws = args.jaws[0] if args.jaws else 60.0

    stages = {"detect": stage_detect, "level": stage_level, "calibrate": stage_calibrate,
              "column": stage_column, "plan": stage_plan, "pick": stage_pick, "park": stage_park,
              "fit": lambda s, a: fit_samples(s, a.tool_range)}
    try:
        return stages[args.stage](state, args)
    except Halt as exc:
        state.log("HALT: %s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
