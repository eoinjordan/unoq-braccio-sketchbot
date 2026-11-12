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

## Colour pick and place

`sketch_artist.pick_place_cli` runs unattended once started, which the Studio
never does. It has been run in simulation only. See [pick-place.md](pick-place.md).

- It is dry-run unless `--live` is given. First run, in this order: dry-run and
  read the plan; `--live --slow` with the servo power off; `--live --slow` with
  the power on, one brick, a hand on the power switch and nobody within reach.
- Every move is planned and checked before its first step is sent: strict
  inverse kinematics, the joint limits used by the Studio, steps no larger than
  `motion.max_step_deg`, and a floor that keeps the claw tips `desk.margin_mm`
  above the desk. A move that fails any check is refused whole.
- That floor is a floor in the model. If `desk.z_mm`, the gripper lengths or
  the servo zeros are wrong, the claws can reach the desk. Calibrate the desk
  height by touch before the first live descent.
- A watchdog halts the run when the camera sends no detection line for
  `watchdog_s` (1 s). Stop on the monitor page and Ctrl-C do the same. The arm
  then holds its pose and the claws stay as they are, so a held brick is not
  dropped. **None of these cuts servo power.**
- It is an independent client: it bypasses the Studio's session interlock.
  Never run it while a Studio session is armed or the calibration server is in
  use.
- There is no force sensing. A brick lying across the claws stalls the gripper
  servo at the brick's length; lay bricks with a long side towards the base.
- Keep the camera cable slack and clear of the claws over the whole base sweep.

See [Studio operation](studio.md) and [current verification status](validation.md).
