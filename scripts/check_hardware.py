#!/usr/bin/env python3
"""Read-only functional harness: device discovery, camera frames and arm status."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.control import ControlApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-host", default="127.0.0.1")
    parser.add_argument("--arm-port", type=int, default=8765)
    parser.add_argument("--probe-cameras", action="store_true")
    parser.add_argument("--require-arm", action="store_true")
    parser.add_argument("--require-face", action="store_true")
    parser.add_argument("--config-dir", type=Path)
    args = parser.parse_args()
    app = ControlApp(args.arm_host, args.arm_port, config_dir=args.config_dir)
    try:
        report = app.diagnostics(probe_cameras=args.probe_cameras or args.require_face)
        report["read_only"] = True
        print(json.dumps(report, indent=2, allow_nan=False))
        failed = not report["paper"]["ok"]
        failed |= args.require_arm and not report["arm"]["connected"]
        failed |= args.require_face and report["cameras"]["face"].get("ok") is not True
        return int(failed)
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())