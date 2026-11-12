# Colour pick and place

The arm looks for 2x4 bricks of chosen colours, picks them up one at a time
and drops them in a parts bin, using only the camera on top of the gripper.

**Status.** The controller, the camera model and the tests are written. All
results on this page are simulated: the whole loop runs closed-loop on the
software arm with a simulated camera. It has not been run on a real arm, and
the detector firmware for the camera is being written separately. Every
number in `config/pick_place.yaml` is a nominal default until you have
measured it on your arm (see [Calibration](#calibration)).

Read [safety.md](safety.md) first. The first-run order is in
[First run](#first-run) below and is not optional.

## What you need

- The Braccio and UNO Q set up as for the Studio, with the arm agent running
  and the standard gripper fitted (no pen grip).
- A Seeed XIAO ESP32S3 Sense in a gripper-top holder
  ([hardware/pencil-grip](../hardware/pencil-grip/README.md#cameras-on-top-of-the-gripper)),
  running a detector that prints one line per frame on USB serial.
- 2x4 bricks in yellow, white and red, and a blue parts bin, on the same
  surface the arm stands on.

## Wiring

One cable: the XIAO's USB-C socket to a USB port on the UNO Q. It carries
power and the detection lines. If the UNO Q's USB-C port is also its power
input, use a USB-C hub that passes power through. Leave slack for the wrist,
keep the cable outside the gripper cable ties, and check by hand that it does
not snag over the whole base sweep.

The XIAO appears as a serial port (`/dev/ttyACM*` on the UNO Q). It is found
by Espressif's USB vendor id, 303A; name it with `--port` if there is more
than one Espressif board. The user running the program needs access to the
port (the `dialout` group on Debian).

## The detection line

One line per frame, 115200 baud:

```
DET n=2 yellow 0.42 0.61 0.93 red 0.70 0.33 0.88 bin 0.15 0.20 0.97 ms=41
```

A count, then label, x, y and confidence for each object, then the inference
time. x and y are the centre of the object in the picture, 0 to 1, origin top
left. Labels: `yellow`, `white`, `red`, and `bin` for the parts bin.

All knowledge of this format is in `sketch_artist/detections.py`. The parser
accepts the changes that are likely while the firmware settles: extra
`key=value` fields, a missing or wrong count, commas, extra numbers after the
confidence, upper case, and log text in front of `DET`. Anything else on the
port is ignored.

## How it works

There is no depth sensor. The controller knows where the camera is from the
arm's own kinematics and the holder's dimensions, and it assumes the bricks
lie on the desk and the bin's rim is at a known height. A point in the
picture then fixes a point on the desk.

The holder tilts the camera so that its optical axis meets the gripper centre
line at the holder's pick distance. The point where the centre line meets
the desk is therefore a known point in the picture, which moves down the
picture as the gripper gets lower. Bringing a brick to that point puts it
straight ahead of the claws.

1. **Search.** The grasp point is held at the search height and the base
   sweeps. A brick of an enabled colour has to be seen at or above the
   confidence threshold in several frames running, in the same place.
2. **Approach.** The claws are pointed at the brick, then the picture takes
   over: the gripper moves sideways until the brick is on the aim point,
   steps down along its centre line, and centres again. Moving along the
   centre line keeps the aim point on the same spot of the desk.
3. **Commit.** A short way above the brick the brick leaves the bottom of
   the picture. The last stretch (`approach.commit_distance_mm`) is a
   straight move down the centre line with no correction.
4. **Grasp, lift, check.** The claws close, the gripper backs up to the
   search height and looks at where the brick was. If a brick of that colour
   is still there the grasp failed and the approach is tried again, up to
   `max_attempts`. A brick that cannot be picked is left alone for the rest
   of the run.
5. **Place.** The bin is found the same way (label `bin`), the gripper
   centres on it, lowers towards the rim and opens. If the bin is not seen
   within `bin.search_timeout_s` the fixed position `bin.fallback_xy_mm` is
   used. Once seen, the bin's position is remembered and bricks detected
   inside it are ignored.
6. Back to the search. The run ends when a whole sweep finds nothing to
   pick, or after `max_picks`.

The kinematics, joint limits and tool model are the existing ones
(`sketch_artist/kinematics.py`, `sketch_artist/fk.py`, the Studio's limits in
`web/control.py`). `sketch_artist/gripper_camera.py` adds only the camera's
fixed offset on the gripper.

## Options

All in [`config/pick_place.yaml`](../config/pick_place.yaml), each with a
comment. Single values can be overridden under a `pick_place:` key in
`config/runtime.yaml`. The ones used most:

| Setting | Default | Meaning |
| --- | --- | --- |
| `colours` | red, yellow, white | Which bricks to pick, most wanted first |
| `strict_order` | false | true clears one colour completely before the next |
| `confidence` | 0.6 | Detections below this are ignored |
| `confirm_frames` | 3 | Frames running before a detection is believed |
| `max_attempts` | 3 | Tries at one brick |
| `max_picks` | 12 | Bricks per run |
| `watchdog_s` | 1.0 | Halt after this long with no detection line |
| `search.height_mm` | 80 | Grasp point above the desk for searching and carrying |
| `brick.grasp_height_mm` | 8 | Grasp point above the desk when the claws close |
| `desk.margin_mm` | 3 | The claws are never commanded lower than this above the desk |
| `gripper.open_width_mm`, `close_width_mm` | 45, 13 | Gap between the claws open, and commanded when holding a 15.8 mm wide brick |
| `speed.max_step_deg`, `step_interval_s` | 2.0, 0.05 | Largest joint change per command and the pause between commands |
| `speed.slow_factor` | 0.4 | `--slow`: 0.8 degrees every 0.125 s |
| `bin.fallback_xy_mm` | 130, 225 | Middle of the bin when it is not seen |

`--colours`, `--confidence`, `--max-picks`, `--max-attempts` and
`--strict-order` override the file for one run.

## Calibration

Nothing below has been done for you. Do each step on your arm, with the
servo power off unless the step says otherwise, and write the result in
`config/pick_place.yaml`.

1. **Arm geometry and servo zeros.** `links` and `servo_calibration` in
   `config/workspace.yaml`, as for drawing ([calibration.md](calibration.md)).
   The `servo_limits` there were measured with the pen grip fitted; measure
   them again with the gripper.
2. **Wrist roll** (`tool.wrist_rotation_deg`). The camera has to be on the
   face of the gripper that looks away from the base when the gripper points
   outwards and down. In the Studio, jog wrist rotation until it is, and
   write that servo angle down. 0 follows from the arm model; your servo may
   need 180. The claws then close sideways, across the arm.
3. **Gripper lengths** (`tool.grasp_from_mount_mm`, `tool.tip_from_mount_mm`).
   With a ruler, from the face the fingers are screwed to: to the point
   between the claws where a brick is held, and to the claw tips.
4. **Tool pitch** (`tool.pitch_deg`). Send the arm to the search pose in the
   Studio (Gripper tool, the same length and pitch) and check the gripper
   centre line against a protractor or a set square. If it is not 60 degrees
   below horizontal, the servo zeros in step 1 are off.
5. **Claw opening** (`gripper.jaw_calibration`). Command two gripper angles
   in the Studio and measure the gap between the claws at each with calipers.
   Then check `open_width_mm` clears a brick lying at any angle (its diagonal
   is 35.5 mm) and `close_width_mm` holds one without stalling the servo.
6. **Desk height** (`desk.z_mm`). With motion enabled at low speed in the
   Studio, lower the open gripper at three places in the pick band until the
   claw tips just touch a sheet of paper on the desk, and read the modelled
   height each time. The tips should read 0. Put the average error in
   `desk.z_mm`. If the three differ by more than 2 mm the arm is not level
   with the desk or the servo zeros are off; fix that first. In simulation
   this is the calibration that matters most (see [Limits](#limits)).
7. **Camera holder** (`camera.tilt_deg`, `height_mm`, `lens_from_mount_mm`).
   Copy the row for the holder you printed from the table in the hardware
   README. If you changed `pick_distance`, `camera_height` or `face_z`, the
   holder's OpenSCAD source echoes the new values.
8. **Picture direction** (`camera.image_rotation_deg`, `camera.mirror`). Run
   `--listen` with the arm at the search pose. A brick moved away from the
   base must move up the picture (y falls). A brick moved to the arm's right,
   seen from behind the arm, must move right (x rises). If not, set the
   rotation (90, 180 or 270) or the mirror until both hold.
9. **Field of view** (`camera.fov_diagonal_deg`). 66 is an estimate. Put two
   bricks a measured distance apart at a measured distance from the lens and
   compare with what `--listen` reports, or take the figure from the sensor's
   data sheet.
10. **Aim check.** The dry-run prints where the aim point should be in the
    picture at the search height. With the arm at the search pose, put a
    brick where the claws point (sight along the centre line) and compare
    with `--listen`. A steady offset means the tilt, height or wrist roll is
    not what the file says.
11. **Bin** (`bin.rim_height_mm`, `bin.fallback_xy_mm`). Measure the height
    of the rim, and the middle of the bin from the base axis: x straight
    ahead of the arm, y to its left.
12. **Threshold and range.** Watch `--listen` over the lighting you will use
    and set `confidence` between what real bricks score and what false
    detections score. Set `search.base_min_deg` and `base_max_deg` so the
    sweep stays clear of everything around the arm.

## Running

On the UNO Q, from the repository, with the arm agent running:

```bash
# 1. All software: the simulated arm and camera. No hardware is used.
python -m sketch_artist.pick_place_cli --source sim

# 2. The camera only: print what it reports. Moves nothing.
python -m sketch_artist.pick_place_cli --listen

# 3. Dry-run with the real camera: plans and logs, sends nothing.
python -m sketch_artist.pick_place_cli --monitor-port 7110

# 4. Live. Sends moves to the arm agent.
python -m sketch_artist.pick_place_cli --live --slow --monitor-port 7110
```

`./scripts/run_demo.sh pickplace ...` passes the same options through the
project's virtualenv.

Dry-run is the default and `--live` is the only way to move the arm. A
dry-run checks the configuration against the limits, prints the plan (search
pose, aim point, claw angles, step size) and then follows the detections,
logging every move it would send. Because the arm does not move, the picture
does not change and the approach cannot converge, so expect an approach
timeout; what you are checking is that detections arrive, that the right
brick is chosen, and that no move is refused.

`--record FILE` saves the camera's lines with their arrival times, and
`--replay FILE` runs the dry-run against such a file, with no camera.

**Monitor page.** `--monitor-port 7110` serves a page at
`http://127.0.0.1:7110/` (add `--monitor-bind 0.0.0.0` to open it from a
tablet on a trusted network) with the live detections, the aim point, the
state, counts, the log, and a Stop button. It is served by this program, not
by the Studio: the Studio's motion is hold-to-run under an armed session, and
an unattended loop does not fit that interlock without rewriting it. Do not
run pick and place while a Studio session is armed.

**At boot.** [pick-place-service.md](pick-place-service.md) covers running
this as a service that waits for a Start press, the reach-behind option,
and what was measured on the floor rig.

**Stopping.** The Stop button, Ctrl-C, or the camera falling silent for
`watchdog_s` all end the run and stop commands being sent. The arm holds its
last pose and the claws stay as they are, so a held brick is not dropped.
None of these cuts servo power.

## First run

In this order, each step only after the one before is clean:

1. `--source sim`, to see the sequence.
2. Calibration, all twelve steps.
3. `--listen`, bricks and bin on the desk, to check the detections.
4. Dry-run. Read the plan it prints.
5. `--live --slow` with the **servo power off**. The agent accepts the moves
   and nothing moves. Check the log shows the search starting and no fault.
6. `--live --slow` with the power on, one brick, the bin in place, a hand on
   the power switch, and nobody within reach of the arm. Be ready to cut
   power on the first descent: if `desk.z_mm` or the gripper lengths are
   wrong, this is when the claws meet the desk.
7. Only then more bricks, and only then without `--slow`.

## Limits

- **Simulated only.** The numbers below come from
  `python -m sketch_artist.pick_place_cli --trials 300 --seed 1000`: random
  layouts of three bricks and a bin, a pinhole camera (66 degrees diagonal,
  4:3) with position noise of 1.2 percent of the picture, 8 percent of
  detections dropped (35 percent near the edge), 4 percent of lines lost, 3
  percent of frames with a false detection, one frame of lag, and a 3 percent
  chance that a good grasp slips. The simulated rig is also built slightly
  off its configuration: camera tilt, height and position by about 1 degree
  and 1 mm, field of view by 2 degrees, each servo zero by 0.4 degrees, the
  desk by 0.8 mm (standard deviations, at scale 1).

  | Calibration error scale | Layouts cleared | Bricks binned | Not cleared because |
  | --- | --- | --- | --- |
  | 1.0 | 273 of 300 (91.0 percent) | 829 of 900 | grasp failed 25, out of reach 2 |
  | 0.5 | 300 of 300 | 900 of 900 | |
  | 0 | 300 of 300 | 900 of 900 | |

  Almost every failure at scale 1 is the same one: the servo zero errors add
  up to a few millimetres of height at the pick radius, the claws close above
  the brick, and every attempt fails the same way. In the same runs the claw
  tips reached 2.8 mm below the simulated desk. The floor in the controller
  is a floor in the model; it is only as good as `desk.z_mm` and the servo
  zeros. That is why calibration step 6 is done by touch.
- **What the simulation leaves out.** Collisions of the arm, the claws or a
  held brick with the bin or other bricks; the claws and a held brick hiding
  part of the picture; blur at close range (the last corrections are made
  with the lens about 70 mm from the brick); lighting; servo lag, dead band
  and backlash; cable drag on the wrist. The dead-band compensation used for
  drawing is not applied here.
- **Reach.** With the gripper at -60 degrees the arm reaches bricks whose
  centres are roughly 260 to 305 mm from the base axis, across the base
  sweep. That band is set by the elbow and wrist limits in `workspace.yaml`,
  not by this code; a steeper gripper narrows it and moves it inwards. The
  middle of the bin should be 240 to 290 mm out. Bricks outside the band are
  detected, refused by the limit checks, and left alone.
- **Brick angle is not seen.** The detector reports a centre, not an angle.
  The claws close across the arm; a brick lying across them is held by its
  31.8 mm length and the servo stalls at that width. Lay bricks with a long
  side pointing at the base, or accept the load on the gripper servo.
- **No grasp sensing.** The only check is looking at where the brick was.
  A brick that is knocked away rather than picked reads as picked.
- **Keep clear.** Bricks at least 45 mm apart and 95 mm from the middle of
  the bin, an empty bin at the start (bricks already in a bin that has not
  been seen yet would be picked out of it), and nothing else on the desk in
  the sweep.
- **One wrist roll.** The camera turns with wrist roll, and the model allows
  for it, but the controller holds one roll angle for the whole run.

## Tests

`tests/test_detections.py` covers the line format, the serial port and
replay. `tests/test_pick_place.py` covers the camera model, the limit checks,
the whole loop on the software arm (directly and over the arm protocol), the
watchdog, stop, dry-run, the bin fallback, a failed grasp, randomised layouts
with noise, the monitor page and the command line. None of it uses hardware.
