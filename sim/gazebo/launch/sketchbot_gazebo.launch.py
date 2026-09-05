"""Gazebo + the Braccio + the sketchbot M/S bridge, so the unchanged sketchbot
pipeline draws into the simulated arm.

    ros2 launch braccio_sim sketchbot_gazebo.launch.py                 # with GUI
    ros2 launch braccio_sim sketchbot_gazebo.launch.py headless:=true  # CI / tests

then, from the sketchbot repo::

    python -m sketch_artist.cli --image examples/sample_face_eoin.png --style none

This composes the stack itself rather than including ``unoq_braccio_sim``'s
``gazebo.launch.py``, for three reasons:

* that launch hard-codes ``gz_args``, so there is no way to run headless, which
  the end-to-end test needs;
* it starts ``joint_state_simulator``, which publishes *commanded* angles onto
  ``/joint_states`` in competition with the ``joint_state_broadcaster``
  publishing the real physics state - fine for an RViz-only preview, but it
  makes anything that measures the arm (the pen tracker, ``S`` replies)
  unreliable;
* the model needs the corrected joint zeros in
  ``urdf/braccio_sketchbot.urdf.xacro`` (see the note at the top of that file).

The arm meshes still come from ``unoq_braccio_sim`` and the servo mapping still
comes from ``unoq_braccio_driver``, so there is one source of truth for both.
The printed pencil grip comes straight out of ``hardware/pencil-grip`` in this
repo - the same STL that gets sliced and printed - so the arm on screen is
carrying the part that is actually on the robot.

With the GUI up it also runs ``ink_marker``, which paints the pen's path onto
the paper as it is drawn (``ink:=false`` to turn that off). It is skipped
headless, because gz markers are served by the GUI process and do not exist
without it.
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

# hardware/pencil-grip holds the printed parts. It is not inside the braccio_sim
# ROS package, so it has no ament share dir to look up - find it from this
# launch file's REAL path instead. The workspace is built with
# `colcon build --symlink-install` (scripts/run_gazebo_e2e.sh does the same), so
# the installed launch file is a symlink chain back into the repo and realpath()
# lands in sim/gazebo/launch, three levels below the repo root.
REPO_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "..", "..", ".."))
DEFAULT_GRIP_MESH_DIR = os.path.join(REPO_ROOT, "hardware", "pencil-grip")

ARGUMENTS = [
    DeclareLaunchArgument("headless", default_value="false",
                         description="Run Gazebo without its GUI (for tests/CI)."),
    DeclareLaunchArgument("port", default_value="8765",
                         description="TCP port for the sketchbot M/S protocol."),
    DeclareLaunchArgument("host", default_value="127.0.0.1",
                         description="Bind address for the M/S server."),
    DeclareLaunchArgument("position_tolerance", default_value="0.15",
                          description="Degrees within which the bridge calls a "
                                      "move arrived (~0.45 mm at the paper)."),
    DeclareLaunchArgument("move_time", default_value="0.25",
                         description="Seconds the arm is given to reach each point."),
    DeclareLaunchArgument("command_mode", default_value="trajectory",
                         description="'trajectory' (fast, direct) or 'joint_state' "
                                     "(via unoq_braccio_driver, 2 s per point)."),
    DeclareLaunchArgument("wait_for_motion", default_value="true",
                         description="Answer OK only once the arm has arrived."),
    DeclareLaunchArgument("wrist_pen", default_value="0.174",
                         description="Wrist axis to pen tip, metres."),
    # Pen-down threshold, matching config/workspace.yaml pen.down_z_mm / up_z_mm.
    DeclareLaunchArgument("pen_down_z", default_value="2.0"),
    DeclareLaunchArgument("pen_up_z", default_value="8.0"),
    DeclareLaunchArgument("paper_origin_x", default_value="0.155"),
    DeclareLaunchArgument("paper_origin_y", default_value="-0.040"),
    DeclareLaunchArgument("paper_width", default_value="0.040"),
    DeclareLaunchArgument("paper_height", default_value="0.040"),
    DeclareLaunchArgument("grip_mesh_dir", default_value="",
                         description="Directory holding the printed grip STLs; "
                                     "defaults to <repo>/hardware/pencil-grip."),
    DeclareLaunchArgument("grip_mesh", default_value="braccio_pen_finger_8mm.stl",
                         description="Which printed grip to show on the arm, e.g. "
                                     "braccio_pen_finger_10mm.stl or "
                                     "braccio_pencil_grip_8mm.stl."),
    DeclareLaunchArgument("ink", default_value="true",
                         description="Paint the pen's path onto the paper in the "
                                     "Gazebo window. Ignored when headless: gz "
                                     "markers are a GUI-process facility."),
    DeclareLaunchArgument("world", default_value="",
                         description="World file; defaults to unoq_braccio_sim's "
                                     "empty.world."),
]


def _setup(context, *args, **kwargs):
    share = get_package_share_directory("braccio_sim")
    sim_share = get_package_share_directory("unoq_braccio_sim")

    xacro_path = os.path.join(share, "urdf", "braccio_sketchbot.urdf.xacro")
    controllers_path = os.path.join(share, "config", "controllers.yaml")
    mesh_dir = os.path.join(sim_share, "meshes", "braccio_stedden")
    # The grip is a repo artifact rather than a package one - see DEFAULT_GRIP_MESH_DIR.
    # Check it here: a missing mesh is otherwise a silent gap in the render, and
    # the failure mode we care about (a plain, non-symlink install, where
    # realpath lands in the install tree) is not obvious from the Gazebo log.
    grip_mesh_dir = LaunchConfiguration("grip_mesh_dir").perform(context) \
        or DEFAULT_GRIP_MESH_DIR
    grip_mesh = LaunchConfiguration("grip_mesh").perform(context)
    if not os.path.isfile(os.path.join(grip_mesh_dir, grip_mesh)):
        raise RuntimeError(
            f"printed grip mesh not found: {os.path.join(grip_mesh_dir, grip_mesh)}. "
            "Build the workspace with 'colcon build --symlink-install' so this "
            "launch file resolves back into the repo, or pass grip_mesh_dir:=<path>.")
    world = LaunchConfiguration("world").perform(context) \
        or os.path.join(sim_share, "worlds", "empty.world")

    headless = LaunchConfiguration("headless").perform(context).lower() in (
        "true", "1", "yes")
    gz_args = f"-r -s {world}" if headless else f"-r {world}"

    # The ink markers are served by `gz sim gui`, so headless is not a case the
    # node can handle - the service simply is not there. Decide here rather than
    # starting it to have it disable itself, so a headless e2e run has one fewer
    # process and no warning to explain.
    ink = LaunchConfiguration("ink").perform(context).lower() in (
        "true", "1", "yes") and not headless

    def arg(name):
        return LaunchConfiguration(name).perform(context)

    robot_description = {
        # Wrap as an explicit string: Jazzy otherwise tries to YAML-parse the
        # URDF that xacro prints and rejects it.
        "robot_description": ParameterValue(Command([
            "xacro ", xacro_path,
            " controllers_file:=", controllers_path,
            " mesh_dir:=", mesh_dir,
            " grip_mesh_dir:=", grip_mesh_dir,
            " grip_mesh:=", grip_mesh,
            " wrist_pen:=", arg("wrist_pen"),
            " paper_origin_x:=", arg("paper_origin_x"),
            " paper_origin_y:=", arg("paper_origin_y"),
            " paper_width:=", arg("paper_width"),
            " paper_height:=", arg("paper_height"),
        ]), value_type=str)
    }

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution(
            [FindPackageShare("ros_gz_sim"), "launch", "gz_sim.launch.py"])),
        launch_arguments={"gz_args": gz_args}.items(),
    )

    # Started with the bridge, by which time the GUI is up and advertising
    # /marker_array. It waits for the service anyway, so the timing is not
    # critical - it just keeps the log quiet.
    ink_nodes = [TimerAction(period=6.0, actions=[
        Node(package="braccio_sim", executable="ink_marker",
             name="sketchbot_ink_marker", output="screen",
             # The pen-down rule must match pen_tracker's, or the ink and the
             # measured path disagree about where a stroke starts and ends.
             parameters=[{"use_sim_time": True,
                          "pen_down_z_mm": ParameterValue(LaunchConfiguration("pen_down_z"), value_type=float),
                          "pen_up_z_mm": ParameterValue(LaunchConfiguration("pen_up_z"), value_type=float)}]),
    ])] if ink else []

    return [
        gazebo,
        # Gazebo's clock -> ROS /clock. Without it every node with
        # use_sim_time never gets a time source, and controller_manager warns
        # "No clock received" on every update.
        Node(package="ros_gz_bridge", executable="parameter_bridge",
             name="gz_clock_bridge", output="log",
             arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"]),
        Node(package="robot_state_publisher", executable="robot_state_publisher",
             # use_sim_time everywhere: with Gazebo publishing /clock, a node on
             # wall time stamps TF in a different time domain and tf2 ends up
             # with two unconnected trees.
             parameters=[robot_description, {"use_sim_time": True}],
             output="screen"),
        Node(package="ros_gz_sim", executable="create",
             arguments=["-name", "unoq_braccio", "-topic", "robot_description",
                        "-x", "0", "-y", "0", "-z", "0"],
             output="screen"),
        TimerAction(period=4.0, actions=[
            Node(package="controller_manager", executable="spawner",
                 arguments=["joint_state_broadcaster",
                            "--controller-manager", "/controller_manager"],
                 output="screen"),
            Node(package="controller_manager", executable="spawner",
                 arguments=["arm_controller",
                            "--controller-manager", "/controller_manager"],
                 output="screen"),
        ]),
        TimerAction(period=6.0, actions=[
            Node(package="braccio_sim", executable="braccio_bridge",
                 name="sketchbot_ms_bridge", output="screen",
                 parameters=[{
                     "use_sim_time": True,
                     "host": LaunchConfiguration("host"),
                     "port": LaunchConfiguration("port"),
                     "command_mode": LaunchConfiguration("command_mode"),
                     "move_time": LaunchConfiguration("move_time"),
                     "position_tolerance_deg": ParameterValue(
                         LaunchConfiguration("position_tolerance"),
                         value_type=float),
                     "wait_for_motion": LaunchConfiguration("wait_for_motion"),
                 }]),
        ]),
        # Kept for the 'joint_state' command mode, where it does the servo ->
        # radian conversion; idle otherwise.
        Node(package="unoq_braccio_driver", executable="joint_trajectory_bridge",
             name="unoq_braccio_joint_trajectory_bridge", output="log",
             condition=IfCondition(
                 _equals(LaunchConfiguration("command_mode"), "joint_state"))),
    ] + ink_nodes


def _equals(configuration, value):
    from launch.substitutions import PythonExpression
    return PythonExpression(["'", configuration, "' == '", value, "'"])


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(ARGUMENTS + [OpaqueFunction(function=_setup)])
