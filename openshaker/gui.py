"""Tk control panel plus the tray icon it hides into: start/stop, live telemetry, per-effect
sliders, test tone, save. Closing the window leaves the app running in the notification area."""
from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from . import APP_NAME, FEEDBACK_URL, REPO_URL, __version__, config, paths, procs, updater
from .audio import CHANNEL_CHOICES, AudioOutput, DeviceNotFound, channel_choice
from .effects import REGISTRY
from .engine import TestTone
from .outputs import load_optional_outputs
from .runtime import Runtime
from .tray import AVAILABLE as TRAY_AVAILABLE, IMPORT_ERROR as TRAY_IMPORT_ERROR, Tray

PROJECT_DIR = paths.RESOURCE_DIR         # bundled files (icon, profiles); user data is in paths.user_dir()
LOST_RETRY_SECONDS = 3.0      # an output that stopped playing is usually back as soon as it is plugged in,
LOST_FAST_WINDOW = 60.0       # so retry that fast for the first minute after it went away
RETRY_SECONDS = 15.0          # the ButtKicker may still be asleep, or a port still held, at boot
TONE_SECONDS, TONE_LOW, TONE_HIGH, TONE_AMP = 5.0, 25.0, 70.0, 0.8
WRAP_MIN = 520                # px: the status and source lines wrap here at the least, wider as the window grows
UPDATE_BG = "#fff4ce"         # the update bar's soft yellow
UPDATE_CONFIRM = "Haptics will stop for about 15 seconds while OpenShaker updates. Update now?"
INSTALLER_WAIT_S = 180.0      # an update installer that has not closed the app by then did not work
AUTO_IDLE_S = 300.0           # automatic updates (off by default) wait until no game has sent data this long
AUTO_TICK_S = 30.0            # ... and look again this often while one does
# parts of the supported games' executable names: one of them running means "not now" (leans towards waiting)
GAME_EXES = ("forza", "assettocorsa", "acevo", "ac2-win64", "acs.exe", "beamng", "trackmania")
AUTO_QUESTION = "Install updates automatically when no game is running?"
HAPTICS_OFF_MSG = ("Haptics are switched off: nothing plays, and the game ports are free for other programs. "
                   "Tick Haptics on (here or in the tray menu) to turn them back on.")
EFFECT_LABELS = {
    "engine": "Engine RPM",
    "gear_shift": "Gear shift",
    "wheel_lock": "Wheel lock (braking)",
    "wheel_slip": "Wheel slip / slide",
    "abs": "ABS pulse",
    "suspension": "Suspension bumps",
    "road": "Kerbs / rough road",
    "impact": "Collisions",
    "acceleration": "G-force rumble",
    "shift_indicator": "Shift indicator",
    "grip_margin": "Grip limit warning",
    "surface": "Surface feel",
    "landing": "Landings",
    "boost": "Turbo & reactor boost",
}
def parse_percent(text: str) -> float | None:
    """A typed strength: '85', '85%', ' 85.5 % ' or '85,5'. None when it is not a number."""
    t = text.strip().rstrip("%").strip().replace(",", ".")
    try:
        value = float(t)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def click_to_jump(scale: ttk.Scale, before=None):
    """Clicking a slider's track puts the value right there, and the knob follows the mouse until the
    button is released. Windows' ttk would only step toward the click and repeat while held.
    Grabbing the knob itself drags as usual. `before()` runs first on any mouse button (it closes an
    open number box, so the number cannot overwrite the slider later). Returns a SliderGrip: whether
    the slider is held right now, and a call that ends a drag in progress.
    """
    follow = {"on": False}
    grip = SliderGrip(follow)

    def press(event):
        grip.held = True
        if before is not None:
            before()
        if "slider" in str(scale.identify(event.x, event.y)):
            return None                          # the knob: ttk's own drag
        scale.set(scale.get(event.x, event.y))   # set() also runs the slider's command
        follow["on"] = True
        return "break"                           # no step-and-repeat toward the click

    def motion(event):
        if not follow["on"]:
            return None
        scale.set(scale.get(event.x, event.y))
        return "break"

    def release(_event):
        follow["on"] = False
        grip.held = False

    def other_button(_event):
        grip.held = True
        if before is not None:
            before()
        return None                              # ttk's own right/middle-button jump still follows

    scale.bind("<Button-1>", press)
    scale.bind("<B1-Motion>", motion)
    scale.bind("<ButtonRelease-1>", release, add="+")
    for button in (2, 3):
        scale.bind(f"<Button-{button}>", other_button)
        scale.bind(f"<ButtonRelease-{button}>", release, add="+")
    return grip


class SliderGrip:
    """What click_to_jump returns: `held` while a mouse button is down on the slider; calling it
    ends our jump-and-follow drag."""

    def __init__(self, follow: dict) -> None:
        self._follow = follow
        self.held = False

    def __call__(self) -> None:
        self._follow["on"] = False


def end_slider_drags(widget, grips) -> None:
    """Stop the drags of these sliders - ours and ttk's own (knob, right/middle button) - e.g.
    before they show another preset. Only call it while one of them is held: ttk's drag state is
    shared by every slider."""
    for grip in grips:
        grip()
    try:
        widget.tk.eval("set ::ttk::scale::State(dragging) 0; ttk::CancelRepeat")
    except tk.TclError:
        pass


def double_click_ms() -> int:
    try:
        import ctypes
        return int(ctypes.windll.user32.GetDoubleClickTime()) or 500
    except (AttributeError, OSError):
        return 500


class ValueBox:
    """The number next to a slider. Click it to type a value: Enter, or clicking anywhere else,
    applies it through `apply(text)`; Esc keeps the old one. `group` ({"open": box}) is shared by
    the boxes of one window, so only one is open at a time.
    """

    def __init__(self, parent, textvariable: tk.StringVar, width: int, apply, group: dict) -> None:
        self.textvariable, self.apply, self.group = textvariable, apply, group
        self.frame = ttk.Frame(parent)
        self.label = ttk.Label(self.frame, textvariable=textvariable, style="Tele.TLabel", width=width,
                               cursor="xterm")
        self.text = tk.StringVar()
        self.entry = ttk.Entry(self.frame, width=width, font=("Consolas", 10), textvariable=self.text)
        self.text.trace_add("write", self._edited)
        self.edited = False                      # anything typed since the box opened
        self.label.pack(fill="x")
        self.label.bind("<Button-1>", self.begin)
        for key in ("<Return>", "<KP_Enter>"):
            self.entry.bind(key, lambda _e: self.finish(True, refocus=True))
        self.entry.bind("<Escape>", lambda _e: self.finish(False, refocus=True))
        self.entry.bind("<FocusOut>", lambda _e: self.finish(True))
        self.entry.bind("<Button-1>", self._press)
        self._opened_at = None

    def _edited(self, *_args) -> None:
        self.edited = True

    @property
    def editing(self) -> bool:
        return self.group.get("open") is self

    def begin(self, event=None):
        if self.editing:
            return "break"
        other = self.group.get("open")
        if other is not None:
            other.finish(True)                   # a box left open elsewhere applies what it holds
        self.group["open"] = self
        self._opened_at = getattr(event, "time", None)
        self.label.pack_forget()
        self.text.set(self.textvariable.get().replace("%", "").strip())
        self.edited = False
        self.entry.pack(fill="x")
        self.entry.focus_set()
        self._select_all()
        return "break"

    def _select_all(self) -> None:
        self.entry.select_range(0, "end")
        self.entry.icursor("end")

    def _press(self, event):
        """The second click of a double-click lands on the box that the first one opened: keep the
        whole number selected, so typing replaces it instead of going into the middle of it."""
        opened, self._opened_at = self._opened_at, None
        try:
            gap = int(event.time) - int(opened) if opened is not None else None
        except (TypeError, ValueError):
            gap = None
        if gap is not None and 0 <= gap <= double_click_ms():
            self._select_all()
            return "break"                       # ttk's press would move the caret, its drag drop the selection
        return None

    def finish(self, apply: bool, refocus: bool = False):
        if not self.editing:
            return "break"
        self.group["open"] = None                # first, so the FocusOut that hiding causes is a no-op
        text = self.entry.get()
        self.entry.pack_forget()
        self.label.pack(fill="x")
        if refocus:
            self.frame.winfo_toplevel().focus_set()   # the hidden box must not keep the keyboard
        if apply and self.edited:                # only what was typed: looking changes nothing
            self.apply(text)
        return "break"


SOURCE_LABELS = {"forza": "Forza (UDP)", "beamng": "BeamNG (UDP)", "ace": "Assetto Corsa EVO",
                 "trackmania": "Trackmania (Openplanet)", "demo": "Demo"}


