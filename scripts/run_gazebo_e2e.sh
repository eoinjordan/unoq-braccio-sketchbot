#!/usr/bin/env bash
# End-to-end test: the sketchbot pipeline draws into the Braccio in Gazebo, and
# the pen tip is measured to confirm the arm traced what was planned.
#
#   scripts/run_gazebo_e2e.sh                    # headless, the sample face
#   scripts/run_gazebo_e2e.sh --gui              # watch it in the Gazebo GUI
#   scripts/run_gazebo_e2e.sh --image my.png --style engineer
#
# Steps: build the ROS workspace, start Gazebo + controllers + the M/S bridge,
# record the pen tip off TF, run `python -m sketch_artist.cli` against the
# bridge exactly as it would run against the real arm, then compare what the
# simulated pen drew with what the planner asked for.
#
# Needs ROS 2 Jazzy with ros_gz_sim + gz_ros2_control, and the unoq-braccio repo
# checked out (see sim/gazebo/README.md). Set BRACCIO_WS to use a different
# workspace, UNOQ_BRACCIO to point at the sibling repo.
# ROS setup scripts reference unset variables, so -u is enabled only around
# our own code (see ros_source below).
set -eo pipefail

ros_source() {
    set +u
    # shellcheck disable=SC1090
    source "$1"
    set -u
}

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ws="${BRACCIO_WS:-$HOME/braccio_ws}"
unoq="${UNOQ_BRACCIO:-$(cd "$repo/.." && pwd)/unoq-braccio}"
ros_distro="${ROS_DISTRO:-jazzy}"
python_bin="${PYTHON:-python3}"

headless=true
image="examples/sample_face_eoin.png"
style="none"
tolerance_mm="${TOLERANCE_MM:-4.0}"
skip_build=false

while [ $# -gt 0 ]; do
    case "$1" in
        --gui) headless=false; shift ;;
        --image) image="$2"; shift 2 ;;
        --style) style="$2"; shift 2 ;;
        --tolerance) tolerance_mm="$2"; shift 2 ;;
        --skip-build) skip_build=true; shift ;;
        -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

log="$repo/output/gazebo_e2e.log"
mkdir -p "$repo/output"
: > "$log"

cleanup() {
    set +e
    [ -n "${tracker_pid:-}" ] && kill -INT "$tracker_pid" 2>/dev/null
    [ -n "${tracker_pid:-}" ] && wait "$tracker_pid" 2>/dev/null
    [ -n "${launch_pid:-}" ] && kill -INT "$launch_pid" 2>/dev/null
    sleep 2
    pkill -f "gz sim" 2>/dev/null
    pkill -f braccio_bridge 2>/dev/null
    pkill -f pen_tracker 2>/dev/null
    pkill -f ink_marker 2>/dev/null
}
trap cleanup EXIT

# A previous run that crashed leaves a gz server (and with it a live
# controller_manager) behind; the spawners then report "Controller already
# loaded ... Failed to configure controller" and nothing works.
echo "== clearing anything left over from a previous run"
cleanup
sleep 1

# ---------------------------------------------------------------------- build
if [ ! -f "/opt/ros/$ros_distro/setup.bash" ]; then
    echo "ROS 2 $ros_distro not found at /opt/ros/$ros_distro." >&2
    exit 1
fi
ros_source "/opt/ros/$ros_distro/setup.bash"

if [ "$skip_build" = false ]; then
    echo "== building the ROS workspace at $ws"
    mkdir -p "$ws/src"
    ln -sfn "$unoq/ros2_ws/src/unoq_braccio_sim" "$ws/src/unoq_braccio_sim"
    ln -sfn "$unoq/ros2_ws/src/unoq_braccio_driver" "$ws/src/unoq_braccio_driver"
    ln -sfn "$repo/sim/gazebo" "$ws/src/braccio_sim"
    (cd "$ws" && colcon build --symlink-install) >>"$log" 2>&1
fi
ros_source "$ws/install/setup.bash"

# Gazebo transport discovery uses multicast, which is unreliable on some hosts
# (WSL in particular); pinning it to loopback keeps everything talking.
export GZ_IP="${GZ_IP:-127.0.0.1}"

