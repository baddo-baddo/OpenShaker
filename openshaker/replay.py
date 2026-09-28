"""Replay a logged real drive into HaptiConnect and record its response, for a real-lap comparison.

  python -m openshaker --source forza --log sessions/fm_drive_1
      (drive; stop)  -> sessions/fm_drive_1/telemetry.csv + ours.wav + meta.json
  python -m openshaker.replay sessions/fm_drive_1 --plugin fm --out sessions/fm_drive_1_hc
      -> sessions/fm_drive_1_hc/audio.wav (HaptiConnect's output) + telemetry.csv + meta.json

HaptiConnect must be running with its output device set, and the plugin's game at its menu (Forza
Motorsport for --plugin fm, FH5 for --plugin fh5); BeamNG needs no game.

Packets. A Forza drive log keeps every packet the game sent (the raw_hex column), and by default those are
what HaptiConnect gets: Horizon packets as they are, Motorsport packets moved into the Horizon layout its
Motorsport plugin reads (forward.horizon_from_raw). Rebuilding packets from the normalized columns
(--packets columns, and always for ACE and BeamNG) loses kerb values in old logs, the cylinder count, tyre
temperatures and the true wheel speeds. Either way HaptiConnect gets the latest packet 60 times a second
(--rate), as the replays of 2026-09-10 did, and the output folder's telemetry.csv holds every packet at
its original time, parsed with today's parser, so the offline render sees what HaptiConnect saw.

The output folder must not exist: a replay never writes over an earlier recording.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import __version__
from .calibrate import PLUGINS, game_process_running, newest_log
from .compare import load_frames
from .config import portable_path
from .forward import TelemetryForwarder, horizon_from_raw
from .record import CSV_FIELDS, LoopbackRecorder, TelemetryLog, tele_row, write_wav
from .sources.base import Source
from .sources.forza import ForzaSource

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROFILE_OF_PLUGIN = {"fm": "forza_motorsport", "fh5": "forza_horizon", "beamng": "beamng"}


class ReplaySource(Source):
    name = "replay"

    def __init__(self, frames, speed: float = 1.0) -> None:
        super().__init__()
        self.seq_frames = frames          # note: Source.frames is the published-frame counter
        self.speed = speed
        self.done = False
        self.index = 0

    def run(self) -> None:
        if not self.seq_frames:
            self.done = True
            return
        t_start = time.perf_counter()
        t0 = self.seq_frames[0].t
        for i, fr in enumerate(self.seq_frames):
            if self.stopping():
                return
            target = t_start + (fr.t - t0) / self.speed
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            self.publish(fr)          # publish() overwrites fr.t with the wall clock time, which is what we log
            self.index = i
        self.done = True


def trim(frames: list, keep_all: bool = False) -> list:
    """The driving portion: 2 s before the first active frame to 2 s after the last."""
    if keep_all:
        return frames
    act = [i for i, fr in enumerate(frames) if fr.active]
    if not act:
        return frames
    t_lo, t_hi = frames[act[0]].t - 2.0, frames[act[-1]].t + 2.0
    return [fr for fr in frames if t_lo <= fr.t <= t_hi]


def raw_frames(session: Path) -> list | None:
    """Every logged Forza packet as a frame parsed by today's parser, with Telemetry.raw = the packet in the
    Horizon layout and .t = its logged time. None when the log has no usable raw packets (ACE, BeamNG,
    Forza Sled format, or a log without raw_hex)."""
    csv.field_size_limit(10 ** 9)
    parser = ForzaSource.__new__(ForzaSource)       # parse() only: no socket
    parser.kind = "?"
    out = []
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hx = r.get("raw_hex") or ""
            if not hx:
                return None
            pkt = horizon_from_raw(bytes.fromhex(hx))
            if pkt is None:
                return None
            tele = parser.parse(pkt)
            if tele is None:
                return None
            tele.t = float(r["t"])
            tele.raw = pkt
            out.append(tele)
    return out or None


# ------------------------------------------------------------------ Assetto Corsa EVO via shared memory
# HaptiConnect's "Assetto Corsa Evo" plugin listens while assettocorsaevo.exe runs and reads the ACC-style
# maps Local\acpmf_physics / _graphics / _static. ACE itself now publishes Local\acevo_pmf_* instead, which
# is why that plugin stopped working. With ACE at its menu (so the plugin is active) this replay creates the
# acpmf maps and plays a drive into them: its physics pages byte for byte from a <drive>_raw capture folder, or
# rebuilt from the drive's telemetry.csv. The physics layout (800 bytes) is the one sources/ace.py reads.
ACE_SHM = {"game": "Assetto Corsa Evo", "process": "assettocorsaevo",
           "physics": "Local\\acpmf_physics", "graphics": "Local\\acpmf_graphics", "static": "Local\\acpmf_static"}
ACE_PHYS_BYTES = 800
ACE_TYRE_RADIUS_M = 0.31          # measured on ace_drive_3: wheel angular speed 192 rad/s at 59.2 m/s
ACE_SM_VERSION = "1.9"            # what every reference so far was recorded with (see ace_static_page)
ACE_WHEEL_SLIP_PER_SLIP = 7.5     # measured on ace_drive_3: wheelSlip ~ 7.2-7.6 x hypot(slipRatio, slipAngle)
# ACC SPageFileStatic offsets (pack 4, wchar_t strings)
STATIC_OFF = dict(smVersion=0, acVersion=30, numberOfSessions=60, numCars=64, carModel=68, track=134,
                  playerName=200, playerSurname=266, playerNick=332, sectorCount=400, maxTorque=404, maxPower=408,
                  maxRpm=412, maxFuel=416, suspensionMaxTravel=420, tyreRadius=436)


def _put_wstr(buf: bytearray, off: int, text: str, chars: int) -> None:
    raw = text.encode("utf-16-le")[: 2 * (chars - 1)]
    buf[off:off + 2 * chars] = raw.ljust(2 * chars, b"\0")


def ace_static_page(max_rpm: float, susp_max_travel_m: float = 0.08, tyre_radius_m: float = ACE_TYRE_RADIUS_M,
                    sm_version: str = ACE_SM_VERSION) -> bytes:
    """The ACC-layout static page HaptiConnect's Assetto plugins read.

    `sm_version` is what goes into smVersion/acVersion. "1.9" is Assetto Corsa Competizione's own version
    string, and HaptiConnect's Competizione plugin carries it too: recordings made with it hold TWO
    renderings of every effect (its Evo and Competizione plugins both read Local\\acpmf_*). Another value
    should leave only the Evo plugin, which gates on the ACE process instead (see --ace-sm-version).
    """
    b = bytearray(4096)
    o = STATIC_OFF
    _put_wstr(b, o["smVersion"], sm_version, 15)
    _put_wstr(b, o["acVersion"], sm_version, 15)
    struct.pack_into("<2i", b, o["numberOfSessions"], 1, 1)
    _put_wstr(b, o["carModel"], "openshaker_replay", 33)
    _put_wstr(b, o["track"], "replay", 33)
    struct.pack_into("<i3f", b, o["sectorCount"], 3, 500.0, 400.0, 0.0)
    struct.pack_into("<i", b, o["maxRpm"], int(max_rpm))
    struct.pack_into("<f", b, o["maxFuel"], 100.0)
    struct.pack_into("<4f", b, o["suspensionMaxTravel"], *([susp_max_travel_m] * 4))
    struct.pack_into("<4f", b, o["tyreRadius"], *([tyre_radius_m] * 4))
    return bytes(b)


def ace_graphics_page(packet_id: int, live: bool) -> bytes:
    b = bytearray(8192)
    struct.pack_into("<3i", b, 0, packet_id, 2 if live else 0, 0)    # packetId, status (AC_LIVE = 2), session
    return bytes(b)


def ace_slip_raw(norm: float, angle: bool) -> float:
    """Undo sources/ace.py's normalization (slip angle / 0.20; slip ratio re-zeroed at 0.05, / 0.15)."""
    if angle:
        return norm * 0.20
    return norm * 0.15 + 0.05 if norm > 0 else norm * 0.15