class App:
    DEFAULT_OUTPUT = "(Windows default output)"

    def __init__(self, root: tk.Tk, cfg: dict, config_path: str, hidden: bool = False,
                 start_haptics: bool = False, use_tray: bool = True, ask_startup: bool = True,
                 update_result: tuple | None = None) -> None:
        self.root = root
        self.cfg = cfg
        self.config_path = config_path
        self.ask_startup = ask_startup
        self._device_warned = False
        self.rt: Runtime | None = None
        self._tone_thread: threading.Thread | None = None
        self.tray: Tray | None = None
        self._ui_queue: queue.Queue = queue.Queue()
        self.listener = None
        self.presets = config.list_presets(cfg)
        self.preset_key = cfg.get("_preset") or config.preset_key(cfg, cfg.get("profile"))
        self.active_preset = self.preset_key
        self._preset_bases: dict = {}
        self._save_job = None
        self.start_error = ""
        self._retry_at = 0.0
        self._keep_running = False     # set by the first start(); until then poll() starts nothing (--no-start)
        self._lost_at = -1e9
        self._last_status: dict | None = None
        self._tray_tick = 0
        self._tray_lines = {"state": "Haptics: stopped", "game": "Game: -", "profile": "Profile: -",
                            "output": "Output: -", "error": ""}
        # the Haptics on switch (window and tray): off stops everything and stays off across launches;
        # --no-start turns it off for this launch only. A plain bool: pystray's thread reads it.
        self._no_start = not start_haptics
        self.haptics_on = cfg.get("haptics_on", True) is not False and start_haptics
        self._unsaved_switch = ""                # set when config.json refused the switch (see _say_unsaved_switch)
        self._save_error = ""
        self._saved_switch = cfg.get("haptics_on", True) is not False    # what config.json says right now
        self._boxes: dict = {"open": None}       # the number box being typed into, if any
        # updates (updater.py): what is available, as a plain string pystray's thread can read
        self.update_release: updater.Release | None = None
        self._update_version = ""
        self._update_state = ""                  # "", "busy" or "failed": the tray's item reads it
        self._update_sticky = False              # the bar says an update stopped partway: a check keeps it
        self._auto_job = None                    # a waiting automatic update's next look (_auto_tick)
        self._auto_update = False                # the update under way was started automatically
        self._auto_failed = ""                   # an automatic update to this version failed: the bar takes over
        self._auto_kept = None                   # (version, sha256, Verified) an interrupted automatic update keeps
        self._notes_version = ""                 # "updated itself to X": What's new opens X's release page
        self._tele_seen_at = time.monotonic()    # the last telemetry from any game (the launch counts as one)
        self._update_busy = False
        self._update_job = None
        self._update_retries = 0                 # network failures in a row (sooner retries)
        self._installer_watch = None             # (process, started) of a running update installer
        self.update_error = ""                   # the last check's problem, if any; also in logs/update.log
        # optional outputs (outputs.py): absent package = nothing here at all
        try:
            found, problems = load_optional_outputs()           # guards itself; this guards the guard
            self.outputs = list(found)
        except (Exception, SystemExit) as exc:
            self.outputs, problems = [], [f"optional outputs: {type(exc).__name__}: {exc}"]
        self._output_notes = [f"Could not load {p}" for p in problems]   # shown once the message line exists
        self.output_rows: dict = {}
        self._strength_grips: list = []          # the strength sliders' grips (see end_slider_drags)
        self._dropped_typing = False

        root.title(f"{APP_NAME} {__version__}")
        root.minsize(560, 620)
        ico = paths.ICON
        if ico.exists():
            try:
                root.iconbitmap(str(ico))
            except tk.TclError:
                pass
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        style.configure("Big.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Big.TCheckbutton", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10))
        style.configure("Tele.TLabel", font=("Consolas", 10))
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Update.TFrame", background=UPDATE_BG)
        style.configure("Update.TLabel", background=UPDATE_BG, font=("Segoe UI", 10, "bold"))
        style.configure("UpdateAsk.TLabel", background=UPDATE_BG, font=("Segoe UI", 10))

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        # -- the update bar: packed above everything only while an update is available ------------
        self.update_bar = ttk.Frame(outer, style="Update.TFrame", padding=(8, 4))
        line = ttk.Frame(self.update_bar, style="Update.TFrame")
        line.pack(fill="x")
        self.update_var = tk.StringVar(value="")
        ttk.Label(line, textvariable=self.update_var, style="Update.TLabel",
                  wraplength=WRAP_MIN - 220).pack(side="left")
        self.update_buttons = {}
        for key, text, command in (("skip", "Skip this version", self.skip_update),
                                   ("news", "What's new", self.open_whats_new),
                                   ("now", "Update now", self.update_now)):
            self.update_buttons[key] = ttk.Button(line, text=text, command=command)
            self.update_buttons[key].pack(side="right", padx=(6, 0))
        # asked once, the first time an update is offered (updates.auto_asked); never a pop-up
        self.update_ask = ttk.Frame(self.update_bar, style="Update.TFrame")
        ttk.Label(self.update_ask, text=AUTO_QUESTION, style="UpdateAsk.TLabel").pack(side="left")
        self.update_ask_buttons = {}
        for key, text, answer in (("no", "No", False), ("yes", "Yes", True)):
            self.update_ask_buttons[key] = ttk.Button(self.update_ask, text=text,
                                                      command=lambda a=answer: self.answer_auto_update(a))
            self.update_ask_buttons[key].pack(side="right", padx=(6, 0))

        # -- top: the haptics switch / mode ------------------------------------------------
        top = ttk.Frame(outer)
        top.pack(fill="x")
        self._top_frame = top
        self.haptics_var = tk.BooleanVar(value=self.haptics_on)
        self.haptics_box = ttk.Checkbutton(top, text="Haptics on", style="Big.TCheckbutton",
                                           variable=self.haptics_var,
                                           command=lambda: self.set_haptics(self.haptics_var.get()))
        self.haptics_box.pack(side="left")
        self.mode = tk.StringVar(value="game")
        self.mode_buttons = {}
        for value, text, pad in (("game", "Games", 0), ("demo", "Demo", (0, 6))):
            self.mode_buttons[value] = ttk.Radiobutton(top, text=text, variable=self.mode, value=value,
                                                       command=self._restart_if_on)
            self.mode_buttons[value].pack(side="right", padx=pad)
        pre = ttk.Frame(outer)
        pre.pack(fill="x", pady=(10, 0))
        ttk.Label(pre, text="Preset", style="Head.TLabel").pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(pre, textvariable=self.preset_var, state="readonly", width=32,
                                       values=[e["label"] for e in self.presets])
        self.preset_box.pack(side="left", padx=8)
        self.preset_box.bind("<<ComboboxSelected>>", self._preset_picked)
        self.preset_note = tk.StringVar(value="")
        ttk.Label(pre, textvariable=self.preset_note, foreground="#555").pack(side="left")

        opts = ttk.Frame(outer)
        opts.pack(fill="x", pady=(8, 0))
        self.startup_var = tk.BooleanVar(value=self.windows_startup_enabled())
        ttk.Checkbutton(opts, text="Start with Windows (in the tray)", variable=self.startup_var,
                        command=self.toggle_windows_startup).pack(side="left")

        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", wraplength=WRAP_MIN)
        self.status_label.pack(anchor="w", pady=(8, 0))

        # -- telemetry --------------------------------------------------------------------
        tele = ttk.LabelFrame(outer, text="Telemetry", padding=8)
        tele.pack(fill="x", pady=(10, 0))
        self.src_var = tk.StringVar(value="no game detected")
        ttk.Label(tele, textvariable=self.src_var, style="Head.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        self.tele_vars = {}
        fields = [("RPM", "rpm"), ("Gear", "gear"), ("Speed", "speed"), ("Throttle", "thr"),
                  ("Brake", "brk"), ("G long", "glong"), ("G lat", "glat"), ("G vert", "gvert")]
        for i, (label, key) in enumerate(fields):
            r, c = 1 + i // 4, (i % 4)
            cell = ttk.Frame(tele)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 18), pady=2)
            ttk.Label(cell, text=label + ":").pack(side="left")
            v = tk.StringVar(value="-")
            self.tele_vars[key] = v
            ttk.Label(cell, textvariable=v, style="Tele.TLabel", width=11).pack(side="left")
        self.sources_var = tk.StringVar(value="")
        self.sources_label = ttk.Label(tele, textvariable=self.sources_var, foreground="#555", wraplength=WRAP_MIN,
                                       justify="left")
        self.sources_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        for c in range(4):                        # a wider window spreads the readouts instead of leaving a gap
            tele.columnconfigure(c, weight=1)
        # long status and source lines wrap at the window's width instead of widening the window
        outer.bind("<Configure>", self._rewrap, add="+")

        # -- output -------------------------------------------------------------------------
        out = ttk.LabelFrame(outer, text="Output", padding=8)
        out.pack(fill="x", pady=(10, 0))
        ttk.Label(out, text="Level").grid(row=0, column=0, sticky="w")
        self.level_bar = ttk.Progressbar(out, length=260, maximum=60.0)
        self.level_bar.grid(row=0, column=1, sticky="we", padx=8)
        self.level_var = tk.StringVar(value="-inf dB")
        ttk.Label(out, textvariable=self.level_var, style="Tele.TLabel", width=10).grid(row=0, column=2, sticky="w")
        ttk.Label(out, text="Master").grid(row=1, column=0, sticky="w", pady=(6, 0))   # 1.00 = calibrated
        self.master_var = tk.DoubleVar(value=float(cfg["audio"]["master_gain"]))
        self.master_scale = ttk.Scale(out, from_=0.0, to=1.0, variable=self.master_var,
                                      command=self._master_changed)
        self.master_scale.grid(row=1, column=1, sticky="we", padx=8, pady=(6, 0))
        click_to_jump(self.master_scale, before=self._close_box)
        for event, step in (("<<PrevChar>>", -0.01), ("<<NextChar>>", 0.01), ("<<PrevLine>>", -0.01),
                            ("<<NextLine>>", 0.01), ("<<PrevWord>>", -0.10), ("<<NextWord>>", 0.10),
                            ("<<PrevPara>>", -0.10), ("<<NextPara>>", 0.10)):
            # ttk steps a slider by 1 (Ctrl: 10) - Master's whole 0..1 range - so step in percent
            self.master_scale.bind(event, lambda _e, d=step: self._master_step(d))
        self.master_lbl = tk.StringVar(value=f"{self.master_var.get() * 100:.0f}%")
        self.master_box = ValueBox(out, self.master_lbl, 10, self._type_master, self._boxes)
        self.master_box.frame.grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Label(out, text="Device").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.device_var = tk.StringVar(value=self._device_label(cfg["audio"].get("device", "")))
        self.device_box = ttk.Combobox(out, textvariable=self.device_var, state="readonly",
                                       postcommand=self._fill_devices)
        self.device_box.grid(row=2, column=1, columnspan=2, sticky="we", padx=8, pady=(6, 0))
        self.device_box.bind("<<ComboboxSelected>>", self._device_picked)
        self._place_output_rows(out, 3)
        out.columnconfigure(1, weight=1)

        # -- effects ----------------------------------------------------------------------------
        eff = ttk.LabelFrame(outer, text="Effects (enable, strength as % of the calibrated level, live level)",
                             padding=8)
        eff.pack(fill="both", expand=True, pady=(10, 0))
        self.effect_vars = {}
        self.effect_bars = {}
        self.effect_scales = {}
        self.strength_boxes = {}
        for row, name in enumerate(REGISTRY):
            e_cfg = cfg["effects"].get(name, {})
            en = tk.BooleanVar(value=bool(e_cfg.get("enabled", True)))
            trim = tk.DoubleVar(value=float(e_cfg.get("trim", 1.0)) * 100.0)
            lbl = tk.StringVar(value=f"{trim.get():3.0f}%")
            self.effect_vars[name] = (en, trim, lbl)
            ttk.Checkbutton(eff, text=EFFECT_LABELS.get(name, name), variable=en,
                            command=lambda n=name: self._effect_changed(n)).grid(row=row, column=0, sticky="w", pady=1)
            scale = ttk.Scale(eff, from_=0.0, to=200.0, variable=trim,
                              command=lambda _v, n=name: self._slider_moved(n))
            scale.grid(row=row, column=1, sticky="we", padx=8)
            self._strength_grips.append(click_to_jump(scale, before=self._close_box))
            self.effect_scales[name] = scale
            box = ValueBox(eff, lbl, 5, lambda text, n=name: self._type_strength(n, text), self._boxes)
            box.frame.grid(row=row, column=2, sticky="w")
            self.strength_boxes[name] = box
            bar = ttk.Progressbar(eff, length=90, maximum=1.0)
            bar.grid(row=row, column=3, sticky="we", padx=(8, 0))
            eff.rowconfigure(row, weight=1)       # a taller window spaces the rows out, not a gap below them
            self.effect_bars[name] = bar
        self.hint_label = ttk.Label(eff, foreground="#555", wraplength=520,
                                    text="Click a slider to jump there, or click a number to type one "
                                         "(Enter or clicking elsewhere applies it, Esc cancels).")
        self.hint_label.grid(row=len(REGISTRY), column=0, columnspan=4, sticky="w", pady=(6, 0))
        eff.columnconfigure(1, weight=3)          # a wider window: mostly longer sliders, a little longer bars
        eff.columnconfigure(3, weight=1)

        # -- bottom buttons -----------------------------------------------------------------------
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="Test tone", command=self.test_tone).pack(side="left")
        self.restart_button = ttk.Button(bottom, text="Restart haptics", command=self.restart_haptics)
        self.restart_button.pack(side="left", padx=8)
        ttk.Button(bottom, text="Reset preset to calibrated", command=self.reset_to_profile).pack(side="right")
        ttk.Button(bottom, text="Advanced...", command=self.advanced).pack(side="right", padx=8)
        msg = "Strengths save themselves. A preset becomes active when its game is detected."
        self.msg_var = tk.StringVar(value=msg)
        ttk.Label(outer, textvariable=self.msg_var, foreground="#555", wraplength=540).pack(anchor="w", pady=(8, 0))

        self._select_preset(self.preset_key)
        if cfg.pop("_resave", False):
            self._save_now()                      # config.load dropped copies of defaults; keep the file slim
        self._setup_windows_startup(hidden)
        self.tray = Tray(self, ico) if use_tray else None
        if self.tray is not None and self.tray.active:
            self.tray.start()
        elif use_tray and not TRAY_AVAILABLE:
            self.msg_var.set(f"{msg}   (no tray icon: {TRAY_IMPORT_ERROR})")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Button-1>", self._click_away, add="+")   # clicking elsewhere applies an open number box
        root.after(200, self.poll)
        self._schedule_update_check(updater.CHECK_DELAY_S)
        if not updater.offline():                 # local only: old update folders in %TEMP%, any setting
            threading.Thread(target=updater.clean_old_downloads, name="update-cleanup", daemon=True).start()
        if update_result:                         # setup started this copy again after a stopped update
            self._installer_came_back(*update_result)
        self._after_automatic_update(bool(update_result))
        if hidden and self.tray is not None and self.tray.active:
            root.withdraw()                       # started by Windows: live in the tray only
        elif hidden:
            root.iconify()                        # no tray icon to hide into; at least stay out of the way
        if self.haptics_on:
            root.after(400, self._start_at_launch)
        elif self._no_start:
            self.msg_var.set('Haptics are off (started with --no-start), so the calibration tools can use the game '
                             'ports. Haptics on (or Restart haptics) starts them.')
        else:
            self.msg_var.set(HAPTICS_OFF_MSG)

    # -- actions ---------------------------------------------------------------------------------
    def _start_at_launch(self) -> None:
        if self.haptics_on:                      # not if the switch went off in the meantime
            self.start()

    def start(self, quiet: bool = True) -> None:
        """Bring the haptics up, and the Haptics on switch with them. Called on launch, by the switch, by
        Restart haptics and by the retry in poll()."""
        self._set_switch(True)
        self._keep_running = True                # from now on poll() brings them back after a failure
        if self.rt is not None and self.rt.running:
            return
        self.rt = Runtime(self.cfg, demo=(self.mode.get() == "demo"), outputs=self.outputs)
        try:
            self.rt.start()
        except Exception as exc:
            self.rt = None
            self.start_error = f"{type(exc).__name__}: {exc}"
            self._retry_at = time.monotonic() + self._retry_interval()
            if isinstance(exc, DeviceNotFound):
                self.start_error = f"{exc} - pick your shaker under Output > Device"
                self._notify_device_missing()
            if quiet:
                self.msg_var.set(f"Could not start haptics: {self.start_error} - retrying.")
            else:
                self.report_error("Could not start haptics", self.start_error)
            return
        self.start_error = ""
        self.msg_var.set("Running. Drive in the game; strengths can be changed live.")
        self._sync_preset_note()

    def _stop_runtime(self) -> None:
        """Internal: the only way to leave the haptics stopped is the Haptics on switch (set_haptics)."""
        if self.rt is not None:
            self.rt.stop()
            self.rt = None
        self.src_var.set("no game detected")      # nothing the stopped runtime said may linger
        self.sources_var.set("")
        for v in self.tele_vars.values():
            v.set("-")
        self.level_bar["value"] = 0
        self.level_var.set("-inf dB")
        for bar in self.effect_bars.values():
            bar["value"] = 0

    def set_haptics(self, on: bool) -> None:
        """The Haptics on switch, in the window and the tray menu. Off stops everything the haptics run -
        the shaker's audio stream, the game ports (free for other programs), the optional outputs - and
        they stay off, across launches too, until the switch (or Restart haptics) turns them on again."""
        if on:
            self.start(quiet=False)
        else:
            self._set_switch(False)
            self._keep_running = False           # poll() must not bring them back
            self._stop_runtime()
            self.start_error = ""
            self.msg_var.set(HAPTICS_OFF_MSG)
        self._sync_preset_note()
        self._refresh()
        self._refresh_tray(force=True)
        self._say_unsaved_switch()

    def toggle_haptics(self) -> None:
        """The tray's Haptics on item (run on the Tk thread)."""
        self.set_haptics(not self.haptics_on)

    def _set_switch(self, on: bool) -> None:
        """Record the switch: the window's box, the tray's tick and config.json (which holds it only while off)."""
        changed = on != self.haptics_on
        self.haptics_on = on
        self._no_start = False                   # from now on it is the user's choice, not the launch flag's
        if bool(self.haptics_var.get()) != on:
            self.haptics_var.set(on)
        if (self.cfg.get("haptics_on", True) is not False) != on:
            self.cfg["haptics_on"] = on
            if not self._save_now() and self._saved_switch != on:
                self._unsaved_switch = (f"The Haptics on switch could not be saved ({self._save_error}), so after "
                                        f"a restart the haptics will be {'on' if self._saved_switch else 'off'} again.")
        if changed and self.tray is not None:
            self.tray.update_menu()              # pystray reads the tick only when it builds the menu

    def _say_unsaved_switch(self) -> None:
        """A switch that could not be saved holds only until the app ends: say so after the switch's own
        message (which would otherwise cover the save error), and in the tray when the window is hidden."""
        note, self._unsaved_switch = self._unsaved_switch, ""
        if not note:
            return
        self.msg_var.set(f"{self.msg_var.get()}  {note}")
        if not self.window_visible() and self.tray is not None:
            self.tray.notify(note)

    def restart_haptics(self) -> None:
        """Restart haptics (window and tray): a fresh runtime. While they are switched off it turns them on."""
        self._stop_runtime()
        self.start(quiet=False)
        self._say_unsaved_switch()

    def _restart_if_on(self) -> None:
        """Pick up a change that needs a fresh runtime - demo mode, the device, ports - now, or, while the
        haptics are switched off, when they are switched on again."""
        if self.haptics_on:
            self.restart_haptics()

    def test_tone(self) -> None:
        """Sweep the ButtKicker's band so you can feel whether the chain works end to end.

        It is mixed into the stream that is already playing. Opening a second stream fails
        outright when the device is held exclusively, which is precisely when someone reaches
        for the test tone.
        """
        if self.rt is not None and self.rt.play_test_tone(TONE_SECONDS, TONE_LOW, TONE_HIGH, TONE_AMP):
            self.msg_var.set(f"Test tone: {TONE_LOW:.0f}-{TONE_HIGH:.0f} Hz sweep, {TONE_SECONDS:.0f} s, "
                             f"through the running output.")
            return
        if self._tone_thread is not None and self._tone_thread.is_alive():
            return

        def say(text: str) -> None:
            self.run_on_ui(lambda: self.msg_var.set(text))      # this runs off the Tk thread

        def worker() -> None:
            """Haptics are down, so there is no stream to mix into: make a short-lived one."""
            a = self.cfg["audio"]
            audio = AudioOutput(device_substr=a["device"], api_pref=a["api"], samplerate=a["samplerate"],
                                blocksize=a["blocksize"], channels=a["channels"])
            try:
                sr = audio.resolve()
                tone = TestTone(sr, TONE_SECONDS, TONE_LOW, TONE_HIGH, TONE_AMP)
                audio.render = tone.block
                audio.start()
                say(f"Test tone: {TONE_LOW:.0f}-{TONE_HIGH:.0f} Hz sweep on {audio.device_name}")
                time.sleep(TONE_SECONDS + 0.2)
                audio.stop()
                say(f"Test tone done ({audio.device_name}, {audio.xruns} dropouts).")
            except Exception as exc:
                say(f"Test tone failed: {type(exc).__name__}: {exc}")

        self._tone_thread = threading.Thread(target=worker, daemon=True)
        self._tone_thread.start()

    def open_folder(self) -> None:
        subprocess.Popen(["explorer", str(paths.user_dir())])      # settings and logs

    def open_feedback(self) -> None:
        """The tray's "Send feedback / report a bug": the project's issue forms in the default browser
        (webbrowser -> os.startfile on Windows, no shell). Nothing is attached or sent - no log, no system
        data; people choose what to paste into the form."""
        try:
            opened = webbrowser.open(FEEDBACK_URL)
        except Exception:
            opened = False
        if not opened:
            self.msg_var.set(f"Could not open a browser. To report a bug or send feedback, go to {FEEDBACK_URL}")

    # -- updates (updater.py): a badge and a bar, never a pop-up --------------------------------
    def updates_enabled(self) -> bool:
        return bool((self.cfg.get("updates") or {}).get("check", True))

    def update_version(self) -> str:
        """The version an update is available to, or "". Read by pystray's thread: a plain string."""
        return self._update_version

    def update_status(self) -> str:
        """"", "busy" (downloading or installing) or "failed": the tray's update item reads it."""
        return self._update_state

    def _schedule_update_check(self, delay_s: float) -> None:
        if self._update_job is not None:
            try:
                self.root.after_cancel(self._update_job)
            except tk.TclError:
                pass
            self._update_job = None
        if self.updates_enabled():
            self._update_job = self.root.after(int(delay_s * 1000), self._start_update_check)

    def _start_update_check(self) -> None:
        """~30 s after start, then daily (sooner after a network failure): ask GitHub on a worker thread.
        The next check is scheduled once this one has answered; this 24 h one is the fallback."""
        self._update_job = None
        if not self.updates_enabled():
            return
        threading.Thread(target=self._update_worker, name="update-check", daemon=True).start()
        self._schedule_update_check(updater.CHECK_EVERY_S)

    def _update_worker(self) -> None:
        release, error, network = None, "", False
        try:
            release = updater.check()
        except Exception as exc:                  # offline, rate-limited, a broken release: quietly
            error, network = f"{type(exc).__name__}: {exc}", isinstance(exc, (updater.NetworkError, OSError))
        self.run_on_ui(lambda: self._update_checked(release, error, network))

    def _skipped(self, version: str) -> bool:
        """Skip this version was clicked for `version` or a newer one (a skip that is no version: no)."""
        skip = (self.cfg.get("updates") or {}).get("skip") or ""
        return bool(updater.parse_version(skip)) and not updater.is_newer(version, skip)

    def _update_checked(self, release, error: str = "", network: bool = False) -> None:
        self.update_error = error
        if error:
            updater.log(f"check failed: {error}")
            self._update_retries = self._update_retries + 1 if network else 0
        else:
            self._update_retries = 0
        if self.updates_enabled():                # after a network failure try again sooner, else daily
            retry = updater.RETRY_AFTER_S
            self._schedule_update_check(retry[self._update_retries - 1] if 0 < self._update_retries <= len(retry)
                                        else updater.CHECK_EVERY_S)
        if error or not self.updates_enabled() or self._update_busy:
            return
        self._offer_update(release)

    def _offer_update(self, release) -> None:
        """Show `release` in the bar and the tray. None (GitHub has nothing newer: a pulled release too) or
        a skipped version hides whatever the bar shows, except the note that an update stopped partway."""
        if release is not None and self._skipped(release.version):
            release = None                        # skipped, and nothing newer than the skipped one
        if release is None:
            if not self._update_sticky and (self._update_version or self.update_bar.winfo_manager()):
                self._hide_update()
            return
        self.update_release, self._update_sticky = release, False
        self._update_version, self._update_state = release.version, ""
        if self._auto_kept is not None and self._auto_kept[0] != release.version:
            self._drop_kept()                     # another version is on offer now
        failed = (self.cfg.get("updates") or {}).get("auto_failed") or ""
        if failed and updater.is_newer(release.version, failed):
            self._set_auto_failed("")             # a newer version: automatic updates may try it
        held = (" Its automatic update did not work, so it waits for Update now."
                if self.updates_auto() and self._auto_blocked(release.version) else "")
        self._show_update(f"{APP_NAME} {release.version} is available (you have {__version__}).{held}", ask=True)
        self._arm_auto()

    def _installer_came_back(self, how: str, version: str) -> None:
        """Setup quit this app for a silent update, stopped, and started this copy again: with
        --update-failed=X when no file had been replaced (it is offered again), --update-incomplete=X when
        it stopped partway through the files, which may now be a mix of two versions."""
        self._update_version, self._update_state = version, "failed"    # "Update to X failed - open ..."
        target = version or "the new version"
        automatic = bool((self.cfg.get("updates") or {}).get("auto_done"))   # read before _after_automatic_update
        if how == "incomplete":
            updater.log(f"update to {version or '?'} stopped partway through its files; setup started "
                        f"{__version__} again")
            self._update_sticky = True
            self._show_update(f"The update to {target} stopped partway, so {APP_NAME}'s files may be a mix of "
                              f"two versions. To repair it, run the installer from the release page "
                              f"(What's new).", buttons=("news",))
        else:
            updater.log(f"update to {version or '?'} failed; setup started {__version__} again")
            again = ("It will not be installed automatically again; Update now tries again." if automatic
                     else "It will be offered again.")
            self._show_update(f"The update to {target} did not install, so {APP_NAME} {__version__} was "
                              f"started again. {again}", buttons=False)

    def _show_update(self, text: str, buttons: bool | tuple = True, ask: bool = False) -> None:
        """buttons: True = all three while a release is offered, False = none, a tuple = just those.
        ask: an offer, where the one-time automatic-updates question may show under it."""
        self.update_var.set(text + (" [update test mode]" if updater.test_mode() else ""))
        for name, button in self.update_buttons.items():
            on = name in buttons if isinstance(buttons, tuple) else buttons and self.update_release is not None
            button.state(["!disabled"] if on else ["disabled"])
        if ask and self._should_ask_auto():
            if not self.update_ask.winfo_manager():
                self.update_ask.pack(fill="x", pady=(4, 0))
        else:
            self.update_ask.pack_forget()
        if not self.update_bar.winfo_manager():
            self.update_bar.pack(fill="x", pady=(0, 10), before=self._top_frame)
        self._refresh_tray(force=True)            # the badge and the menu items

    def _hide_update(self) -> None:
        self._drop_kept()
        self.update_release, self._update_version, self._update_state = None, "", ""
        self._update_sticky, self._notes_version = False, ""
        self._cancel_auto()
        self.update_ask.pack_forget()
        self.update_bar.pack_forget()
        self._refresh_tray(force=True)

    def open_whats_new(self) -> None:
        version = self._update_version or self._notes_version
        if self.update_release is not None:
            url = self.update_release.page_url
        elif updater.parse_version(version):      # after a stopped or an automatic update: that release
            url = f"{REPO_URL}/releases/tag/v{version}"
        else:
            url = f"{REPO_URL}/releases"
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            self.msg_var.set(f"Could not open a browser. The release notes are at {url}")

    def skip_update(self) -> None:
        """Hide this version's badge and bar for good; a newer version shows them again."""
        if self.update_release is None or self._update_busy:
            return
        self.cfg.setdefault("updates", {})["skip"] = self.update_release.version
        self._mark_auto_asked()                   # an answer too: the question never comes back
        self._hide_update()

    def update_from_tray(self) -> None:
        if self._update_state == "failed":        # "Update to X failed - open OpenShaker"
            self.show_window()
            return
        self.update_now(from_window=False)

    def _game_sending(self) -> bool:
        tele = (self._last_status or {}).get("tele")
        return tele is not None and bool(getattr(tele, "active", True))

    def update_now(self, from_window: bool = True, auto: bool = False) -> None:
        """Download, verify and run the new installer (installed copies only). The installer closes this
        app and starts it again - with its window when the click came from the window. `auto`: started
        by _auto_tick once no game is running; it asks nothing and always comes back in the tray."""
        release = self.update_release
        if release is None or self._update_busy:
            return
        if not updater.is_installed_copy():
            if auto:
                return
            self.open_whats_new()                 # a source copy: the release page instead
            self._show_update(f"This copy runs from source, so it cannot update itself: get "
                              f"{APP_NAME} {release.version} from the release page.")
            return
        self._update_busy = True                  # before asking: a second click cannot start a second update
        if not auto and self._game_sending():
            self.show_window()                    # never a question hidden behind a full-screen game
            if not messagebox.askyesno(f"Update {APP_NAME}", UPDATE_CONFIRM, parent=self.root) \
                    or self.update_release is not release:
                self._update_busy = False
                self._arm_auto()                  # a tick may have come and gone while the question was open
                return
        self._cancel_auto()
        self._auto_update = auto
        if auto:
            from_window = False                   # an update nobody clicked never brings a window up
        else:
            self._mark_auto_asked()               # installing it counts as an answer to the question
        self._update_state = "busy"
        self._show_update(f"Downloading {APP_NAME} {release.version}{' to install it automatically' if auto else ''} ...",
                          buttons=False)
        threading.Thread(target=self._update_download_worker, args=(release, from_window, self._auto_kept),
                         name="update", daemon=True).start()

    def _update_download_worker(self, release, show_window: bool, kept=None) -> None:
        try:
            fresh = updater.check()               # still offered, and still the version clicked?
            if fresh is None or fresh.version != release.version or self._skipped(fresh.version):
                self.run_on_ui(lambda: self._update_withdrawn(release, fresh))
                return
            if (kept is not None and fresh.sha256 and kept[:2] == (fresh.version, fresh.sha256)
                    and kept[2].size == fresh.installer.size and Path(kept[2].path).is_file()):
                verified = kept[2]                # checked before, still the same file on GitHub; the
            else:                                 # installer re-hashes it right before it runs anyway
                verified = updater.download(fresh)
        except Exception as exc:
            error = str(exc)                      # `exc` is gone once the except block ends
            transient = isinstance(exc, updater.NetworkError)
            self.run_on_ui(lambda: self._update_failed(error, transient))
            return
        self.run_on_ui(lambda: self._install_update(fresh, verified, show_window))

    def _update_withdrawn(self, release, fresh=None) -> None:
        """GitHub no longer offers the version clicked (pulled, or replaced): install nothing, and offer
        what it offers now - unless that is nothing, or a skipped version."""
        self._update_busy, self._auto_update = False, False
        self._hide_update()
        self._offer_update(fresh)
        self.msg_var.set(f"{APP_NAME} {release.version} is no longer offered, so nothing was installed.")

    def _install_update(self, release, verified, show_window: bool) -> None:
        self.update_release, self._update_version = release, release.version
        if self._auto_update:
            consent = self._auto_may_run() and not self._skipped(release.version)
            if not (consent and self._game_idle() and self._user_away()):
                # switched off or skipped: throw the download away. A game started or the window opened
                # during the download: keep it for the next quiet moment (no second download).
                if consent:
                    self._keep_download(release, verified)
                else:
                    self._drop_kept()
                    updater.discard(verified.path)
                self._update_busy, self._auto_update = False, False
                if self.updates_enabled():
                    self._offer_update(release)   # waits again if automatic updates are still on
                else:
                    self._hide_update()
                return
            updater.log(f"installing {release.version} automatically (no game running)")
            self.cfg.setdefault("updates", {})["auto_done"] = release.version   # the new version says so once
            self._save_now()
        if self._auto_kept is not None and self._auto_kept[2] is not verified:
            self._drop_kept()                     # superseded by this download
        self._auto_kept = None                    # the installer uses this file now
        try:
            process = updater.run_installer(verified, show_window)
        except Exception as exc:
            updater.discard(verified.path)
            self._update_failed(str(exc))
            return
        self._show_update(f"Installing {APP_NAME} {release.version}: it closes and comes back by itself in a few "
                          f"seconds.", buttons=False)
        self._installer_watch = (process, time.monotonic())
        self.root.after(2000, self._watch_installer)

    def _watch_installer(self) -> None:
        """The installer quits this app when it works. If it ends first, or takes too long, say so."""
        if self._installer_watch is None:
            return
        process, started = self._installer_watch
        try:
            code = process.poll()
        except Exception:
            code = None
        if code is not None:
            self._installer_watch = None
            self._update_failed(f"the installer ended without updating (exit code {code})")
        elif time.monotonic() - started > INSTALLER_WAIT_S:
            self._installer_watch = None
            self._update_failed("the installer did not finish")
        else:
            self.root.after(2000, self._watch_installer)

    def _update_failed(self, error: str, transient: bool = False) -> None:
        """transient: the network failed (NetworkError), not the update itself."""
        self._update_busy, self._update_state = False, "failed"
        release = self.update_release
        auto, self._auto_update = self._auto_update, False
        upd = self.cfg.get("updates") or {}
        if upd.get("auto_done"):
            upd.pop("auto_done")
            self._save_now()
        if auto and transient and release is not None:
            updater.log(f"automatic update to {release.version} postponed: {error}")
            self._offer_update(release)           # the plain offer again, and a later try
            self._cancel_auto()
            self._arm_auto(updater.RETRY_AFTER_S[0])
            return
        if auto and release is not None:
            self._set_auto_failed(release.version)    # the bar takes over for this version, also after a restart
        updater.log(f"{'automatic ' if auto else ''}update to {release.version if release else '?'} failed: {error}")
        self._show_update(f"{'Automatic update' if auto else 'Update'} to "
                          f"{release.version if release else 'the new version'} failed: {error}. "
                          f"Nothing was installed; Update now tries again.")

    # -- automatic updates (updates.auto, off by default) ---------------------------------------
    def updates_auto(self) -> bool:
        return self.updates_enabled() and (self.cfg.get("updates") or {}).get("auto") is True

    def _should_ask_auto(self) -> bool:
        """The one-time question: never asked yet, automatic updates off, and an installed copy."""
        upd = self.cfg.get("updates") or {}
        return not upd.get("auto_asked") and upd.get("auto") is not True and updater.is_installed_copy()

    def answer_auto_update(self, yes: bool) -> None:
        """The update bar's Yes / No. Either answer is final: the question never comes back."""
        upd = self.cfg.setdefault("updates", {})
        upd["auto"], upd["auto_asked"] = bool(yes), True
        self._save_now()
        self.update_ask.pack_forget()
        if yes:
            self.msg_var.set("Updates now install by themselves once no game is running "
                             "(Advanced... > Install updates automatically).")
            self._arm_auto()
        else:
            self.msg_var.set("Updates stay manual: Update now installs them "
                             "(Advanced... > Install updates automatically).")

    def _mark_auto_asked(self) -> None:
        upd = self.cfg.setdefault("updates", {})
        if not upd.get("auto_asked"):
            upd["auto_asked"] = True
            self._save_now()
        self.update_ask.pack_forget()

    def _keep_download(self, release, verified) -> None:
        if self._auto_kept is not None and self._auto_kept[2] is not verified:
            self._drop_kept()
        self._auto_kept = (release.version, release.sha256, verified)

    def _drop_kept(self) -> None:
        if self._auto_kept is not None:
            updater.discard(self._auto_kept[2].path)
            self._auto_kept = None

    def _auto_may_run(self) -> bool:
        """Automatic updates may act: switched on, an installed copy, and not a launch with --no-start or
        without a tray icon (setup's relaunch would drop those flags)."""
        return (self.updates_auto() and updater.is_installed_copy() and not self._no_start
                and self.tray is not None and self.tray.active)

    def _user_away(self) -> bool:
        """Nobody is using OpenShaker itself: its window and any dialog of it are closed, and no test tone
        plays. An automatic update waits for that, so it never closes something the user is looking at."""
        if self.window_visible():
            return False
        try:
            if any(isinstance(w, tk.Toplevel) and w.winfo_viewable() for w in self.root.winfo_children()):
                return False
        except tk.TclError:
            return False
        tone = self._tone_thread
        return not (tone is not None and tone.is_alive())

    def _auto_blocked(self, version: str) -> bool:
        """An automatic update to `version` failed: in this session, or recorded in updates.auto_failed."""
        return bool(version) and version in (self._auto_failed, (self.cfg.get("updates") or {}).get("auto_failed") or "")

    def _set_auto_failed(self, version: str, save=None) -> None:
        self._auto_failed = version
        upd = self.cfg.setdefault("updates", {})
        if version:
            upd["auto_failed"] = version
        else:
            upd.pop("auto_failed", None)
        (save or self._save_now)()

    def _game_idle(self) -> bool:
        """Safe to install by itself: no game has sent data for AUTO_IDLE_S (the data Update now's question
        looks at), and no supported game runs on this PC."""
        if self._game_sending() or time.monotonic() - self._tele_seen_at < AUTO_IDLE_S:
            return False
        try:
            return not any(procs.is_running(exe) for exe in GAME_EXES)
        except Exception:
            return False

    def _arm_auto(self, delay_s: float = AUTO_TICK_S) -> None:
        """An update is on offer and automatic updates are on: look for a quiet moment (_auto_tick)."""
        release = self.update_release
        if (self._auto_job is not None or release is None or self._update_busy or not self._auto_may_run()
                or self._auto_blocked(release.version)):
            return
        self._auto_job = self.root.after(int(delay_s * 1000), self._auto_tick)

    def _cancel_auto(self) -> None:
        if self._auto_job is not None:
            try:
                self.root.after_cancel(self._auto_job)
            except tk.TclError:
                pass
            self._auto_job = None

    def _auto_tick(self) -> None:
        self._auto_job = None
        release = self.update_release
        if (release is None or self._update_busy or not self._auto_may_run() or self._skipped(release.version)
                or self._auto_blocked(release.version)):
            return
        if not (self._game_idle() and self._user_away()):
            self._arm_auto()                      # a game, its data lately, or the window open: look again later
            return
        self.update_now(auto=True)

    def _after_automatic_update(self, came_back: bool) -> None:
        """At start. updates.auto_done names the version an automatic update was installing:
        - this version: it worked, so the bar says so until an update is offered or OpenShaker restarts;
        - setup came back (--update-failed / --update-incomplete), or a newer version than this one: it
          did not, so updates.auto_failed holds it back from automatic updates (Update now still works).
        A recorded failure this version has reached (installed by hand) is cleared."""
        upd = self.cfg.get("updates") or {}
        failed = upd.get("auto_failed") or ""
        if failed and not updater.is_newer(failed, __version__):
            self._set_auto_failed("", self._save_quietly)
        done = upd.get("auto_done")
        if not done:
            return
        upd.pop("auto_done")
        self._save_quietly()
        self._device_warned = True                # an update nobody watched: no "device not found" toast now
        if done == __version__ and not came_back:
            updater.log(f"now running {__version__}, installed automatically")
            self._notes_version, self._update_sticky = done, True
            self._show_update(f"{APP_NAME} updated itself to {__version__}.", buttons=("news",))
        elif came_back or updater.is_newer(done, __version__):
            updater.log(f"automatic update to {done} did not complete; not tried again automatically")
            self._set_auto_failed(done, self._save_quietly)

    # -- output device ----------------------------------------------------------------------
    def _device_label(self, name: str) -> str:
        return name if str(name or "").strip() else self.DEFAULT_OUTPUT

    def _fill_devices(self) -> None:
        """Every output on a shared host API, read afresh each time the list opens."""
        try:
            names = AudioOutput.shared_outputs()
        except Exception as exc:
            names = []
            self.msg_var.set(f"Could not list the audio outputs: {type(exc).__name__}: {exc}")
        values = [self.DEFAULT_OUTPUT] + names
        current = str(self.cfg["audio"].get("device", "") or "")
        if current and current not in values:
            values.insert(1, current)            # a saved device that is unplugged right now stays visible
        self.device_box["values"] = values

    def _device_picked(self, _event=None) -> None:
        label = self.device_var.get()
        name = "" if label == self.DEFAULT_OUTPUT else label
        if name == str(self.cfg["audio"].get("device", "") or ""):
            return
        self.cfg["audio"]["device"] = name
        self._device_warned = False
        self._save_now()
        self._restart_if_on()
        if self.is_running():
            self.msg_var.set(f"Output: {label}. Start with the amplifier turned down and use Test tone.")

    # -- presets -------------------------------------------------------------------------------
    def _preset(self, key: str) -> dict:
        for entry in self.presets:
            if entry["key"] == key:
                return entry
        return self.presets[0] if self.presets else {"key": key, "label": key, "profile": None}

    def _bases(self, key: str) -> tuple[dict, dict]:
        """(gains, enabled) a preset's profile was calibrated at - what 100% means for it.

        Read straight from the profile file, so a preset can be edited while a different one is
        playing, or with no game running at all.
        """
        if key not in self._preset_bases:
            probe = config.load(None)
            try:
                config.apply_profile(probe, config.resolve_profile(self.cfg, self._preset(key)["profile"]),
                                     keep_user={})
            except Exception:
                pass
            self._preset_bases[key] = (probe.get("_base_gains", {}), probe.get("_base_enabled", {}))
        return self._preset_bases[key]

    def _select_preset(self, key: str) -> None:
        """Show a preset's saved strengths, whether or not it is the one currently playing."""
        if key != self.preset_key:
            box = self._boxes.get("open")
            if box is not None and box is not self.master_box:
                self._dropped_typing = box.edited
                self._close_box(apply=False)     # a half-typed strength belongs to the preset it was typed for
            if any(grip.held for grip in self._strength_grips):
                end_slider_drags(self.root, self._strength_grips)   # a held strength drag must not write here
        self.preset_key = key
        entry = self._preset(key)
        self.preset_var.set(entry["label"])
        stored = (config.preset_settings(self.cfg, key).get("effects") or {})
        gains, enabled = self._bases(key)
        for name, (en, trim, lbl) in self.effect_vars.items():
            params = stored.get(name) or {}
            en.set(bool(params.get("enabled", enabled.get(name, True))))
            trim.set(round(float(params.get("trim", 1.0)) * 100.0, 1))
            lbl.set(f"{float(trim.get()):3.0f}%")
        self._sync_preset_note()

    def _sync_preset_note(self) -> None:
        if self.preset_key == self.active_preset:
            live = "active" if self.is_running() else "loaded"
            self.preset_note.set(f"({live} - editing changes what you feel now)")
        else:
            self.preset_note.set(f"(editing; {self._preset(self.active_preset)['label']} is active)")

    def _preset_picked(self, _event=None) -> None:
        self._close_box()                        # picked by hand (even the mouse wheel): apply the typing first
        label = self.preset_var.get()
        for entry in self.presets:
            if entry["label"] == label:
                self._select_preset(entry["key"])
                break
        if self.preset_key != self.active_preset and not self.is_running():
            # nothing is playing, so make the chosen one the one that will play
            self._make_active(self.preset_key)

    def _make_active(self, key: str) -> None:
        entry = self._preset(key)
        path = str(config.resolve_profile(self.cfg, entry["profile"]))
        try:
            config.apply_profile(self.cfg, path, preset=key)
        except Exception as exc:
            self.msg_var.set(f"Could not load {entry['label']}: {type(exc).__name__}: {exc}")
            return
        self.cfg["profile"] = path
        self.active_preset = key
        self._sync_preset_note()

    def _save_soon(self) -> None:
        """Strengths save themselves a moment after you stop dragging."""
        if self._save_job is not None:
            try:
                self.root.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.root.after(800, self._save_now)

    def _save_now(self) -> bool:
        self._save_job = None
        self.cfg["audio"]["master_gain"] = float(self.master_var.get())
        try:
            config.save_user(self.cfg, self.config_path)
        except OSError as exc:
            self._save_error = str(exc)
            self.msg_var.set(f"Could not save settings: {exc}")
            return False
        self._saved_switch = self.cfg.get("haptics_on", True) is not False
        return True

    def reset_to_profile(self) -> None:
        """Put the preset being edited back to the level it ships with."""
        self._close_box(apply=False)
        _gains, enabled = self._bases(self.preset_key)
        for name, (en, trim, _lbl) in self.effect_vars.items():
            en.set(bool(enabled.get(name, True)))
            trim.set(100.0)
            self._effect_changed(name)
        self.msg_var.set(f"{self._preset(self.preset_key)['label']}: back to 100% (the shipped level).")

    # -- advanced settings (ports and scales that used to be config.json only) ----------------
    ADVANCED_FIELDS = [
        ("Forza / Horizon Data Out port", ("sources", "forza", "port"), int),
        ("BeamNG OutGauge port", ("sources", "beamng", "port"), int),
        ("BeamNG Motion Sim port (0 = same as OutGauge)", ("sources", "beamng", "motion_port"), int),
        ("ACE poll rate (Hz)", ("sources", "ace", "poll_hz"), float),
        ("ACE suspension travel scale (m)", ("sources", "ace", "susp_scale_m"), float),
        ("Trackmania Data Sender port", ("sources", "trackmania", "port"), int),
        ("Forza listen address (0.0.0.0 also takes an Xbox or another PC)", ("sources", "forza", "host"), str),
        ("Output channel", ("audio", "channels"), "channel"),
        ("Check for updates (asks GitHub once a day)", ("updates", "check"), bool),
        ("Install updates automatically (when no game is running)", ("updates", "auto"), bool),
    ]

    def _cfg_at(self, path: tuple):
        node = self.cfg
        for key in path[:-1]:
            node = node.setdefault(key, {})
        return node, path[-1]

    def advanced(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Advanced settings")
        win.transient(self.root)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        entries = []
        for row, (label, path, cast) in enumerate(self.ADVANCED_FIELDS):
            node, key = self._cfg_at(path)
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            if cast == "channel":
                var = tk.StringVar(value=channel_choice(node.get(key)))
                ttk.Combobox(frame, textvariable=var, state="readonly", width=22,
                             values=list(CHANNEL_CHOICES)).grid(row=row, column=1, sticky="we", padx=(12, 0))
            elif cast is bool:
                var = tk.BooleanVar(value=node.get(key, True) is not False)
                ttk.Checkbutton(frame, variable=var).grid(row=row, column=1, sticky="w", padx=(12, 0))
            else:
                var = tk.StringVar(value=str(node.get(key, "")))
                ttk.Entry(frame, textvariable=var, width=24).grid(row=row, column=1, sticky="we", padx=(12, 0))
            entries.append((path, cast, var))
        last = len(self.ADVANCED_FIELDS)
        ttk.Label(frame, text="OK saves these; haptics that are on restart to use them.",
                  foreground="#555").grid(row=last, column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(frame)
        btns.grid(row=last + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def apply() -> None:
            try:
                values = []
                for path, cast, var in entries:
                    node, key = self._cfg_at(path)
                    if cast is bool:
                        values.append(((node, key), bool(var.get())))
                        continue
                    raw = var.get().strip()
                    if cast == "channel":
                        value = list(CHANNEL_CHOICES.get(raw, node.get(key) or [0]))
                    else:
                        value = cast(raw)
                    values.append(((node, key), value))
            except ValueError as exc:
                messagebox.showerror("Advanced settings", f"Not a number: {exc}", parent=win)
                return
            win.destroy()
            self._apply_advanced(values)

        ttk.Button(btns, text="OK", command=apply).pack(side="right")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=(0, 8))
        win.grab_set()

    def _apply_advanced(self, values: list) -> None:
        """Advanced OK, after its fields were checked: [((node, key), value), ...]."""
        auto_before = (self.cfg.get("updates") or {}).get("auto") is True
        for (node, key), value in values:
            node[key] = value
        upd = self.cfg.setdefault("updates", {})
        if (upd.get("auto") is True) != auto_before:
            upd["auto_asked"] = True              # chosen here: the update bar never asks
            self.update_ask.pack_forget()
        self._save_now()
        if self.updates_auto():
            self._arm_auto()
        else:
            self._cancel_auto()
            self._drop_kept()
        if not self.updates_enabled():
            self._schedule_update_check(0)            # off: cancels the next check; nothing asks GitHub
            if self.update_release is not None and not self._update_busy:
                self._hide_update()
        elif self._update_job is None:
            self._schedule_update_check(updater.CHECK_DELAY_S)
        self._restart_if_on()
        self.msg_var.set("Advanced settings saved and applied." if self.haptics_on else
                         "Advanced settings saved; they apply when the haptics are switched on.")

    # -- live tuning --------------------------------------------------------------------------------
    def _close_box(self, apply: bool = True) -> None:
        box = self._boxes.get("open")
        if box is not None:
            box.finish(apply)

    def _click_away(self, event) -> None:
        box = self._boxes.get("open")
        if box is not None and event.widget is not box.entry:
            box.finish(True)

    def _slider_moved(self, name: str) -> None:
        """Strength sliders move in whole percent, like the number next to them."""
        _en, trim, _lbl = self.effect_vars[name]
        pct = round(float(trim.get()))
        if pct != float(trim.get()):
            trim.set(pct)
        self._effect_changed(name)

    def _type_strength(self, name: str, text: str) -> bool:
        value = parse_percent(text)
        if value is None:
            if text.strip():
                self.msg_var.set(f"'{text.strip()}' is not a number: type a strength from 0 to 200 (%).")
            return False
        pct = round(min(max(value, 0.0), 200.0))
        if not 0.0 <= value <= 200.0:
            self.msg_var.set(f"Strengths go from 0 to 200 %, so {EFFECT_LABELS.get(name, name)} is at {pct} %.")
        _en, trim, _lbl = self.effect_vars[name]
        trim.set(pct)
        self._effect_changed(name)
        return True

    def _type_master(self, text: str) -> bool:
        value = parse_percent(text)
        if value is None:
            if text.strip():
                self.msg_var.set(f"'{text.strip()}' is not a number: type the master level from 0 to 100 (%).")
            return False
        pct = round(min(max(value, 0.0), 100.0))
        if not 0.0 <= value <= 100.0:
            self.msg_var.set(f"Master goes from 0 to 100 %, so it is at {pct} %.")
        self.master_var.set(pct / 100.0)
        self._master_changed(None)
        return True

    def _master_step(self, step: float):
        self.master_scale.set(float(self.master_var.get()) + step)   # clamps, then _master_changed snaps
        return "break"

    def _master_changed(self, _v) -> None:
        g = round(float(self.master_var.get()), 2)      # whole percent, like the number next to it
        if g != float(self.master_var.get()):
            self.master_var.set(g)
        self.master_lbl.set(f"{g * 100:.0f}%")
        self.cfg["audio"]["master_gain"] = g
        if self.rt is not None:
            self.rt.set_master(g)
        self._save_soon()                        # a lowered master must still be lowered after a restart

    def _effect_changed(self, name: str) -> None:
        """Edits belong to the preset on screen; the audio only moves if that preset is playing."""
        en, trim, lbl = self.effect_vars[name]
        t = round(float(trim.get()) / 100.0, 4)
        enabled = bool(en.get())
        lbl.set(f"{float(trim.get()):3.0f}%")
        _gains, profile_on = self._bases(self.preset_key)
        config.set_preset_effect(self.cfg, self.preset_key, name, trim=t, enabled=enabled,
                                 profile_enabled=profile_on.get(name))   # a switch equal to the profile's follows it
        if self.preset_key == self.active_preset:
            self.cfg["effects"].setdefault(name, {})["enabled"] = enabled
            if self.rt is not None:
                self.rt.set_trim(name, t)                  # profile gain * trim, applied live
                self.rt.set_effect(name, enabled=enabled)
            else:
                gains, _ = self._bases(self.preset_key)
                e = self.cfg["effects"].setdefault(name, {})
                e["trim"], e["gain"] = t, gains.get(name, 1.0) * t
        self._save_soon()

    # -- polling ---------------------------------------------------------------------------------------
    def poll(self) -> None:
        try:
            self._drain_ui_queue()
            if self.rt is not None and self.rt.running and self.rt.audio_lost():
                self._audio_lost()
            if self._keep_running and not self.is_running() and time.monotonic() >= self._retry_at:
                self._retry_at = time.monotonic() + self._retry_interval()
                self.start()                  # the shaker may have been asleep when Windows booted
            self._refresh()
            self._refresh_tray()
        except Exception:
            traceback.print_exc()
        self.root.after(150, self.poll)

    def _refresh_tray(self, force: bool = False) -> None:
        """Once a second (or now, when forced), recompute what the tray menu and tooltip say."""
        self._tray_tick = (self._tray_tick + 1) % 7
        if (self._tray_tick and not force) or self.tray is None or not self.tray.active:
            return
        st, lines = self._last_status, dict(self._tray_lines)
        if st is None:
            starting = not self.start_error
            lines.update({"state": "Haptics: starting..." if starting else "Haptics: NOT running",
                          "game": "Game: -", "profile": "Profile: -", "output": "Output: -",
                          "error": "" if starting else f"Problem: {self.start_error}"})
            title = f"{APP_NAME} - starting" if starting else f"{APP_NAME} - NOT running"
            if not self.haptics_on:
                lines["state"] = "Haptics: off (--no-start)" if self._no_start else "Haptics: off"
                lines["error"], title = "", f"{APP_NAME} - haptics off"
        else:
            drops = f", {st['xruns']} dropouts" if st["xruns"] else ""
            lines["state"] = f"Haptics: running ({st['device'] or 'no audio device'}{drops})"
            tele = st["tele"]
            if tele is None:
                lines["game"] = "Game: none detected (waiting for telemetry)"
            else:
                src = next((x for x in st["sources"] if x["name"] == tele.source), None)
                fps = f" at {src['fps']:.0f} fps" if src else ""
                paused = " (paused)" if not tele.active else ""
                lines["game"] = f"Game: {st['game'] or tele.source}{fps}{paused}"
            prof = Path(st["profile"]).parent.name if st.get("profile") else "defaults"
            lines["profile"] = f"Profile: {prof}" + (" (chosen by hand)" if st.get("manual_profile") else "")
            db = st["peak_db"]
            lines["output"] = "Output: silent" if db <= -100 else f"Output: {db:.1f} dBFS"
            bad = st["audio_error"] or next((x["status"] for x in st["sources"] if x["error"]), "")
            lines["error"] = f"Problem: {bad}" if bad else ""
            game = st["game"] or ("no game" if tele is None else tele.source)
            title = f"{APP_NAME} - running - {game}"
        self._tray_lines = lines
        self.tray.refresh(title, st is not None, tuple(lines.values()))

    def _refresh(self) -> None:
        self._refresh_outputs()
        if self.rt is None or not self.rt.running:
            self._last_status = None
            state = (("Haptics off (--no-start) - Haptics on starts them" if self._no_start else "Haptics off")
                     if not self.haptics_on
                     else "Starting..." if not self.start_error
                     else f"Not running: {self.start_error} - retrying every {self._retry_interval():.0f} s")
            if self.status_var.get() != state:
                self.status_var.set(state)
            return
        st = self._last_status = self.rt.status()
        if st.get("tele") is not None:                # any game's data, paused or not: not the time to update
            self._tele_seen_at = time.monotonic()
        dev = f"{st['device']} @ {st['sr']} Hz, {st['latency_ms']:.0f} ms"
        extra = f", {st['xruns']} dropouts" if st["xruns"] else ""
        prof = Path(st["profile"]).parent.name if st.get("profile") else "defaults"
        game = st.get("game") or "no game"
        self.status_var.set(f"Running -> {dev}{extra}   |   {game} -> profile {prof}")
        if st.get("preset") and st["preset"] != self.active_preset:
            self.active_preset = st["preset"]              # the detected game owns what is playing
            self.rt.profile_changed = False
            self._select_preset(self.active_preset)
            dropped = " The number you were typing was not applied." if self._dropped_typing else ""
            self._dropped_typing = False
            self.msg_var.set(f"{self._preset(self.active_preset)['label']} preset is active ({game}).{dropped}")
        elif self.rt.profile_changed:
            self.rt.profile_changed = False
            self._sync_preset_note()
        if st["audio_error"]:
            self.status_var.set(f"Audio error: {st['audio_error']}")

        self.sources_var.set("\n".join(f"{SOURCE_LABELS.get(s['name'], s['name'])}: {s['status']}"
                                       for s in st["sources"]))          # one game per line
        tele = st["tele"]
        if tele is None:
            self.src_var.set("no game detected (waiting for telemetry)")
            for v in self.tele_vars.values():
                v.set("-")
        else:
            src = next((s for s in st["sources"] if s["name"] == tele.source), None)
            fps = src["fps"] if src else 0.0
            phase = f"  [{src['phase']}]" if src and src["phase"] else ""
            paused = "" if tele.active else "  (paused)"
            self.src_var.set(f"{SOURCE_LABELS.get(tele.source, tele.source)}  {fps:.0f} fps{phase}{paused}")
            g = 9.81
            gear = "R" if tele.gear < 0 else ("N" if tele.gear == 0 else str(tele.gear))
            self.tele_vars["rpm"].set(f"{tele.rpm:5.0f}/{tele.max_rpm:.0f}")
            self.tele_vars["gear"].set(gear)
            self.tele_vars["speed"].set(f"{tele.speed * 3.6:5.1f} km/h")
            self.tele_vars["thr"].set(f"{tele.throttle * 100:3.0f} %")
            self.tele_vars["brk"].set(f"{tele.brake * 100:3.0f} %")
            self.tele_vars["glong"].set(f"{tele.accel_long / g:+.2f}")
            self.tele_vars["glat"].set(f"{tele.accel_lat / g:+.2f}")
            self.tele_vars["gvert"].set(f"{tele.accel_vert / g:+.2f}")
        db = st["peak_db"]
        self.level_bar["value"] = max(0.0, 60.0 + db)
        self.level_var.set("-inf dB" if db <= -100 else f"{db:5.1f} dB")
        for name, bar in self.effect_bars.items():
            bar["value"] = min(1.0, st["levels"].get(name, 0.0))

    def _rewrap(self, event) -> None:
        """The window's content changed size: wrap the status and source lines at its width, so a long line
        (Trackmania's "waiting for Openplanet Data Sender ..." one) never makes the window wider."""
        width = max(WRAP_MIN, int(event.width) - 40)
        if width != getattr(self, "_wrap_width", None):
            self._wrap_width = width
            for label in (self.status_label, self.sources_label):
                label.configure(wraplength=width)
            self.hint_label.configure(wraplength=width - 24)      # inside the Effects frame's border and padding

    # -- tray-facing API -----------------------------------------------------------------------
    def run_on_ui(self, fn) -> None:
        """Queue a call for the Tk thread.

        Tray menu actions and the "another launch wants the window" message both arrive on other
        threads, and Tk raises "main thread is not in main loop" if they touch it directly - which
        is exactly the kind of failure that disappears into a worker thread. poll() drains this.
        """
        self._ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                traceback.print_exc()

    def window_visible(self) -> bool:
        try:
            return self.root.state() == "normal"
        except tk.TclError:
            return False

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide_window(self) -> None:
        self.root.withdraw()

    def is_running(self) -> bool:
        return self.rt is not None and self.rt.running

    # -- optional outputs (outputs.py) ---------------------------------------------------------------
    def _output_guard(self, output, what: str, fn, *args):
        """An output's trouble is a message, never an exception in the window."""
        try:
            return fn(*args)
        except Exception as exc:
            note = f"{getattr(output, 'name', 'output')}: {what} failed: {type(exc).__name__}: {exc}"
            if hasattr(self, "msg_var"):
                self.msg_var.set(note)
            else:                                    # still building the window: say it on the first refresh
                self._output_notes.append(note)
            return None

    def _place_output_rows(self, parent, first_row: int) -> None:
        """Each output builds its own row (Tk thread); the window only puts it in place."""
        for i, output in enumerate(self.outputs):
            build = getattr(output, "build_row", None)
            widget = self._output_guard(output, "building its row", build, parent) if build else None
            if widget is not None:
                widget.grid(row=first_row + i, column=0, columnspan=3, sticky="we", pady=(6, 0))
                self.output_rows[output.name] = widget

    def output_tray_line(self, output):
        """The output's tray status line, or None. Called from pystray's thread: no Tk here."""
        try:
            line = output.tray_line() if hasattr(output, "tray_line") else None
        except Exception as exc:
            return f"{getattr(output, 'name', 'output')}: {type(exc).__name__}"
        return str(line) if line is not None else None

    def stop_output(self, output) -> None:
        """The tray's "Stop ..." item. The output's stop_now() is thread-safe, so no Tk thread hop."""
        try:
            output.stop_now()
        except Exception:
            pass

    def _refresh_outputs(self) -> None:
        if self._output_notes:
            self.msg_var.set("; ".join(self._output_notes))
            self._output_notes = []

    def tray_line(self, key: str) -> str:
        return self._tray_lines.get(key, "")

    def _notify_device_missing(self) -> None:
        """Once per session in the tray; the window's status line says it for as long as it lasts."""
        if self._device_warned:
            return
        self._device_warned = True
        if not self.window_visible() and self.tray is not None:
            self.tray.notify("The output device was not found. Open the window and pick your shaker "
                             "under Output > Device.")

    def _audio_lost(self) -> None:
        """The output stopped playing (unplugged, switched off): say so and keep retrying, so the haptics
        come back by themselves when the device does."""
        device = getattr(getattr(self.rt, "audio", None), "device_name", "") or "The output device"
        self._stop_runtime()
        self.start_error = f"{device} stopped playing - unplugged or switched off?"
        self._lost_at = time.monotonic()
        self._retry_at = self._lost_at + LOST_RETRY_SECONDS
        self.msg_var.set(f"{self.start_error} Retrying; Restart haptics tries again now.")
        if not self.window_visible() and self.tray is not None:
            self.tray.notify(f"{device} stopped playing. {APP_NAME} picks it up again when it is back.")
        self._device_warned = True             # this said it already; no second "not found" toast

    def _retry_interval(self) -> float:
        return LOST_RETRY_SECONDS if time.monotonic() - self._lost_at < LOST_FAST_WINDOW else RETRY_SECONDS

    def report_error(self, title: str, detail: str) -> None:
        """A hidden tray app must not block on a modal dialog nobody can see."""
        self.msg_var.set(f"{title}: {detail}")
        if self.window_visible():
            messagebox.showerror(title, detail)
        elif self.tray is not None:
            self.tray.notify(f"{title}: {detail}")

    def windows_startup_enabled(self) -> bool:
        from . import autostart
        return autostart.is_enabled()

    def toggle_windows_startup(self) -> None:
        from . import autostart
        try:
            if autostart.is_enabled():
                autostart.disable()
                self.msg_var.set(f"{APP_NAME} will no longer start with Windows.")
            else:
                autostart.enable()
                self.msg_var.set(f"{APP_NAME} will start with Windows, in the tray.")
            self.cfg["windows_startup_asked"] = True
            self._save_quietly()
        except OSError as exc:
            self.msg_var.set(f"Could not change the Windows startup entry: {exc}")
        self._startup_changed()

    def _startup_changed(self) -> None:
        """Show the startup entry as it now is: the window's box, and the tray's tick (which pystray reads
        only when it builds the menu)."""
        from . import autostart
        self.startup_var.set(autostart.is_enabled())
        if self.tray is not None:
            self.tray.update_menu()

    def _save_quietly(self) -> None:
        from . import config
        try:
            config.save_user(self.cfg, self.config_path)
        except OSError:
            return
        self._saved_switch = self.cfg.get("haptics_on", True) is not False

    def _setup_windows_startup(self, hidden: bool = False) -> None:
        """Starting with Windows is opt-in. The first time the window opens the app asks once and
        remembers the answer (`windows_startup_asked`), so nothing is registered without a yes.
        Later launches only refresh a stale command (the app folder moved, or the venv was rebuilt).
        """
        from . import autostart
        try:
            if autostart.migrate_legacy():         # an entry under the app's old name moves to this one
                self.cfg["windows_startup_asked"] = True
                self._save_quietly()
            if autostart.is_enabled() and not autostart.is_current():
                autostart.enable()
            self.startup_var.set(autostart.is_enabled())
        except OSError:
            pass
        if paths.is_frozen() and not self.cfg.get("windows_startup_asked"):
            self.cfg["windows_startup_asked"] = True       # the installer already offered it
            self._save_quietly()
        if self.ask_startup and not hidden and not self.cfg.get("windows_startup_asked"):
            self.root.after(1500, self.ask_windows_startup)

    def ask_windows_startup(self, answer: bool | None = None) -> None:
        """The one-time question; `answer` skips the dialog."""
        from . import autostart
        if self.cfg.get("windows_startup_asked"):
            return
        if answer is None:
            answer = messagebox.askyesno(
                APP_NAME, f"Start {APP_NAME} with Windows?\n\nIt would wait in the notification area and "
                "play haptics whenever a supported game sends telemetry. You can change this at any time "
                "with the Start with Windows box.", parent=self.root)
        try:
            if answer and not autostart.is_enabled():
                autostart.enable()
        except OSError as exc:
            self.msg_var.set(f"Could not add the Windows startup entry: {exc}")
        self.cfg["windows_startup_asked"] = True
        self._startup_changed()
        self._save_quietly()

    def quit_app(self) -> None:
        try:
            self._save_now()
            self._stop_runtime()
        finally:
            for output in self.outputs:
                try:
                    output.close()
                except Exception:
                    pass
            if self.tray is not None:
                self.tray.stop()
            if self.listener is not None:
                self.listener.close()
            self.root.destroy()

    def on_close(self) -> None:
        """The X button hides to the tray - haptics keep running - and only Quit really exits."""
        if self.tray is not None and self.tray.active:
            self.hide_window()
            self.tray.notify("Still running here. Right-click for status, left-click to open.",
                             once=True)
        else:
            self.quit_app()


def ensure_tcl() -> None:
    """Make Tk work from the venv: a Windows venv has no tcl/ directory of its own, and Tcl then
    looks for init.tcl in places that do not exist (see gui_error.log). Point it at the base
    interpreter's copy before the first Tk() call; a TCL_LIBRARY already set is left alone.
    """
    if os.environ.get("TCL_LIBRARY") or paths.is_frozen():      # PyInstaller sets up Tcl/Tk itself
        return
    base = Path(getattr(sys, "base_prefix", sys.prefix)) / "tcl"
    tcl = sorted(base.glob("tcl8.*"))
    tk_lib = sorted(base.glob("tk8.*"))
    if tcl and tk_lib:
        os.environ["TCL_LIBRARY"], os.environ["TK_LIBRARY"] = str(tcl[-1]), str(tk_lib[-1])


def run_gui(cfg: dict, config_path: str, hidden: bool = False, start_haptics: bool = True,
            use_tray: bool = True, listener=None, update_result: tuple | None = None) -> int:
    ensure_tcl()
    root = tk.Tk()
    app = App(root, cfg, config_path, hidden=hidden, start_haptics=start_haptics, use_tray=use_tray,
              update_result=update_result)
    if listener is not None:
        connect_listener(app, listener)
    root.mainloop()
    return 0


def connect_listener(app: App, listener) -> None:
    """A second launch raises this window; --quit (and the installer) quits this copy cleanly."""
    listener.on_show = lambda: app.run_on_ui(app.show_window)
    listener.on_quit = lambda: app.run_on_ui(app.quit_app)
    app.listener = listener


def quit_running(timeout: float = 10.0) -> bool | None:
    """--quit: ask a running copy (the tray app or a console run) to quit and wait until it has gone.

    None when nothing was running, True once it has gone, False if it was still there after `timeout`.
    """
    from . import single_instance
    if not single_instance.signal_existing(single_instance.QUIT):
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not single_instance.is_running() and not single_instance.mutex_held():
            return True
        time.sleep(0.2)
    return False


def _start_menu_entry() -> None:
    """A copy run from source adds itself to the Start menu once (the installer does it otherwise)."""
    try:
        from . import autostart
        autostart.ensure_start_menu_entry()
    except Exception:
        pass                                     # a missing Start menu entry must never stop the app


def _startup_failure(message: str, details: str | None = None) -> None:
    """The app could not get as far as its window: leave the reason in logs/gui_error.log and show it."""
    try:
        log = paths.log_dir() / "gui_error.log"
        log.write_text(message + (f"\n\n{details}" if details else "") + "\n", encoding="utf-8")
    except OSError:
        log = None
    try:
        ensure_tcl()
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message + (f"\n\nDetails: {log}" if log else ""), parent=root)
        root.destroy()
    except Exception:
        pass


def installer_result(args) -> tuple | None:
    """("failed" or "incomplete", "X.Y.Z" or "") from --update-failed=X.Y.Z / --update-incomplete=X.Y.Z,
    which setup passes when it starts this copy again after a silent update stopped (see DeinitializeSetup
    in installer/OpenShaker.iss). A value that is no X.Y.Z version is dropped."""
    for arg in args:
        for how in ("failed", "incomplete"):
            flag = f"--update-{how}"
            if arg == flag or arg.startswith(flag + "="):
                version = updater.parse_version(arg[len(flag) + 1:])
                return how, ".".join(map(str, version)) if version else ""
    return None


def main(argv=None) -> int:
    """Entry for OpenShaker.exe and openshaker/app.pyw. Errors go to logs/gui_error.log in the settings folder.

    --hidden    start in the tray with no window (what the Windows startup entry uses)
    --no-start  haptics off for this launch only, until Haptics on or Restart haptics (frees the game ports for
                the calibration tools); the saved switch is left as it is
    --no-tray   window only, no notification-area icon
    --quit      ask a running copy to quit, wait until it has gone, and exit (the installer uses it)
    --update-failed=X.Y.Z      setup started this copy again after a silent update to X.Y.Z failed before
                               replacing any file: the bar says so, and the update is offered again
    --update-incomplete=X.Y.Z  ... after it stopped partway through the files: the bar asks for the
                               installer to be run again from the release page
    """
    from . import config, single_instance
    args = list(sys.argv[1:] if argv is None else argv)
    if "--quit" in args:
        gone = quit_running()
        print({None: f"{APP_NAME} is not running.", True: f"{APP_NAME} has quit.",
               False: f"{APP_NAME} did not quit within 10 s."}[gone])
        return 1 if gone is False else 0
    listener = single_instance.acquire()
    if listener is None:
        if single_instance.signal_existing():  # already running: raise its window and leave
            return 0
        _startup_failure(
            f"{APP_NAME} could not start: another copy seems to be running but does not answer, or another "
            f"program is using its local port {single_instance.PORT}.\n\nQuit {APP_NAME} from the tray, or end "
            f"OpenShaker.exe in Task Manager, and start it again.")
        return 1
    single_instance.hold_app_mutex()           # lets the installer see that the app is running
    threading.Thread(target=_start_menu_entry, name="start-menu", daemon=True).start()
    config_path = str(paths.config_path())
    try:
        paths.migrate_config()                 # settings from an earlier version, copied once
        return run_gui(config.load(config_path), config_path,
                       hidden="--hidden" in args, start_haptics="--no-start" not in args,
                       use_tray="--no-tray" not in args, listener=listener,
                       update_result=installer_result(args))
    except Exception:
        _startup_failure(f"{APP_NAME} failed to start.", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