# ------------------------------------------------------- paper box from config
read -r paper_x paper_y paper_w paper_h pen_mm down_mm up_mm <<EOF
$(cd "$repo" && "$python_bin" -c '
from sketch_artist import config as cfg
w = cfg.load_all()["workspace"]
p, pen, links = w["paper"], w["pen"], w["links"]
# Always emit floats: ros2 param rejects an int where a double is declared.
print(*(f"{float(v):.6f}" for v in (
    p["origin_x_mm"] / 1000, p["origin_y_mm"] / 1000,
    p["width_mm"] / 1000, p["height_mm"] / 1000,
    links["wrist_pen_mm"] / 1000, pen["down_z_mm"], pen["up_z_mm"])))')
EOF
echo "== paper box ${paper_w}x${paper_h} m at (${paper_x}, ${paper_y}), pen ${pen_mm} m"

echo "== checking the paper box is reachable"
(cd "$repo" && "$python_bin" scripts/check_workspace.py)

# --------------------------------------------------------------------- launch
echo "== starting Gazebo (headless=$headless)"
ros2 launch braccio_sim sketchbot_gazebo.launch.py \
    headless:="$headless" wrist_pen:="$pen_mm" \
    paper_origin_x:="$paper_x" paper_origin_y:="$paper_y" \
    paper_width:="$paper_w" paper_height:="$paper_h" >>"$log" 2>&1 &
launch_pid=$!

echo "== waiting for the arm controller"
for _ in $(seq 1 60); do
    if ros2 control list_controllers 2>/dev/null | grep -q "arm_controller.*active"; then
        break
    fi
    sleep 2
done
ros2 control list_controllers 2>&1 | tee -a "$log"
ros2 control list_controllers 2>/dev/null | grep -q "arm_controller.*active" || {
    echo "arm_controller never became active; see $log" >&2; exit 1; }

echo "== waiting for the M/S bridge on :8765"
for _ in $(seq 1 30); do
    if "$python_bin" -c 'import socket,sys; sys.exit(0 if socket.socket().connect_ex(("127.0.0.1",8765))==0 else 1)'; then
        break
    fi
    sleep 1
done

# --------------------------------------------------------------------- record
echo "== recording the pen tip"
rm -f "$repo/output/gazebo_drawing.csv" "$repo/output/gazebo_drawing.png"
# idle_timeout_s makes the tracker write its files and exit on its own once the
# pen stops moving: `ros2 run` does not forward SIGINT to the node it spawned,
# so signalling it from here just hangs.
ros2 run braccio_sim pen_tracker --ros-args \
    -p use_sim_time:=true -p idle_timeout_s:=15.0 \
    -p out:="$repo/output/gazebo_drawing.png" \
    -p paper_origin_x_mm:="$(echo "$paper_x * 1000" | bc -l)" \
    -p paper_origin_y_mm:="$(echo "$paper_y * 1000" | bc -l)" \
    -p paper_width_mm:="$(echo "$paper_w * 1000" | bc -l)" \
    -p paper_height_mm:="$(echo "$paper_h * 1000" | bc -l)" \
    -p pen_down_z_mm:="$down_mm" -p pen_up_z_mm:="$up_mm" >>"$log" 2>&1 &
tracker_pid=$!
sleep 3

# ----------------------------------------------------------------------- draw
echo "== drawing (this streams every planned move over M/S, as on hardware)"
(cd "$repo" && "$python_bin" -m sketch_artist.cli \
    --image "$image" --style "$style" --host 127.0.0.1 --port 8765) | tee -a "$log"

echo "== waiting for the pen tracker to flush its log"
for _ in $(seq 1 40); do
    [ -f "$repo/output/gazebo_drawing.csv" ] && break
    sleep 1
done
pkill -f pen_tracker 2>/dev/null || true
tracker_pid=""
[ -f "$repo/output/gazebo_drawing.csv" ] || {
    echo "the pen tracker wrote no log; see $log" >&2; exit 1; }

# --------------------------------------------------------------------- verify
echo "== comparing the simulated pen path with the plan"
(cd "$repo" && "$python_bin" scripts/verify_gazebo_drawing.py \
    --csv output/gazebo_drawing.csv --image "$image" --style "$style" \
    --tolerance "$tolerance_mm")
