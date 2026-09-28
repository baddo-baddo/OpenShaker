"""The one-time cleanup of copied on/off switches in the Forza, Horizon and BeamNG presets (maintainer-approved
2026-09-20): the old window stored every switch ON in every preset, which froze them against later
calibrations - BeamNG's shift light stayed on after its profile turned it off. Temp config files only."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import config                                                  # noqa: E402

RACING = ("engine", "gear_shift", "wheel_lock", "wheel_slip", "abs", "suspension", "road", "impact",
          "acceleration", "shift_indicator")


def all_on(**trims):
    """A preset the way the old window wrote it: every racing switch ON."""
    return {"effects": {name: dict({"enabled": True}, **({"trim": trims[name]} if name in trims else {}))
                        for name in RACING}}


class PresetCleanupTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"

    def load(self, user: dict) -> dict:
        self.path.write_text(json.dumps(user), encoding="utf-8")
        return config.load(self.path)

    def switches(self, cfg, key):
        return {n: e["enabled"] for n, e in (cfg["presets"][key].get("effects") or {}).items() if "enabled" in e}

    def effective(self, cfg, key):
        """What plays for that game: its profile with its preset on top."""
        config.apply_profile(cfg, config.resolve_profile(cfg, cfg["profiles"][key]), preset=key)
        return {n: bool(e.get("enabled", True)) for n, e in cfg["effects"].items()}

    def test_the_owners_all_on_presets_follow_their_profiles_again(self):
        presets = {key: all_on() for key in config.SWITCH_CLEANUP_PRESETS}
        cfg = self.load({"presets": presets})
        for key in config.SWITCH_CLEANUP_PRESETS:
            self.assertEqual(self.switches(cfg, key), {}, key)
        self.assertFalse(self.effective(cfg, "beamng")["shift_indicator"], "the bug this fixes")
        self.assertTrue(self.effective(cfg, "forza")["shift_indicator"], "Forza's profile has it on")
        self.assertTrue(cfg.get("_resave"), "the window writes the cleaned file back once")

    def test_a_stored_off_where_the_profile_is_on_survives(self):
        preset = all_on()
        preset["effects"]["engine"]["enabled"] = False            # the user switched the engine off
        cfg = self.load({"presets": {"beamng": preset}})
        self.assertEqual(self.switches(cfg, "beamng"), {"engine": False})
        self.assertFalse(self.effective(cfg, "beamng")["engine"])

    def test_an_off_the_profile_also_has_is_dropped(self):
        preset = {"effects": {"shift_indicator": {"enabled": False}, "wheel_slip": {"enabled": True}}}
        cfg = self.load({"presets": {"beamng": preset}})
        self.assertEqual(self.switches(cfg, "beamng"), {})

    def test_strengths_stay(self):
        cfg = self.load({"presets": {"forza": all_on(engine=0.8, impact=1.2)}})
        effects = cfg["presets"]["forza"]["effects"]
        self.assertEqual((effects["engine"], effects["impact"]), ({"trim": 0.8}, {"trim": 1.2}))
        self.assertNotIn("gear_shift", effects, "an entry left with nothing in it goes")

    def test_trackmania_is_not_touched_and_ace_is_cleaned_too(self):
        tm = {"effects": {"engine": {"enabled": False}, "shift_indicator": {"enabled": True}}}
        cfg = self.load({"presets": {"trackmania": tm, "ace": all_on()}})
        self.assertEqual(self.switches(cfg, "trackmania"), {"engine": False, "shift_indicator": True})
        self.assertEqual(self.switches(cfg, "ace"), {}, "ACE's copies go the same way (PM, 2026-09-22)")

    def test_a_config_cleaned_before_ace_was_added_gets_one_ace_pass(self):
        """The first build wrote `true` for the four; ACE must still be cleaned, once, and they not again."""
        forza = {"effects": {"abs": {"enabled": True}}}                 # the user's choice after that cleanup
        cfg = self.load({config.SWITCH_CLEANUP_MARK: True, "presets": {"ace": all_on(), "forza": forza}})
        self.assertEqual(self.switches(cfg, "ace"), {})
        self.assertEqual(self.switches(cfg, "forza"), {"abs": True}, "not cleaned twice")
        self.assertTrue(cfg.get("_resave"))
        config.save_user(cfg, self.path)
        mark = json.loads(self.path.read_text(encoding="utf-8"))[config.SWITCH_CLEANUP_MARK]
        self.assertEqual(sorted(mark), sorted(config.SWITCH_CLEANUP_PRESETS))
        config.set_preset_effect(cfg, "ace", "abs", enabled=False, profile_enabled=True)
        config.save_user(cfg, self.path)
        self.assertEqual(self.switches(config.load(self.path), "ace"), {"abs": False}, "and only once")

    def test_it_runs_once(self):
        cfg = self.load({"presets": {"beamng": all_on()}})
        config.save_user(cfg, self.path)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(saved.get(config.SWITCH_CLEANUP_MARK))
        again = config.load(self.path)
        self.assertEqual(again["presets"], cfg["presets"], "a second run is a no-op")
        self.assertFalse(again.get("_resave"))

    def test_a_switch_set_after_the_cleanup_is_kept(self):
        cfg = self.load({"presets": {"beamng": all_on()}})
        config.set_preset_effect(cfg, "beamng", "shift_indicator", enabled=True, profile_enabled=False)
        config.save_user(cfg, self.path)
        again = config.load(self.path)
        self.assertEqual(self.switches(again, "beamng"), {"shift_indicator": True}, "the user's choice now")
        self.assertTrue(self.effective(again, "beamng")["shift_indicator"])

    def test_a_preset_whose_profile_would_not_load_is_retried_and_only_it(self):
        missing = self.dir / "gone" / "profile.json"
        profiles = dict(config.DEFAULTS["profiles"], beamng=str(missing))
        cfg = self.load({"profiles": profiles, "presets": {"beamng": all_on(), "forza": all_on()}})
        self.assertEqual(self.switches(cfg, "forza"), {})
        self.assertEqual(len(self.switches(cfg, "beamng")), len(RACING), "not checked: left alone")
        config.set_preset_effect(cfg, "forza", "abs", enabled=True, profile_enabled=False)   # a later choice
        config.save_user(cfg, self.path)
        mark = json.loads(self.path.read_text(encoding="utf-8"))[config.SWITCH_CLEANUP_MARK]
        self.assertNotIn("beamng", mark, "not done: tried again next launch")
        self.assertIn("forza", mark)
        missing.parent.mkdir()
        shutil.copyfile(Path(config.PROJECT_DIR) / "profiles" / "beamng" / "profile.json", missing)
        again = config.load(self.path)
        self.assertEqual(self.switches(again, "beamng"), {}, "cleaned once its profile loads")
        self.assertEqual(self.switches(again, "forza"), {"abs": True}, "the done preset is not cleaned twice")
        self.assertIn("beamng", again["_user"][config.SWITCH_CLEANUP_MARK])

    def test_the_pending_list_of_the_build_in_between_is_honoured(self):
        cfg = self.load({config.SWITCH_CLEANUP_MARK: True, config.SWITCH_CLEANUP_PENDING: ["beamng"],
                         "presets": {"beamng": all_on(), "forza": {"effects": {"abs": {"enabled": True}}}}})
        self.assertEqual(self.switches(cfg, "beamng"), {})
        self.assertEqual(self.switches(cfg, "forza"), {"abs": True})
        self.assertNotIn(config.SWITCH_CLEANUP_PENDING, cfg["_user"])

    def test_a_first_run_has_nothing_to_clean(self):
        cfg = config.load(self.path)                               # no file yet
        self.assertTrue(cfg["_user"].get(config.SWITCH_CLEANUP_MARK))
        self.assertFalse(cfg.get("_resave"))


if __name__ == "__main__":
    unittest.main()
