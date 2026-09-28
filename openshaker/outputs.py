"""Extra outputs beside the shaker.

An output runs alongside the audio while the haptics run: the Runtime starts it once everything else
is up, tells it when the game's preset changes, asks it for its status and stops it before the
sources stop. Every call is guarded, so a failing output never stops the haptics.

Outputs come from optional packages (`openshaker.<name>`, with a `make_output()` that returns an
Output) that are not part of this repository and never part of the installer: usually the package is
simply absent, and then nothing changes at all. Only the window loads them, so the console runner, `--log` recordings
and the tests never arm one.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable, Optional

OPTIONAL_PACKAGES = ("wheel",)       # optional local extras


@dataclass
class OutputContext:
    sources: list                                    # the runtime's live sources: read latest() only
    cfg: dict                                        # read-only
    demo: bool
    log_dir: Optional[str]
    preset: Callable[[], Optional[str]]              # the preset (game) playing right now


class Output:
    """What an output provides (duck-typed: an output need not subclass this). Nothing may raise into
    the app; the Runtime and the window guard every call anyway."""

    name = "output"                  # short id, used in messages
    label = ""                       # what the user calls it, e.g. "extra output" (default: the name)
    stop_label = ""                  # its tray item (default: "Stop <label>")

    # -- lifecycle, called by the Runtime -----------------------------------------------------------
    def start(self, ctx: OutputContext) -> None:
        """Non-blocking; the output owns its threads. Called whenever the haptics start."""

    def stop(self) -> None:
        """The haptics are stopping; never raises."""

    def on_preset(self, preset: Optional[str], profile: Optional[str]) -> None:
        """The game's preset (and its profile file) changed. Tk thread."""

    def status(self) -> dict:
        """{"state", "summary", "problem"}; thread-safe."""
        return {"state": "off", "summary": "", "problem": ""}

    def close(self) -> None:
        """The app is quitting for good; never raises."""

    # -- its own user interface ---------------------------------------------------------------------
    def build_row(self, parent):
        """Its row in the window (a Tk widget), or None for none. Tk thread only."""
        return None

    def tray_line(self) -> Optional[str]:
        """A status line for the tray menu, or None. Thread-safe, never touches Tk."""
        return None

    def stop_now(self) -> None:
        """The tray's "Stop ..." item. Thread-safe, never touches Tk."""


def stop_label(output) -> str:
    """The tray item that stops an output: its own `stop_label`, else "Stop <label>"."""
    label = getattr(output, "label", None) or getattr(output, "name", None) or "output"
    return getattr(output, "stop_label", None) or f"Stop {label}"


def _problem(name: str, exc: BaseException) -> str:
    text = f"{name}: {type(exc).__name__}: {exc}"
    return text if len(text) <= 200 else text[:197] + "..."


def load_optional_outputs() -> tuple[list, list]:
    """The outputs of the optional packages that are present, and a message for each one that is there
    but broken. A package that cannot be imported at all - absent (the public build), or missing
    something it needs (ImportError) - gives no output and no message. Anything else its import or its
    make_output() raises (a half-written file's SyntaxError, a NameError, a DLL's OSError, even
    sys.exit) is one message, and the app carries on without it. Never raises."""
    outputs, problems = [], []
    for name in OPTIONAL_PACKAGES:
        module_name = ".".join((__package__ or "openshaker", name))   # built at run time: PyInstaller never follows it
        try:
            make_output = getattr(importlib.import_module(module_name), "make_output", None)
        except ImportError:
            continue
        except (Exception, SystemExit) as exc:
            problems.append(_problem(name, exc))
            continue
        if make_output is None:
            continue
        try:
            output = make_output()
        except (Exception, SystemExit) as exc:
            problems.append(_problem(name, exc))
            continue
        if output is not None:
            outputs.append(output)
    return outputs, problems
