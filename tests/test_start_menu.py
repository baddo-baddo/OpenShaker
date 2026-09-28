"""A copy run from source can be found from the Start menu, without taking over an installed copy's entry."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import autostart, paths                                   # noqa: E402

READ = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:OS_LNK); "
        "$s.TargetPath; $s.Arguments; $s.WorkingDirectory; $s.IconLocation")


def read_shortcut(lnk: Path) -> list:
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", READ],
                         env=dict(os.environ, OS_LNK=str(lnk)), capture_output=True, text=True, timeout=60,
                         check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.stdout.splitlines()


class StartMenuTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())             # never the real Start menu
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_a_source_copy_adds_itself(self):
        lnk = autostart.ensure_start_menu_entry(self.folder)
        self.assertEqual(lnk, self.folder / "OpenShaker.lnk", "found by typing OpenShaker in Start")
        target, args, workdir, icon = read_shortcut(lnk)
        self.assertEqual(Path(target), autostart.pythonw())
        self.assertEqual(args, f'"{autostart.LAUNCHER}"')
        self.assertEqual(Path(workdir), autostart.LAUNCHER.parent.parent)
        self.assertTrue(icon.lower().startswith(str(paths.ICON).lower()))
        self.assertIsNone(autostart.ensure_start_menu_entry(self.folder), "made once, not on every start")

    def test_an_existing_entry_is_left_alone(self):
        installed = self.folder / "OpenShaker.lnk"
        installed.write_bytes(b"an installed copy's shortcut")
        self.assertIsNone(autostart.ensure_start_menu_entry(self.folder))
        self.assertEqual(installed.read_bytes(), b"an installed copy's shortcut")

    def test_its_own_entry_with_the_old_icon_place_gets_the_icon_back(self):
        old = self.folder / "OpenShaker.lnk"
        autostart.make_shortcut(old, autostart.pythonw(), f'"{autostart.LAUNCHER}"', icon=autostart.OLD_ICON)
        self.assertFalse(autostart.OLD_ICON.exists(), "the icon has moved into the package")
        self.assertEqual(autostart.ensure_start_menu_entry(self.folder), old, "made again once")
        self.assertTrue(read_shortcut(old)[3].lower().startswith(str(paths.ICON).lower()))
        self.assertIsNone(autostart.ensure_start_menu_entry(self.folder), "then left alone")

    def test_the_installed_app_leaves_it_to_the_installer(self):
        self.addCleanup(setattr, paths, "is_frozen", paths.is_frozen)
        paths.is_frozen = lambda: True
        self.assertIsNone(autostart.ensure_start_menu_entry(self.folder))
        self.assertFalse((self.folder / "OpenShaker.lnk").exists())

    def test_the_programs_folder_is_the_users_start_menu(self):
        self.assertTrue(str(autostart.programs_folder()).lower().endswith(r"start menu\programs"))


if __name__ == "__main__":
    unittest.main()
