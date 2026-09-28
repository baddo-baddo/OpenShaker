"""Write THIRD-PARTY-NOTICES.txt: every third-party component inside the OpenShaker build with its version,
licence and project page, followed by the full licence texts.

Run it with the build environment's Python (build.ps1 does) so the versions are the bundled ones:

    python installer/third_party_notices.py [--out THIRD-PARTY-NOTICES.txt]
"""
from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# (distribution, what OpenShaker uses it for, licence, project page, note)
PACKAGES = [
    ("numpy", "signal maths", "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", "https://numpy.org",
     "The Windows wheel bundles OpenBLAS (BSD-3-Clause) and its runtime DLLs in numpy.libs; their licences are "
     "part of numpy's LICENSE.txt below."),
    ("sounddevice", "audio output", "MIT", "https://github.com/spatialaudio/python-sounddevice",
     "Includes the PortAudio library (64-bit Windows build only), licence below."),
    ("cffi", "C bindings used by sounddevice", "MIT-0", "https://github.com/python-cffi/cffi", ""),
    ("pycparser", "C declaration parser used by cffi", "BSD-3-Clause", "https://github.com/eliben/pycparser", ""),
    ("pillow", "tray icon images", "MIT-CMU", "https://python-pillow.github.io",
     "Pillow's licence below also covers the image libraries its wheel bundles."),
    ("pystray", "notification-area icon", "LGPL-3.0-or-later", "https://github.com/moses-palmer/pystray",
     "Shipped as plain Python source files in _internal\\pystray, so it can be replaced with a modified "
     "version as the LGPL allows. Full LGPL and GPL texts below."),
    ("six", "compatibility helpers used by pystray", "MIT", "https://github.com/benjaminp/six", ""),
]
LICENCE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")

PORTAUDIO = """PortAudio Portable Real-Time Audio Library
Copyright (c) 1999-2011 Ross Bencina and Phil Burk

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The text above constitutes the entire PortAudio license; however,
the PortAudio community also makes the following non-binding requests:

Any person wishing to distribute modifications to the Software is
requested to send the modifications to the original developer so that
they can be incorporated into the canonical version. It is also
requested that these non-binding requests be included along with the
license above.
"""


