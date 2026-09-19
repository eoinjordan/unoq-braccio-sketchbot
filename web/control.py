"""Read-only hardware discovery, camera configuration and bounded manual control."""

from __future__ import annotations

import copy
import importlib.util
import math
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import cv2

from sketch_artist import config as cfg
from sketch_artist.arm_client import ArmClient
from sketch_artist.cameras import list_video_nodes, open_camera, resolve_camera_spec
from sketch_artist.fk import BraccioForwardKinematics
from sketch_artist.kinematics import BraccioKinematics, UnreachableError
from sketch_artist.paper import paper_corners, paper_to_world
from sketch_artist.portrait import detect_face_rect, _find_face_cascade

JOINTS = ("base", "shoulder", "elbow", "wrist_vertical", "wrist_rotation", "gripper")
HARD_LIMITS = ((0, 180), (15, 165), (0, 180), (0, 180), (0, 180), (10, 110))
REST_POSE = [90, 45, 180, 180, 90, 10]
DEFAULT_CONTROLS = {
    "child_mode": True, "step_deg": 0.75, "gamepad_enabled": False,
    "gamepad_deadzone": 0.22, "gamepad_enable_button": 4, "gamepad_stop_button": 1,
    "gamepad_open_button": 6, "gamepad_close_button": 7,
    "gamepad_axes": [0, 1, 3, 2], "gamepad_invert": [False, True, True, False],
}
DEFAULT_TOOLS = {
    "active": "sketch",
    "gripper": {"length_mm": 100.0, "pitch_deg": -75.0,
                "open_deg": 10.0, "closed_deg": 65.0, "clearance_mm": 5.0,
                "lift_z_mm": 70.0,
                "pick": {"x": 220.0, "y": -35.0, "z": 30.0},
                "place": {"x": 220.0, "y": 35.0, "z": 30.0}},
}


class ControlBusy(ValueError):
    """A transient refusal: no hardware command was queued or sent."""


def workspace_for_tool(workspace, tools):
    adapted = copy.deepcopy(workspace)
    if tools["active"] == "gripper":
        gripper = tools["gripper"]
        adapted["links"]["wrist_pen_mm"] = gripper["length_mm"]
        adapted["links"]["pen_tilt_deg"] = 90.0 + gripper["pitch_deg"]
        adapted["pen"]["down_gripper"] = gripper["open_deg"]
    return adapted


def number(value, name, lower, upper):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{name} must be between {lower:g} and {upper:g}")
    return result


def discover_video_devices():
    devices = []
    if sys.platform == "darwin" and shutil.which("ffmpeg"):
        try:
            result = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation",
                                     "-list_devices", "true", "-i", ""],
                                    capture_output=True, text=True, timeout=8, check=False)
            video_text = result.stderr.split("AVFoundation audio devices:")[0]
            for index, label in re.findall(r"\[(\d+)\] ([^\n]+)", video_text):
                if "Capture screen" not in label:
                    devices.append({"device": int(index), "label": label.strip(), "format": "usb"})
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        for row in list_video_nodes():
            device, usb_id = row.split("\t", 1)
            if "?" not in usb_id:
                devices.append({"device": device, "usb_id": usb_id, "label": row, "format": "usb"})
    return devices


def joint_limits(workspace):
    configured = workspace.get("servo_limits", {})
    return [(max(low, float(configured.get(name, {}).get("min", low))),
             min(high, float(configured.get(name, {}).get("max", high))))
            for name, (low, high) in zip(JOINTS, HARD_LIMITS)]


def check_paper(workspace):
    try:
        paper, pen = workspace["paper"], workspace["pen"]
        kin = BraccioKinematics(workspace)
        limits = joint_limits(workspace)
        down = float(pen["down_z_mm"])
        heights = (down, float(pen["up_z_mm"]),
                   down - float(workspace.get("motion", {}).get("pen_down_overshoot_mm", 0)))
        minimum_margin = 180.0
        for row in range(7):
            for column in range(7):
                world_x, world_y = paper_to_world(paper, float(paper["width_mm"]) * row / 6,
                                                  float(paper["height_mm"]) * column / 6)
                for height in heights:
                    angles = kin.solve(world_x, world_y, height, strict=True).as_tuple()
                    for name, value, (low, high) in zip(JOINTS, angles, limits):
                        if not low <= value <= high:
                            raise ValueError(f"Paper position exceeds {name} limits")
                        minimum_margin = min(minimum_margin, value - low, high - value)
        return {"ok": True, "samples": 147, "margin_deg": round(minimum_margin, 2),
                "corners": paper_corners(paper)}
    except (ValueError, KeyError, TypeError, ZeroDivisionError, UnreachableError) as exc:
        return {"ok": False, "error": str(exc), "samples": 0}


