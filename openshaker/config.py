"""JSON configuration with defaults; unknown keys are kept so users can experiment."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .paths import RESOURCE_DIR as PROJECT_DIR   # bundled profiles: the exe's bundle, or the source folder

DEFAULTS = {
    "windows_startup_asked": False,  # whether the Run entry has been set up (or declined) once
    "haptics_on": True,              # the window's and tray's Haptics on switch; config.json keeps it only while off
    "presets": {},                   # per-profile user strengths: {key: {"effects": {name: {trim, enabled}}}}
    "profile": None,                 # fallback profile.json (optional); per-game profiles below take precedence
    "profiles": {                    # profile to use for each detected game (auto-switching)
        "forza": "profiles/forza_motorsport/profile.json",         # Forza Motorsport (331-byte packets)
        "forza_horizon5": "profiles/forza_horizon/profile.json",   # FH5 (324-byte Horizon packets)
        "forza_horizon6": "profiles/forza_horizon/profile.json",   # FH6 sends the same layout
        "ace": "profiles/ace/profile.json",                           # its own since 2026-09-18
        "beamng": "profiles/beamng/profile.json",
        "trackmania": "profiles/trackmania/profile.json",            # no HaptiConnect reference exists
    },
    "game_processes": {              # FH5 and FH6 are identical on the wire; the exe tells them apart
        "forza": "forza_gaming.desktop",
        "forza_horizon5": "forzahorizon5.exe",
        "forza_horizon6": "forzahorizon6.exe",
    },
    "audio": {
        "device": "ButtKicker",      # output name, or part of it; "" = Windows' default output
        "api": "WASAPI",             # preferred host API
        "samplerate": 48000,
        "blocksize": 480,            # 10 ms blocks
        "channels": [0],             # HaptiConnect drives the ButtKicker on channel 0 only; both channels sum louder
        "master_gain": 1.0,          # learned profiles carry HaptiConnect's absolute levels
    },
    "sources": {
        "forza": {"enabled": True, "port": 5555, "host": "127.0.0.1"},   # 0.0.0.0 also takes an Xbox / another PC
        "beamng": {"enabled": True, "port": 4444, "host": "127.0.0.1", "accel_scale": 1.0,
                   "motion_port": 0},        # 0 = Motion Sim on the OutGauge port (BeamNG's default for both)
        "ace": {"enabled": True, "poll_hz": 200, "susp_scale_m": 0.08},
        "trackmania": {"enabled": True, "host": "127.0.0.1", "port": 28765,   # Openplanet Data Sender (TCP)
                       "max_rate": 200, "damper_range_m": 0.2, "accel_window_ms": 20.0,
                       "slip_ratio_full": 0.15, "max_rpm": 11000.0, "idle_rpm": 1000.0},
    },
    "effects": {
        "engine":          {"enabled": True, "gain": 1.0, "freq_min": 22.0, "freq_max": 80.0,
                            "amp_idle": 0.30, "amp_throttle": 0.35, "harmonic": 0.15, "curve_pow": 1.0},
        "gear_shift":      {"enabled": True, "gain": 1.0, "freq": 45.0, "tau": 0.06, "cooldown": 0.12},
        "wheel_lock":      {"enabled": True, "gain": 1.0, "threshold": 1.0, "full": 3.0,
                            "freq": 28.0, "noise_cutoff": 70.0, "min_speed": 2.0},
        "wheel_slip":      {"enabled": True, "gain": 1.0, "spin_threshold": 1.0, "spin_full": 2.5,
                            "slide_threshold": 1.0, "slide_full": 2.0, "freq": 42.0, "noise_cutoff": 45.0},
        "abs":             {"enabled": True, "gain": 1.0, "pulse_hz": 13.0, "freq": 50.0},
        "suspension":      {"enabled": True, "gain": 1.0, "threshold": 1.0, "full": 8.0,
                            "front_freq": 38.0, "rear_freq": 30.0, "tau": 0.045, "min_interval": 0.04,
                            "texture_gain": 0.35, "texture_cutoff": 40.0},
        "road":            {"enabled": True, "gain": 1.0, "strip_spacing": 0.35, "strip_amp": 1.0,
                            "surface_gain": 0.6, "noise_cutoff": 55.0},
        "impact":          {"enabled": True, "gain": 1.0, "threshold": 25.0, "full": 100.0,
                            "freq": 26.0, "tau": 0.15, "cooldown": 0.12},
        "acceleration":    {"enabled": True, "gain": 0.6, "freq": 30.0, "ref": 8.0,
                            "lat_weight": 0.7, "long_weight": 1.0},
        "shift_indicator": {"enabled": False, "gain": 0.8, "rpm_pct": 0.95, "pulse_hz": 9.0, "freq": 65.0},
        # off unless a profile turns it on: the calibrated games must not gain an effect HaptiConnect lacks
        "grip_margin":     {"enabled": False, "gain": 0.3, "onset": 0.6, "full": 1.0, "curve_pow": 1.5,
                            "freq": 55.0, "pulse_min_hz": 4.0, "pulse_max_hz": 14.0, "pulse_depth": 0.7,
                            "lat_limit": 20.0, "slip_limit_deg": 6.0, "smooth": 0.15, "min_speed": 8.0},
        # Trackmania-only for now (they need per-wheel materials, ground contact and boost state)
        "surface":         {"enabled": False, "gain": 0.5, "speed_full": 40.0, "min_speed": 2.0,
                            "water_level": 0.5, "water_cutoff": 18.0, "splash_freq": 22.0, "splash_amp": 0.8,
                            "splash_tau": 0.25, "scrape_level": 0.5, "scrape_cutoff": 85.0},
        "landing":         {"enabled": False, "gain": 0.6, "min_air_s": 0.12, "v_min": 1.5, "v_full": 15.0,
                            "freq": 30.0, "tau": 0.18, "click_freq": 60.0, "click_amp": 0.35},
        "boost":           {"enabled": False, "gain": 0.4, "surge_freq": 42.0, "surge_tau": 0.25,
                            "sweep_lo": 35.0, "sweep_hi": 75.0, "sweep_s": 0.6, "turbo_hum": 0.25,
                            "reactor_freq": 34.0, "reactor_amp": 0.4},
    },
}


# Used when no profile has been chosen yet (a fresh install, or Demo before any game): a calibrated level.
# The synthetic DEFAULTS above run close to full scale.
FALLBACK_PROFILE = "profiles/forza_motorsport/profile.json"
# Profile folders renamed in 1.0.0; configs written before still point at the old names.
RENAMED_PROFILES = {"hapticonnect_fm": "forza_motorsport", "hapticonnect_fh5": "forza_horizon",
                    "hapticonnect_beamng": "beamng"}
# ACE shared the Forza Motorsport profile until it got its own; a config still pointing ACE there moves.
ACE_OLD_PROFILES = ("profiles/forza_motorsport/profile.json", "profiles/hapticonnect_fm/profile.json")
ACE_SPLIT_MARK = "ace_profile_split"     # set in config.json once the move above has been checked
# The window once stored every on/off switch in every preset - all ON, a copy rather than a choice - which
# froze them against later calibrations (BeamNG's shift light stayed on after its profile turned it off).
SWITCH_CLEANUP_MARK = "preset_switch_cleanup"             # the presets already cleaned (a list)
SWITCH_CLEANUP_FIRST = ("forza", "forza_horizon5", "forza_horizon6", "beamng")   # what a `true` mark covered
SWITCH_CLEANUP_PENDING = "preset_switch_cleanup_pending"   # read only: a build in between listed skipped ones
SWITCH_CLEANUP_PRESETS = SWITCH_CLEANUP_FIRST + ("ace",)   # ACE added 2026-09-22 (PM): cleaned once too


def _cleanup_done(user: dict) -> set:
    """The presets config.json says were cleaned already."""
    mark = user.get(SWITCH_CLEANUP_MARK)
    done = {str(k) for k in mark} if isinstance(mark, list) else set(SWITCH_CLEANUP_FIRST) if mark else set()
    return done - {str(k) for k in (user.get(SWITCH_CLEANUP_PENDING) or [])}


# Blocks config.json holds only where they differ from DEFAULTS. A copy of a default would freeze it:
# a later release that changes the default (a port, a rate) would never reach that user.
USER_BLOCKS = ("audio", "sources", "profiles", "game_processes")


def _diff(value, default):
    """What of `value` differs from `default` (dicts key by key), or None when nothing does."""
    if isinstance(value, dict) and isinstance(default, dict):
        out = {}
        for k, v in value.items():
            d = copy.deepcopy(v) if k not in default else _diff(v, default[k])
            if d is not None:
                out[k] = d
        return out or None
    return None if value == default else copy.deepcopy(value)


def _drop_defaults(user: dict) -> bool:
    """Remove settings that only repeat DEFAULTS; True when anything went.

    Earlier versions wrote every default into config.json (the whole file on a first run, and the
    whole audio/sources blocks on every save). Stripping them on load lets new defaults through.
    """
    before = json.dumps(user, sort_keys=True, default=str)
    for key in USER_BLOCKS:
        if key in user:
            d = _diff(user[key], DEFAULTS[key])
            if d is None:
                user.pop(key)
            else:
                user[key] = d
    effects = user.get("effects")
    if isinstance(effects, dict):
        for name, params in list(effects.items()):
            if not isinstance(params, dict):
                continue
            base = DEFAULTS["effects"].get(name, {})
            for k in [k for k, v in params.items() if k not in ("trim", "enabled") and k in base and v == base[k]]:
                params.pop(k)
            if not params:
                effects.pop(name)
        if not effects:
            user.pop("effects")
    return json.dumps(user, sort_keys=True, default=str) != before


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


GAME_LABELS = {
    "forza": "Forza Motorsport",
    "forza_horizon5": "Forza Horizon 5",
    "forza_horizon6": "Forza Horizon 6",
    "forza_horizon": "Forza Horizon",          # only seen in configs written before the two were split
    "ace": "Assetto Corsa EVO",
    "beamng": "BeamNG.drive",
    "trackmania": "Trackmania",
    "demo": "Demo",
}


def profile_folder(profile_path: str | Path | None) -> str:
    """The folder a learned profile lives in: profiles/<folder>/profile.json."""
    if not profile_path:
        return "default"
    p = Path(profile_path)
    return p.parent.name if p.suffix == ".json" else p.name


def list_presets(cfg: dict) -> list[dict]:
    """One preset per GAME in the `profiles` map.

    Two games may share a calibration - Forza Horizon 5 and 6 use the same profile - but they still
    get separate presets, so a change made for one game never moves the other.
    """
    return [{"key": game, "profile": prof, "label": GAME_LABELS.get(game, game)}
            for game, prof in (cfg.get("profiles") or {}).items()]


def preset_key(cfg: dict, profile_path: str | Path | None) -> str:
    """Which preset a bare profile path belongs to, when no game has been detected yet.

    Falls back to the profile's folder so a profile outside the game map still keeps its own
    settings instead of borrowing another game's.
    """
    if not profile_path:
        return "default"
    want = resolve_profile(cfg, profile_path).resolve()
    for game, prof in (cfg.get("profiles") or {}).items():
        try:
            if resolve_profile(cfg, prof).resolve() == want:
                return game
        except OSError:
            continue
    return profile_folder(profile_path)


def preset_settings(cfg: dict, key: str) -> dict:
    """The user's saved strengths for one preset, shaped the way apply_trims wants them."""
    return (cfg.get("presets") or {}).get(key) or {}


