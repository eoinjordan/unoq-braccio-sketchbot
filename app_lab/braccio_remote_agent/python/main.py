"""Braccio remote agent (Linux side) for Arduino App Lab.

Opens a TCP server on :8765 speaking the sketchbot's M/S protocol and calls the
MCU sketch's ``move_braccio`` Bridge function to drive the servos:

    M <base> <shoulder> <elbow> <wrist_vertical> <wrist_rotation> <gripper>  -> OK
    S                                                                        -> STAT ...
"""

from arduino.app_utils import App, Bridge
import socket
import time


HOST = "0.0.0.0"
PORT = 8765
START_TIME = time.monotonic()
move_count = 0
last_move_ms = 0
last_command_ms = 0
last_target = [90, 45, 180, 180, 90, 10]


def handle_command(command):
    global move_count, last_move_ms, last_command_ms, last_target

    parts = command.strip().split()
    if len(parts) == 1 and parts[0] == "S":
        uptime_ms = int((time.monotonic() - START_TIME) * 1000)
        target = ",".join(str(value) for value in last_target)
        return (
            f"STAT uptime_ms={uptime_ms} move_count={move_count} "
            f"last_move_ms={last_move_ms} last_command_ms={last_command_ms} "
            f"target={target}"
        )

    if len(parts) != 7 or parts[0] != "M":
        return "ERR"

    try:
        # float(): the sketchbot streams tenths of a degree, because a whole
        # degree moves the pen ~3 mm at the paper. Whole-degree senders still
        # parse fine.
        values = [float(value) for value in parts[1:]]
    except ValueError:
        return "ERR"

    start = time.monotonic()
    result = Bridge.call("move_braccio", *values)
    last_move_ms = int((time.monotonic() - start) * 1000)
    last_command_ms = int((time.monotonic() - START_TIME) * 1000)
    move_count += 1
    last_target = values
    return "OK" if result is None or result is True else str(result)


def loop():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        server.settimeout(1.0)
        print(f"Braccio remote agent listening on {PORT}")

        while True:
            try:
                client, address = server.accept()
            except socket.timeout:
                time.sleep(0.05)
                continue

            # Keep the connection open and process every newline-delimited
            # command: the sketchbot streams all its moves over one socket, so
            # closing after the first (the old behaviour) broke the pipe on
            # move #2.
            with client:
                client.settimeout(30.0)
                buffer = ""
                while True:
                    try:
                        chunk = client.recv(256)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buffer += chunk.decode("ascii", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line.strip():
                            continue
                        response = handle_command(line)
                        try:
                            client.sendall((response + "\n").encode("ascii"))
                        except OSError:
                            break
                        print(f"{address[0]}: {line.strip()} -> {response}")


App.run(user_loop=loop)
