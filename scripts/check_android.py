#!/usr/bin/env python3
"""Install and inspect the APK only on an explicitly selected Android emulator."""

import argparse
import json
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"emulator-\d+", args.serial):
        parser.error("This check refuses physical devices; pass an emulator serial")
    output = ROOT / "output/android-check"
    output.mkdir(parents=True, exist_ok=True)

    def adb(*arguments, binary=False):
        result = subprocess.run(["adb", "-s", args.serial, *arguments], check=True,
                                capture_output=True, text=not binary, timeout=60)
        return result.stdout

    def hierarchy():
        adb("shell", "uiautomator", "dump", "/sdcard/sketchbot-ui.xml")
        xml = adb("shell", "cat", "/sdcard/sketchbot-ui.xml")
        (output / "hierarchy.xml").write_text(xml)
        return ET.fromstring(xml)

    def tap(node):
        coordinates = [int(value) for value in re.findall(r"\d+", node.attrib["bounds"])]
        left, top, right, bottom = coordinates
        adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))

    server = subprocess.Popen([sys.executable, str(ROOT / "web/tests/serve.py")], cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(server.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if not selector.select(max(0.01, deadline - time.monotonic())):
                    raise RuntimeError("Simulator server did not become ready")
                line = server.stdout.readline()
                if "SKETCHBOT_TEST_SERVER_READY" in line:
                    break
                if not line and server.poll() is not None:
                    raise RuntimeError("Simulator server exited before readiness")
            else:
                raise RuntimeError("Simulator startup timed out")
        with urllib.request.urlopen("http://127.0.0.1:7119/api/control/state", timeout=5) as response:
            before = json.load(response)
        print(adb("install", "-r", str(args.apk.resolve())))
        print(adb("shell", "am", "start", "-W", "-n", "com.sketchbot.studio/.StudioActivity"))
        tree = hierarchy()
        address = next(node for node in tree.iter("node") if node.get("class") == "android.widget.EditText")
        tap(address)
        adb("shell", "input", "text", "http://10.0.2.2:7119")
        tree = hierarchy()
        connect = next(node for node in tree.iter("node") if node.get("text", "").lower() == "connect")
        tap(connect)
        connected = False
        for _ in range(8):
            tree = hierarchy()
            if any("Arm connected" in node.get("text", "") or "Arm connected" in node.get("content-desc", "") for node in tree.iter("node")):
                connected = True
                break
        (output / "screen.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
        process = adb("shell", "pidof", "com.sketchbot.studio").strip()
        logs = adb("logcat", "-d", f"--pid={process}", "-s", "AndroidRuntime:E", "chromium:I")
        (output / "runtime.log").write_text(logs)
        (output / "webview.txt").write_text(adb("shell", "dumpsys", "webviewupdate"))
        if "FATAL EXCEPTION" in logs:
            raise RuntimeError("Android app crashed")
        if not connected:
            raise RuntimeError("APK did not display the simulator's connected Studio screen; see screenshot, hierarchy and WebView logs")
        with urllib.request.urlopen("http://127.0.0.1:7119/api/control/state", timeout=5) as response:
            after = json.load(response)
        if after["armed"] or after["arm"]["pose"] != before["arm"]["pose"]:
            raise RuntimeError("Connecting the app unexpectedly changed control state")
        print("PASS: signed APK installs, opens the event screen and leaves the software arm unchanged")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()