def set_preset_effect(cfg: dict, key: str, name: str, trim: float | None = None,
                      enabled: bool | None = None, profile_enabled: bool | None = None) -> dict:
    """Record one effect's strength against a preset (not against whatever is loaded right now).

    With `profile_enabled` (the profile's own switch for that effect), an `enabled` equal to it is not
    stored: the preset then follows the profile, so a later calibration that switches an effect on or
    off still reaches the user - a copied switch would freeze it.
    """
    preset = cfg.setdefault("presets", {}).setdefault(key, {})
    entry = preset.setdefault("effects", {}).setdefault(name, {})
    if trim is not None:
        entry["trim"] = round(float(trim), 4)
    if enabled is not None:
        if profile_enabled is not None and bool(enabled) == bool(profile_enabled):
            entry.pop("enabled", None)
        else:
            entry["enabled"] = bool(enabled)
    return entry


def apply_trims(cfg: dict, user: dict | None = None) -> dict:
    """Apply the user's own per-effect settings on top of the gains currently in cfg.

    `trim` (1.0 = exactly as calibrated) is the only gain the user owns. A learned profile's
    gains are HaptiConnect's absolute levels, so a saved absolute gain would silently undo a
    calibration; the trim scales it instead. Call this once, after a profile has been merged in.
    Records the pre-trim gains in cfg["_base_gains"] so a UI can move the trim without reloading.
    """
    user_effects = (user or {}).get("effects") or {}
    base, base_enabled = {}, {}
    for name, e in cfg.get("effects", {}).items():
        base[name] = float(e.get("gain", 1.0))
        base_enabled[name] = bool(e.get("enabled", True))
        params = user_effects.get(name) or {}
        if "enabled" in params:
            e["enabled"] = bool(params["enabled"])
        trim = float(params.get("trim", 1.0))
        e["trim"] = trim
        e["gain"] = base[name] * trim
    cfg["_base_gains"] = base
    cfg["_base_enabled"] = base_enabled
    return cfg


