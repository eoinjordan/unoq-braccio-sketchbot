#!/usr/bin/env bash
# Bring the sketchbot arm agent up after boot. The App Lab daemon on :8800 has
# to be answering first, and the arm should already be parked at the firmware
# rest pose (see README.md) so that boot moves nothing.
for _ in $(seq 1 60); do
    (echo > /dev/tcp/127.0.0.1/8800) >/dev/null 2>&1 && break
    sleep 2
done
exec /usr/bin/arduino-app-cli app start "$HOME/ArduinoApps/braccio_remote_agent"
