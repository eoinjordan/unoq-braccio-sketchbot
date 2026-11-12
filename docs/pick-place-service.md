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

The UNO Q image runs Xorg with the LightDM greeter and has no browser
installed, and there is no automatic login, so a full-screen page at boot
needs three things done with sudo, once:

    sudo apt install chromium
    sudo mkdir -p /etc/lightdm/lightdm.conf.d
    printf '[Seat:*]\nautologin-user=arduino\nautologin-user-timeout=0\n' \
      | sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf
    mkdir -p ~/.config/autostart
    cp ~/sketchbot-pickplace/deploy/pickplace/pickplace-kiosk.desktop ~/.config/autostart/

`~/bin/pickplace-kiosk.sh` (installed already) exits quietly when no
display is connected, waits for the service, and opens the first browser it
finds full screen. The board's video output is DisplayPort over USB-C
(`/sys/class/drm/card0-DP-1`); an HDMI screen needs a USB-C adapter or hub
that carries DisplayPort. On 2026-11-12 that connector read `disconnected`
with the screen lying next to the arm, so none of this was tried on the
screen. Automatic login means anyone at the screen is logged in as
`arduino`; that is the price of a kiosk.

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