def apply_profile(cfg: dict, profile_path: str | Path, keep_user: dict | None = None,
                  preset: str | None = None) -> dict:
    """Merge a learned profile's effect parameters into cfg (sample paths made absolute).

    keep_user: per-effect 'trim'/'enabled' to re-apply on top of the profile. Defaults to the
    settings saved for `preset` - the detected game - so each game keeps its own strengths even
    when two of them share a calibration.
    """
    preset = preset or preset_key(cfg, profile_path)
    pp = Path(profile_path)
    if not pp.is_absolute():
        pp = Path.cwd() / pp
    if keep_user is None:
        keep_user = preset_settings(cfg, preset)
    # start from the unprofiled defaults: a profile only overrides the keys it defines, so applying
    # one on top of another would otherwise leave the previous profile's gains in place
    cfg["effects"] = base_effects(cfg.get("_user"))
    data = json.loads(pp.read_text(encoding="utf-8"))
    learned = {}
    for name, params in data.get("effects", {}).items():
        params = dict(params)
        for key in ("sample", "wavetable"):
            if params.get(key) and not Path(params[key]).is_absolute():
                params[key] = str((pp.parent / params[key]).resolve())
        cfg["effects"].setdefault(name, {}).update(params)
        learned[name] = sorted(params)
    apply_trims(cfg, keep_user)
    cfg["_profile_effects"] = learned
    cfg["_preset"] = preset
    return cfg