def validate_camera(spec):
    if not isinstance(spec, dict):
        raise ValueError("Camera settings must be an object")
    enabled = spec.get("enabled", True)
    mounted = spec.get("mounted_on_arm", False)
    if not isinstance(enabled, bool) or not isinstance(mounted, bool):
        raise ValueError("Camera enabled and mounted_on_arm must be boolean")
    cleaned = {"url": None, "usb_id": None, "device": None, "serial": None,
               "enabled": enabled, "mounted_on_arm": mounted}
    if not enabled:
        return cleaned
    transport = spec.get("format", "snapshot" if spec.get("url") else "usb")
    if transport not in ("snapshot", "mjpeg", "rtsp", "usb", "serial"):
        raise ValueError("Unsupported camera format")
    cleaned["format"] = transport
    if transport in ("snapshot", "mjpeg", "rtsp"):
        url = str(spec.get("url", "")).strip()
        parts = urlsplit(url)
        schemes = ("rtsp", "rtsps") if transport == "rtsp" else ("http", "https")
        if len(url) > 1024 or parts.scheme not in schemes or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use a credential-free HTTP camera URL, or RTSP URL in RTSP mode")
        cleaned["url"] = url
    elif transport == "serial":
        port = str(spec.get("serial", "auto"))
        if port != "auto" and not re.fullmatch(r"/dev/(?:ttyUSB\d+|ttyACM\d+|cu\.[\w.-]+)", port):
            raise ValueError("Invalid ESP serial device")
        cleaned["serial"] = port
        cleaned["baud"] = int(number(spec.get("baud", 921600), "baud", 9600, 2_000_000))
    elif spec.get("usb_id"):
        usb_id = str(spec["usb_id"]).lower()
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", usb_id):
            raise ValueError("USB identity must be a VID:PID such as 046d:0893")
        cleaned["usb_id"] = usb_id
    else:
        device = spec.get("device", 0)
        if isinstance(device, int) and not isinstance(device, bool) and 0 <= device <= 16:
            cleaned["device"] = device
        elif isinstance(device, str) and re.fullmatch(r"/dev/video\d+", device):
            cleaned["device"] = device
        else:
            raise ValueError("USB device must be an index or /dev/videoN")
    for name, default, low, high in (("width", 640, 160, 3840), ("height", 480, 120, 2160),
                                    ("fps", 15, 1, 60), ("warmup_frames", 2, 0, 20)):
        cleaned[name] = int(number(spec.get(name, default), name, low, high))
    rotation = number(spec.get("rotation", 0), "rotation", 0, 270)
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180 or 270")
    if not isinstance(spec.get("mirror", False), bool):
        raise ValueError("Mirror must be boolean")
    cleaned.update(rotation=int(rotation), mirror=spec.get("mirror", False))
    pixel_format = spec.get("pixel_format", "auto")
    if pixel_format not in ("auto", "MJPG", "YUYV", "UYVY", "NV12", "H264"):
        raise ValueError("Unsupported USB pixel format")
    cleaned["pixel_format"] = pixel_format
    cleaned["timeout"] = 3.0
    return cleaned


