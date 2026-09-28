"""Config round-trips: a learned profile must survive Save, and trims must scale it, not replace it."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import config                       # noqa: E402
from openshaker.runtime import Runtime              # noqa: E402

PROFILE = {
    "effects": {
        # engine.gain is HaptiConnect's absolute level; the numbers are the real FM profile's
        "engine": {"gain": 0.175, "curve": [[0.0, 0.0], [1.0, 0.96]], "harmonics": [0.1]},
        "suspension": {"gain": 1.6, "freq": 41.0},
        "acceleration": {"gain": 0.12},
        # the real FM/FH5 profiles switch this one on; the synthetic default is off
        "shift_indicator": {"gain": 1.0, "enabled": True},
    }
}


class AceProfileTests(unittest.TestCase):
    """ACE has its own profile now; a config that still sent ACE to the Forza one moves, strengths and all."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"

    def load(self, user):
        self.path.write_text(json.dumps(user), encoding="utf-8")
        return config.load(self.path)

    def test_ace_has_a_shipped_profile_of_its_own(self):
        self.assertEqual(config.DEFAULTS["profiles"]["ace"], "profiles/ace/profile.json")
        cfg = config.load(None)
        self.assertTrue(config.resolve_profile(cfg, "profiles/ace/profile.json").exists())
        meta = json.loads(config.resolve_profile(cfg, "profiles/ace/profile.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["seeded_from"]["profile"], "profiles/forza_motorsport/profile.json")

    def test_an_old_config_moves_ace_and_keeps_its_strengths(self):
        for old in ("profiles/forza_motorsport/profile.json", "profiles/hapticonnect_fm/profile.json"):
            cfg = self.load({"profiles": {"forza": "profiles/forza_motorsport/profile.json", "ace": old},
                             "presets": {"ace": {"effects": {"engine": {"trim": 0.6}}},
                                         "forza": {"effects": {"engine": {"trim": 0.9}}}}})
            self.assertEqual(cfg["profiles"]["ace"], "profiles/ace/profile.json", old)
            self.assertEqual(cfg["presets"]["ace"]["effects"]["engine"]["trim"], 0.6)
            self.assertEqual(cfg["presets"]["forza"]["effects"]["engine"]["trim"], 0.9)
            self.assertTrue(cfg.get("_resave"), "the move is written back once")
            config.save_user(cfg, self.path)
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertNotIn("ace", saved.get("profiles") or {}, "no copy of the new default is kept")
            self.assertEqual(saved["presets"]["ace"]["effects"]["engine"]["trim"], 0.6)

    def test_ace_strengths_apply_to_the_ace_profile(self):
        cfg = self.load({"presets": {"ace": {"effects": {"engine": {"trim": 0.5}}}}})
        base = config.load(None)
        config.apply_profile(base, config.resolve_profile(cfg, "profiles/ace/profile.json"), keep_user={})
        full = base["effects"]["engine"]["gain"]
        config.apply_profile(cfg, config.resolve_profile(cfg, cfg["profiles"]["ace"]), preset="ace")
        self.assertAlmostEqual(cfg["effects"]["engine"]["gain"], full * 0.5)

    def test_switches_copied_from_the_forza_profile_are_dropped_on_the_move(self):
        probe = config.load(None)
        config.apply_profile(probe, config.resolve_profile(probe, "profiles/forza_motorsport/profile.json"), keep_user={})
        fm_on = probe["_base_enabled"]
        cfg = self.load({"profiles": {"ace": "profiles/forza_motorsport/profile.json"},
                         "presets": {"ace": {"effects": {
                             "shift_indicator": {"enabled": fm_on["shift_indicator"], "trim": 1.0},
                             "engine": {"enabled": not fm_on["engine"], "trim": 0.6},
                             "impact": {"enabled": fm_on["impact"]}}}}})
        effects = cfg["presets"]["ace"]["effects"]
        self.assertNotIn("enabled", effects["shift_indicator"], "a copy of Forza's switch: ACE's profile decides")
        self.assertEqual(effects["shift_indicator"]["trim"], 1.0)
        self.assertEqual(effects["engine"], {"enabled": not fm_on["engine"], "trim": 0.6}, "a real choice stays")
        self.assertNotIn("impact", effects, "nothing left of it")

    def test_a_switch_equal_to_the_profile_is_not_stored(self):
        cfg = config.load(None)
        entry = config.set_preset_effect(cfg, "ace", "engine", trim=0.5, enabled=True, profile_enabled=True)
        self.assertEqual(entry, {"trim": 0.5})
        entry = config.set_preset_effect(cfg, "ace", "engine", enabled=False, profile_enabled=True)
        self.assertEqual(entry, {"trim": 0.5, "enabled": False})
        entry = config.set_preset_effect(cfg, "ace", "engine", enabled=True, profile_enabled=True)
        self.assertEqual(entry, {"trim": 0.5}, "switched back: follows the profile again")
        self.assertEqual(config.set_preset_effect(cfg, "x", "abs", enabled=True), {"enabled": True},
                         "without the profile's switch it is stored as before")

    def test_a_hand_picked_ace_profile_is_left_alone(self):
        cfg = self.load({"profiles": {"ace": "profiles/my_ace/profile.json"}})
        self.assertEqual(cfg["profiles"]["ace"], "profiles/my_ace/profile.json")

    def test_the_move_happens_once_and_a_later_choice_stays(self):
        cfg = self.load({"profiles": {"ace": "profiles/forza_motorsport/profile.json"}})
        self.assertEqual(cfg["profiles"]["ace"], "profiles/ace/profile.json")
        config.save_user(cfg, self.path)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(saved.get(config.ACE_SPLIT_MARK), "the check is recorded")
        saved.setdefault("profiles", {})["ace"] = "profiles/forza_motorsport/profile.json"   # the user's choice
        cfg = self.load(saved)
        self.assertEqual(cfg["profiles"]["ace"], "profiles/forza_motorsport/profile.json", "not moved again")
        self.assertFalse(cfg.get("_resave"))
        config.save_user(cfg, self.path)
        again = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(again["profiles"]["ace"], "profiles/forza_motorsport/profile.json", "and saved as chosen")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        prof_dir = self.dir / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
        self.profile = prof_dir / "profile.json"
        self.path = self.dir / "config.json"

    def write_config(self, user: dict) -> None:
        user.setdefault("profile", "profiles/test/profile.json")
        self.path.write_text(json.dumps(user), encoding="utf-8")

    # -- the profile is the source of truth for levels -------------------------------------
    def test_profile_gains_are_used(self):
        self.write_config({})
        cfg = config.load(self.path)
        self.assertAlmostEqual(cfg["effects"]["engine"]["gain"], 0.175)
        self.assertAlmostEqual(cfg["_base_gains"]["engine"], 0.175)
        self.assertEqual(cfg["effects"]["engine"]["trim"], 1.0)

    def test_absolute_gain_in_config_is_ignored(self):
        """Pre-trim configs stored absolute gains; those must not mask a calibrated profile."""
        self.write_config({"effects": {"engine": {"gain": 1.0}, "acceleration": {"gain": 0.6}}})
        cfg = config.load(self.path)
        self.assertAlmostEqual(cfg["effects"]["engine"]["gain"], 0.175)
        self.assertAlmostEqual(cfg["effects"]["acceleration"]["gain"], 0.12)

    def test_trim_scales_the_profile_gain(self):
        self.write_config({"effects": {"engine": {"trim": 0.5}, "suspension": {"enabled": False}}})
        cfg = config.load(self.path)
        self.assertAlmostEqual(cfg["effects"]["engine"]["gain"], 0.0875)
        self.assertAlmostEqual(cfg["effects"]["suspension"]["gain"], 1.6)
        self.assertFalse(cfg["effects"]["suspension"]["enabled"])
        self.assertTrue(cfg["_base_enabled"]["suspension"])

    def test_legacy_enable_flag_does_not_mask_profile(self):
        """A pre-trim config just repeated the defaults; the profile's own switch must win."""
        self.write_config({"effects": {"shift_indicator": {"enabled": False, "gain": 0.8}}})
        cfg = config.load(self.path)
        self.assertTrue(cfg["effects"]["shift_indicator"]["enabled"])
        self.assertAlmostEqual(cfg["effects"]["shift_indicator"]["gain"], 1.0)

    def test_saved_enable_flag_is_honoured(self):
        """Once the UI has saved trims, switching an effect off must stick."""
        self.write_config({"effects": {"shift_indicator": {"enabled": False, "trim": 1.0}}})
        cfg = config.load(self.path)
        self.assertFalse(cfg["effects"]["shift_indicator"]["enabled"])
        self.assertTrue(cfg["_base_enabled"]["shift_indicator"])       # profile's own value kept

    # -- Save must not corrupt the calibration ---------------------------------------------
    def test_save_does_not_write_profile_data(self):
        self.write_config({})
        cfg = config.load(self.path)
        config.set_preset_effect(cfg, "test", "engine", trim=0.5, enabled=True)
        config.save_user(cfg, self.path)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["presets"]["test"]["effects"]["engine"], {"trim": 0.5, "enabled": True})
        self.assertNotIn("curve", json.dumps(saved))                       # no learned data anywhere
        self.assertNotIn('"gain"', json.dumps(saved))      # master_gain is fine; effect gains are not
        self.assertEqual(saved["profile"], "profiles/test/profile.json")   # relative, still portable

    def test_save_reload_keeps_calibrated_levels(self):
        self.write_config({})
        cfg = config.load(self.path)
        config.save_user(cfg, self.path)
        again = config.load(self.path)
        for name in PROFILE["effects"]:
            self.assertAlmostEqual(again["effects"][name]["gain"], PROFILE["effects"][name]["gain"], places=6)

    def test_save_reload_keeps_trim_and_switches(self):
        """A preset's strengths must come back exactly, applied to its own profile."""
        self.write_config({})
        cfg = config.load(self.path)
        config.set_preset_effect(cfg, "test", "engine", trim=0.5)
        config.set_preset_effect(cfg, "test", "suspension", enabled=False)
        config.save_user(cfg, self.path)
        again = config.load(self.path)
        self.assertAlmostEqual(again["effects"]["engine"]["gain"], 0.0875)
        self.assertFalse(again["effects"]["suspension"]["enabled"])
        self.assertEqual(again["_preset"], "test")

    def test_folder_keyed_presets_migrate_to_every_game_that_uses_them(self):
        """Older configs keyed presets by profile folder, so both games shared one entry."""
        self.write_config({"presets": {"test": {"effects": {"engine": {"trim": 0.4}}}},
                           "profiles": {"forza": "profiles/test/profile.json",
                                        "ace": "profiles/test/profile.json"}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["presets"]["forza"]["effects"]["engine"]["trim"], 0.4)
        self.assertEqual(cfg["presets"]["ace"]["effects"]["engine"]["trim"], 0.4)
        self.assertNotIn("test", cfg["presets"])          # the shared entry is retired

    def test_old_single_horizon_entry_splits_into_fh5_and_fh6(self):
        """FH5 and FH6 used to share one preset; both must inherit its settings."""
        self.write_config({"profiles": {"forza_horizon": "profiles/test/profile.json"},
                           "presets": {"forza_horizon": {"effects": {"engine": {"trim": 0.6}}}}})
        cfg = config.load(self.path)
        self.assertIn("forza_horizon5", cfg["profiles"])
        self.assertIn("forza_horizon6", cfg["profiles"])
        self.assertNotIn("forza_horizon", cfg["profiles"])
        self.assertEqual(cfg["presets"]["forza_horizon5"]["effects"]["engine"]["trim"], 0.6)
        self.assertEqual(cfg["presets"]["forza_horizon6"]["effects"]["engine"]["trim"], 0.6)
        self.assertNotIn("forza_horizon", cfg["presets"])

    def test_presets_are_independent(self):
        """Turning an effect down for one game must not touch another game's preset."""
        self.write_config({})
        cfg = config.load(self.path)
        config.set_preset_effect(cfg, "test", "engine", trim=0.25)
        config.set_preset_effect(cfg, "other", "engine", trim=1.0)
        config.save_user(cfg, self.path)
        again = config.load(self.path)
        self.assertEqual(again["presets"]["test"]["effects"]["engine"]["trim"], 0.25)
        self.assertEqual(again["presets"]["other"]["effects"]["engine"]["trim"], 1.0)

    def test_windows_startup_decision_is_remembered(self):
        """Without this the app would re-enable the Run entry every launch after a deliberate off."""
        self.write_config({})
        cfg = config.load(self.path)
        self.assertFalse(cfg["windows_startup_asked"])
        cfg["windows_startup_asked"] = True
        config.save_user(cfg, self.path)
        self.assertTrue(config.load(self.path)["windows_startup_asked"])

    def test_old_start_on_launch_switch_is_dropped(self):
        """Haptics now always start with the app; a stale 'autostart: false' must not linger."""
        self.write_config({"autostart": False})
        cfg = config.load(self.path)
        config.save_user(cfg, self.path)
        self.assertNotIn("autostart", json.loads(self.path.read_text(encoding="utf-8")))

    def test_save_keeps_hand_edited_settings(self):
        self.write_config({"sources": {"forza": {"port": 5301}, "ace": {"susp_scale_m": 0.1}}})
        cfg = config.load(self.path)
        config.save_user(cfg, self.path)
        again = config.load(self.path)
        self.assertEqual(again["sources"]["forza"]["port"], 5301)
        self.assertAlmostEqual(again["sources"]["ace"]["susp_scale_m"], 0.1)

    def test_saved_blocks_hold_only_what_differs_from_the_defaults(self):
        self.write_config({})
        cfg = config.load(self.path)
        cfg["sources"]["forza"]["port"] = 5301
        cfg["audio"]["device"] = "Line Out"
        config.save_user(cfg, self.path)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["sources"], {"forza": {"port": 5301}})
        self.assertEqual(saved["audio"], {"device": "Line Out"})
        self.assertNotIn("profiles", saved)
        self.assertNotIn("game_processes", saved)

    def test_a_default_changed_later_reaches_an_existing_config(self):
        """Older versions froze every default into config.json; loading strips the copies."""
        old = copy.deepcopy(config.DEFAULTS)            # what a first run used to write
        old["sources"]["forza"]["port"] = 5301          # plus one genuine edit
        old["effects"]["engine"]["freq_min"] = 25.0
        self.write_config(old)
        cfg = config.load(self.path)
        self.assertTrue(cfg.get("_resave"), "the window should write the slimmer file back")
        config.save_user(cfg, self.path)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["sources"], {"forza": {"port": 5301}})
        self.assertEqual(saved["effects"], {"engine": {"freq_min": 25.0}})
        self.addCleanup(setattr, config, "DEFAULTS", config.DEFAULTS)
        config.DEFAULTS = copy.deepcopy(config.DEFAULTS)   # a later release changes two defaults
        config.DEFAULTS["sources"]["trackmania"]["max_rate"] = 250
        config.DEFAULTS["sources"]["forza"]["port"] = 5600
        again = config.load(self.path)
        self.assertEqual(again["sources"]["trackmania"]["max_rate"], 250, "the new default arrives")
        self.assertEqual(again["sources"]["forza"]["port"], 5301, "the user's own edit still wins")
        self.assertFalse(again.get("_resave"))

    def test_a_first_run_writes_no_copy_of_the_defaults(self):
        fresh = self.path.parent / "fresh" / "config.json"
        config.load(fresh)
        self.assertEqual(json.loads(fresh.read_text(encoding="utf-8")), {})

    def test_repeated_saves_are_stable(self):
        """Save twice: the second file must equal the first (no gain drift, no growth)."""
        self.write_config({})
        cfg = config.load(self.path)
        config.save_user(cfg, self.path)
        first = self.path.read_text(encoding="utf-8")
        cfg = config.load(self.path)
        config.save_user(cfg, self.path)
        self.assertEqual(first, self.path.read_text(encoding="utf-8"))


class RuntimeTrimTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        prof_dir = self.dir / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
        self.profile = str(prof_dir / "profile.json")
        path = self.dir / "config.json"
        path.write_text(json.dumps({"profile": "profiles/test/profile.json"}), encoding="utf-8")
        self.cfg = config.load(path)

    def test_set_trim_scales_from_the_profile(self):
        rt = Runtime(self.cfg)
        self.assertAlmostEqual(rt.set_trim("engine", 0.5), 0.0875)
        self.assertAlmostEqual(self.cfg["effects"]["engine"]["gain"], 0.0875)
        self.assertAlmostEqual(rt.set_trim("engine", 1.0), 0.175)     # exactly back to calibrated

    def test_preset_strengths_are_applied_on_a_profile_switch(self):
        """Switching to a game's profile must bring that preset's saved strengths with it."""
        config.set_preset_effect(self.cfg, "test", "engine", trim=0.5)
        config.set_preset_effect(self.cfg, "test", "suspension", enabled=False)
        rt = Runtime(self.cfg)
        rt.switch_profile(self.profile)
        self.assertAlmostEqual(self.cfg["effects"]["engine"]["gain"], 0.0875)
        self.assertEqual(self.cfg["effects"]["engine"]["trim"], 0.5)
        self.assertFalse(self.cfg["effects"]["suspension"]["enabled"])
        self.assertAlmostEqual(self.cfg["effects"]["suspension"]["gain"], 1.6)
        self.assertEqual(rt.cfg["_preset"], "test")

    def test_two_games_sharing_a_profile_keep_separate_strengths(self):
        """Forza Motorsport and ACE use one calibration; tuning one must not move the other."""
        self.cfg["profiles"] = {"forza": "profiles/test/profile.json", "ace": "profiles/test/profile.json"}
        config.set_preset_effect(self.cfg, "forza", "engine", trim=0.5)
        config.set_preset_effect(self.cfg, "ace", "engine", trim=1.0)
        rt = Runtime(self.cfg)

        rt.switch_profile(self.profile, preset="forza")
        self.assertEqual(self.cfg["_preset"], "forza")
        self.assertAlmostEqual(self.cfg["effects"]["engine"]["gain"], 0.0875)

        rt.switch_profile(self.profile, preset="ace")
        self.assertEqual(self.cfg["_preset"], "ace")
        self.assertAlmostEqual(self.cfg["effects"]["engine"]["gain"], 0.175)

    def test_horizon_preset_follows_the_running_executable(self):
        """FH5 and FH6 are identical on the wire, so the exe decides which preset is used."""
        from openshaker import procs
        self.cfg["profiles"] = {"forza_horizon5": "profiles/test/profile.json",
                                "forza_horizon6": "profiles/test/profile.json"}
        self.cfg["game_processes"] = {"forza_horizon5": "forzahorizon5.exe",
                                      "forza_horizon6": "forzahorizon6.exe"}
        rt = Runtime(self.cfg)
        rt.profiles = dict(self.cfg["profiles"])
        real = procs.is_running
        self.addCleanup(setattr, procs, "is_running", real)

        procs.is_running = lambda exe: exe == "forzahorizon6.exe"
        self.assertEqual(rt._horizon_key(), "forza_horizon6")
        procs.is_running = lambda exe: exe == "forzahorizon5.exe"
        self.assertEqual(rt._horizon_key(), "forza_horizon5")

        procs.is_running = lambda exe: False          # game not up yet: do not flap
        self.cfg["_preset"] = "forza_horizon6"
        self.assertEqual(rt._horizon_key(), "forza_horizon6")
        self.cfg["_preset"] = "forza"
        self.assertEqual(rt._horizon_key(), "forza_horizon5")

    def test_resume_auto_clears_manual(self):
        rt = Runtime(self.cfg)
        rt.switch_profile(self.profile, manual=True)
        self.assertTrue(rt.manual_profile)
        rt.resume_auto()
        self.assertFalse(rt.manual_profile)


if __name__ == "__main__":
    unittest.main()
