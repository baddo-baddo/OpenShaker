"""Audio output to the shaker (any Windows output device) via PortAudio / WASAPI."""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

# the output channel choices offered in Advanced; the app writes the same signal to each listed channel
CHANNEL_CHOICES = {"Left": [0], "Right": [1], "Both": [0, 1]}


class DeviceNotFound(RuntimeError):
    """The configured output device is not connected, or was never picked on this PC."""


def refresh_devices() -> None:
    """Re-scan the sound devices.

    PortAudio snapshots them when it initialises, so an app launched by Windows at boot can hold a
    list from before the shaker finished enumerating - and then never see its WASAPI endpoint.
    Callers must have no stream open (AudioOutput refuses while one is).
    """
    if AudioOutput.open_streams:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def normalize_name(name: str) -> str:
    """Compare device names the way Windows renames them.

    Re-plugging a USB audio device can turn "Speakers (ButtKicker PRO)" into
    "Speakers (2- ButtKicker PRO)"; both are the same shaker.
    """
    s = re.sub(r"\(\d+- ", "(", str(name or ""))
    return " ".join(s.lower().split())


def channel_choice(channels) -> str:
    """The Advanced dialog's label for a channel list ("Custom" for anything it does not offer)."""
    try:
        chans = sorted({int(c) for c in (channels or [0])})
    except (TypeError, ValueError):
        return "Custom"
    for label, want in CHANNEL_CHOICES.items():
        if chans == want:
            return label
    return "Custom"


