"""The drive log: the telemetry.csv that `python -m openshaker --log DIR` writes and the calibration
tools (record, replay, analyze, tm_tune, ...) read.

CSV_FIELDS and tele_row() define that file and are shared with the calibration tools, which import
them from here or through openshaker.record. A change to the columns needs both sides to agree.
"""
from __future__ import annotations

import csv
import threading
import time
from pathlib import Path

from .telemetry import Telemetry

CSV_FIELDS = (["t", "source", "seq", "active", "engine_running", "rpm", "max_rpm", "idle_rpm", "gear",
               "speed", "throttle", "brake", "clutch", "handbrake", "accel_lat", "accel_long", "accel_vert"]
              + [f"slip_ratio_{i}" for i in range(4)] + [f"slip_angle_{i}" for i in range(4)]
              + [f"susp_travel_{i}" for i in range(4)] + [f"rumble_strip_{i}" for i in range(4)]
              + [f"surface_rumble_{i}" for i in range(4)]
              + ["abs_active", "tc_active", "kerb_vib", "slip_vib", "road_vib", "abs_vib", "raw_hex"])


def tele_row(t: Telemetry, t0: float) -> list:
    b = lambda v: 1 if v else 0  # noqa: E731
    row = [f"{t.t - t0:.4f}", t.source, t.seq, b(t.active), b(t.engine_running), f"{t.rpm:.1f}", f"{t.max_rpm:.0f}",
           f"{t.idle_rpm:.0f}", t.gear, f"{t.speed:.3f}", f"{t.throttle:.3f}", f"{t.brake:.3f}", f"{t.clutch:.3f}",
           f"{t.handbrake:.3f}", f"{t.accel_lat:.3f}", f"{t.accel_long:.3f}", f"{t.accel_vert:.3f}"]
    row += [f"{v:.4f}" for v in t.slip_ratio] + [f"{v:.4f}" for v in t.slip_angle]
    row += [f"{v:.4f}" for v in t.susp_travel] + [b(v) for v in t.rumble_strip] + [f"{v:.3f}" for v in t.surface_rumble]
    row += [b(t.abs_active), b(t.tc_active), f"{t.kerb_vib:.3f}", f"{t.slip_vib:.3f}", f"{t.road_vib:.3f}",
            f"{t.abs_vib:.3f}", t.raw.hex() if t.raw else ""]
    return row


class TelemetryLog:
    """Every frame in memory, written out by the caller at the end (the calibration tools' recorders)."""

    def __init__(self) -> None:
        self.rows: list[Telemetry] = []
        self.lock = threading.Lock()

    def __call__(self, tele: Telemetry) -> None:
        with self.lock:
            self.rows.append(tele)

    def __len__(self) -> int:
        with self.lock:
            return len(self.rows)


class DriveLogWriter:
    """Streams frames into telemetry.csv while the drive runs, so a killed run keeps what it had.

    Times in the file count from t0, the moment the audio starts (ours.wav's first sample). Sources
    start a moment earlier, so frames that arrive before begin(t0) are held and written by it.
    Afterwards each frame is written as it arrives and the file is flushed about once a second.
    """

    FLUSH_S = 1.0

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self.frames = 0
        self.by_source: dict[str, int] = {}
        self._t0: float | None = None
        self._pending: list[Telemetry] = []
        self._f = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(CSV_FIELDS)
        self._f.flush()
        self._flushed = time.monotonic()

    def __call__(self, tele: Telemetry) -> None:
        with self.lock:
            if self._f is None:
                return
            self.frames += 1
            self.by_source[tele.source] = self.by_source.get(tele.source, 0) + 1
            if self._t0 is None:
                self._pending.append(tele)
                return
            self._w.writerow(tele_row(tele, self._t0))
            now = time.monotonic()
            if now - self._flushed >= self.FLUSH_S:
                self._f.flush()
                self._flushed = now

    def __len__(self) -> int:
        with self.lock:
            return self.frames

    def counts(self) -> dict:
        """Frames per source so far."""
        with self.lock:
            return dict(self.by_source)

    def begin(self, t0: float) -> None:
        with self.lock:
            self._t0 = t0
            self._write_pending()

    def _write_pending(self) -> None:
        for tele in self._pending:
            self._w.writerow(tele_row(tele, self._t0))
        self._pending.clear()
        self._f.flush()
        self._flushed = time.monotonic()

    def close(self) -> None:
        with self.lock:
            if self._f is None:
                return
            if self._pending:                      # stopped before the audio ever started
                self._t0 = self._pending[0].t if self._t0 is None else self._t0
                self._write_pending()
            self._f.close()
            self._f = None
