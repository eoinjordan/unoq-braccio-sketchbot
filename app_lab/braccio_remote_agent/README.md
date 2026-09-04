# Braccio Remote Agent (Arduino App Lab)

The **arm-control agent** for the sketchbot. It runs on the UNO Q and exposes
the sketchbot's `M`/`S` protocol on TCP **:8765**:

```text
M <base> <shoulder> <elbow> <wrist_vertical> <wrist_rotation> <gripper>   -> OK
S                                                                         -> STAT ...
```

- **`python/main.py`** — Linux side: the TCP `:8765` server (App Lab
  `arduino.app_utils`). Each `M` calls the MCU's `move_braccio` over the Bridge.
- **`sketch/`** — MCU side (`arduino:zephyr:unoq`): drives the six servos via a
  self-contained `Servo` driver (`UnoQBraccioBridge`) and provides
  `move_braccio` over the App Lab Bridge.

> **Libraries:** only **`RoboServo`** (by *dunknowcoding*) — it supports the
> UNO Q. Do **not** use **`Servo`** or **`Braccio`** (no `arduino:zephyr` build),
> nor list **`Arduino_RouterBridge`** (bundled in the platform). Install
> RoboServo from the App Lab library panel (or Library Manager) before running.

## Deploy on the UNO Q

```bash
mkdir -p ~/ArduinoApps
cp -r app_lab/braccio_remote_agent ~/ArduinoApps/
arduino-app-cli app start ~/ArduinoApps/braccio_remote_agent   # compiles + flashes + runs
arduino-app-cli app logs  ~/ArduinoApps/braccio_remote_agent   # "listening on 8765"
ss -ltn | grep 8765                                            # confirm it's up
```

First start compiles the Zephyr sketch and flashes the MCU (a few minutes).
Power the Braccio shield from its servo supply; keep the shield power switch as
your e-stop. On boot the arm moves to a rest pose.

Then draw from the repo root:

```bash
.venv/bin/python -m sketch_artist.cli \
    --image examples/sample_face_eoin.png --style none --slow
```

## Servo pin map

Braccio shield defaults: base `11`, shoulder `10`, elbow `9`, wrist_vertical `6`,
wrist_rotation `5`, gripper `3`, soft-start enable `12`. Joint limits match the
firmware (`shoulder 15–165`, `gripper 10–110`, others `0–180`).