class ControlApp:
    def __init__(self, host="127.0.0.1", port=8765, allow_motion=False,
                 config_dir=None, arm_factory=None):
        self.config_dir = Path(config_dir or cfg.CONFIG_DIR)
        self.allow_motion = allow_motion
        self.arm_factory = arm_factory or (lambda: ArmClient(host, port, timeout=1.5))
        self.motion_lock = threading.RLock()
        self.command_lock = threading.Lock()
        self.task_step_lock = threading.Lock()
        self.auth_lock = threading.Lock()
        self.camera_lock = threading.Lock()
        self.token = None
        self.stop_generation = 0
        self.armed_until = 0.0
        self.last_move = 0.0
        self.task = None
        self.camera_handles = {}
        self.camera_configs = {}
        self.camera_health = {}
        self.reload()

    def reload(self):
        loaded = cfg.load_all(self.config_dir)
        if hasattr(self, "conf") and self.conf != loaded:
            self.stop()
        self.conf = loaded
        self.workspace = self.conf["workspace"]
        self.controls = {**DEFAULT_CONTROLS, **self.conf.get("control", {})}
        self.tools = cfg.merge_config(DEFAULT_TOOLS, self.conf.get("tools", {}))
        self.tool_workspace = workspace_for_tool(self.workspace, self.tools)
        self.paper_check = check_paper(self.workspace)

    def camera_specs(self):
        specs = {}
        for role in ("face", "gripper"):
            configured = self.conf["cameras"].get("cameras", {}).get(role)
            if isinstance(configured, dict) and configured.get("enabled") is False:
                specs[role] = copy.deepcopy(configured)
                continue
            try:
                specs[role] = copy.deepcopy(resolve_camera_spec(self.conf["cameras"], role))
            except KeyError:
                specs[role] = {"enabled": False, "mounted_on_arm": False}
        return specs

    def read_pose(self):
        with self.motion_lock, self.arm_factory() as arm:
            pose = arm.status_angles()
        if pose is None or len(pose) != 6 or not all(math.isfinite(value) for value in pose):
            raise RuntimeError("Arm did not report six finite commanded joint angles")
        return list(pose)

    def state(self):
        with self.motion_lock:
            self.reload()
        try:
            arm = {"connected": True, "pose": self.read_pose(), "error": None}
        except (OSError, RuntimeError) as exc:
            self.stop()
            arm = {"connected": False, "pose": None, "error": str(exc)}
        remaining = max(0.0, self.armed_until - time.monotonic())
        return {"arm": arm, "armed": bool(self.token and remaining),
                "lease_seconds": round(remaining, 1), "motion_enabled": self.allow_motion,
                "workspace": self.workspace, "controls": self.controls,
                "tools": self.tools, "tool_workspace": self.tool_workspace,
                "task": self.task_status(),
                "limits": joint_limits(self.workspace), "cameras": self.camera_specs(),
                "camera_health": self.camera_health, "paper_check": self.paper_check,
                "calibration_required": self.conf.get("calibration_required", True)}

    def arm(self, confirmed=False, tool_confirmed=False):
        if not self.allow_motion:
            raise ValueError("Hardware motion is disabled on this server")
        if confirmed is not True:
            raise ValueError("Operator confirmation is required")
        if self.tools["active"] == "gripper" and tool_confirmed is not True:
            raise ValueError("Confirm the gripper is fitted, the pen is removed and tool dimensions are checked")
        if self.tools["active"] == "sketch" and not self.paper_check["ok"]:
            raise ValueError("Resolve the unreachable paper configuration before enabling motion")
        generation = self.stop_generation
        self.read_pose()
        with self.auth_lock:
            if generation != self.stop_generation:
                raise ValueError("Arming was cancelled by a stop request")
            if self.token and time.monotonic() < self.armed_until:
                raise ValueError("Another control session is already armed")
            self.token = secrets.token_urlsafe(24)
            self.armed_until = time.monotonic() + 15.0
            return {"token": self.token, "lease_seconds": 15}

    def stop(self):
        with self.auth_lock:
            self.token = None
            self.stop_generation += 1
            self.armed_until = 0.0
            self.task = None
        return {"ok": True, "armed": False}

    def _authorize(self, token, held):
        with self.auth_lock:
            if held is not True or not self.token or not isinstance(token, str) or not secrets.compare_digest(token, self.token):
                raise ValueError("Motion requires an armed session and held enable control")
            if time.monotonic() >= self.armed_until:
                self.token = None
                raise ValueError("Control session expired; re-arm explicitly")

    def move(self, body):
        self._authorize(body.get("token"), body.get("held"))
        if not self.command_lock.acquire(blocking=False):
            raise ControlBusy("Arm is busy; no move was queued")
        acquired = False
        try:
            acquired = self.motion_lock.acquire(timeout=2.0)
            if not acquired:
                raise ControlBusy("Arm is busy; no move was queued")
            self._authorize(body.get("token"), body.get("held"))
            if time.monotonic() - self.last_move < 0.12:
                raise ControlBusy("Motion rate limited; no move was queued")
            with self.arm_factory() as arm:
                current = arm.status_angles()
                if current is None or len(current) != 6 or not all(math.isfinite(value) for value in current):
                    raise RuntimeError("Cannot move without a current commanded pose")
                target = list(current)
                if "angles" in body:
                    if not isinstance(body["angles"], list) or len(body["angles"]) != 6:
                        raise ValueError("Expected six joint angles")
                    target = [number(value, name, low, high) for name, value, (low, high)
                              in zip(JOINTS, body["angles"], joint_limits(self.workspace))]
                else:
                    joint = body.get("joint")
                    if joint not in JOINTS:
                        raise ValueError("Unknown joint")
                    target[JOINTS.index(joint)] += number(body.get("delta"), "delta", -2, 2)
                maximum = min(float(self.controls["step_deg"]), 0.75 if self.controls["child_mode"] else 2.0)
                span = max(abs(end - start) for start, end in zip(current, target))
                fraction = min(1.0, maximum / max(span, 0.0001))
                next_pose = [round(start + (end - start) * fraction, 3) for start, end in zip(current, target)]
                for name, value, (low, high) in zip(JOINTS, next_pose, joint_limits(self.workspace)):
                    if not low <= value <= high:
                        raise ValueError(f"{name} would exceed {low:g}..{high:g} degrees")
                floor = self.tools["gripper"]["clearance_mm"] if self.tools["active"] == "gripper" else -3.0
                if self.controls["child_mode"]:
                    floor = max(floor, 5.0)
                forward = BraccioForwardKinematics(self.tool_workspace)
                for sample in range(1, 6):
                    intermediate = tuple(start + (end - start) * sample / 5 for start, end in zip(current, next_pose))
                    if forward.solve(intermediate).z_mm < floor:
                        raise ValueError(f"Modelled tool clearance would fall below {floor:g} mm")
                self._authorize(body.get("token"), body.get("held"))
                reply = arm.move(tuple(next_pose))
                if not reply.startswith("OK"):
                    raise RuntimeError(f"Arm rejected the move: {reply}")
            self.last_move = time.monotonic()
            with self.auth_lock:
                if self.token:
                    self.armed_until = time.monotonic() + 15.0
            return {"ok": True, "pose": next_pose}
        except (OSError, RuntimeError):
            self.stop()
            raise
        finally:
            if acquired:
                self.motion_lock.release()
            self.command_lock.release()

    def preview(self, body):
        if self.tools["active"] == "gripper":
            gripper = self.tools["gripper"]
            world_x = number(body.get("x"), "base-frame x", -400, 400)
            world_y = number(body.get("y"), "base-frame y", -400, 400)
            height = number(body.get("z", gripper["lift_z_mm"]), "tool height", gripper["clearance_mm"], 400)
            angles = BraccioKinematics(self.tool_workspace).solve(world_x, world_y, height, strict=True).as_tuple()
            return {"angles": angles, "tip": [world_x, world_y, height], "tool": "gripper"}
        paper = self.workspace["paper"]
        local_x = number(body.get("x"), "paper x", 0, paper["width_mm"])
        local_y = number(body.get("y"), "paper y", 0, paper["height_mm"])
        height = number(body.get("z", self.workspace["pen"]["up_z_mm"]), "height", -3, 40)
        world_x, world_y = paper_to_world(paper, local_x, local_y)
        angles = BraccioKinematics(self.workspace).solve(world_x, world_y, height, strict=True).as_tuple()
        return {"angles": angles, "tip": [world_x, world_y, height]}

    def save_tools(self, updates):
        self.stop()
        if not isinstance(updates, dict) or not set(updates) <= {"active", "gripper"}:
            raise ValueError("Unsupported tool settings")
        values = cfg.merge_config(self.tools, updates)
        if values["active"] not in ("sketch", "gripper"):
            raise ValueError("Tool must be sketch or gripper")
        gripper = values["gripper"]
        if not isinstance(gripper, dict) or not set(gripper) <= set(DEFAULT_TOOLS["gripper"]):
            raise ValueError("Unsupported gripper settings")
        for key, low, high in (("length_mm", 30, 250), ("pitch_deg", -90, 0),
                               ("open_deg", 10, 110), ("closed_deg", 10, 110),
                               ("clearance_mm", 0, 100), ("lift_z_mm", 5, 350)):
            gripper[key] = number(gripper[key], key, low, high)
        if abs(gripper["open_deg"] - gripper["closed_deg"]) < 2:
            raise ValueError("Open and closed gripper angles must differ by at least 2 degrees")
        for name in ("pick", "place"):
            target = gripper[name]
            if not isinstance(target, dict) or set(target) != {"x", "y", "z"}:
                raise ValueError("Pick and place targets need x, y and z in the base frame")
            for axis in ("x", "y"):
                target[axis] = number(target[axis], f"{name} {axis}", -400, 400)
            target["z"] = number(target["z"], f"{name} height", gripper["clearance_mm"], 350)
            if gripper["lift_z_mm"] < target["z"] + 5:
                raise ValueError("Lift height must be at least 5 mm above both pick and place")
        adapted = workspace_for_tool(self.workspace, {**values, "active": "gripper"})
        kin = BraccioKinematics(adapted)
        for name in ("pick", "place"):
            target = gripper[name]
            for height in (target["z"], gripper["lift_z_mm"]):
                angles = kin.solve(target["x"], target["y"], height, strict=True).as_tuple()
                for joint, value, (low, high) in zip(JOINTS, angles, joint_limits(adapted)):
                    if not low <= value <= high:
                        raise ValueError(f"{name} exceeds {joint} limits")
        with self.motion_lock:
            cfg.save_overrides({"tools": values}, self.config_dir)
            self.reload()
        return {"ok": True, "tools": self.tools, "armed": False}

    def task_status(self):
        task = self.task
        if task is None:
            return None
        return {"id": task["id"], "kind": task["kind"], "tool": task["tool"],
                "index": task["index"], "count": len(task["waypoints"]),
                "label": task["waypoints"][task["index"]]["label"], "complete": False}

    def prepare_task(self, body):
        self.stop()
        kind = body.get("kind")
        tool = self.tools["active"]
        if (tool, kind) not in (("gripper", "pick_place"), ("sketch", "test_sketch")):
            raise ValueError("Select the matching tool before planning this task")
        with self.motion_lock:
            start = body.get("start")
            if start is None:
                start = self.read_pose()
            if not isinstance(start, (list, tuple)) or len(start) != 6:
                raise ValueError("Task preview needs six starting joint angles")
            limits = joint_limits(self.tool_workspace)
            start = [number(value, name, low, high) for name, value, (low, high)
                     in zip(JOINTS, start, limits)]
            kin = BraccioKinematics(self.tool_workspace)
            forward = BraccioForwardKinematics(self.tool_workspace)
            waypoints = []

            def point(label, position, gripper):
                target = list(kin.solve(*position, strict=True).as_tuple())
                target[5] = gripper
                waypoints.append({"label": label, "angles": target, "tip": list(position)})

            if tool == "gripper":
                settings = self.tools["gripper"]
                pick, place = settings["pick"], settings["place"]
                lift = settings["lift_z_mm"]
                open_angle, closed_angle = settings["open_deg"], settings["closed_deg"]
                floor = max(settings["clearance_mm"], 5.0 if self.controls["child_mode"] else 0.0)
                point("Approach pick", (pick["x"], pick["y"], lift), start[5])
                point("Open gripper", (pick["x"], pick["y"], lift), open_angle)
                point("Lower to pick", (pick["x"], pick["y"], pick["z"]), open_angle)
                point("Grip object", (pick["x"], pick["y"], pick["z"]), closed_angle)
                point("Lift object", (pick["x"], pick["y"], lift), closed_angle)
                point("Transfer", (place["x"], place["y"], lift), closed_angle)
                point("Lower to place", (place["x"], place["y"], place["z"]), closed_angle)
                point("Release object", (place["x"], place["y"], place["z"]), open_angle)
                point("Retract", (place["x"], place["y"], lift), open_angle)
            else:
                paper, pen = self.workspace["paper"], self.workspace["pen"]
                size = number(body.get("size_mm", 10), "test square size", 1,
                              min(20, float(paper["width_mm"]) - 2, float(paper["height_mm"]) - 2))
                left = (float(paper["width_mm"]) - size) / 2
                bottom = (float(paper["height_mm"]) - size) / 2
                corners = [(left, bottom), (left + size, bottom), (left + size, bottom + size),
                           (left, bottom + size), (left, bottom)]
                start_x, start_y = paper_to_world(paper, *corners[0])
                lift, floor = float(pen["up_z_mm"]), -3.0
                point("Approach paper", (start_x, start_y, lift), pen["down_gripper"])
                point("Pen down", (start_x, start_y, pen["down_z_mm"]), pen["down_gripper"])
                samples = max(1, math.ceil(size))
                for edge, (first, last) in enumerate(zip(corners, corners[1:]), 1):
                    for sample in range(1, samples + 1):
                        world_x, world_y = paper_to_world(paper,
                            first[0] + (last[0] - first[0]) * sample / samples,
                            first[1] + (last[1] - first[1]) * sample / samples)
                        point(f"Draw edge {edge}", (world_x, world_y, pen["down_z_mm"]), pen["down_gripper"])
                point("Pen up", (start_x, start_y, lift), pen["down_gripper"])

            if forward.solve(start).z_mm < lift - 0.5:
                raise ValueError("Raise the tool to travel height before planning a new task")
            previous = start
            checked = 0
            for waypoint in waypoints:
                target = waypoint["angles"]
                for name, value, (low, high) in zip(JOINTS, target, limits):
                    number(value, name, low, high)
                steps = max(1, math.ceil(max(abs(last - first) for first, last in zip(previous, target)) / 0.5))
                for sample in range(steps + 1):
                    angles = tuple(first + (last - first) * sample / steps for first, last in zip(previous, target))
                    if forward.solve(angles).z_mm < floor:
                        raise ValueError(f"{waypoint['label']} crosses the {floor:g} mm tool-clearance floor")
                    checked += 1
                previous = target
            self.task = {"id": secrets.token_hex(12), "kind": kind, "tool": tool,
                         "waypoints": waypoints, "index": 0, "last_pose": start}
            return {**self.task_status(), "waypoints": waypoints, "checked_poses": checked,
                    "start": start, "requires_contact_confirmation": tool == "sketch"}

    def advance_task(self, body):
        self._authorize(body.get("token"), body.get("held"))
        if not self.task_step_lock.acquire(blocking=False):
            raise ControlBusy("Task is busy; no move was queued")
        try:
            return self._advance_task(body)
        finally:
            self.task_step_lock.release()

    def _advance_task(self, body):
        self._authorize(body.get("token"), body.get("held"))
        with self.motion_lock:
            task = self.task
            if task is None or body.get("task_id") != task["id"] or task["tool"] != self.tools["active"]:
                raise ValueError("Task is missing or stale; prepare it again")
            if task["tool"] == "sketch":
                if self.controls["child_mode"]:
                    raise ValueError("Pen-contact tasks require supervised mode; child mode stays above the paper")
                if body.get("contact_confirmed") is not True:
                    raise ValueError("Verify pen contact height before running the test sketch")
            current = self.read_pose()
            if max(abs(value - expected) for value, expected in zip(current, task["last_pose"])) > 0.3:
                self.stop()
                raise ValueError("The arm moved outside this task; prepare it again from the current pose")
            target = task["waypoints"][task["index"]]["angles"]
            result = self.move({"token": body.get("token"), "held": body.get("held"), "angles": target})
            task["last_pose"] = result["pose"]
            if max(abs(value - expected) for value, expected in zip(result["pose"], target)) <= 0.015:
                task["index"] += 1
            complete = task["index"] == len(task["waypoints"])
            if complete:
                summary = {"id": task["id"], "kind": task["kind"], "index": task["index"],
                           "count": len(task["waypoints"]), "label": "Complete", "complete": True}
                self.stop()
            else:
                summary = self.task_status()
            return {**result, "task": summary, "complete": complete}

    def save_workspace(self, updates):
        self.stop()
        allowed = {"paper", "links", "pen", "servo_calibration", "servo_limits", "motion", "camera_poses", "planner"}
        if not isinstance(updates, dict) or not set(updates) <= allowed:
            raise ValueError("Unsupported workspace settings")
        workspace = cfg.merge_config(self.workspace, updates)
        paper, links, pen = workspace["paper"], workspace["links"], workspace["pen"]
        for key, low, high in (("origin_x_mm", -500, 500), ("origin_y_mm", -500, 500),
                               ("width_mm", 5, 200), ("height_mm", 5, 200), ("rotation_deg", -180, 180)):
            paper[key] = number(paper.get(key, 0), key, low, high)
        for key in ("base_height_mm", "shoulder_mm", "elbow_mm", "wrist_pen_mm"):
            links[key] = number(links[key], key, 10, 500)
        links["pen_tilt_deg"] = number(links.get("pen_tilt_deg", 0), "pen tilt", -45, 45)
        pen["down_z_mm"] = number(pen["down_z_mm"], "pen down", -3, 30)
        pen["up_z_mm"] = number(pen["up_z_mm"], "pen up", pen["down_z_mm"] + 2, 40)
        pen["down_gripper"] = number(pen["down_gripper"], "gripper", 10, 110)
        rotation = workspace["servo_calibration"]["wrist_rotation"]
        rotation["fixed"] = number(rotation["fixed"], "wrist rotation", 0, 180)
        for name in JOINTS[:4]:
            mapping = workspace["servo_calibration"][name]
            mapping["offset"] = number(mapping["offset"], f"{name} offset", -180, 180)
            if isinstance(mapping["sign"], bool) or mapping["sign"] not in (-1, 1):
                raise ValueError("Joint direction must be -1 or 1")
        motion = workspace.get("motion", {})
        for key, low, high in (("max_step_deg", 0.1, 2.5), ("ramp_above_deg", 0, 45),
                               ("settle_s", 0.03, 5), ("pen_change_s", 0.05, 5),
                               ("pen_down_overshoot_mm", 0, 3), ("servo_decimals", 0, 2)):
            if key in motion:
                motion[key] = number(motion[key], key, low, high)
        for name, value in motion.get("deadband_deg", {}).items():
            if name not in JOINTS:
                raise ValueError("Unknown joint in dead-band settings")
            number(value, f"{name} dead band", 0, 2)
        for name, angles in workspace.get("camera_poses", {}).items():
            if angles is None:
                continue
            if name not in ("person", "page") or not isinstance(angles, list) or len(angles) != 6:
                raise ValueError("Camera poses need six angles for person or page")
            for value, (low, high) in zip(angles, HARD_LIMITS):
                number(value, f"{name} pose", low, high)
        if "planner" in workspace:
            number(workspace["planner"].get("join_gap_mm", 0), "join gap", 0, 5)
        for name, (low, high) in zip(JOINTS, joint_limits(workspace)):
            if not math.isfinite(low) or not math.isfinite(high) or low >= high:
                raise ValueError(f"Invalid {name} limits")
        check = check_paper(workspace)
        if not check["ok"]:
            raise ValueError(check["error"])
        with self.motion_lock:
            cfg.save_overrides({"workspace": workspace, "calibration_required": True}, self.config_dir)
            self.reload()
        return {"ok": True, "paper_check": check, "calibration_required": True}

    def save_controls(self, updates):
        self.stop()
        if not isinstance(updates, dict) or not set(updates) <= set(DEFAULT_CONTROLS):
            raise ValueError("Unsupported controller setting")
        values = {**self.controls, **updates}
        for key in ("child_mode", "gamepad_enabled"):
            if not isinstance(values[key], bool):
                raise ValueError(f"{key} must be boolean")
        values["step_deg"] = number(values["step_deg"], "step", 0.1, 2)
        values["gamepad_deadzone"] = number(values["gamepad_deadzone"], "deadzone", 0.05, 0.6)
        for key in ("gamepad_enable_button", "gamepad_stop_button", "gamepad_open_button", "gamepad_close_button"):
            values[key] = int(number(values[key], key, 0, 31))
        buttons = [values[key] for key in ("gamepad_enable_button", "gamepad_stop_button", "gamepad_open_button", "gamepad_close_button")]
        if len(set(buttons)) != len(buttons):
            raise ValueError("Enable, stop, open and close buttons must be different")
        axes, invert = values["gamepad_axes"], values["gamepad_invert"]
        if not isinstance(axes, list) or len(axes) != 4 or any(type(axis) is not int or not 0 <= axis <= 15 for axis in axes):
            raise ValueError("Map four gamepad axes, each between 0 and 15")
        if not isinstance(invert, list) or len(invert) != 4 or any(type(value) is not bool for value in invert):
            raise ValueError("Four axis inversion flags are required")
        cfg.save_overrides({"control": values}, self.config_dir)
        self.reload()
        return {"ok": True, "controls": self.controls}

    def save_camera(self, role, spec):
        if role not in ("face", "gripper"):
            raise ValueError("Unknown camera role")
        camera = validate_camera(spec)
        self.stop()
        with self.camera_lock:
            previous = self.camera_handles.pop(role, None)
            if previous is not None:
                previous.close()
            specs = self.camera_specs()
            if not camera["enabled"]:
                camera = {**specs[role], "enabled": False,
                          "mounted_on_arm": camera["mounted_on_arm"]}
            specs[role] = camera
            specs.update(single={"enabled": False}, wrist={"enabled": False})
            cfg.save_overrides({"cameras": {"cameras": specs}}, self.config_dir)
            self.reload()
        return {"ok": True, "cameras": self.camera_specs()}

    def snapshot(self, role):
        if role not in ("face", "gripper"):
            raise ValueError("Unknown camera role")
        with self.camera_lock:
            try:
                current_spec = resolve_camera_spec(self.conf["cameras"], role)
                if role in self.camera_handles and self.camera_configs.get(role) != current_spec:
                    self.camera_handles.pop(role).close()
                if role not in self.camera_handles:
                    self.camera_handles[role] = open_camera(self.conf["cameras"], role)
                    self.camera_configs[role] = copy.deepcopy(current_spec)
                frame = self.camera_handles[role].read()
                face = detect_face_rect(frame) if role == "face" else None
                if face is not None:
                    left, top, width, height = face
                    frame = frame.copy()
                    cv2.rectangle(frame, (left, top), (left + width, top + height), (70, 190, 40), 2)
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise RuntimeError("Could not encode camera frame")
                self.camera_health[role] = {"ok": True, "width": frame.shape[1], "height": frame.shape[0],
                                            "face_detected": face is not None,
                                            "face_detection_available": bool(_find_face_cascade()),
                                            "observed_at": time.time()}
                return encoded.tobytes(), self.camera_health[role]
            except Exception as exc:
                previous = self.camera_handles.pop(role, None)
                if previous is not None:
                    previous.close()
                self.camera_health[role] = {"ok": False, "error": str(exc), "observed_at": time.time()}
                raise

    def diagnostics(self, probe_cameras=False):
        state = self.state()
        devices = discover_video_devices()
        cameras = {}
        for role, spec in self.camera_specs().items():
            if probe_cameras and spec.get("enabled", True):
                try:
                    self.snapshot(role)
                except Exception:
                    pass
            cameras[role] = self.camera_health.get(role, {"ok": None, "status": "configured" if spec.get("enabled", True) else "disabled"})
        return {"arm": state["arm"], "paper": self.paper_check, "cameras": cameras,
            "capabilities": {"face_detection": bool(_find_face_cascade()),
                     "network_streams": cv2.CAP_FFMPEG in cv2.videoio_registry.getBackends(),
                     "esp_serial": importlib.util.find_spec("serial") is not None},
                "devices": devices, "defaults": {"mode": "preview", "armed": False,
                                                  "controls": DEFAULT_CONTROLS},
                "motion_enabled": self.allow_motion, "calibration_required": state["calibration_required"]}

    def close(self):
        self.stop()
        with self.camera_lock:
            for camera in self.camera_handles.values():
                camera.close()
            self.camera_handles.clear()