"""Sketchbot orchestrator: capture -> line art -> strokes -> plan -> draw ->
branded gallery card.

Examples:
    python -m sketch_artist.cli --image examples/sample_face.jpg --dry-run
    python -m sketch_artist.cli                 # full demo (captures + draws)
    python -m sketch_artist.cli --no-arm        # capture + gallery, no motion
    python -m sketch_artist.cli --slow          # slower, safer arm moves
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
from .portrait import to_line_art
from .preview import render_png, render_svg
from .vectorize import strokes_from_edges


def _capture_face(conf) -> "cv2.Mat":
    from .cameras import open_camera
    cam = open_camera(conf["cameras"], "face")
    try:
        return cam.read()
    finally:
        cam.close()


def _draw_on_arm(moves, workspace_cfg, kin: BraccioKinematics,
                 host: str, port: int, slow: bool) -> None:
    pen = workspace_cfg["pen"]
    motion = workspace_cfg.get("motion", {})
    down_z = float(pen["down_z_mm"])
    up_z = float(pen["up_z_mm"])
    settle = float(motion.get("settle_s", 0.15)) * (2.0 if slow else 1.0)
    pen_change = float(motion.get("pen_change_s", 0.4)) * (2.0 if slow else 1.0)

    skipped = 0
    with ArmClient(host=host, port=port) as arm:
        for m in moves:
            z = down_z if m.pen_down else up_z
            try:
                angles = kin.solve(m.x_mm, m.y_mm, z)
            except UnreachableError:
                skipped += 1
                continue
            arm.move(angles.as_tuple())
            time.sleep(pen_change if not m.pen_down else settle)
    if skipped:
        print(f"  ! {skipped} move(s) were out of reach and skipped "
              f"(check config/workspace.yaml geometry)")


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
    edges = to_line_art(frame, conf["drawing"])
    cv2.imwrite(str(Path(out_dir) / "lineart.png"), edges)

    # 3. Vectorize -> strokes.
    strokes = strokes_from_edges(edges, conf["drawing"])
    print(f"Traced {len(strokes)} strokes.")

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

    # 7. Draw on the arm (unless dry-run / no-arm).
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
    parser.add_argument("--slow", action="store_true",
                        help="Slower, safer arm moves.")
    parser.add_argument("--title", default="Visitor", help="Title on the postcard.")
    parser.add_argument("--host", default="127.0.0.1", help="Arm agent host.")
    parser.add_argument("--port", type=int, default=8765, help="Arm agent port.")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
