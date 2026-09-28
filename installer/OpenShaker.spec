# PyInstaller spec for OpenShaker: a one-folder, windowed build (no console). installer\build.bat runs it.
# Only what the app needs at run time is bundled: the recording and calibration tools and the packages only
# they use (matplotlib, scipy, soundcard) stay out. Python's ssl (OpenSSL) is in, for the update check's
# HTTPS request to GitHub (openshaker/updater.py).
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
RUNTIME_PROFILES = ("forza_motorsport", "forza_horizon", "ace", "beamng", "trackmania")
DEV_ONLY = ("analyze", "beamng_check", "calibrate", "compare", "fit", "optimize", "probe", "replay",
            "tm_grip", "tm_tune", "viz")
# optional local packages (openshaker/outputs.py): never in the installer (build.ps1 checks the result too)
PRIVATE = ("openshaker.wheel",)

# the icon keeps its place in the package (paths.ICON); LICENSE and the notices go next to the exe (installer)
datas = [(str(ROOT / "openshaker" / "openshaker.ico"), "openshaker")]
for name in RUNTIME_PROFILES:
    datas.append((str(ROOT / "profiles" / name / "profile.json"), f"profiles/{name}"))

a = Analysis(
    [str(ROOT / "openshaker" / "app.pyw")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["pystray._win32"],
    excludes=["matplotlib", "scipy", "soundcard", "pytest", "IPython", "pandas"]
             + [f"openshaker.{m}" for m in DEV_ONLY] + list(PRIVATE),
    # pystray is LGPL-3.0: ship it as plain .py files next to the exe, so a user can replace it
    module_collection_mode={"pystray": "py"},
    noarchive=False,
)


def _wanted(entry):
    dest = str(entry[0]).replace("\\", "/")
    if "portaudio-binaries/" in dest:
        # sounddevice ships PortAudio for every platform; the app loads only the plain 64-bit Windows build
        # (the *-asio builds contain Steinberg's ASIO SDK and load only when SD_ENABLE_ASIO is set)
        return dest.endswith(("libportaudio64bit.dll", "README.md"))
    return True


a.binaries = [e for e in a.binaries if _wanted(e)]
a.datas = [e for e in a.datas if _wanted(e)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenShaker",
    icon=str(ROOT / "openshaker" / "openshaker.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="OpenShaker", upx=False)