def base_effects(user: dict | None = None) -> dict:
    """The effect parameters before any profile or user strength: DEFAULTS plus the user's own
    free parameters (frequencies, thresholds), minus the two keys the UI owns. Keeping `enabled`
    out of it is what lets apply_trims record the profile's own on/off in cfg["_base_enabled"].
    """
    u = copy.deepcopy((user or {}).get("effects") or {})
    for params in u.values():
        if isinstance(params, dict):
            params.pop("gain", None)
            params.pop("enabled", None)
    return _merge(DEFAULTS["effects"], u)


def _sanitize_user(user: dict | None) -> dict:
    """Drop effect keys that are no longer the user's to set.

    Pre-trim configs (no "trim" anywhere in the entry) saved an absolute gain, which would now
    mask a calibrated profile, and a copy of the DEFAULTS' enable flag, which was never a choice
    the user made - the old loader ignored both. Anything the current UI writes is kept.
    """
    u = copy.deepcopy(user or {})
    u.pop("autostart", None)          # an old start-with-the-app switch: its false must not mean Haptics off
    u.pop("forward", None)            # live forwarding to HaptiConnect was removed
    if not isinstance(u.get("haptics_on", True), bool):
        u.pop("haptics_on")           # a hand-edit that is not true/false: the haptics stay on
    for name, params in ((u.get("effects") or {})).items():
        if not isinstance(params, dict):
            continue
        params.pop("gain", None)
        legacy = "trim" not in params
        if legacy and params.get("enabled") == DEFAULTS["effects"].get(name, {}).get("enabled"):
            params.pop("enabled", None)
    return u


