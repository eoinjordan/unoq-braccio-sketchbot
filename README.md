# Edge Impulse Sketchbot (UNO Q + Braccio)

A live "sketchbot" demo: a **TinkerKit Braccio** arm driven by an **Arduino
UNO Q** takes a photo of a visitor, turns it into a line-art caricature, and
**draws it with a real pencil** on an Edge Impulse–branded postcard. Finished
sketches appear on a branded **live web gallery**, exactly like a trade-show
Sketchbot wall.

```
 Razer Kiyo (face cam) ──► portrait ──► vectorize ──► plan strokes ──► IK ──► Braccio pencil
                                                                        │
 Solid Year gripper cam ──► paper calibration / monitoring ◄───────────┘
                                                                        │
                                     branded PNG ──► live web gallery ◄─┘
```

> Inspired by the classic caricature "Sketchbot" installations, rebuilt on
> low-cost Arduino hardware with Edge Impulse branding.

## What it does

1. **Capture** – grab a frame from the person-facing **Razer Kiyo** webcam.
2. **Portrait → line art** – detect the face, crop, and convert to clean
   single-stroke line art (edges + contours). Optionally use an Edge Impulse
   model to gate capture (e.g. "person present" / "smile").
3. **Vectorize** – turn the line art into ordered pen strokes.
4. **Plan** – scale strokes into the paper workspace, order them to minimise
   pen travel, and insert pen-up / pen-down moves.
5. **Draw** – stream joint commands to the Braccio over the arm agent
   (`127.0.0.1:8765`), using inverse kinematics to place the pencil tip.
6. **Calibrate / monitor** – the **gripper-mounted** Solid Year camera finds
   the paper corners (homography) so drawings land on the branded box, and
   provides a live view while drawing.
7. **Gallery** – composite the finished sketch onto the Edge Impulse postcard
   template and publish it to the **live web gallery** page.

## Hardware

| Role            | Device                              | USB ID       |
| --------------- | ----------------------------------- | ------------ |
| Face camera     | Razer Kiyo                          | `1532:0e03`  |
| Gripper camera  | Solid Year SW72011                  | `060b:8038`  |
| Arm             | Arduino UNO Q + TinkerKit Braccio   | —            |
| Pen             | A pencil clamped in the gripper     | —            |

Cameras are resolved by **USB vendor:product ID**, not by `/dev/videoN`
(which is unstable across reboots). Update `config/cameras.yaml` if you swap
cameras.

## Prerequisites

- An UNO Q running the Braccio **arm-control agent** on `127.0.0.1:8765`
  (use the arm-only `braccio_remote_agent`, **not** the web agent, so the
  cameras stay free for this app). It speaks the same `M`/`S` protocol as the
  `unoq-braccio` project.
- Docker on the UNO Q (arm64), or Python 3.11+ with the `requirements.txt`
  installed.
- Both cameras plugged in. Verify with:

  ```bash
  ./scripts/list_cameras.sh
  ```

## Quick start (dry run, no arm)

Prove the pipeline end-to-end without moving the arm — it reads a photo,
produces the toolpath preview, and writes a branded gallery card:

```bash
pip install -r requirements.txt
python -m sketch_artist.cli --image examples/sample_face.jpg --dry-run
open output/preview.png            # toolpath the arm would draw
open output/gallery/*.png          # branded postcard
```

## Run the full demo

```bash
# 1. Start the arm agent on the UNO Q (braccio_remote_agent) -> :8765
# 2. Print assets/edge_impulse_paper_template.svg and tape it in the paper box
# 3. Calibrate the paper with the gripper camera:
python -m sketch_artist.calibration --save config/homography.json
# 4. Run: capture a visitor, draw them, publish to the gallery:
python -m sketch_artist.cli
```

Start the branded live gallery on its own (port `7100`):

```bash
python -m web.server            # http://<uno-q>:7100
```

Or bring the whole thing up with Docker (cameras + arm reach + gallery):

```bash
docker compose up -d --build
docker compose logs -f sketchbot
```

## Configuration

| File                    | Purpose                                                        |
| ----------------------- | ------------------------------------------------------------- |
| `config/cameras.yaml`   | USB IDs + resolution for the face and gripper cameras         |
| `config/workspace.yaml` | Braccio link lengths, paper placement, pen up/down heights    |
| `config/drawing.yaml`   | Edge/contour parameters, stroke simplification, stroke cap    |
| `config/branding.yaml`  | Edge Impulse colours, tagline, logo/QR paths, paper layout    |

## Calibration & safety

Drawing is only as good as the geometry. Measure your arm's link lengths and
paper placement and put them in `config/workspace.yaml`. See
[docs/calibration.md](docs/calibration.md) for the homography step and
[docs/safety.md](docs/safety.md) before letting the arm move near people.

> ⚠️ The inverse-kinematics servo mapping in `sketch_artist/kinematics.py` uses
> configurable offsets that **must be tuned to your servos' zero positions**.
> Start with `--dry-run`, then `--slow`, and keep the e-stop within reach.

## How it maps to Edge Impulse

- **Branding** – the postcard template and web gallery use the Edge Impulse
  palette and tagline (`config/branding.yaml`). Drop the official logo at
  `assets/edge_impulse_logo.png` and a QR at `assets/qr.png`.
- **Optional model gate** – wire an Edge Impulse image model (person / smile /
  pose) to decide *when* to capture, reusing the `edgeimpulse_ros` or
  `edge_impulse_linux` runner from the `unoq-braccio` project.

## Repository layout

```text
sketch_artist/     Vision + planning + kinematics + arm client (the pipeline)
web/               Branded live gallery web server + static assets
config/            Camera, workspace, drawing and branding configuration
assets/            Edge Impulse postcard template + logo/QR slots
scripts/           Camera listing and demo runner helpers
docs/              Architecture, calibration and safety notes
examples/          A sample face image for dry runs
```

## License

MIT — see [LICENSE](LICENSE).