def ace_physics_page(row: dict, packet_id: int, logged_scale_m: float, template: bytes | None = None) -> bytes:
    """An 800-byte ACE/ACC physics page rebuilt from one drive-log row (the CSV has no raw ACE memory).
    Fields the log does not hold (tyre loads, temperatures, pressures...) come from `template`."""
    from .sources.ace import OFF
    b = bytearray(template[:ACE_PHYS_BYTES] if template else bytes(ACE_PHYS_BYTES))
    f = lambda k: float(row.get(k) or 0.0)                                                 # noqa: E731
    speed = f("speed")
    sr = [ace_slip_raw(f(f"slip_ratio_{i}"), False) if speed > 1.0 else 0.0 for i in range(4)]
    sa = [ace_slip_raw(f(f"slip_angle_{i}"), True) if speed > 1.0 else 0.0 for i in range(4)]
    struct.pack_into("<i2f", b, OFF["packetId"], packet_id, f("throttle"), f("brake"))
    struct.pack_into("<2i", b, OFF["gear"], int(float(row.get("gear") or 0)) + 1, int(f("rpm")))
    struct.pack_into("<f", b, OFF["speedKmh"], speed * 3.6)
    struct.pack_into("<3f", b, 32, 0.0, 0.0, speed)                                        # velocity
    struct.pack_into("<3f", b, OFF["accG"], f("accel_lat") / 9.81, f("accel_vert") / 9.81, f("accel_long") / 9.81)
    struct.pack_into("<4f", b, OFF["wheelSlip"],
                     *[ACE_WHEEL_SLIP_PER_SLIP * (sr[i] ** 2 + sa[i] ** 2) ** 0.5 for i in range(4)])
    struct.pack_into("<4f", b, OFF["wheelAngularSpeed"],
                     *[speed * (1.0 + sr[i]) / ACE_TYRE_RADIUS_M for i in range(4)])
    struct.pack_into("<4f", b, OFF["suspensionTravel"], *[-f(f"susp_travel_{i}") * logged_scale_m for i in range(4)])
    struct.pack_into("<f", b, OFF["clutch"], f("clutch"))
    struct.pack_into("<i", b, OFF["currentMaxRpm"], int(f("max_rpm")))
    struct.pack_into("<4f", b, OFF["slipRatio"], *sr)
    struct.pack_into("<4f", b, OFF["slipAngle"], *sa)
    struct.pack_into("<2i", b, OFF["tcInAction"], int(f("tc_active")), int(f("abs_active")))
    struct.pack_into("<3i", b, OFF["ignitionOn"], 1, 0, int(f("engine_running")))
    struct.pack_into("<4f", b, OFF["kerbVibration"], f("kerb_vib"), f("slip_vib"), f("road_vib"), f("abs_vib"))
    return bytes(b)


