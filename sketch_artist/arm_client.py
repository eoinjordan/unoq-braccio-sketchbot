"""TCP client for the Braccio arm agent.

Speaks the same line protocol as the ``unoq-braccio`` project:

    ``M <base> <shoulder> <elbow> <wrist_v> <wrist_rot> <gripper>\n``  -> ``OK``
    ``S\n``                                                            -> status line

All joint values are integer degrees.
"""

from __future__ import annotations

import socket
from typing import Optional, Tuple


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
