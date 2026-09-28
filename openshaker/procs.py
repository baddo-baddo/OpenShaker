"""Which game executables are running.

Forza Horizon 5 and 6 send byte-identical telemetry (the same 324-byte Horizon layout on the same
port), so the running process is the only thing that separates them. Uses the Win32 toolhelp
snapshot rather than shelling out to `tasklist`: this app runs windowless, and a subprocess would
flash a console window every time it polled.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260
_CACHE_SECONDS = 5.0
_cache: tuple[float, frozenset[str]] = (0.0, frozenset())


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


def _snapshot() -> frozenset[str]:
    try:
        k32 = ctypes.windll.kernel32
    except AttributeError:                       # not Windows
        return frozenset()
    handle = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if handle == -1:
        return frozenset()
    names = set()
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        ok = k32.Process32First(handle, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.decode("latin-1", "replace").lower())
            ok = k32.Process32Next(handle, ctypes.byref(entry))
    finally:
        k32.CloseHandle(handle)
    return frozenset(names)


def running(force: bool = False) -> frozenset[str]:
    """Lower-cased executable names of every running process, cached for a few seconds."""
    global _cache
    now = time.monotonic()
    if force or now - _cache[0] > _CACHE_SECONDS:
        _cache = (now, _snapshot())
    return _cache[1]


def is_running(exe: str | None) -> bool:
    """True when a process whose name contains `exe` is running (case-insensitive)."""
    if not exe:
        return False
    needle = exe.lower()
    names = running()
    return needle in names or any(needle in name for name in names)
