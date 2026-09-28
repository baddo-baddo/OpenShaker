"""Sliders jump to a click, and the number next to a slider can be clicked and typed into."""
import json
import re
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import close_window, fake_registry, no_optional_outputs, tk_root                                       # noqa: E402
from openshaker import config, gui                                             # noqa: E402
from openshaker.audio import DeviceNotFound                                    # noqa: E402
from openshaker.gui import ValueBox, click_to_jump, parse_percent              # noqa: E402

HINT = "Click a slider to jump there, or click a number to type one"


def fire(widget, sequence):
    """Run the handler bound to `sequence` on `widget`, the way Tk would. Tk only delivers key events
    to the window with the keyboard focus, and a test window must never take that from the user's
    game, so the bound script is called directly: a wrong binding (Esc applying, Enter dropping) fails."""
    script = widget.bind(sequence)
    assert script, f"{sequence} is not bound on {widget}"
    command = re.search(r"\[(\S+)", script).group(1)
    args = ["0"] * len(widget._subst_format)
    args[widget._subst_format.index("%W")] = str(widget)
    return widget.tk.call(command, *args)


class ParsePercentTests(unittest.TestCase):
    def test_what_people_type(self):
        for text, value in (("85", 85.0), ("85%", 85.0), (" 85.5 % ", 85.5), ("85,5", 85.5), ("0", 0.0),
                            ("-5", -5.0), ("250", 250.0)):
            self.assertEqual(parse_percent(text), value, text)
        for text in ("", "   ", "%", "abc", "8 5", "nan", "inf", "1e999"):
            self.assertIsNone(parse_percent(text), text)