class AudioOutput:
    # Shared-mode host APIs, best first. WDM-KS is deliberately not here: it is an exclusive kernel
    # stream, so taking it locks out every other app and every second stream of our own (which is how
    # the test tone used to die with "WdmSyncIoCtl: DeviceIoControl GLE = 0x490").
    SHARED_APIS = ("wasapi", "directsound", "mme")
    open_streams = 0

    def __init__(self, device_substr: str = "ButtKicker", api_pref: str = "WASAPI",
                 samplerate: int = 48000, blocksize: int = 480, channels=(0, 1)) -> None:
        self.device_substr = device_substr or ""
        self.api_pref = api_pref
        self.samplerate = int(samplerate)
        self.blocksize = int(blocksize)
        self.channels = [int(c) for c in channels] or [0]
        self.render: Optional[Callable[[int], np.ndarray]] = None
        self.on_block: Optional[Callable[[np.ndarray], None]] = None
        self.stream: Optional[sd.OutputStream] = None
        self.device_index: Optional[int] = None
        self.device_name = ""
        self.api = ""
        self.nch = 2
        self.xruns = 0
        self.callbacks = 0
        self.last_error: Optional[str] = None
        self.finished = False           # PortAudio's finished_callback fired
        self.last_callback = 0.0        # monotonic time of the last audio callback

    # -- device discovery -------------------------------------------------
    @staticmethod
    def output_devices() -> list:
        apis = sd.query_hostapis()
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                out.append({"index": i, "name": d["name"], "api": apis[d["hostapi"]]["name"],
                            "channels": d["max_output_channels"], "samplerate": d["default_samplerate"]})
        return out

    @classmethod
    def _api_rank(cls, api_name: str) -> int:
        low = api_name.lower()
        return next((i for i, a in enumerate(cls.SHARED_APIS) if a in low), len(cls.SHARED_APIS))

    @classmethod
    def shared_outputs(cls) -> list[str]:
        """Names for the device picker: every output on a shared host API, one entry per endpoint,
        spelled the way WASAPI spells it (MME cuts names off at 31 characters)."""
        devs = [d for d in cls.output_devices() if cls._api_rank(d["api"]) < len(cls.SHARED_APIS)]
        names: list[str] = []
        seen: list[str] = []
        for d in sorted(devs, key=lambda d: cls._api_rank(d["api"])):
            key = normalize_name(d["name"])
            if key in seen or (len(d["name"]) >= 31 and any(s.startswith(key) for s in seen)):
                continue
            seen.append(key)
            names.append(d["name"])
        return names

    @classmethod
    def find_device(cls, name: str, api_pref: str) -> Optional[int]:
        """The device on the best shared host API, never silently an exclusive one.

        An exact name wins (ignoring Windows' "2- " renumbering), then any name containing it, so a
        name picked from the list and a short hand-typed "ButtKicker" both work.
        """
        want = normalize_name(name)
        if not want:
            return None
        outs = cls.output_devices()
        exact = [d for d in outs if normalize_name(d["name"]) == want]
        contains = [d for d in outs if want in normalize_name(d["name"])]
        pref = api_pref.lower().strip()
        order = ([pref] if pref else []) + [a for a in cls.SHARED_APIS if a != pref]
        for group in (exact, contains):
            for api in order:
                hit = [d for d in group if api in d["api"].lower()]
                if hit:
                    return hit[0]["index"]
        return None                     # only exclusive APIs left: better to retry than to lock the device

    @staticmethod
    def default_output() -> Optional[int]:
        """Windows' default output, on WASAPI when PortAudio offers it."""
        try:
            for api in sd.query_hostapis():
                if "wasapi" in api["name"].lower() and int(api.get("default_output_device", -1)) >= 0:
                    return int(api["default_output_device"])
            idx = sd.default.device[1]
        except Exception:
            return None
        return None if idx is None or int(idx) < 0 else int(idx)

    # -- setup --------------------------------------------------------------
    def resolve(self) -> int:
        """Pick the device and a sample rate it accepts. Returns the sample rate to synthesize at.

        Raises DeviceNotFound when the named device is not there. It never falls back to another
        output: on a PC without the shaker that would be the speakers or headphones.
        """
        if not normalize_name(self.device_substr):
            idx = self.default_output()
            if idx is None:
                raise DeviceNotFound("Windows has no default output device")
        else:
            idx = self.find_device(self.device_substr, self.api_pref)
            if idx is None:
                seen = [f"{d['name']} ({d['api']})" for d in self.output_devices()
                        if normalize_name(self.device_substr) in normalize_name(d["name"])]
                if seen:
                    raise RuntimeError(f"'{self.device_substr}' is only offered on an exclusive host API "
                                       f"right now ({', '.join(seen)}); it is probably still waking up")
                raise DeviceNotFound(f"output device '{self.device_substr}' is not connected")
        info = sd.query_devices(idx)
        self.device_index = idx
        self.device_name = info["name"]
        self.api = sd.query_hostapis(info["hostapi"])["name"]
        # Open every channel the endpoint has and write only the chosen ones (_cb zeroes the rest). A
        # narrower stream is not "left only": WASAPI up-mixes a mono stream to a stereo endpoint, so the
        # signal also reaches the right channel - up to +6 dB on a shaker that sums them, where
        # HaptiConnect writes the left channel and leaves the right one silent.
        device_ch = max(1, min(int(info["max_output_channels"]), 8))
        needed = max(1, min(max(self.channels) + 1, device_ch))
        for nch in dict.fromkeys((device_ch, needed)):          # the narrow stream only if the full one is refused
            for sr in (self.samplerate, int(info["default_samplerate"]), 48000, 44100):
                try:
                    sd.check_output_settings(device=idx, samplerate=sr, channels=nch, dtype="float32",
                                             extra_settings=self._extra())
                except Exception:
                    continue
                self.nch = nch
                self.channels = [c for c in self.channels if c < nch] or [0]
                self.samplerate = sr
                return sr
        raise RuntimeError(f"device '{self.device_name}' rejected every sample rate")

    def _extra(self):
        if "wasapi" in self.api.lower():
            return sd.WasapiSettings(exclusive=False)
        return None

    def start(self) -> None:
        if self.device_index is None:
            self.resolve()
        if self.render is None:
            raise RuntimeError("AudioOutput.render is not set")
        self.finished = False
        self.last_callback = time.monotonic()
        self.stream = sd.OutputStream(device=self.device_index, samplerate=self.samplerate,
                                      blocksize=self.blocksize, channels=self.nch, dtype="float32",
                                      latency="low", callback=self._cb, finished_callback=self._on_finished,
                                      extra_settings=self._extra())
        self.stream.start()
        AudioOutput.open_streams += 1

    def stop(self) -> None:
        if self.stream is not None:
            try:
                for step in (self.stream.stop, self.stream.close):
                    try:
                        step()
                    except Exception:        # a stream whose device vanished can refuse to stop
                        pass
            finally:
                self.stream = None
                AudioOutput.open_streams = max(0, AudioOutput.open_streams - 1)

    # -- callback -------------------------------------------------------------
    def _cb(self, outdata, frames, time_info, status) -> None:
        self.callbacks += 1
        self.last_callback = time.monotonic()
        if status:
            self.xruns += 1
        try:
            mono = self.render(frames)
        except Exception as exc:  # never let an effect bug kill the stream
            self.last_error = repr(exc)
            mono = np.zeros(frames, dtype=np.float32)
        outdata.fill(0.0)
        for c in self.channels:
            outdata[:, c] = mono
        if self.on_block is not None:
            self.on_block(mono)

    STALL_S = 2.0          # no audio callback for this long: the device has gone away

    def _on_finished(self) -> None:
        self.finished = True

    @property
    def alive(self) -> bool:
        """False once the stream has stopped delivering audio - the device was unplugged, switched off
        or taken away - even though nothing raised an error."""
        if self.stream is None or self.finished:
            return False
        try:
            if not self.stream.active:
                return False
        except Exception:
            return False
        return time.monotonic() - self.last_callback < self.STALL_S

    @property
    def latency_ms(self) -> float:
        if self.stream is None:
            return 0.0
        lat = self.stream.latency
        return float(lat if not isinstance(lat, tuple) else lat[-1]) * 1000.0