def licence_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """(path, text) of every licence file a package ships: all of .dist-info/licenses/ (PEP 639; numpy
    keeps one per vendored library there, under that library's own path) and LICENSE*, COPYING* ... at the
    top of .dist-info. The path is relative to that folder, so no two headings look alike."""
    out = []
    for f in dist.files or []:
        parts = str(f).replace("\\", "/").split("/")
        if not parts[0].endswith(".dist-info"):
            continue
        if len(parts) > 2 and parts[1] == "licenses":
            rel = "/".join(parts[2:])
        elif len(parts) == 2 and parts[1].upper().startswith(LICENCE_NAMES):
            rel = parts[1]
        else:
            continue
        try:
            out.append((rel, Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def tcl_tk(base: Path) -> tuple[str, list[str], Path | None]:
    """The bundled Tcl/Tk's version, DLL names and licence file, from the base Python's own copy."""
    folders = sorted(p for p in (base / "tcl").glob("tk[0-9]*") if p.is_dir())       # tk8.6, not tk86t.lib
    version = folders[-1].name[2:] if folders else "8.6"
    dlls = sorted(p.name for p in (base / "DLLs").glob("tcl[0-9]*.dll")) + \
        sorted(p.name for p in (base / "DLLs").glob("tk[0-9]*.dll"))
    if not dlls:
        digits = version.replace(".", "")
        dlls = [f"tcl{digits}t.dll", f"tk{digits}t.dll"]
    terms = folders[-1] / "license.terms" if folders else None
    return version, dlls, terms if terms is not None and terms.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "THIRD-PARTY-NOTICES.txt"))
    args = ap.parse_args(argv)
    base = Path(getattr(sys, "base_prefix", sys.prefix))
    py_version = ".".join(str(v) for v in sys.version_info[:3])
    major, minor = sys.version_info[:2]
    dll = f"python{major}{minor}.dll"
    incorporated = HERE / f"cpython-{major}.{minor}-incorporated-licenses.txt"
    # CPython's docs have no HACL* section: its MIT licence is the header of each Modules/_hacl file
    hacl = HERE / "hacl-star-LICENSE.txt"
    for needed in (incorporated, hacl):
        if not needed.exists():
            print(f"error: {needed.name} is missing: CPython's licences for the software it incorporates "
                  f"must ship with a Python {major}.{minor} build (see installer/build.ps1)", file=sys.stderr)
            return 1

    rows = [("Python", py_version, "PSF-2.0 (plus the components listed in its licence)", "https://www.python.org",
             f"{dll}, the standard library and its Windows DLLs (OpenSSL for the update check's HTTPS, libffi, "
             "zlib, bzip2, XZ, expat, mpdecimal, HACL* ...). Its LICENSE.txt (which includes OpenSSL's Apache "
             "License 2.0) and the licences of the software it incorporates follow below.")]
    texts = []
    py_licence = base / "LICENSE.txt"
    if py_licence.exists():
        texts.append((f"Python {py_version}", "LICENSE.txt", py_licence.read_text(encoding="utf-8", errors="replace")))
    texts.append((f"Python {py_version}", "Licenses and Acknowledgements for Incorporated Software",
                  incorporated.read_text(encoding="utf-8")))
    texts.append((f"HACL* (in {dll}: hashlib MD5/SHA-1/SHA-2/SHA-3)", "MIT", hacl.read_text(encoding="utf-8")))
    tk_version, tk_dlls, tk_terms = tcl_tk(base)
    rows.append(("Tcl/Tk", tk_version, "Tcl/Tk License (BSD-style)", "https://www.tcl-lang.org",
                 f"{', '.join(tk_dlls)} and their script libraries, used by the window."))
    if tk_terms:
        texts.append((f"Tcl/Tk {tk_version}", "license.terms", tk_terms.read_text(encoding="utf-8", errors="replace")))
    for dist_name, use, licence, url, note in PACKAGES:
        try:
            dist = metadata.distribution(dist_name)
        except metadata.PackageNotFoundError:
            print(f"warning: {dist_name} is not installed in this environment", file=sys.stderr)
            continue
        rows.append((dist.metadata["Name"], dist.version, licence, url, f"{use}. {note}".strip()))
        for rel, text in licence_files(dist):
            texts.append((f"{dist.metadata['Name']} {dist.version}", rel, text))
    rows.append(("PortAudio", "19.7 (as shipped by sounddevice)", "MIT-style", "https://www.portaudio.com",
                 "libportaudio64bit.dll, the audio I/O library."))
    texts.append(("PortAudio", "licence", PORTAUDIO))
    try:
        pyi = metadata.distribution("pyinstaller")
        rows.append(("PyInstaller bootloader", pyi.version, "GPL-2.0-or-later with the bootloader exception",
                     "https://pyinstaller.org", "OpenShaker.exe is PyInstaller's launcher; the exception allows "
                     "distributing it with any program. Full text below."))
        for rel, text in licence_files(pyi):
            texts.append((f"PyInstaller {pyi.version}", rel, text))
    except metadata.PackageNotFoundError:
        pass
    rows.append(("Microsoft Visual C++ runtime", "-", "Microsoft Visual Studio redistributable terms",
                 "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
                 "VCRUNTIME140*.dll, ucrtbase.dll, api-ms-win-*.dll and msvcp140 in numpy.libs, as shipped with "
                 "Python and numpy."))

    lines = ["OpenShaker - third-party notices", "=" * 32, "",
             "OpenShaker itself is released under the MIT License: see LICENSE.txt next to this file (LICENSE in",
             "the source code). The installed program also contains the following third-party components, each",
             "under its own licence. Full licence texts follow the list.", ""]
    for name, version, licence, url, note in rows:
        lines += [f"* {name} {version}", f"  Licence: {licence}", f"  Project: {url}"]
        if note:
            lines.append(f"  {note}")
        lines.append("")
    for title, filename, text in texts:
        lines += ["", "-" * 78, f"{title} - {filename}", "-" * 78, "", text.rstrip(), ""]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(rows)} components, {len(texts)} licence texts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