def load(path: str | Path | None, profile: str | None = None, with_profile: bool = True) -> dict:
    """Load config from path, creating it with the defaults when it does not exist yet.

    with_profile=False returns the merged config without any profile applied (the base the runtime
    uses when it switches profiles per game); the raw user dict is kept in cfg["_user"].
    """
    if path is None:
        cfg, user = copy.deepcopy(DEFAULTS), {}
    else:
        p = Path(path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}\n", encoding="utf-8")          # the defaults live in code, not in the file
            cfg, user = copy.deepcopy(DEFAULTS), {}
            cfg["_first_run"] = True
        else:
            with p.open("r", encoding="utf-8") as f:
                user = _sanitize_user(json.load(f))
            resave = _drop_defaults(user)
            cfg = _merge(DEFAULTS, user)
            cfg["effects"] = base_effects(user)
            if resave:
                cfg["_resave"] = True                 # the window writes the slimmer file back once
    cfg["_user"] = copy.deepcopy(user)
    cfg["_config_dir"] = str(Path(path).resolve().parent) if path is not None else str(Path.cwd())
    _migrate_games(cfg)
    _migrate_profile_names(cfg)
    _seed_presets(cfg, user)                     # before the ACE move: old folder-keyed presets reach ACE too
    if not user.get(ACE_SPLIT_MARK):
        # once per config: a later hand-edit that points ACE at the Forza profile again is the user's choice
        _migrate_ace_profile(cfg)
        cfg["_user"][ACE_SPLIT_MARK] = True
        if path is not None and not cfg.get("_first_run"):
            cfg["_resave"] = True                # write the move, and the mark, back once
    if path is not None:
        # once per preset and config, like the ACE move: a switch set after this is the user's and stays.
        # A preset whose profile would not load stays off the list and is tried again next launch.
        done = _cleanup_done(user)
        todo = [k for k in SWITCH_CLEANUP_PRESETS if k not in done]
        if todo:
            skipped = _cleanup_preset_switches(cfg, todo)
            now_done = sorted(done | (set(todo) - set(skipped)))
            cfg["_user"][SWITCH_CLEANUP_MARK] = now_done
            cfg["_user"].pop(SWITCH_CLEANUP_PENDING, None)
            if not cfg.get("_first_run") and (now_done != sorted(done) or user.get(SWITCH_CLEANUP_PENDING)):
                cfg["_resave"] = True
    prof = profile or cfg.get("profile") or (FALLBACK_PROFILE if path is not None else None)
    if with_profile and prof:
        prof_path = resolve_profile(cfg, prof)
        if prof_path.exists():
            cfg["profile"] = str(prof_path)
            apply_profile(cfg, prof_path)          # uses this profile's own preset settings
            return cfg
        cfg["_profile_missing"] = str(prof_path)
    apply_trims(cfg, user)
    return cfg


HORIZON_KEYS = ("forza_horizon5", "forza_horizon6")


def _migrate_games(cfg: dict) -> dict:
    """Split the old single `forza_horizon` entry into FH5 and FH6, keeping its settings for both."""
    profiles = cfg.get("profiles") or {}
    presets = cfg.setdefault("presets", {})
    if "forza_horizon" not in profiles:
        return cfg
    path = profiles.pop("forza_horizon")
    for key in HORIZON_KEYS:
        profiles.setdefault(key, path)
        if key not in presets and "forza_horizon" in presets:
            presets[key] = copy.deepcopy(presets["forza_horizon"])
    presets.pop("forza_horizon", None)
    return cfg


