# Pick and place with an overhead camera

A fixed webcam looks straight down at the floor around the arm. The arm
picks plain bricks off the floor and drops them in a bin, checking a camera
frame after every move. The code is in `sketch_artist/pickplace_overhead/`
and is independent of the Studio pick-and-place panel and of the wrist
camera work.

This page covers the rig the code was developed on, how the pieces fit, how
to run it, and what is not done.

**Status on 2026-11-12.** Detection, the dry-run plan, the camera, the
checked moves and the level-pose stage have run on the real rig. The camera
calibration against the arm and the pick itself have not: the first
calibration attempt caught the bin, the base was then moved several times,
and the board reset under servo load in a stretched pose. Both incidents
are written up in [pick-place-service.md](pick-place-service.md#incidents).
There is no measured calibration residual and no brick has been picked
with this code. Everything about calibration and picking below describes
what the code does, tested on synthetic data only.

## Rig

- TinkerKit Braccio on the UNO Q arm agent (`M`/`S` protocol on port 8765),
  standing on its printed base sheet on a wooden floor.
- A USB webcam about a metre above the floor, looking down, with the arm
  near the middle of the picture. Developed with a Razer Kiyo at 1920x1080.
- DUPLO-size bricks in yellow, red and white, and a blue parts bin.

The camera is selected by its USB id, not by index. Indexes move when a
laptop lid closes or another camera is plugged in, and index 0 is often the
laptop's own webcam.

Autofocus has to be off. When the arm rises toward the lens the camera
refocuses on it and the floor goes soft, which looks to the frame checks
like the whole scene changing. The session locks focus at a fixed value;
find it once with `rig.sweep_focus` (on the development rig: autofocus off,
`CAP_PROP_FOCUS` 55).

## How it works

    frame -> detect -> pixels -> camera model -> base-frame mm -> plan -> checked moves
                                                                    ^          |
                                                                    +-- frame after every move

**Detection** (`detect.py`). The first detector is classical colour
segmentation and is a stand-in: it finds compact blobs of brick colour and
the largest blue blob, nothing more. Colours are judged in Lab relative to
the floor, because warm wood and a yellow brick are within a few degrees of
hue of each other under indoor light. The orange arm is told from a red
brick by its yellow content. White is "bluer than the floor, neutral and
bright". Anything that implements

    detect(frame) -> list of (label, x_px, y_px, confidence)

can replace it. `Detection` is a tuple that starts with those four fields
and adds the box angle and size, which the planner uses to turn the jaws
across a brick; a detector without them leaves the defaults.

**Camera model** (`geometry.py`, `calibrate.py`). One 3x4 projection matrix
maps base-frame millimetres to pixels. It is fitted to fingertip sightings:
the arm holds its closed gripper out at a few dozen poses, all with the
fingertips at least 150 mm up, and in each frame the far end of the white
jaws is located. The same data gives the tool length, because only the
right length lets a single camera explain sightings taken at different tool
pitches. A pixel is mapped back to the base frame on the plane of the brick
tops.

Nothing in the calibration goes near the floor, the bin or the bricks. The
first version did, with a tool length taken from a configuration file, and
it caught the bin
([incident 1](pick-place-service.md#incidents)).

**Reach** (`geometry.py`). The sketchbot kinematics reach forward with a
pen. The gripper is longer, and on the development rig the bricks were
behind the base, so the arm leans over its shoulder (shoulder servo above
90): the mirror image of the forward pose. The usable tool pitch changes
with height, so each brick gets a column of poses
straight above it, every 14 mm, each at the steepest pitch the joints allow.

**Plan** (`plan.py`). For each brick: turn, hover, descend the column,
close, lift, fold into the rest posture, turn to the bin, reach over it
above the rim, open, fold, park. The whole joint-space line between
consecutive waypoints is checked against the envelope before the brick is
called reachable: joint limits, a floor guard, the bin as a keep-out prism
(footprint plus margin, up to rim plus margin), any extra keep-out
polygons, the allowed base sector and a limit on reach in front of the
base. A brick that fails is reported with the reason and not attempted.

**Checked moves** (`rig.py`, `watch.py`). Every move is validated, sent in
steps of at most 2.5 degrees with a dwell, and followed by a frame. The run
halts, leaving the arm where it is, if:

- the frame is out of focus or the camera stops;
- the outline of the white base sheet differs from the reference frame
  outside the area the arm covers (the base slid or turned);
- anything else changed in the work zone that the arm's silhouette and the
  expected spots (the brick being picked, the bin) do not explain: a hand,
  a foot, a dragged cable, a knocked bin;
- the arm agent does not answer `OK`.

After the lift the floor is checked for the brick; if it is still there the
jaws are opened at once and the grasp is retried 4 mm lower, twice at most.
After the release the bin is checked for new brick-coloured pixels.

These checks stop a run early. They are not a safety system. Keep the
shield power connector within reach and stay out of the arm's sweep.

## Run it

Stages share a state directory holding `state.json`, `session.log` and
every frame taken.

    S=output/overhead
    python -m sketch_artist.pickplace_overhead.session detect    --state $S
    python -m sketch_artist.pickplace_overhead.session level     --state $S --base 140
    python -m sketch_artist.pickplace_overhead.session calibrate --state $S
    python -m sketch_artist.pickplace_overhead.session plan      --state $S
    python -m sketch_artist.pickplace_overhead.session pick      --state $S --limit 1
    python -m sketch_artist.pickplace_overhead.session park      --state $S

Set rig values with `--set`, for example `--set arm_host='"192.168.1.63"'`,
`--set pick.bin_rim_mm=80`, `--set base_range=[60,172]`. Before the first
`calibrate`, put rough numbers for the base position, scale and heading
under `nominal` so the arm silhouette lands in the right part of the
picture; they are replaced by the fitted camera.

Do not run it while the Studio is driving the arm. Both talk to the same
agent and neither knows about the other.

## Limits and what is not done

- The colour detector needs a plain floor and plain bricks. It ignores
  shape, so a red wheel or a yellow duster is a brick to it. It is a
  placeholder for a trained detector.
- Brick tops are assumed to be at one height (`pick.brick_top_mm`).
- The floor height is taken from the arm model, not sensed. A grasp that
  closes above the brick is retried lower; nothing detects the fingertips
  touching the floor.
- No force or position feedback from the servos. A stalled joint is only
  noticed if it shows in the picture.
- The calibration poses hold the arm stretched out, which is where the
  board has reset under servo load. Do not run `calibrate` or `level` until
  the servo supply is known to hold; when it does not, the arm falls.
- The person check watches a margin around the arm's silhouette, about
  115 mm. Someone sitting beyond it does not stop a run.
- One camera gives no depth. Stacked or leaning bricks are not handled.
