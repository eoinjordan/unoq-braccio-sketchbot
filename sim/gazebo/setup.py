from glob import glob

from setuptools import setup

package_name = "braccio_sim"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/urdf", glob("urdf/*.xacro")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Edge Impulse",
    maintainer_email="hello@edgeimpulse.com",
    description="Sketchbot M/S bridge for the unoq_braccio_sim Gazebo model.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "braccio_bridge = braccio_sim.braccio_bridge:main",
            "pen_tracker = braccio_sim.pen_tracker:main",
            "ink_marker = braccio_sim.ink_marker:main",
        ],
    },
)
