"""One app at a time: the second launch hands its "show the window" over and exits, and --quit
(also used by the installer and uninstaller) asks the running copy to shut down cleanly.

A loopback listening socket is both the lock and the message channel - the sources already own
UDP ports, so a second instance would fail half-way anyway, and this way double-clicking the
Desktop shortcut while the tray copy is running just raises the existing window.
Bound to 127.0.0.1 only, so it is not reachable from the network and raises no firewall prompt.
"""
from __future__ import annotations

import socket
import threading

HOST = "127.0.0.1"
PORT = 49731            # private range; the app's telemetry ports are elsewhere
SHOW = b"show"
QUIT = b"quit"


class Listener:
    """Holds the lock for this process; calls on_show() / on_quit() when another process asks."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.on_show = None
        self.on_quit = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="single-instance", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1.0)
                    data = conn.recv(64).strip()
                except OSError:
                    data = b""
            handler = {SHOW: self.on_show, QUIT: self.on_quit}.get(data)
            if handler is not None:
                try:
                    handler()
                except Exception:
                    pass

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def acquire() -> Listener | None:
    """Become the one instance, or None when another one already holds the port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, PORT))      # no SO_REUSEADDR: on Windows that would allow a second bind
        sock.listen(1)
    except OSError:
        sock.close()
        return None
    return Listener(sock)


def signal_existing(message: bytes = SHOW, timeout: float = 2.0) -> bool:
    """Send "show" or "quit" to the running instance. False if nobody answered."""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as conn:
            conn.sendall(message + b"\n")
        return True
    except OSError:
        return False


def is_running() -> bool:
    """True while some process holds the lock (the tray app or a console run)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, PORT))
        return False
    except OSError:
        return True
    finally:
        sock.close()


MUTEX_NAME = "OpenShakerRunning"    # installer/OpenShaker.iss AppMutex: setup waits for the app to quit
_mutex = None


def hold_app_mutex() -> None:
    """Hold a named mutex for as long as the app runs, the way Inno Setup checks for a running copy."""
    global _mutex
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        _mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
    except (AttributeError, OSError):
        _mutex = None


def mutex_held() -> bool:
    """True while a running app still holds the mutex (it goes when that process has exited)."""
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = ctypes.c_void_p
        handle = k32.OpenMutexW(0x00100000, False, MUTEX_NAME)      # SYNCHRONIZE
        if not handle:
            return False
        k32.CloseHandle(ctypes.c_void_p(handle))
        return True
    except (AttributeError, OSError):
        return False