class SharedPages:
    """Creates the acpmf maps and writes pages into them (Windows named file mappings)."""

    def __init__(self, names: dict, sizes: dict) -> None:
        import ctypes
        import ctypes.wintypes as wt
        self._c = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileMappingW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
        k32.CreateFileMappingW.restype = wt.HANDLE
        k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        self._k32 = k32
        self.views, self.handles, self.sizes = {}, {}, sizes
        for key, name in names.items():
            h = k32.CreateFileMappingW(wt.HANDLE(-1), None, 0x04, 0, sizes[key], name)   # PAGE_READWRITE
            if not h:
                raise OSError(f"cannot create {name} (error {ctypes.get_last_error()})")
            existed = ctypes.get_last_error() == 183                                     # ERROR_ALREADY_EXISTS
            v = k32.MapViewOfFile(h, 0x0002, 0, 0, sizes[key])                              # FILE_MAP_WRITE
            self.handles[key], self.views[key] = h, v
            if existed and key == "physics":
                # HaptiConnect keeps the map of an earlier replay open, so it outlives that replay: reuse it,
                # unless something is still writing into it (a game publishing the same name)
                first = ctypes.string_at(v, 4)
                time.sleep(0.3)
                if ctypes.string_at(v, 4) != first:
                    self.close()
                    raise OSError(f"{name} is being written by another program (a game?)")

    def write(self, key: str, data: bytes) -> None:
        n = min(len(data), self.sizes[key])
        self._c.memmove(self.views[key], data, n)

    def close(self) -> None:
        for v in self.views.values():
            self._k32.UnmapViewOfFile(v)
        for h in self.handles.values():
            self._k32.CloseHandle(h)
        self.views, self.handles = {}, {}


