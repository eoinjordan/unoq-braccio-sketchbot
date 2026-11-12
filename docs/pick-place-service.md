# Pick and place at boot

How the gripper-camera pick and place ([pick-place.md](pick-place.md)) is
run as a service on the UNO Q, how to stop it, how to put its page on a
touchscreen, and what was and was not measured on the floor rig on
2026-11-12.

**Status on 2026-11-12.** The service is installed on the development board
and comes up by itself in dry-run mode. It has never moved the arm: the
camera was not connected to the board, the calibration in pick-place.md is
not done, and the board reset under servo load during testing (see
[Incidents](#incidents)). Live motion is off and must stay off until those
three things are dealt with.

## What runs

`sketch_artist/pick_place_service.py` wraps the pick-and-place controller in
a process that stays up and serves the monitor page on port 7110.

| State | Meaning |
| --- | --- |
| waiting | The arm agent or the camera is missing, or the arm is not parked. The page says which. Nothing moves. |
| ready | Arm agent answering, arm parked, camera present. Waiting for Start. |
| running | A session is in progress. Stop ends it; the arm holds its pose. |
| done, stopped, fault | How the last session ended. Start runs another once the arm is parked. |

Buttons on the page: **Start**, **Stop**, **Park**. Park is a checked,
stepped move back to the rest pose and is the only motion offered outside a
session. After a session that finishes by itself the arm parks; after Stop
or a fault it holds its pose, as documented for the controller, and Park has
to be pressed.

Nothing moves until Start is pressed. `--autostart` changes that: one
session starts by itself the first time everything is ready after the
service starts. It is off by default, because an arm that starts moving at
power-on with nobody ready is a hazard. A service restarted by systemd
never resumes a session.

Sessions are dry runs unless the service is started with
`--live --i-have-calibrated-this-arm`. There is nobody to type the CLI's
"move" confirmation at boot, so the confirmation is made once, in the
unit's options, by whoever installs it after doing the calibration.

Two watchdogs:

- the controller halts a session when the camera sends no detection line
  for `watchdog_s` (1 s);
- the unit is `Type=notify` with `WatchdogSec=20`: the service reports to
  systemd every second and is killed and restarted if it stops. Tested by
  freezing the process: systemd replaced it after 20 s and it came back
  in `waiting`.

Neither cuts servo power. Only the power switch does.

## One driver at a time

The Studio and this service both send moves to the same arm agent and
neither knows about the other. The unit declares
`Conflicts=sketchbot-studio.service`: starting either one stops the other.

Which one comes up at boot is chosen with `sketchbot-mode`, which enables
one unit and disables the other. With both enabled systemd would have to
drop one at every boot and the choice would not be predictable.

    sketchbot-mode pickplace     # pick and place at boot, Studio off
    sketchbot-mode studio        # Studio at boot, pick and place off
    sketchbot-mode none          # neither
    sketchbot-mode status

The older `braccio-calibrate` and `braccio-sketch` units are in the
conflict list too. The command line tools (`pick_place_cli`, the drawing
CLI, anything that opens port 8765 itself) are not covered by any of this:
do not run them while a session is running.

## Install

On the UNO Q, with the code in `~/sketchbot-pickplace` (a separate
directory from the Studio's checkout, which is left alone):

    cd ~/sketchbot-pickplace
    bash deploy/pickplace/install.sh
    sketchbot-mode pickplace

`install.sh` needs no sudo. It makes a virtualenv that can see the system
Python packages and adds pyserial, copies the unit to
`~/.config/systemd/user/`, the options to
`~/.config/sketchbot/pickplace.env` (kept if it exists), and `sketchbot-mode`
and `pickplace-kiosk.sh` to `~/bin`. User units start at boot without a
login because lingering is on for the user (`loginctl show-user $USER -p
Linger`); the arm agent unit already relied on that.

Options are one line in `~/.config/sketchbot/pickplace.env`:

    PICKPLACE_ARGS=--bind 0.0.0.0

`--bind 0.0.0.0` serves the page to the local network. Anyone who can open
it can press Start, so use it on a trusted network only; leave it out to
serve the board's own screen alone. Add `--live
--i-have-calibrated-this-arm`, and `--autostart` if wanted, only after the
calibration. Then `systemctl --user restart sketchbot-pickplace`.

Logs: `journalctl --user -u sketchbot-pickplace -f`.

## Stop it, disable it, remove it

- Stop a session: the Stop button, or
  `curl -X POST -d '{}' http://127.0.0.1:7110/api/pickplace/stop`.
- Stop the service now: `systemctl --user stop sketchbot-pickplace`.
- Keep it from starting at boot: `sketchbot-mode studio` (back to the
  Studio) or `sketchbot-mode none`.
- Remove it:

      sketchbot-mode studio
      rm ~/.config/systemd/user/sketchbot-pickplace.service
      rm -r ~/.config/sketchbot ~/bin/sketchbot-mode ~/bin/pickplace-kiosk.sh
      systemctl --user daemon-reload
      rm -rf ~/sketchbot-pickplace

## Bricks behind the arm

The controller reaches forward: base servo 90 points at the work. On the
floor rig the bricks and bin were on the other side, where the folded
gripper points, and the owner sat in front. `arm.reach_behind: true` makes
the arm lean over its shoulder instead (`sketch_artist/mirrored_arm.py`):
shoulder, elbow, wrist and wrist roll are each sent as 180 minus the
planned angle, which is the forward pose turned half a turn about the base
axis. The controller plans in its usual frame and never knows.

The servo ends swap with it, so limits measured at the low end of the elbow
or wrist for forward reach are applied at the high end, and the low end
becomes the rest pose.

`arm.wrist_zero_deg` is the wrist servo angle at which the gripper centre
line is in line with the forearm. The zero in `workspace.yaml` was
calibrated with the pen grip, which sits at an angle on the gripper.

## Touchscreen

The page has a kiosk layout at `http://127.0.0.1:7110/?kiosk=1`: three
large buttons and the state, no log.

The UNO Q image runs Xorg with the LightDM greeter. With the screen
connected (checked on 2026-11-12: `card0-DP-1` connected, 800x480) it shows
the login prompt, because nobody is logged in and there is no automatic
login. A program started over ssh or by a user unit cannot draw on that
screen. One step needs sudo, once: log the `arduino` user in automatically.

    sudo mkdir -p /etc/lightdm/lightdm.conf.d
    printf '[Seat:*]
autologin-user=arduino
autologin-user-timeout=0
autologin-session=xfce
'       | sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf
    sudo systemctl restart lightdm

The rest is already in place for the user: `~/.config/autostart/
pickplace-kiosk.desktop` starts `~/bin/pickplace-kiosk.sh` with the desktop
session. The script exits quietly when no display is connected, waits for
the service, and opens the page full screen in chromium or firefox if one is
installed, otherwise in a small WebKitGTK viewer
(`deploy/pickplace/pickplace-kiosk.py`); the image has WebKitGTK and its
Python bindings, so no browser has to be installed. The viewer has not been
seen on the screen: there was no desktop session to try it in.

Automatic login means anyone at the screen is logged in as `arduino`; that
is the price of a kiosk. To undo it, delete the `50-autologin.conf` file
and `~/.config/autostart/pickplace-kiosk.desktop`.

Power the screen from its own supply. See the second incident.

## What was measured on 2026-11-12

Values for the floor rig are in `config/rigs/floor-rig-2026-11-12.yaml`
and are installed as `config/runtime.yaml` in the board's copy. None of
them was measured with a ruler.

Read off an overhead camera frame of the arm held level and high, jaws
closed (pixel lengths against the 125 mm forearm):

| Quantity | Value | How good |
| --- | --- | --- |
| Wrist pitch axis to fingertips | about 105 mm | plus or minus 15 mm |
| Gripper in line with the forearm at wrist servo | 90 | within about 10 degrees |
| Jaw gap at servo 10 | about 45 mm | rough |
| Jaws closed at servo | 60 | seen closed; contact angle not found |
| Holder on the outer face at wrist roll servo | 90, reaching behind | seen: display faces up |

This arm has short printed fingers. The stock length in
`config/pick_place.yaml` (147 mm to the grasp point) is too long for it,
and the 100 mm in the board's Studio settings is about right.

Not measured, and needed before live motion:

- floor height in the arm frame (`desk.z_mm`), by touch at the pick radius;
  also whether the shoulder is 82 mm (workspace.yaml) or 92 mm (the board's
  Studio settings) above the floor;
- bin wall height (110 mm is assumed);
- the split of the tool length into mount, grasp point and tip;
- everything under `camera:`: holder geometry, picture rotation and
  mirror, field of view, aim point;
- jaw gap against a brick with calipers;
- the search sweep range that the camera lead allows.

The overhead camera was not calibrated against the arm either: the base
was moved three times during the session, and the stretched poses the
calibration needs are the ones that reset the board.

## Second session, same day, after the power change

The owner put a stronger supply on the board and confirmed the motor shield
has its own wall supply; the camera was connected through a USB hub.

- After a real power cycle the service came up by itself and reached
  `ready` about a minute after boot.
- The camera sends `DET` lines at about 6 per second.
- A bent-arm reach behind the base (model: grasp point 215 mm out, 110 mm
  up), driven one joint at a time in 2 degree steps, ran 14 moves without a
  reset. The stretched level pose was not repeated.
- At that pose the overhead camera shows the gripper hanging close to
  straight down under the wrist, about 150 mm from the base axis, where the
  model has it pitched 60 degrees outward with the grasp point at 215 mm.
  That contradicts the level-frame reading in the table above (in line at
  wrist servo 90). One of the two readings is wrong, and both were made by
  eye from an uncalibrated, oblique camera. **The tool length and the wrist
  zero are therefore not established.** They need a ruler and a set square
  on the arm: forearm level, step the wrist until the claws continue the
  forearm's line, note the servo angle (`arm.wrist_zero_deg`, mirrored to
  the forward frame: 180 minus the servo angle when reaching behind), and
  measure wrist axis to claw tips.
- At that pose the gripper camera reported nothing for most frames and a
  few `white` detections at the bottom edge of the picture, which is where
  its own white fingers are. It did not report the yellow 2x4 brick that
  lay about 80 mm beyond the gripper. Whether that is the camera's aim,
  the picture rotation or the detector is not known.
- The camera's lit USB lead drapes over the forearm and elbow and off to
  one side. It moved with every joint and did not snag in this reach; it
  crosses the elbow joint and will need routing before a full sweep.
- The base heading was about 12 degrees off where the overhead estimate put
  it, toward a chair leg. The search sweep must be limited by measurement
  on the day, not from this file.

No pick was attempted. Live mode was not enabled.

## Third session: the owner's Studio tool model, reaching behind

The owner's grabber bench settings (`config/runtime.yaml` in the Studio
checkout: tool 100 mm, pitch -55, jaws 10 open and 65 closed, base height
92, pick at x 232, y -45, z 40) were used through the Studio's own
`workspace_for_tool` and inverse kinematics, mirrored to reach behind the
base where the bricks and bin are. Moves were one joint at a time, 2 degree
steps, with an overhead frame and an agent status read after each.

- The Studio's own pick and place spots are in front of the base, where the
  touchscreen, the camera lead and the USB hub lay. They were not used.
- With that model, his pick height of 40 mm at 232 mm out is the lowest the
  pose can reach (the elbow limit stops it), so z 40 is unlikely to be the
  floor in his frame.
- Three hovers at a commanded 100 to 130 mm put the claws well away from
  the commanded point in the overhead picture: about 60 mm short at base
  121 and 240 mm, and the base angle changed the picture angle by well under
  half as much as expected. Mirrored behind the base, the front-side
  calibration is not accurate enough to pick blind. Picking there needs the
  overhead camera calibrated against the arm, or steering by eye at low
  height.
- The bricks lay in one touching cluster; with 45 mm between the open jaws
  none could be gripped without hitting a neighbour. No pick was attempted.

## Incidents

**1. Gripper caught the bin, base turned (2026-11-12, about 16:05).**
During an overhead-camera calibration sweep the open gripper was inside the
bin with the fingertips commanded to 100 mm above the floor. Stepping the
base servo 70 to 85 to 100 dragged the bin and turned the arm's base about
30 degrees on the floor. The camera check halted the run two frames after
the dragging began. Nothing was damaged. Cause: no keep-out around the bin
and a margin of a few centimetres at most between the fingertips and the
rim, which arm sag and the unsettled shoulder height used up. Since then:
the bin is a keep-out volume to rim plus margin, calibration poses keep the
fingertips 150 mm up, and the forearm is checked against the commanded
pose after every move, which fails on the first frame of a base that did
not follow.

**2. Board reset under servo load, arm fell (2026-11-12, 18:00:43).** With
the arm held out level and high (forearm horizontal, about 230 mm of reach)
a ramped move lifted the wrist 20 degrees while the jaws opened, 2.5
degrees per step. The UNO Q reset: the kernel log ends with USB gadget
reconnects in the same second. The servos went limp, the arm sagged to the
floor and knocked two bricks about 40 mm. About a minute later the board
came back and the firmware drove the arm to the rest pose in one unramped
move. A touchscreen and the gripper camera had been added to the rig
shortly before. This is the brown-out that `config/workspace.yaml` warns
about under `motion`, at a smaller step than the one recorded there.

Until the servo supply is separated from the board's, or shown to hold:

- do not run the arm with anyone or anything under it;
- expect the same reset in the middle of a pick, with a brick in the jaws;
- treat the unramped move to rest at start-up as part of every power
  cycle: lift the arm to its rest pose by hand before powering up.

A reset also defeats every software stop on this page.
