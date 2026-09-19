# Safety

The Braccio is a powered arm that moves near people at a booth. Read this before
enabling motion.

## Before any motion

- Select the tool that is actually fitted. Gripper mode requires the pen to be
  removed and its wrist-to-grasp-point length checked. Switching a software
  profile does not change the physical attachment.

- **Keep the e-stop / power switch within reach.** The Braccio shield power
  connector is the fastest cut-off.
- Start every new setup with `--dry-run`, then `--slow`. Only run at full speed
  once the toolpath and geometry look correct.
- Clear the workspace: nothing (and nobody's hands) inside the arm's reach while
  it draws.

## Pen holder

- Use the printed grip in `hardware/pencil-grip/`. It bolts on in place of a
  Braccio finger and clamps the tool with an M3 screw, so the pen can't slip
  mid-drawing.
- It is **rigid** (no Z compliance), so tune `pen.down_z_mm` carefully and keep
  downward force light — too low and the pen digs in or snaps a lead. Add a
  spring-loaded Z stage between the wrist and grip if your table isn't flat.

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

## Studio Controls

- Hardware motion requires server opt-in (`--allow-motion`), Real arm mode,
  operator confirmation and an armed session. Sliders only set preview targets;
  movement is hold-to-run, with one bounded step per request.
- Child mode limits steps to 0.75 degrees and modelled tool clearance to at
  least 5 mm. It is not a certified safety system or a substitute for supervision.
- Sketch tasks require supervised mode and explicit contact-height confirmation.
  They never turn off child mode automatically.
- Pick/place settings describe commanded jaw angles, not grip force. Test with
  small, light objects. No force sensing or successful-grasp detection is present.
- Release pauses task advancement. Stop cancels and disarms while preserving the
  current jaw position; it does not drop the load or attempt an automatic park.
  An already accepted bounded step may finish.
- **Software Stop does not cut servo power.** Keep the physical power cutoff
  accessible. Do not rely on a browser or network connection as an emergency stop.
- Use the control server only on a trusted local network. The adult checkbox is
  not authentication. Independent CLI clients, boot sketches and the legacy
  calibration server bypass the studio's session interlock; never run them at
  the same time.

See [Studio operation](studio.md) and [current verification status](validation.md).