def ace_drive_rows(session: Path) -> list[dict]:
    csv.field_size_limit(10 ** 9)
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ace_logged_scale(session: Path) -> float:
    try:
        meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
        if meta.get("ace_susp_scale_m"):
            return float(meta["ace_susp_scale_m"])
    except (OSError, ValueError):
        pass
    return 0.05                               # ACE drives logged before meta.json recorded it


ACE_MODES = ("raw log", "raw capture", "rebuilt")


def ace_timeline(session: Path, packets: str = "auto", keep_all: bool = False):
    """(pages, max rpm, mode) for replay --plugin ace; pages are [(t, physics page, live)].

    Sources, best first: "raw log" (ACE logs since 2026-09-18 keep the game's own physics page in raw_hex),
    "raw capture" (a <drive>_raw folder next to the drive holding pages.npz, the game's physics pages captured
    while it was driven, possibly only part of the drive), "rebuilt" (pages rebuilt from the log's columns). packets: "auto" takes the best available,
    "raw" the best raw source (mode None when there is none), "columns" always rebuilds. The log is trimmed to
    2 s around the driving unless keep_all."""
    rows = ace_drive_rows(session)
    if not keep_all:
        act = [i for i, r in enumerate(rows) if r["active"] == "1"]
        if act:
            lo, hi = float(rows[act[0]]["t"]) - 2.0, float(rows[act[-1]]["t"]) + 2.0
            rows = [r for r in rows if lo <= float(r["t"]) <= hi]
    capture = session.with_name(session.name + "_raw") / "pages.npz"
    if packets in ("auto", "raw"):
        hexes = [r.get("raw_hex") or "" for r in rows]
        if rows and all(len(h) == 2 * ACE_PHYS_BYTES for h in hexes):
            pages = [(float(r["t"]), bytes.fromhex(h), r["active"] == "1") for r, h in zip(rows, hexes)]
            return pages, max(struct.unpack_from("<i", p, 588)[0] for _, p, _ in pages) or 8000, "raw log"
        if capture.exists():
            import numpy as np_
            z = np_.load(capture)
            t, phys, gt, gfx = z["t"], z["phys"], z["gfx_t"], z["gfx"]
            status = [int.from_bytes(g[4:8].tobytes(), "little") for g in gfx]
            pages = []
            for i in range(len(t)):
                j = int(np_.searchsorted(gt, t[i], side="right")) - 1
                live = status[j] == 2 if 0 <= j < len(status) else True
                pages.append((float(t[i]), phys[i, :ACE_PHYS_BYTES].tobytes(), live))
            return pages, max(struct.unpack_from("<i", p, 588)[0] for _, p, _ in pages) or 8000, "raw capture"
        if packets == "raw":
            return [], 0, None
    scale = ace_logged_scale(session)
    template = None
    if capture.exists():                       # constants (tyre loads, temperatures) from this drive's own capture
        import numpy as np_
        z = np_.load(capture)
        spd = [struct.unpack_from("<f", p.tobytes(), 28)[0] for p in z["phys"]]
        template = z["phys"][int(np_.argmax(np_.array(spd) > 20))][:ACE_PHYS_BYTES].tobytes()
    pages = [(float(r["t"]), ace_physics_page(r, k + 1, scale, template), r["active"] == "1") for k, r in enumerate(rows)]
    max_rpm = max((float(r["max_rpm"]) for r in rows), default=8000.0)
    return pages, max_rpm, "rebuilt"


