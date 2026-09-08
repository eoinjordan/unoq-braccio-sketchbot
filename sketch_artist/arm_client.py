"""TCP client for the Braccio arm agent.

Speaks the same line protocol as the ``unoq-braccio`` project:

    ``M <base> <shoulder> <elbow> <wrist_v> <wrist_rot> <gripper>\n``  -> ``OK``
    ``S\n``                                                            -> status line

Joint values carry fractional degrees (see sketch_artist.kinematics).
"""

from __future__ import annotations

import re
import socket
import time
from typing import Optional, Sequence, Tuple


class ArmClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765,
                 timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), self.timeout)
        self._sock.settimeout(self.timeout)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "ArmClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _send(self, line: str) -> str:
        if self._sock is None:
            raise RuntimeError("ArmClient is not connected; call connect() first")
        self._sock.sendall((line.strip() + "\n").encode("ascii"))
        return self._recv_line()

    def _recv_line(self) -> str:
        assert self._sock is not None
        buf = bytearray()
        while b"\n" not in buf:
            chunk = self._sock.recv(64)
            if not chunk:
                break
            buf.extend(chunk)
        return buf.decode("ascii", errors="replace").strip()

    def move(self, angles: Tuple[float, float, float, float, float, float]) -> str:
        """Send an ``M`` move command and return the agent's reply.

        Angles go out with fractional degrees when they have them (``%g`` drops
        a trailing ``.0``), because whole degrees are ~3 mm at the paper and
        far too coarse to draw a face. Agents parse with ``float()``.
        """
        return self._send("M " + " ".join(f"{float(a):g}" for a in angles))

    def status(self) -> str:
        """Query the current arm status line."""
        return self._send("S")

    def status_angles(self) -> Optional[Tuple[float, ...]]:
        """Six servo angles parsed out of the ``S`` reply, or None.

        Agents disagree on the wording: the software simulator and the Gazebo
        bridge answer ``S 90 90 ...`` while the UNO Q agent answers
        ``STAT uptime_ms=... target=90,45,180,180,90,10``. Both are accepted.
        """
        try:
            reply = self.status()
        except (OSError, RuntimeError):
            return None
        match = re.search(r"target=([-\d.,]+)", reply)
        parts = match.group(1).split(",") if match else reply.split()[1:]
        try:
            values = tuple(float(v) for v in parts[:6])
        except ValueError:
            return None
        return values if len(values) == 6 else None

    def move_ramped(self, angles: Sequence[float], max_step_deg: float = 5.0,
                    dwell_s: float = 0.04) -> None:
        """Move to ``angles`` in bounded steps from wherever the arm is now.

        One command that swings every joint at once pulls all six servos to
        full torque together. On a Braccio powered through the board that
        current spike browns the board out and hard-resets it mid-draw -- the
        first move, from the rest pose to the paper, is the worst offender.
        Splitting it keeps the peak draw down.

        Falls back to a single move when the agent will not report its pose.
        """
        target = tuple(float(a) for a in angles)
        current = self.status_angles()
        if current is None:
            self.move(target)
            return
        span = max(abs(t - c) for t, c in zip(target, current))
        steps = int(span / max(0.1, max_step_deg)) + 1
        for i in range(1, steps + 1):
            f = i / steps
            self.move(tuple(c + (t - c) * f for c, t in zip(current, target)))
            if i < steps:
                time.sleep(dwell_s)


def move_to_pose(angles, host: str = "127.0.0.1", port: int = 8765,
                 timeout: float = 3.0) -> bool:
    """Best-effort: move the arm to a 6-servo pose. Returns False (without
    raising) if the arm agent is unreachable, so camera-aiming is optional."""
    try:
        with ArmClient(host=host, port=port, timeout=timeout) as arm:
            arm.move(tuple(int(a) for a in angles))
        return True
    except OSError:
        return False
