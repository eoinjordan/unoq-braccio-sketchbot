"""Launch the sketchbot M/S bridge on top of the ``unoq_braccio_sim`` Gazebo
model, so the sketchbot pipeline draws into the real Braccio in Gazebo.

This includes ``unoq_braccio_sim``'s ``gazebo.launch.py`` (Gazebo + the Braccio
STL model + ros2_control + the ``unoq_braccio_driver`` bridges) and adds the
sketchbot's ``M``/``S`` TCP bridge. Build both packages in one ROS 2 workspace
(see README.md), then::

    ros2 launch braccio_sim sketchbot_gazebo.launch.py

and draw from the sketchbot repo::

    python -m sketch_artist.cli --image examples/sample_face_eoin.png --style none
"""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([FindPackageShare("unoq_braccio_sim"),
                                  "launch", "gazebo.launch.py"])
        ]),
    )

    bridge = Node(
        package="braccio_sim",
        executable="braccio_bridge",
        name="sketchbot_ms_bridge",
        output="screen",
        parameters=[{"port": LaunchConfiguration("port")}],
    )

    return LaunchDescription([
        DeclareLaunchArgument("port", default_value="8765",
                              description="TCP port for the sketchbot M/S protocol."),
        gazebo,
        bridge,
    ])
