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

    def move(self, angles: Tuple[int, int, int, int, int, int]) -> str:
        """Send an ``M`` move command and return the agent's reply."""
        base, shoulder, elbow, wv, wr, grip = angles
        return self._send(f"M {base} {shoulder} {elbow} {wv} {wr} {grip}")

    def status(self) -> str:
        """Query the current arm status line."""
        return self._send("S")
