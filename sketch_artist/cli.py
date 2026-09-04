"""Sketchbot orchestrator: capture -> line art -> strokes -> plan -> draw ->
branded gallery card.

Examples:
    python -m sketch_artist.cli --image examples/sample_face_eoin.png --dry-run
    python -m sketch_artist.cli                 # full demo (captures + draws)
    python -m sketch_artist.cli --no-arm        # capture + gallery, no motion
    python -m sketch_artist.cli --slow          # slower, safer arm moves
    python -m sketch_artist.cli --dry-run --debug  # inspect the face crop
    python -m sketch_artist.cli --list-styles      # list caricature scenes
    python -m sketch_artist.cli --style engineer   # face into a scene template
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from . import config as cfg
from .arm_client import ArmClient
from .gallery import publish, render_postcard
from .kinematics import BraccioKinematics, UnreachableError
from .planner import Move, move_count, plan
from .portrait import crop_to_face, to_line_art
from .preview import render_png, render_svg
from .scenes import (available_styles, compose, resolve_style)
from .sim import SimArmAgent
from .vectorize import strokes_from_edges


def _capture_face(conf) -> "cv2.Mat":
    from .cameras import open_camera
    cam = open_camera(conf["cameras"], "face")
    try:
        return cam.read()
    finally:
        cam.close()


def _draw_on_arm(moves, workspace_cfg, kin: BraccioKinematics,
                 host: str, port: int, slow: bool) -> dict:
    pen = workspace_cfg["pen"]
    motion = workspace_cfg.get("motion", {})
    down_z = float(pen["down_z_mm"])
    up_z = float(pen["up_z_mm"])
    settle = float(motion.get("settle_s", 0.15)) * (2.0 if slow else 1.0)
    pen_change = float(motion.get("pen_change_s", 0.4)) * (2.0 if slow else 1.0)

    drawn = skipped = 0
    with ArmClient(host=host, port=port) as arm:
        for m in moves:
            z = down_z if m.pen_down else up_z
            try:
                angles = kin.solve(m.x_mm, m.y_mm, z)
            except UnreachableError:
                skipped += 1
                continue
            arm.move(angles.as_tuple())
            drawn += 1
            time.sleep(pen_change if not m.pen_down else settle)
    if skipped:
        print(f"  ! {skipped} move(s) were out of reach and skipped "
              f"(check config/workspace.yaml geometry)")
    return {"drawn": drawn, "skipped": skipped}


def run(args) -> int:
    conf = cfg.load_all()
    out_dir = cfg.ensure_dir(cfg.resolve_path("output"))

    # 1. Capture / load the face image.
    if args.image:
        frame = cv2.imread(str(cfg.resolve_path(args.image)))
        if frame is None:
            print(f"Could not read image: {args.image}")
            return 2
        print(f"Loaded {args.image}")
    else:
        print("Capturing from the face camera ...")
        frame = _capture_face(conf)

    # 2. Portrait -> line art.
    if args.debug:
        cv2.imwrite(str(Path(out_dir) / "debug_capture.png"), frame)
        portrait_cfg = conf["drawing"].get("portrait", {})
        crop, found = crop_to_face(
            frame,
            margin=float(portrait_cfg.get("crop_margin", 0.35)),
            cascade_path=str(portrait_cfg.get("face_cascade", "")),
            scale_factor=float(portrait_cfg.get("scale_factor", 1.1)),
            min_neighbors=int(portrait_cfg.get("min_neighbors", 4)),
            min_size_px=int(portrait_cfg.get("min_size_px", 60)),
        )
        cv2.imwrite(str(Path(out_dir) / "debug_face_crop.png"), crop)
        print(f"  debug: face {'detected' if found else 'NOT detected'}; "
              f"wrote debug_capture.png + debug_face_crop.png")

    edges = to_line_art(frame, conf["drawing"])
    cv2.imwrite(str(Path(out_dir) / "lineart.png"), edges)

    # 3. Vectorize -> strokes.
    strokes = strokes_from_edges(edges, conf["drawing"])
    print(f"Traced {len(strokes)} strokes.")

    # 3b. Place the face into the chosen caricature scene.
    canvas_px = int(conf["drawing"].get("capture", {}).get("target_px", 512))
    style = resolve_style(conf["scenes"], args.style, interactive=True)
    strokes = compose(strokes, style, conf["scenes"], canvas_px)
    print(f"Style: {style} ({len(strokes)} strokes after composing).")

    # 4. Plan.
    moves = plan(strokes, conf["workspace"])
    down, up = move_count(moves)
    print(f"Planned {len(moves)} moves ({down} pen-down points, {up} pen-up).")

    # 5. Preview always (useful even for the live demo).
    preview_png = render_png(moves, conf["workspace"], str(Path(out_dir) / "preview.png"))
    render_svg(moves, conf["workspace"], str(Path(out_dir) / "preview.svg"))
    print(f"Wrote preview: {preview_png}")

    # 6. Branded gallery card.
    gallery_dir = cfg.ensure_dir(cfg.resolve_path(conf["branding"]["gallery"]["output_dir"]))
    card_name = f"sketch_{int(time.time())}.png"
    card_path = str(Path(gallery_dir) / card_name)
    render_postcard(moves, conf["workspace"], conf["branding"], card_path,
                    title=args.title)
    publish(card_path, conf["branding"], title=args.title)
    print(f"Published gallery card: {card_path}")

    # 7. Draw: on the software simulator (--sim), or the real arm, or not at all.
    if args.sim:
        agent = SimArmAgent(conf["workspace"]).start()
        kin = BraccioKinematics(conf["workspace"])
        print(f"Drawing on the software simulator at 127.0.0.1:{agent.port} ...")
        try:
            stats = _draw_on_arm(moves, conf["workspace"], kin,
                                 "127.0.0.1", agent.port, args.slow)
            sim_out = str(cfg.resolve_path(args.sim_render))
            agent.simulator.render(sim_out)
        finally:
            agent.stop()
        print(f"Simulator drew {stats['drawn']} points "
              f"({stats['skipped']} out of reach); wrote {sim_out}")
        return 0

    if args.dry_run or args.no_arm:
        print("Skipping arm motion (dry-run / no-arm).")
        return 0

    kin = BraccioKinematics(conf["workspace"])
    print(f"Drawing on the Braccio via {args.host}:{args.port} ...")
    _draw_on_arm(moves, conf["workspace"], kin, args.host, args.port, args.slow)
    print("Done.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Braccio sketchbot pipeline.")
    parser.add_argument("--image", help="Draw from an image file instead of the camera.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the whole pipeline but do not move the arm.")
    parser.add_argument("--no-arm", action="store_true",
                        help="Capture + preview + gallery, but skip arm motion.")
    parser.add_argument("--sim", action="store_true",
                        help="Draw against the built-in software simulator "
                             "instead of a real arm (no hardware needed) and "
                             "save what it drew to --sim-render.")
    parser.add_argument("--sim-render", default="output/sim_drawing.png",
                        help="Where --sim writes the simulated drawing PNG.")
    parser.add_argument("--slow", action="store_true",
                        help="Slower, safer arm moves.")
    parser.add_argument("--debug", action="store_true",
                        help="Save the raw capture and detected face crop to "
                             "output/ (debug_capture.png, debug_face_crop.png).")
    parser.add_argument("--title", default="Visitor", help="Title on the postcard.")
    parser.add_argument("--style", default=None,
                        help="Caricature scene style (e.g. engineer, cyclist, "
                             "driver, painter, none). Omit to be prompted. "
                             "See --list-styles.")
    parser.add_argument("--list-styles", action="store_true",
                        help="List the available caricature styles and exit.")
    parser.add_argument("--host", default="127.0.0.1", help="Arm agent host.")
    parser.add_argument("--port", type=int, default=8765, help="Arm agent port.")
    args = parser.parse_args(argv)

    if args.list_styles:
        scenes_cfg = cfg.load_all()["scenes"]
        print("Available caricature styles:")
        for name, label in available_styles(scenes_cfg):
            print(f"  {name:12s} {label}")
        return 0

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
