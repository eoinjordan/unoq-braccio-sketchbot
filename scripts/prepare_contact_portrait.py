"""Prepare, but never execute, a portrait around a verified contact pose."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np

from sketch_artist.fk import BraccioForwardKinematics


ROOT = Path(__file__).resolve().parents[1]
MAX_STEP_DEG = 0.7
LIFT_SHOULDER_DEG = 3.0


def simplify_stroke(stroke):
    if len(stroke) < 3:
        return stroke
    points = np.asarray([command["tip_mm"][:2] for command in stroke], dtype=np.float32)
    simplified = cv2.approxPolyDP(points.reshape(-1, 1, 2), 0.05, False).reshape(-1, 2)
    selected = []
    cursor = 0
    for point in simplified:
        matches = np.flatnonzero(np.all(points[cursor:] == point, axis=1))
        if not len(matches):
            raise ValueError("Simplified point is not in the original stroke")
        cursor += int(matches[0])
        selected.append(stroke[cursor])
        cursor += 1
    return selected


def prepare(candidate, reference, state):
    if state["armed"] or not state["arm"]["connected"]:
        raise ValueError("Prepare from a connected, disarmed arm")
    if state["tools"]["active"] != "sketch" or state["controls"]["child_mode"]:
        raise ValueError("A supervised sketch setup is required")
    contact = list(state["arm"]["pose"])
    original_contact = reference["contact"]["servo_deg"]
    if any(abs(actual - original) > 0.01
           for actual, original in zip(contact[1:], original_contact[1:])):
        raise ValueError("Only a base rotation may differ from the reference contact")
    forward = BraccioForwardKinematics(state["workspace"])
    contact_z = forward.solve(contact).z_mm
    if abs(contact_z - candidate["contact_model_z_mm"]) > 0.02:
        raise ValueError("The contact model has changed")
    shift = contact[0] - original_contact[0]
    base_sign = float(state["workspace"]["servo_calibration"]["base"]["sign"])
    rotation = math.radians(shift / base_sign)
    paper = candidate["paper"]
    if paper.get("rotation_deg", 0) != 0:
        raise ValueError("This candidate must use an axis-aligned source paper")
    strokes = []
    stroke = []
    for command in candidate["commands"]:
        actual = forward.solve(command["angles"]).as_tuple()
        if math.dist(actual, command["tip_mm"]) > 0.03:
            raise ValueError("Candidate geometry differs from the active model")
        if command["pen_down"]:
            if abs(command["tip_mm"][2] - contact_z) <= 0.02:
                stroke.append(command)
        elif stroke:
            strokes.append(simplify_stroke(stroke))
            stroke = []
    if stroke:
        strokes.append(simplify_stroke(stroke))
    if not strokes:
        raise ValueError("No contact strokes in candidate")

    current = list(contact)
    commands = []
    checkpoints = []
    minimum_travel_clearance = math.inf
    maximum_draw_height_error = 0.0

    def append(target, phase, stroke_index):
        nonlocal current, minimum_travel_clearance, maximum_draw_height_error
        if len(target) != 6 or not all(math.isfinite(value) for value in target):
            raise ValueError("Invalid target")
        if any(abs(value - expected) > 0.001
               for value, expected in zip(target[3:], contact[3:])):
            raise ValueError("Wrist, roll and grip must remain fixed")
        origin = list(current)
        span = max(abs(end - start) for start, end in zip(origin, target))
        if span < 0.001:
            return
        steps = max(1, math.ceil(span / MAX_STEP_DEG))
        for step in range(1, steps + 1):
            next_pose = [round(start + (end - start) * step / steps, 3)
                         for start, end in zip(origin, target)]
            for value, (low, high) in zip(next_pose, state["limits"]):
                if not low <= value <= high:
                    raise ValueError("Target exceeds a joint limit")
            if max(abs(end - start) for start, end in zip(current, next_pose)) > 0.702:
                raise ValueError("Target exceeds the bounded step")
            for sample in range(11):
                intermediate = [start + (end - start) * sample / 10
                                for start, end in zip(current, next_pose)]
                tip = forward.solve(intermediate)
                clearance = tip.z_mm - contact_z
                if clearance < -0.1:
                    raise ValueError("Path goes below the reference contact plane")
                if phase == "travel":
                    minimum_travel_clearance = min(minimum_travel_clearance, clearance)
                    if clearance < 8.0:
                        raise ValueError("Pen-up travel has insufficient model clearance")
                if phase == "draw":
                    maximum_draw_height_error = max(maximum_draw_height_error, abs(clearance))
                    if abs(clearance) > 0.1:
                        raise ValueError("Drawing departs from the reference plane")
                    source_x = tip.x_mm * math.cos(rotation) + tip.y_mm * math.sin(rotation)
                    source_y = -tip.x_mm * math.sin(rotation) + tip.y_mm * math.cos(rotation)
                    if not (paper["origin_x_mm"] - 0.1 <= source_x
                            <= paper["origin_x_mm"] + paper["width_mm"] + 0.1
                            and paper["origin_y_mm"] - 0.1 <= source_y
                            <= paper["origin_y_mm"] + paper["height_mm"] + 0.1):
                        raise ValueError("Drawing leaves the original paper area")
            commands.append({"angles": next_pose, "phase": phase, "stroke": stroke_index})
            current = next_pose

    raised = list(current)
    raised[1] += LIFT_SHOULDER_DEG
    append(raised, "lift", -1)
    for stroke_index, stroke in enumerate(strokes):
        targets = [[point["angles"][0] + shift, *point["angles"][1:]] for point in stroke]
        approach = list(targets[0])
        approach[1] += LIFT_SHOULDER_DEG
        append(approach, "travel", stroke_index)
        append(targets[0], "lower", stroke_index)
        for target in targets[1:]:
            append(target, "draw", stroke_index)
        raised = list(current)
        raised[1] += LIFT_SHOULDER_DEG
        append(raised, "lift", stroke_index)
        checkpoints.append(len(commands))
    if len(commands) > 2500:
        raise ValueError("Prepared path exceeds the command budget")
    return {
        "source": candidate["source"], "source_sha256": candidate["source_sha256"],
        "physical_drawing_complete": False, "expected_start_servo_deg": contact,
        "workspace": state["workspace"], "contact_model_z_mm": contact_z,
        "drawing_area_mm": candidate["drawing_area_mm"], "base_shift_deg": shift,
        "lift_shoulder_deg": LIFT_SHOULDER_DEG, "max_step_deg": MAX_STEP_DEG,
        "source_strokes": candidate["source_strokes"], "planned_strokes": len(strokes),
        "checks": {"minimum_model_travel_clearance_mm": minimum_travel_clearance,
                   "maximum_model_draw_height_error_mm": maximum_draw_height_error},
        "stroke_checkpoints": checkpoints, "commands": commands,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--studio", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text())
    reference = json.loads(args.reference.read_text())
    source = (ROOT / candidate["source"]).resolve()
    if not source.is_relative_to(ROOT):
        raise ValueError("Portrait source must be inside the repository")
    if hashlib.sha256(source.read_bytes()).hexdigest() != candidate["source_sha256"]:
        raise ValueError("Portrait source has changed")
    with urlopen(args.studio.rstrip("/") + "/api/control/state", timeout=8) as response:
        state = json.load(response)
    prepared = prepare(candidate, reference, state)
    args.output.write_text(json.dumps(prepared, indent=2) + "\n")
    print(json.dumps({"commands": len(prepared["commands"]),
                      "strokes": prepared["planned_strokes"],
                      "checks": prepared["checks"],
                      "first_checkpoint": prepared["stroke_checkpoints"][0],
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()