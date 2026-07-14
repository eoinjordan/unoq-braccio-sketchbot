# Safety

The Braccio is a powered arm that moves near people at a booth. Read this before
enabling motion.

## Before any motion

- **Keep the e-stop / power switch within reach.** The Braccio shield power
  connector is the fastest cut-off.
- Start every new setup with `--dry-run`, then `--slow`. Only run at full speed
  once the toolpath and geometry look correct.
- Clear the workspace: nothing (and nobody's hands) inside the arm's reach while
  it draws.

## Pen holder

- Use the spring-loaded holder in `hardware/pen-holder/`. The compliance means a
  Z error pushes the spring instead of driving the tool into the paper or
  snapping a pencil lead.
- Set `pen.down_z_mm` so the spring is only lightly preloaded on contact.

## Software guards

- `kinematics.py` raises `UnreachableError` for out-of-workspace points; `cli.py`
  skips and counts them rather than commanding a bad pose. If many moves are
  skipped, your `workspace.yaml` geometry is wrong — stop and re-measure.
- The arm agent should be the arm-only `braccio_remote_agent`. Do not point the
  app at an agent that also streams a camera, so both USB cameras stay free.
- Servo offsets are unverified until you calibrate them. A wrong `sign`/`offset`
  can drive a joint to a limit — always test with `--slow` and a hand on the
  power.

## People

- No loose hair, sleeves, or lanyards near the arm.
- Treat the pen tip as sharp; keep faces away from the drawing plane.
