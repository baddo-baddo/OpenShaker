"""Source base classes: a background thread publishes Telemetry frames thread-safely."""
from __future__ import annotations

import math
import socket
import threading
import time
from typing import Optional

from ..telemetry import Telemetry


class Source:
    name = "source"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[Telemetry] = None
        self._seq = 0
        self.frames = 0
        self._fps_frames = 0
        self._fps_t = time.perf_counter()
        self.fps = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self.status = "starting"
        self.listeners: list = []      # callables receiving every published frame (recorders)

    # -- publishing -------------------------------------------------------
    def publish(self, tele: Telemetry) -> None:
        now = time.perf_counter()
        with self._lock:
            self._seq += 1
            tele.seq = self._seq
            tele.t = now
            tele.source = self.name
            self._latest = tele
            self.frames += 1
            self._fps_frames += 1
            if now - self._fps_t >= 1.0:
                self.fps = self._fps_frames / (now - self._fps_t)
                self._fps_frames = 0
                self._fps_t = now
        for cb in self.listeners:
            cb(tele)

    def latest(self) -> Optional[Telemetry]:
        with self._lock:
            return self._latest

    def age(self) -> float:
        tele = self.latest()
        return math.inf if tele is None else time.perf_counter() - tele.t

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_safe, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)

    def stopping(self) -> bool:
        return self._stop.is_set()

    def _run_safe(self) -> None:
        try:
            self.run()
        except Exception as exc:  # keep the app alive, surface the error
            self.error = f"{type(exc).__name__}: {exc}"
            self.status = "error"

    def run(self) -> None:
        raise NotImplementedError


class UDPSource(Source):
    """Binds a UDP port and hands every datagram to parse()."""

    def __init__(self, port: int, host: str = "127.0.0.1", bufsize: int = 4096) -> None:
        super().__init__()
        self.port = port
        self.host = host
        self.bufsize = bufsize
        self.packets = 0
        self.last_len = 0
        self.malformed = 0              # packets parse() choked on

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))
        except OSError as exc:
            self.error = (f"cannot bind UDP {self.port} ({exc.strerror or exc}); "
                          f"is HaptiConnect or another tool using it?")
            self.status = "error"
            sock.close()
            return
        sock.settimeout(0.5)
        self.status = f"listening on UDP {self.port}"
        try:
            while not self.stopping():
                try:
                    data, _ = sock.recvfrom(self.bufsize)
                except socket.timeout:
                    continue
                self.packets += 1
                self.last_len = len(data)
                try:
                    tele = self.parse(data)
                except Exception:            # a malformed packet must never take the source down
                    self.malformed += 1
                    continue
                if tele is not None:
                    tele.raw = data
                    self.publish(tele)
        finally:
            sock.close()

    def parse(self, data: bytes) -> Optional[Telemetry]:
        raise NotImplementedError
