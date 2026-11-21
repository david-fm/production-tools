"""Utilidades de test: cliente del motor con lectura con timeout (un cuelgue no bloquea el CI)."""

from __future__ import annotations

import json
import queue
import subprocess
import tempfile
import sys
import threading
from typing import Any


class EngineClient:
    def __init__(self, argv: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        self._err = tempfile.TemporaryFile()  # stderr del motor, visible si hay timeout
        self.proc = subprocess.Popen(
            argv or [sys.executable, "-m", "audio_enhancer_engine"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._err,
            env=env,
        )
        self._lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(b"")  # EOF

    def send_raw(self, data: bytes) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def send(self, payload: Any) -> None:
        self.send_raw(json.dumps(payload).encode() + b"\n")

    def recv(self, timeout: float = 10) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self._err.seek(0)
            raise AssertionError(f"timeout esperando al motor; stderr:\n{self._err.read().decode(errors='replace')[-3000:]}") from None
        assert line, "el motor cerró stdout"
        return json.loads(line)

    def rpc(self, payload: dict[str, Any], timeout: float = 10) -> dict[str, Any]:
        self.send(payload)
        return self.recv(timeout)

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=5)