class ClickToJumpTests(unittest.TestCase):
    def setUp(self):
        self.root = tk_root(offscreen=True)
        self.addCleanup(close_window, self.root)
        self.var = tk.DoubleVar(value=100.0)
        self.calls = []
        self.before = []
        self.scale = ttk.Scale(self.root, from_=0.0, to=200.0, variable=self.var, length=400,
                               command=lambda v: self.calls.append(float(v)))
        self.scale.pack(padx=10, pady=10)
        self.grip = click_to_jump(self.scale, before=lambda: self.before.append(1))
        self.root.update()
        self.w, self.h = self.scale.winfo_width(), self.scale.winfo_height()

    def click(self, x, *drag_to, button=1):
        y = self.h // 2
        self.scale.event_generate(f"<Button-{button}>", x=x, y=y)
        for dx in drag_to:
            self.scale.event_generate(f"<B{button}-Motion>", x=dx, y=y)
        self.scale.event_generate(f"<ButtonRelease-{button}>", x=drag_to[-1] if drag_to else x, y=y)
        self.root.update()

    def test_a_click_on_the_track_jumps_there(self):
        x = int(self.w * 0.25)
        self.click(x)
        self.assertAlmostEqual(self.var.get(), self.scale.get(x, self.h // 2), places=6)
        self.assertGreater(self.var.get(), 5.0, "all the way there, not one step or to the end")
        self.assertLess(self.var.get(), 60.0)
        self.assertEqual(len(self.calls), 1, "the slider's command ran once, so the change is applied and saved")
        self.assertEqual(self.before, [1])

    def test_the_knob_follows_the_mouse_until_release(self):
        x = int(self.w * 0.25)
        self.click(x, x + 80, self.w + 50)                  # and off the end
        self.assertEqual(self.var.get(), 200.0)
        self.scale.event_generate("<B1-Motion>", x=10, y=self.h // 2)   # button already up
        self.root.update()
        self.assertEqual(self.var.get(), 200.0)

    def test_grabbing_the_knob_still_drags(self):
        self.click(self.w // 2, self.w // 2 + 100)
        self.assertGreater(self.var.get(), 130.0)

    def test_pressing_the_knob_without_moving_changes_nothing(self):
        y = self.h // 2
        xs = [x for x in range(self.w) if "slider" in str(self.scale.identify(x, y))]
        self.assertTrue(xs, "the knob is found")
        x = xs[-1]                                          # off centre, still on the knob
        self.assertNotAlmostEqual(self.scale.get(x, y), 100.0, places=3, msg="a jump here would show")
        self.click(x)
        self.assertEqual(self.var.get(), 100.0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.before, [1])

    def test_right_and_middle_buttons_close_an_open_box_first(self):
        for n, button in enumerate((2, 3), start=1):
            self.var.set(100.0)
            self.root.update()                              # redraw the knob where the value now is
            self.click(int(self.w * 0.8), button=button)
            self.assertEqual(len(self.before), n, f"button {button} ran before()")
            self.assertGreater(self.var.get(), 150.0, f"and ttk's own button-{button} jump still happens")

    def test_the_grip_knows_when_the_slider_is_held(self):
        y = self.h // 2
        for button in (1, 2, 3):
            self.scale.event_generate(f"<Button-{button}>", x=int(self.w * 0.25), y=y)
            self.assertTrue(self.grip.held, button)
            self.scale.event_generate(f"<ButtonRelease-{button}>", x=int(self.w * 0.25), y=y)
            self.assertFalse(self.grip.held, button)

    def test_the_drag_can_be_ended_from_outside(self):
        y = self.h // 2
        self.scale.event_generate("<Button-1>", x=int(self.w * 0.25), y=y)
        self.grip()                                         # e.g. the view moved to another preset
        value = self.var.get()
        self.scale.event_generate("<B1-Motion>", x=int(self.w * 0.9), y=y)
        self.scale.event_generate("<ButtonRelease-1>", x=int(self.w * 0.9), y=y)
        self.root.update()
        self.assertEqual(self.var.get(), value)


class ValueBoxTests(unittest.TestCase):
    def setUp(self):
        self.root = tk_root()
        self.addCleanup(close_window, self.root)
        self.group = {"open": None}
        self.applied = []
        self.var = tk.StringVar(value="100%")
        self.box = ValueBox(self.root, self.var, 5, self.applied.append, self.group)
        self.box.frame.pack()
        self.other_var = tk.StringVar(value="40%")
        self.other = ValueBox(self.root, self.other_var, 5, self.applied.append, self.group)
        self.other.frame.pack()

    def type(self, text):
        self.box.entry.delete(0, "end")
        self.box.entry.insert(0, text)

    def test_clicking_the_number_opens_a_box_with_it(self):
        fire(self.box.label, "<Button-1>")
        self.assertTrue(self.box.editing)
        self.assertEqual(self.box.entry.get(), "100", "the number without the % sign, ready to overtype")
        self.assertTrue(self.box.entry.selection_present())
        self.assertTrue(self.box.entry.winfo_manager(), "the box is shown")
        self.assertFalse(self.box.label.winfo_manager(), "in place of the number")

    def test_enter_keypad_enter_and_leaving_apply_escape_does_not(self):
        for key, value in (("<Return>", "150"), ("<KP_Enter>", "120"), ("<FocusOut>", "90")):
            self.box.begin()
            self.type(value)
            fire(self.box.entry, key)
            self.assertEqual(self.applied[-1], value, key)
            self.assertFalse(self.box.editing, key)
            self.assertTrue(self.box.label.winfo_manager(), f"{key}: the number is back")
        self.box.begin()
        self.type("9")
        fire(self.box.entry, "<Escape>")
        self.assertEqual(self.applied, ["150", "120", "90"], "Esc throws the typing away")

    def test_looking_applies_nothing_but_retyping_the_same_number_does(self):
        self.box.begin()
        fire(self.box.entry, "<FocusOut>")                  # opened to look, then clicked away
        self.assertEqual(self.applied, [], "a stored 87.5 % must not become the 88 % on show")
        self.box.begin()
        self.type("100")                                    # typed the number that is shown
        fire(self.box.entry, "<Return>")
        self.assertEqual(self.applied, ["100"], "typing it means it: 0 over a shown '0%' must mute")

    def double_click(self, jitter):
        self.box.label.event_generate("<Button-1>", x=2, y=2, time=1000)       # opens the box
        self.box.entry.event_generate("<Button-1>", x=2, y=2, time=1200)       # second click lands on it
        self.root.update()                                  # idle work runs before the mouse moves, as it would
        if jitter:
            self.box.entry.event_generate("<B1-Motion>", x=2 + jitter, y=2, time=1205)
        self.box.entry.event_generate("<ButtonRelease-1>", x=2 + jitter, y=2, time=1210)
        self.root.update()

    def test_a_double_click_keeps_the_whole_number_selected(self):
        for jitter in (0, 1, 3):                            # the mouse may move a little
            self.double_click(jitter)
            self.assertTrue(self.box.entry.selection_present(), f"{jitter} px: typing replaces the number")
            self.assertEqual(self.box.entry.index("insert"), len(self.box.entry.get()))
            fire(self.box.entry, "<Escape>")

    def test_a_later_click_in_the_box_places_the_caret_as_usual(self):
        late = 1000 + gui.double_click_ms() + 500
        self.box.label.event_generate("<Button-1>", x=2, y=2, time=1000)
        self.box.entry.event_generate("<Button-1>", x=2, y=2, time=late)
        self.box.entry.event_generate("<ButtonRelease-1>", x=2, y=2, time=late + 10)
        self.root.update()
        self.assertFalse(self.box.entry.selection_present())

    def test_one_box_at_a_time(self):
        self.box.begin()
        self.type("90")
        fire(self.other.label, "<Button-1>")                # clicking the next number
        self.assertEqual(self.applied, ["90"], "the first box applies what it held")
        self.assertIs(self.group["open"], self.other)
        fire(self.box.entry, "<FocusOut>")                  # a late FocusOut from the first box
        self.assertEqual(self.applied, ["90"], "does nothing twice")


class FakeRunningRuntime:
    """Just enough of a running Runtime for App._refresh to see a game being detected."""

    running = True

    def __init__(self, preset):
        self.preset = preset
        self.profile_changed = False

    def status(self):
        return {"device": "Fake", "sr": 48000, "latency_ms": 10.0, "xruns": 0, "profile": None,
                "game": "FakeGame", "preset": self.preset, "audio_error": None, "sources": [], "tele": None,
                "peak_db": -120.0, "levels": {}}

    def set_trim(self, *_a):
        pass

    def set_effect(self, *_a, **_k):
        pass

    def set_master(self, *_a):
        pass

    def audio_lost(self):
        return False

    def stop(self):
        self.running = False


class AppInputTests(unittest.TestCase):
    """The real window, mapped off screen (invisible, never activated), with a runtime that opens no audio."""

    def setUp(self):
        fake_registry(self)                                    # never the real registry
        no_optional_outputs(self)                              # the public build's window
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"

        class NoAudio:
            running = False

            def __init__(_s, *a, **k):
                pass

            def start(_s):
                raise DeviceNotFound("output device 'ButtKicker' is not connected")

            def stop(_s):
                pass

        self.addCleanup(setattr, gui, "Runtime", gui.Runtime)
        gui.Runtime = NoAudio
        self.make_app()

    def make_app(self):
        self.root = tk_root(offscreen=True)
        self.addCleanup(close_window, self.root)
        self.app = gui.App(self.root, config.load(self.path), str(self.path), use_tray=False, ask_startup=False)
        self.root.update()

    def stored_trim(self, name, key=None):
        effects = config.preset_settings(self.app.cfg, key or self.app.preset_key).get("effects") or {}
        return (effects.get(name) or {}).get("trim")

    def click(self, widget, fraction=None, button=1):
        x = 2 if fraction is None else int(widget.winfo_width() * fraction)
        y = 2 if fraction is None else widget.winfo_height() // 2
        widget.event_generate(f"<Button-{button}>", x=x, y=y)
        widget.event_generate(f"<ButtonRelease-{button}>", x=x, y=y)
        self.root.update()
        return x, y

    def open_box(self, box, text):
        self.click(box.label)
        self.assertIs(self.app._boxes["open"], box, "clicking the number opened its box")
        box.entry.delete(0, "end")
        box.entry.insert(0, text)

    def type_into(self, box, text, key="<Return>"):
        self.open_box(box, text)
        fire(box.entry, key)
        self.root.update()

    def other_preset(self):
        return next(p["key"] for p in self.app.presets if p["key"] != self.app.preset_key)

    def set_master(self, value):
        self.app.master_var.set(value)
        self.app._master_changed(None)

    # -- sliders ---------------------------------------------------------------------------------------
    def test_clicking_a_strength_slider_jumps_there_in_whole_percent(self):
        x, y = self.click(self.app.effect_scales["engine"], 0.25)
        _en, trim, lbl = self.app.effect_vars["engine"]
        self.assertAlmostEqual(trim.get(), round(self.app.effect_scales["engine"].get(x, y)), places=6)
        self.assertEqual(trim.get(), round(trim.get()), "whole percent")
        self.assertEqual(lbl.get().strip(), f"{trim.get():.0f}%")
        self.assertAlmostEqual(self.stored_trim("engine"), trim.get() / 100.0)

    def test_clicking_the_master_slider_jumps_there_in_whole_percent(self):
        self.open_box(self.app.strength_boxes["engine"], "55")
        scale = self.app.master_scale
        x, y = self.click(scale, 0.25)
        self.assertIsNone(self.app._boxes["open"], "touching a slider applied the open box")
        v = self.app.master_var.get()
        self.assertEqual(v, round(scale.get(x, y), 2))
        self.assertGreater(v, 0.05)
        self.assertEqual(self.app.master_lbl.get(), f"{v * 100:.0f}%")
        self.assertEqual(self.app.cfg["audio"]["master_gain"], v)
        self.set_master(0.3712)
        self.assertEqual(self.app.master_var.get(), 0.37, "Master moves in whole percent")

    def test_every_master_key_steps_one_or_ten_percent(self):
        for event, step in (("<<PrevChar>>", -0.01), ("<<NextChar>>", 0.01), ("<<PrevLine>>", -0.01),
                            ("<<NextLine>>", 0.01), ("<<PrevWord>>", -0.10), ("<<NextWord>>", 0.10),
                            ("<<PrevPara>>", -0.10), ("<<NextPara>>", 0.10)):
            self.set_master(0.5)
            self.app.master_scale.event_generate(event)     # virtual events need no keyboard focus
            self.root.update()
            self.assertAlmostEqual(self.app.master_var.get(), 0.5 + step, msg=event)

    def test_a_left_click_on_the_same_slider_is_not_undone_by_the_box(self):
        self.open_box(self.app.strength_boxes["engine"], "150")
        self.click(self.app.effect_scales["engine"], 0.25)
        self.click(self.app.hint_label)
        value = self.app.effect_vars["engine"][1].get()
        self.assertLess(value, 100.0, "the click wins over the number typed before it")
        self.assertAlmostEqual(self.stored_trim("engine"), value / 100.0)

    def test_a_right_or_middle_click_on_the_same_slider_is_not_undone_by_the_box(self):
        for button in (2, 3):
            self.type_into(self.app.strength_boxes["engine"], "100")
            self.open_box(self.app.strength_boxes["engine"], "150")
            self.click(self.app.effect_scales["engine"], 0.25, button=button)
            self.assertIsNone(self.app._boxes["open"], button)
            self.click(self.app.hint_label)
            value = self.app.effect_vars["engine"][1].get()
            self.assertLess(value, 100.0, f"button {button}: ttk's jump wins over the typed 150")
            self.assertAlmostEqual(self.stored_trim("engine"), value / 100.0)

    # -- typing ----------------------------------------------------------------------------------------
    def test_typing_a_strength(self):
        box = self.app.strength_boxes["engine"]
        _en, trim, lbl = self.app.effect_vars["engine"]
        self.type_into(box, "150")
        self.assertEqual(trim.get(), 150.0)
        self.assertEqual(lbl.get().strip(), "150%")
        self.assertAlmostEqual(self.stored_trim("engine"), 1.5)
        self.assertIsNotNone(self.app._save_job, "and it saves itself like a slider change")
        self.type_into(box, "37.4 %")
        self.assertEqual(trim.get(), 37.0)
        self.type_into(box, "250")
        self.assertEqual(trim.get(), 200.0)
        self.assertIn("0 to 200", self.app.msg_var.get())
        self.type_into(box, "loud")
        self.assertEqual(trim.get(), 200.0, "not a number: nothing changes")
        self.assertIn("not a number", self.app.msg_var.get())
        self.type_into(box, "10", key="<Escape>")
        self.assertEqual(trim.get(), 200.0, "Esc cancels")

    def test_typing_the_master_level(self):
        self.assertEqual(self.app.master_lbl.get(), "100%")
        self.type_into(self.app.master_box, "80")
        self.assertAlmostEqual(self.app.master_var.get(), 0.8)
        self.assertAlmostEqual(self.app.cfg["audio"]["master_gain"], 0.8)
        self.assertEqual(self.app.master_lbl.get(), "80%")
        self.type_into(self.app.master_box, "150%")
        self.assertAlmostEqual(self.app.master_var.get(), 1.0)
        self.assertIn("0 to 100", self.app.msg_var.get())

    def reload_with(self, user: dict):
        close_window(self.root)
        self.path.write_text(json.dumps(user), encoding="utf-8")
        self.make_app()
        self.app._select_preset("forza")

    def test_looking_at_a_number_leaves_the_stored_value_alone(self):
        self.reload_with({"audio": {"master_gain": 0.875},
                          "presets": {"forza": {"effects": {"engine": {"trim": 0.875}, "impact": {"trim": 0.005}}}}})
        for box in (self.app.strength_boxes["engine"], self.app.strength_boxes["impact"], self.app.master_box):
            self.click(box.label)
            fire(box.entry, "<FocusOut>")                # opened, then clicked away without typing
        self.assertAlmostEqual(self.stored_trim("engine", "forza"), 0.875)
        self.assertAlmostEqual(self.stored_trim("impact", "forza"), 0.005, msg="must not be rounded to 0 = muted")
        self.assertAlmostEqual(self.app.cfg["audio"]["master_gain"], 0.875)

    def test_typing_the_number_on_show_still_applies_it(self):
        self.reload_with({"presets": {"forza": {"effects": {"impact": {"trim": 0.004}}}}})
        box = self.app.strength_boxes["impact"]
        self.assertEqual(self.app.effect_vars["impact"][2].get().strip(), "0%")
        self.type_into(box, "0")                         # the user means: off
        self.assertEqual(self.stored_trim("impact", "forza"), 0.0)

    def test_clicking_elsewhere_applies_the_typing(self):
        self.open_box(self.app.strength_boxes["impact"], "55")
        self.click(self.app.effect_scales["engine"], 0.25)     # another slider (its own before() path)
        self.assertEqual(self.app.effect_vars["impact"][1].get(), 55.0)
        self.open_box(self.app.strength_boxes["impact"], "66")
        self.click(self.app.hint_label)                        # plain window background: the root binding
        self.assertIsNone(self.app._boxes["open"])
        self.assertEqual(self.app.effect_vars["impact"][1].get(), 66.0)
        self.open_box(self.app.strength_boxes["impact"], "77")
        self.click(self.app.strength_boxes["impact"].entry)    # a click inside the box keeps it open
        self.assertIs(self.app._boxes["open"], self.app.strength_boxes["impact"])

    def test_the_window_stores_only_switches_that_differ_from_the_profile(self):
        en, _trim, _lbl = self.app.effect_vars["engine"]
        profile_on = self.app._bases(self.app.preset_key)[1]["engine"]
        stored = lambda: (config.preset_settings(self.app.cfg, self.app.preset_key).get("effects") or {}).get("engine", {})
        en.set(not profile_on)
        self.app._effect_changed("engine")
        self.assertEqual(stored().get("enabled"), (not profile_on))
        en.set(profile_on)
        self.app._effect_changed("engine")
        self.assertNotIn("enabled", stored(), "back to the profile's own switch: nothing frozen")
        en.set(not profile_on)
        self.app._effect_changed("engine")
        self.app.reset_to_profile()
        self.assertNotIn("enabled", stored(), "reset follows the profile too")

    def test_the_hint_stays_on_screen(self):
        self.assertIn(HINT, str(self.app.hint_label.cget("text")))
        self.app.start()                                       # replaces the message line
        self.root.update()
        self.assertIn(HINT, str(self.app.hint_label.cget("text")))
        self.assertTrue(self.app.hint_label.winfo_ismapped())

    # -- presets switching under the user's hands -----------------------------------------------------
    def test_a_game_detected_while_typing(self):
        start = self.app.preset_key
        box = self.app.strength_boxes["engine"]
        self.open_box(box, "60")
        self.app._select_preset(start)                         # the same preset stays on screen
        self.assertIs(self.app._boxes["open"], box, "the typing survives")
        fire(box.entry, "<Return>")
        self.assertAlmostEqual(self.stored_trim("engine", start), 0.6)
        self.open_box(self.app.master_box, "70")
        other = self.other_preset()
        self.app._select_preset(other)                         # Master is not per preset
        self.assertIs(self.app._boxes["open"], self.app.master_box)
        fire(self.app.master_box.entry, "<Return>")
        self.assertAlmostEqual(self.app.master_var.get(), 0.7)
        self.app._select_preset(start)
        self.open_box(box, "5")
        self.app._select_preset(other)                         # the view moves: the half-typed 5 is dropped
        self.assertIsNone(self.app._boxes["open"])
        self.assertNotEqual(self.stored_trim("engine", other), 0.05)
        self.app._select_preset(start)
        self.assertAlmostEqual(self.stored_trim("engine", start), 0.6)

    def test_the_message_says_when_typing_was_dropped_and_only_then(self):
        start = self.app.preset_key
        other = self.other_preset()
        self.app.rt = FakeRunningRuntime(start)
        self.app.active_preset = start
        self.open_box(self.app.strength_boxes["engine"], "60")
        self.app.rt.preset = other
        self.app._refresh()                                    # a game for the other preset is detected
        self.assertIn("was not applied", self.app.msg_var.get())
        self.app.rt.preset = start                             # the next switch, with nothing open
        self.app._refresh()
        self.assertNotIn("was not applied", self.app.msg_var.get(), "said once, not again")
        self.click(self.app.strength_boxes["engine"].label)    # opened to look only
        self.app.rt.preset = other
        self.app._refresh()
        self.assertNotIn("was not applied", self.app.msg_var.get(), "nothing was typed")

    def test_picking_a_preset_by_hand_applies_the_typing_first(self):
        start = self.app.preset_key
        other = self.other_preset()
        self.open_box(self.app.strength_boxes["engine"], "65")
        self.app.preset_var.set(self.app._preset(other)["label"])   # e.g. the mouse wheel over the list
        self.app._preset_picked()
        self.assertAlmostEqual(self.stored_trim("engine", start), 0.65)
        self.assertFalse(self.app._dropped_typing, "nothing is reported as lost")

    def held_drag_then_switch(self, press_x, button=1):
        scale = self.app.effect_scales["road"]
        w, h = scale.winfo_width(), scale.winfo_height()
        start, other = self.app.preset_key, self.other_preset()
        before = self.stored_trim("road", other)
        scale.event_generate(f"<Button-{button}>", x=press_x(w, h), y=h // 2)
        scale.event_generate(f"<B{button}-Motion>", x=press_x(w, h) + 2, y=h // 2)
        self.root.update()
        self.app._select_preset(other)                         # a game is detected mid-drag
        scale.event_generate(f"<B{button}-Motion>", x=int(w * 0.1), y=h // 2)
        scale.event_generate(f"<ButtonRelease-{button}>", x=int(w * 0.1), y=h // 2)
        self.root.update()
        self.assertEqual(self.stored_trim("road", other), before, f"button {button}")
        self.app._select_preset(start)

    def knob_x(self, w, h):
        scale = self.app.effect_scales["road"]
        xs = [x for x in range(w) if "slider" in str(scale.identify(x, h // 2))]
        self.assertTrue(xs, "the knob is found")
        return xs[len(xs) // 2]

    def test_a_held_drag_does_not_write_into_the_next_preset(self):
        self.held_drag_then_switch(lambda w, h: int(w * 0.8))              # our jump-and-follow
        self.held_drag_then_switch(self.knob_x)                             # ttk's own knob drag
        self.held_drag_then_switch(lambda w, h: int(w * 0.8), button=3)    # ttk's right-button drag

    def test_a_master_drag_carries_on_across_a_preset_switch(self):
        scale = self.app.master_scale
        w, h = scale.winfo_width(), scale.winfo_height()
        start, other = self.app.preset_key, self.other_preset()
        for press_at in ("track", "knob"):                      # our follow, then ttk's own knob drag
            self.set_master(0.5)
            self.root.update()
            xs = [x for x in range(w) if "slider" in str(scale.identify(x, h // 2))]
            x0 = int(w * 0.8) if press_at == "track" else xs[len(xs) // 2]
            scale.event_generate("<Button-1>", x=x0, y=h // 2)
            scale.event_generate("<B1-Motion>", x=x0 + 2, y=h // 2)
            self.root.update()
            self.app._select_preset(other if self.app.preset_key == start else start)   # Master is not per preset
            scale.event_generate("<B1-Motion>", x=int(w * 0.3), y=h // 2)
            scale.event_generate("<ButtonRelease-1>", x=int(w * 0.3), y=h // 2)
            self.root.update()
            self.assertEqual(self.app.master_var.get(), round(scale.get(int(w * 0.3), h // 2), 2), press_at)


if __name__ == "__main__":
    unittest.main()