def _migrate_ace_profile(cfg: dict) -> bool:
    """ACE got its own profile (profiles/ace); move a config that still sends ACE to the Forza one.

    Presets are kept per game, so the user's ACE strengths come along unchanged. True when moved.
    """
    profiles = cfg.get("profiles") or {}
    old = str(profiles.get("ace") or "").replace("\\", "/")
    if old and any(old == path or old.endswith("/" + path) for path in ACE_OLD_PROFILES):
        _drop_copied_switches(cfg, "ace", old)
        profiles["ace"] = DEFAULTS["profiles"]["ace"]
        return True
    return False


def _drop_copied_switches(cfg: dict, key: str, profile: str) -> None:
    """Forget a preset's on/off switches that only repeat `profile`'s own - the window used to store
    every switch - so the preset follows its new profile's switches. Deliberate changes stay."""
    try:
        probe = load(None)
        apply_profile(probe, resolve_profile(cfg, profile), keep_user={})
        base = probe.get("_base_enabled") or {}
    except Exception:
        return
    effects = ((cfg.get("presets") or {}).get(key) or {}).get("effects") or {}
    for name, entry in list(effects.items()):
        if isinstance(entry, dict) and "enabled" in entry and name in base and bool(entry["enabled"]) == base[name]:
            entry.pop("enabled")
            if not entry:
                effects.pop(name)


def _cleanup_preset_switches(cfg: dict, keys=SWITCH_CLEANUP_PRESETS) -> list:
    """Forget the copied on/off switches in the Forza, Horizon, BeamNG and ACE presets (maintainer-approved
    2026-09-20; ACE added 2026-09-22).

    A stored switch equal to the profile's is a copy: dropped, so the preset follows the profile. A stored
    ON where the profile says off is dropped too - the old window stored every switch ON, so those are
    copies as well. A stored OFF where the profile says on is the one thing that can only be a choice: kept.
    A deliberate switch that matched the profile follows the profile from now on. Returns the presets it
    had to skip because their profile would not load (to try again later).
    """
    presets = cfg.get("presets") or {}
    profiles = cfg.get("profiles") or {}
    skipped = []
    for key in keys:
        effects = (presets.get(key) or {}).get("effects") or {}
        if key not in profiles or not any(isinstance(e, dict) and "enabled" in e for e in effects.values()):
            continue
        try:
            probe = load(None)
            apply_profile(probe, resolve_profile(cfg, profiles[key]), keep_user={})
            base = probe.get("_base_enabled") or {}
        except Exception:
            skipped.append(key)                  # a profile that will not load right now: try again later
            continue
        for name, entry in list(effects.items()):
            if not isinstance(entry, dict) or "enabled" not in entry or name not in base:
                continue
            if not bool(entry["enabled"]) and bool(base[name]):
                continue                         # OFF where the profile is on: a choice, kept
            entry.pop("enabled")
            if not entry:
                effects.pop(name)
    return skipped


def _migrate_profile_names(cfg: dict) -> dict:
    """Point profile paths at the renamed folders, and carry presets once keyed by an old folder name."""
    def fix(value):
        if not isinstance(value, str):
            return value
        for old, new in RENAMED_PROFILES.items():
            value = re.sub(rf"(^|[\\/]){old}(?=[\\/]|$)", rf"\g<1>{new}", value)
        return value

    profiles = cfg.get("profiles") or {}
    for game, prof in list(profiles.items()):
        profiles[game] = fix(prof)
    if cfg.get("profile"):
        cfg["profile"] = fix(cfg["profile"])
    presets = cfg.get("presets") or {}
    for old, new in RENAMED_PROFILES.items():
        if old in presets:
            moved = presets.pop(old)
            presets.setdefault(new, moved)
    return cfg