def replay_ace(args, session: Path, out: Path) -> int:
    from . import config
    from .sources.ace import parse_physics
    pages, max_rpm, mode = ace_timeline(session, args.packets, args.all)
    if mode is None:
        print(f"no raw ACE pages for {session.name}: neither raw_hex in its log nor a capture at "
              f"{session.name}_raw/pages.npz (physics pages captured while driving); use --packets columns")
        return 1
    if not pages:
        print("nothing to replay")
        return 1
    raw_dir = session.with_name(session.name + "_raw") if mode == "raw capture" else None
    if not game_process_running(ACE_SHM["process"]):
        print("Assetto Corsa EVO is not running; HaptiConnect's ACE plugin only listens while it is (menu is enough).")
        return 1
    scale_now = float(config.load(None)["sources"]["ace"]["susp_scale_m"])
    try:
        shm = SharedPages({k: ACE_SHM[k] for k in ("physics", "graphics", "static")},
                          {"physics": 4096, "graphics": 8192, "static": 4096})
    except OSError as exc:
        print(f"refused: {exc}")
        return 1
    out.mkdir(parents=True)
    shm.write("static", ace_static_page(max_rpm, 2 * ace_logged_scale(session), sm_version=args.ace_sm_version))
    shm.write("graphics", ace_graphics_page(0, False))
    dur = pages[-1][0] - pages[0][0]
    print(f"replaying {len(pages)} {mode} ACE physics pages ({dur:.1f} s) into {ACE_SHM['physics']} for HaptiConnect's "
          f"{ACE_SHM['game']} plugin; recording {args.device}")
    rec = LoopbackRecorder(args.device)
    rec.start()
    time.sleep(1.0)                           # let the plugin see a live-but-idle memory first
    rows_out = []
    t_start, t0 = time.perf_counter(), pages[0][0]
    gfx_id = 0
    try:
        for i, (t, page, live) in enumerate(pages):
            delay = t_start + (t - t0) / args.speed - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            shm.write("physics", page)
            if i % 5 == 0:
                gfx_id += 1
                shm.write("graphics", ace_graphics_page(gfx_id, live))
            tele = parse_physics(page, True, scale_now, max_rpm)
            tele.active = live and (tele.engine_running or tele.rpm > 0 or tele.speed > 0.5)
            tele.t, tele.seq, tele.source = time.perf_counter(), i + 1, "replay_ace"
            rows_out.append(tele)
            if i % 400 == 0:
                sys.stdout.write(f"\r  {t - t0:6.1f}/{dur:6.1f} s  HaptiConnect out "
                                 f"{20 * np.log10(max(rec.peak, 1e-6)):6.1f} dBFS".ljust(70))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\ninterrupted")
    print()
    shm.write("graphics", ace_graphics_page(gfx_id + 1, False))
    time.sleep(1.0)
    rec.stop()
    shm.close()
    if rec.error or rec.t0 is None:
        print("audio capture failed:", rec.error)
        return 1
    audio = rec.audio()
    write_wav(out / "audio.wav", audio, rec.sr)
    with (out / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for tele in rows_out:
            w.writerow(tele_row(tele, rec.t0))
    peak = 20 * np.log10(max(float(np.max(np.abs(audio))), 1e-6))
    (out / "meta.json").write_text(json.dumps({
        "note": f"HaptiConnect {ACE_SHM['game']} plugin (shared memory) response to the ACE drive {session.name}",
        "replayed_from": portable_path(session), "plugin": "ace", "fmt": "acpmf", "packets": mode,
        "raw_capture": portable_path(raw_dir) if raw_dir else None, "logged_susp_scale_m": ace_logged_scale(session),
        "parsed_susp_scale_m": scale_now, "speed": args.speed, "device": rec.mic.name, "samplerate": rec.sr,
        "duration_s": round(len(audio) / rec.sr, 2), "frames": len(rows_out), "peak_dbfs": round(peak, 1),
        "version": __version__, "created": datetime.now().isoformat(timespec="seconds")}, indent=2), encoding="utf-8")
    print(f"saved {len(audio) / rec.sr:.1f} s of HaptiConnect output (peak {peak:.1f} dBFS) to {out}")
    if peak < -60:
        print("warning: silence - the ACE plugin did not react (ACE not at its menu? a different memory layout?)")
    print(f"score it:  python -m openshaker.compare {out} --profile profiles/ace/profile.json")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.replay", description="Replay a logged drive into HaptiConnect.")
    ap.add_argument("session", help="folder with telemetry.csv from a --log run")
    ap.add_argument("--plugin", choices=list(PLUGINS) + ["ace"], default="fm",
                    help="fm / fh5 / beamng: UDP plugins; ace: HaptiConnect's own ACE plugin via shared memory")
    ap.add_argument("--out", help="NEW output folder (default <session>_hc); an existing folder is refused")
    ap.add_argument("--packets", choices=("auto", "raw", "columns"), default="auto",
                    help="auto: the logged raw packets for Forza drives, rebuilt from the columns otherwise")
    ap.add_argument("--rate", type=float, default=60.0,
                    help="packets per second to HaptiConnect, the latest each time; 0 = every packet at its own time")
    ap.add_argument("--fmt", help="packet layout override for rebuilt packets (default: the plugin's)")
    ap.add_argument("--ace-sm-version", default=ACE_SM_VERSION,
                    help="--plugin ace: the smVersion/acVersion written to the static page. The default is "
                         "Competizione's own string, which makes HaptiConnect render the drive twice (its Evo and "
                         "Competizione plugins both read the same memory); another value should leave only the "
                         "Evo plugin, which gates on the ACE process")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--device", default="ButtKicker")
    ap.add_argument("--all", action="store_true", help="replay everything (default: trim to the driving portion)")
    args = ap.parse_args(argv)

    session = Path(args.session)
    out = Path(args.out) if args.out else session.with_name(session.name + "_hc")
    if out.exists():
        print(f"{out} already exists; pick a new --out (a replay never writes over an earlier recording)")
        return 1
    if args.plugin == "ace":
        return replay_ace(args, session, out)
    cfg = PLUGINS[args.plugin]
    frames = None
    if args.packets in ("auto", "raw") and cfg["fmt"] == "horizon":
        frames = raw_frames(session)
        if frames is None and args.packets == "raw":
            print("this log has no usable raw Forza packets (ACE, BeamNG, the Sled format or an old log); "
                  "use --packets columns")
            return 1
    packets = "raw" if frames is not None else "columns"
    if frames is None:
        frames = load_frames(session / "telemetry.csv")
    if not frames:
        print("no telemetry frames in", session)
        return 1
    frames = trim(frames, args.all)
    if not args.all:
        print(f"trimmed to the driving portion: {len(frames)} frames, {frames[-1].t - frames[0].t:.0f} s")
    fmt = "raw" if packets == "raw" else (args.fmt or cfg["fmt"])
    if not game_process_running(cfg["process"]):
        print(f"{cfg['game']} is not running; HaptiConnect's plugin only listens while it is (menu is enough).")
        return 1
    log = newest_log()
    if log is None or f'"{cfg["game"]}" bound to port {cfg["port"]}' not in log.read_text(encoding="utf-8", errors="ignore"):
        print(f"warning: HaptiConnect's latest log does not show {cfg['game']} bound to port {cfg['port']}; "
              "restart HaptiConnect if nothing is felt.")
    out.mkdir(parents=True)
    t_first, t_last = frames[0].t, frames[-1].t
    duration = t_last - t_first
    pace = f"{args.rate:g}/s (latest packet)" if args.rate > 0 else "every packet at its own time"
    print(f"replaying {len(frames)} frames ({duration:.1f} s) into HaptiConnect {cfg['game']} plugin "
          f"at 127.0.0.1:{cfg['port']}: {packets} packets, {pace}; recording {args.device}")

    rec = LoopbackRecorder(args.device)
    src = ReplaySource(frames, args.speed)
    tlog = TelemetryLog()
    src.listeners.append(tlog)
    fwd = None
    sent = [0]
    if args.rate > 0:
        fwd = TelemetryForwarder(lambda: src.latest() if src.age() < 1.0 else None, host="127.0.0.1",
                                 port=cfg["port"], rate_hz=args.rate, fmt=fmt)
    else:
        from .forward import pack
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send_now(tele):
            sock.sendto(pack(tele, fmt), ("127.0.0.1", cfg["port"]))
            sent[0] += 1
        src.listeners.append(send_now)
    rec.start()
    time.sleep(0.3)
    src.start()
    if fwd:
        fwd.start()
    t0 = time.perf_counter()
    try:
        while not src.done and not rec.error and not src.error:
            time.sleep(0.5)
            el = time.perf_counter() - t0
            pk = 20 * np.log10(max(rec.peak, 1e-6))
            sys.stdout.write(f"\r  {el:6.1f}/{duration / args.speed:6.1f} s  HaptiConnect out {pk:6.1f} dBFS  "
                             f"frame {src.index}/{len(frames)}".ljust(90))
            sys.stdout.flush()
        if src.error:
            print("\nreplay thread failed:", src.error)
    except KeyboardInterrupt:
        print("\ninterrupted")
    print()
    time.sleep(1.0)
    if fwd:
        fwd.stop()
    src.stop()
    rec.stop()
    if rec.error or rec.t0 is None:
        print("audio capture failed:", rec.error)
        return 1
    audio = rec.audio()
    write_wav(out / "audio.wav", audio, rec.sr)
    with (out / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        with tlog.lock:
            for t in tlog.rows:
                w.writerow(tele_row(t, rec.t0))
    if (session / "ours.wav").exists():
        shutil.copy(session / "ours.wav", out / "ours.wav")
    peak = 20 * np.log10(max(float(np.max(np.abs(audio))), 1e-6))
    (out / "meta.json").write_text(json.dumps({
        "note": f"HaptiConnect {cfg['game']} plugin response to the replayed real drive {session.name}",
        "replayed_from": portable_path(session), "plugin": args.plugin, "fmt": fmt, "packets": packets,
        "rate": args.rate if args.rate > 0 else "original", "speed": args.speed,
        "trim_s": [round(t_first, 3), round(t_last, 3)], "device": rec.mic.name,
        "samplerate": rec.sr, "duration_s": round(len(audio) / rec.sr, 2), "frames": len(tlog),
        "packets_sent": fwd.sent if fwd else sent[0], "peak_dbfs": round(peak, 1), "version": __version__,
        "created": datetime.now().isoformat(timespec="seconds")}, indent=2), encoding="utf-8")
    print(f"saved {len(audio) / rec.sr:.1f} s of HaptiConnect output (peak {peak:.1f} dBFS) to {out}")
    if peak < -60:
        print("warning: that is silence - HaptiConnect was not bound (device not set? game not at its menu?)")
    profile = PROFILE_OF_PLUGIN.get(args.plugin, "forza_motorsport")
    print(f"score it:  python -m openshaker.compare {out} --profile profiles/{profile}/profile.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
