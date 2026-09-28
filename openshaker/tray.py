"""Notification-area icon: left click opens the window, right click shows status and actions.

pystray owns a Win32 message loop, so it runs on its own thread and every menu action is handed
back to the Tk thread through App.run_on_ui(). The icon is colour while haptics are running and
grey while they are stopped or switched off (the Haptics on item), so the tray alone says whether
the app is working.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import APP_NAME

try:
    import pystray
    from PIL import Image, ImageOps
    IMPORT_ERROR = None
except Exception as exc:                              # pystray/Pillow missing: the window still works
    pystray = None
    Image = ImageOps = None
    IMPORT_ERROR = exc

AVAILABLE = IMPORT_ERROR is None
LINES = ("state", "game", "profile", "output")


def _images(icon_path: Path):
    """(running, stopped) icons: the second is the first desaturated."""
    base = Image.open(icon_path).convert("RGBA")
    if base.width > 128:                              # the tray wants a small image, not a 256 px one
        base = base.resize((64, 64), Image.LANCZOS)
    r, g, b, alpha = base.split()
    grey = ImageOps.grayscale(Image.merge("RGB", (r, g, b)))
    return base, Image.merge("RGBA", (grey, grey, grey, alpha))


class Tray:
    """Wraps a pystray Icon around an App. Inert (active=False) when pystray is not installed."""

    def __init__(self, app, icon_path: Path) -> None:
        self.app = app
        self.icon = None
        self.active = False
        self._thread = None
        self._notified = False
        self._last_title = ""
        self._last_lines = ()
        if not AVAILABLE:
            return
        try:
            self._running_img, self._stopped_img = _images(icon_path)
            self.icon = pystray.Icon("openshaker", self._stopped_img, APP_NAME, self._menu())
        except Exception as exc:
            self.icon = None
            self.error = f"{type(exc).__name__}: {exc}"
            return
        self.active = True

    # -- menu ------------------------------------------------------------------------------
    def _ui(self, fn):
        """pystray calls actions on its own thread; bounce them onto Tk's."""
        def handler(_icon=None, _item=None) -> None:
            self.app.run_on_ui(fn)
        return handler

    def _line(self, key: str):
        return lambda _item=None: self.app.tray_line(key)

    def _output_items(self) -> list:
        """Per optional output: its status line (while it has one) and its "Stop ..." item. Both run on
        pystray's thread, which the outputs' tray_line() and stop_now() are made for."""
        from .outputs import stop_label
        item, items = pystray.MenuItem, []
        for output in getattr(self.app, "outputs", ()):
            items.append(item(lambda _i, o=output: self.app.output_tray_line(o) or "", lambda *_a: None,
                              enabled=False, visible=lambda _i, o=output: bool(self.app.output_tray_line(o))))
            items.append(item(stop_label(output), lambda *_a, o=output: self.app.stop_output(o)))
        return items

    def _menu(self):
        item, menu = pystray.MenuItem, pystray.Menu
        nothing = lambda *_a: None                                                  # noqa: E731
        return menu(
            # default=True is what a single left click triggers
            item(f"Open {APP_NAME}", self._ui(self.app.show_window), default=True),
            menu.SEPARATOR,
            *[item(self._line(key), nothing, enabled=False) for key in LINES],
            item(self._line("error"), nothing, enabled=False,
                 visible=lambda _i: bool(self.app.tray_line("error"))),
            *self._output_items(),
            menu.SEPARATOR,
            item("Haptics on", self._ui(self.app.toggle_haptics), checked=lambda _i: self.app.haptics_on),
            item("Restart haptics", self._ui(self.app.restart_haptics)),
            item("Test tone", self._ui(self.app.test_tone)),
            menu.SEPARATOR,
            item("Start with Windows", self._ui(self.app.toggle_windows_startup),
                 checked=lambda _i: self.app.windows_startup_enabled()),
            item("Open settings folder", self._ui(self.app.open_folder)),
            item("Send feedback / report a bug", self._ui(self.app.open_feedback)),
            menu.SEPARATOR,
            item("Quit", self._ui(self.app.quit_app)),
        )

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        if not self.active or self._thread is not None:
            return
        self._thread = threading.Thread(target=self.icon.run, name="tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.active and self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.active = False

    # -- status ----------------------------------------------------------------------------
    def update_menu(self) -> None:
        """Rebuild the menu now. On Windows pystray reads checked/enabled/visible only while it builds
        the menu, so a tick changed between the poll's refreshes would otherwise show the old state."""
        if not self.active or self.icon is None:
            return
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def refresh(self, title: str, running: bool, lines: tuple) -> None:
        """Called from the Tk poll; only touches the icon when something actually changed."""
        if not self.active or self.icon is None:
            return
        try:
            if title != self._last_title:
                self.icon.title = title[:127]                 # Win32 tooltips stop at 128 chars
                self._last_title = title
            want = self._running_img if running else self._stopped_img
            if want is not getattr(self.icon, "icon", None):
                self.icon.icon = want
            if lines != self._last_lines:
                self._last_lines = lines
                self.icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = APP_NAME, once: bool = False) -> None:
        if not self.active or self.icon is None or (once and self._notified):
            return
        self._notified = True
        try:
            self.icon.notify(message, title)
        except Exception:
            pass