def _seed_presets(cfg: dict, user: dict) -> dict:
    """Give every preset an entry, carrying over the single global set of trims older configs had."""
    legacy = {name: {k: v for k, v in (params or {}).items() if k in ("trim", "enabled")}
              for name, params in ((user or {}).get("effects") or {}).items()}
    legacy = {name: v for name, v in legacy.items() if v}
    presets = cfg.setdefault("presets", {})
    entries = list_presets(cfg)
    # presets used to be keyed by profile folder, so both Forza and ACE shared one entry; hand that
    # entry to every game that uses the profile, then retire it
    for entry in entries:
        folder = profile_folder(entry["profile"])
        if folder in presets and entry["key"] not in presets:
            presets[entry["key"]] = copy.deepcopy(presets[folder])
    for folder in {profile_folder(e["profile"]) for e in entries}:
        if folder not in {e["key"] for e in entries}:
            presets.pop(folder, None)

    keys = [e["key"] for e in entries]
    if cfg.get("profile"):
        keys.append(preset_key(cfg, cfg["profile"]))   # the fallback profile has settings too
    for key in dict.fromkeys(keys):
        effects = presets.setdefault(key, {}).setdefault("effects", {})
        for name, params in legacy.items():
            effects.setdefault(name, dict(params))
    return cfg


def resolve_profile(cfg: dict, prof: str | Path) -> Path:
    """A profile path from the config: absolute as given, else next to config.json, else the copy
    shipped with the app (so a config kept somewhere else still finds the bundled profiles)."""
    p = Path(prof)
    if p.is_absolute():
        return p
    here = Path(cfg.get("_config_dir", ".")) / p
    if here.exists():
        return here
    shipped = PROJECT_DIR / p
    return shipped if shipped.exists() else here


def portable_path(path: str | Path, root: str | Path | None = None) -> str:
    """How a path is written into files other people may see (profiles, session metadata).

    Inside the project it becomes relative with forward slashes; outside it keeps only its last two
    parts, so no user name, drive or folder layout from the PC that wrote it ends up in the file.
    """
    p = Path(path)
    base = Path(root) if root is not None else PROJECT_DIR
    try:
        return p.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        parts = [x for x in p.parts if x not in (p.anchor, "/", "\\")]
        return "/".join(parts[-2:]) if parts else p.name


def relative_profile(cfg: dict, prof: str | Path | None) -> str | None:
    """Store profiles inside the project folder as relative paths so config.json stays portable."""
    if not prof:
        return None
    p = Path(prof)
    for base in (Path(cfg.get("_config_dir", ".")), PROJECT_DIR):
        try:
            return p.resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            continue
    return str(p)


def save_user(cfg: dict, path: str | Path) -> dict:
    """Write back only what the user owns; learned profile data must never land in config.json.

    Starts from the file as it was loaded (cfg["_user"]), so hand-edited keys such as source ports
    survive, and updates the settings the UI controls: audio, sources, profiles and presets. Those
    blocks are written only where they differ from DEFAULTS, so later default changes still apply.
    """
    user = copy.deepcopy(cfg.get("_user") or {})
    current = {key: copy.deepcopy(cfg.get(key, DEFAULTS[key])) for key in USER_BLOCKS}
    current["audio"]["master_gain"] = round(float(current["audio"].get("master_gain", 1.0)), 4)
    for key, value in current.items():             # only what differs from DEFAULTS (see USER_BLOCKS)
        d = _diff(value, DEFAULTS[key])
        if d is None:
            user.pop(key, None)
        else:
            user[key] = d
    user["profile"] = relative_profile(cfg, cfg.get("profile"))
    user["windows_startup_asked"] = bool(cfg.get("windows_startup_asked", False))
    if cfg.get("haptics_on", True) is False:
        user["haptics_on"] = False
    else:
        user.pop("haptics_on", None)                 # on is the default: nothing to keep
    user["presets"] = copy.deepcopy(cfg.get("presets") or {})   # strengths live per preset now
    effects = user.setdefault("effects", {})
    for name in list(effects):
        entry = effects[name]
        if not isinstance(entry, dict):
            continue
        for key, val in list(entry.items()):         # keep only genuine hand-edits of free parameters
            if key in ("gain", "trim", "enabled") or val == DEFAULTS["effects"].get(name, {}).get(key):
                entry.pop(key)
        if not entry:
            effects.pop(name)
    if not effects:
        user.pop("effects", None)
    Path(path).write_text(json.dumps(user, indent=2), encoding="utf-8")
    cfg["_user"] = copy.deepcopy(user)
    return user
