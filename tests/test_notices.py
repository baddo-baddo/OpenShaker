"""THIRD-PARTY-NOTICES.txt and its generator: every licence file a package ships, headed by its own
path; Tcl/Tk and the Python DLL named from what is installed; CPython's licences for the software it
incorporates; and a release build pinned to the Python those texts belong to. On fake folders only."""
import contextlib
import importlib.util
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer"

spec = importlib.util.spec_from_file_location("third_party_notices", INSTALLER / "third_party_notices.py")
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


def release_python() -> str:
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    return re.search(r'^\$ReleasePython = "(\d+\.\d+)"$', build, re.M).group(1)


class FakeDist:
    def __init__(self, root: Path, files: dict):
        self.root = root
        self.files = list(files)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")

    def locate_file(self, f):
        return self.root / str(f)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_every_licence_file_with_its_own_path(self):
        dist = FakeDist(self.dir, {
            "pkg-1.0.dist-info/licenses/LICENSE.txt": "top",
            "pkg-1.0.dist-info/licenses/pkg/fft/pocketfft/LICENSE.md": "fft",
            "pkg-1.0.dist-info/licenses/pkg/core/dragon4_LICENSE.txt": "dragon4",   # no LICENSE prefix: still one
            "pkg-1.0.dist-info/COPYING": "old style",
            "pkg-1.0.dist-info/METADATA": "not a licence",
            "pkg-1.0.dist-info/RECORD": "not a licence",
            "pkg/LICENSE.txt": "inside the package, not the metadata",
        })
        self.assertEqual(notices.licence_files(dist), [
            ("LICENSE.txt", "top"), ("pkg/fft/pocketfft/LICENSE.md", "fft"),
            ("pkg/core/dragon4_LICENSE.txt", "dragon4"), ("COPYING", "old style")])

    def test_tcl_tk_from_the_folder_and_the_dlls_found(self):
        (self.dir / "tcl" / "tk8.6").mkdir(parents=True)
        (self.dir / "tcl" / "tk8.6" / "license.terms").write_text("terms", encoding="utf-8")
        (self.dir / "tcl" / "tk86t.lib").write_text("", encoding="utf-8")         # a file, not the version
        (self.dir / "DLLs").mkdir()
        for dll in ("tk86t.dll", "tcl86t.dll", "_tkinter.pyd"):
            (self.dir / "DLLs" / dll).write_text("", encoding="utf-8")
        version, dlls, terms = notices.tcl_tk(self.dir)
        self.assertEqual((version, dlls, terms.name), ("8.6", ["tcl86t.dll", "tk86t.dll"], "license.terms"))
        (self.dir / "tcl" / "tk9.0").mkdir()
        shutil.rmtree(self.dir / "DLLs")
        self.assertEqual(notices.tcl_tk(self.dir), ("9.0", ["tcl90t.dll", "tk90t.dll"], None))

    def test_a_python_without_its_incorporated_licences_cannot_build_notices(self):
        real = notices.HERE
        self.addCleanup(setattr, notices, "HERE", real)
        notices.HERE = self.dir
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(notices.main(["--out", str(self.dir / "out.txt")]), 1)
        self.assertIn("incorporated-licenses.txt is missing", err.getvalue())
        major, minor = sys.version_info[:2]
        shutil.copy(real / f"cpython-{release_python()}-incorporated-licenses.txt",
                    self.dir / f"cpython-{major}.{minor}-incorporated-licenses.txt")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(notices.main(["--out", str(self.dir / "out.txt")]), 1, "HACL* is needed too")
        self.assertIn("hacl-star-LICENSE.txt is missing", err.getvalue())
        self.assertFalse((self.dir / "out.txt").exists())
        self.assertFalse((self.dir / "out.txt").exists())


class ShippedNoticesTests(unittest.TestCase):
    def test_the_release_python_is_the_one_everything_names(self):
        version = release_python()
        self.assertTrue((INSTALLER / f"cpython-{version}-incorporated-licenses.txt").is_file())
        self.assertIn(f"Tested with Python {version}", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertIn(f"Python {version}", (ROOT / "build.bat").read_text(encoding="utf-8"))
        self.assertIn(f"Python {version}", (ROOT / "README.md").read_text(encoding="utf-8"))
        text = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
        self.assertIn(f"* Python {version}.", text)
        self.assertIn(f"python{version.replace('.', '')}.dll", text)

    def test_cpythons_incorporated_software_is_listed(self):
        vendored = (INSTALLER / f"cpython-{release_python()}-incorporated-licenses.txt").read_text(encoding="utf-8")
        for part in ("Mersenne Twister", "SipHash24", "strtod and dtoa", "expat", "zlib", "libmpdec", "mimalloc",
                     "libffi", "asyncio", "Global Unbounded Sequences (GUS)"):
            self.assertRegex(vendored, rf"\n{re.escape(part)}\n-+\n", part)
        text = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
        self.assertIn(vendored.strip(), text)
        hacl = (INSTALLER / "hacl-star-LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("MIT License", hacl)
        self.assertIn(hacl.strip(), text, "HACL*, which CPython's docs do not list")
        dll = f"python{release_python().replace('.', '')}.dll"
        self.assertIn(f"\nHACL* (in {dll}: hashlib MD5/SHA-1/SHA-2/SHA-3) - MIT\n", text)

    def test_no_two_licence_texts_have_the_same_heading(self):
        text = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
        headings = re.findall(r"\n-{78}\n(.+?)\n-{78}\n", text)
        self.assertGreater(len(headings), 20)
        self.assertEqual(len(headings), len(set(headings)), [h for h in headings if headings.count(h) > 1])
        self.assertIn("numpy 2.5.3 - numpy/fft/pocketfft/LICENSE.md", headings)
        self.assertIn("Tcl/Tk 8.6 - license.terms", headings)


if __name__ == "__main__":
    unittest.main()
