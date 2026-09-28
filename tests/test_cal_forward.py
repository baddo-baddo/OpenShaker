"""Packets sent to HaptiConnect for the A/B comparison: gear byte and the raw-packet layout."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.forward import forza_gear_byte, horizon_from_raw, pack, pack_forza   # noqa: E402
from openshaker.sources.forza import ForzaSource                                     # noqa: E402
from openshaker.telemetry import Telemetry                                           # noqa: E402


def frame(**kw) -> Telemetry:
    base = dict(active=True, engine_running=True, rpm=5100.0, max_rpm=7600.0, idle_rpm=900.0, gear=4,
                speed=31.0, throttle=0.8, brake=0.1, accel_lat=2.0, accel_long=-3.0, accel_vert=0.5,
                slip_ratio=[0.1, 0.1, 2.0, 2.0], slip_angle=[0.3] * 4, susp_travel=[0.4, 0.5, 0.6, 0.7],
                rumble_strip=[False, True, False, True], surface_rumble=[2.1, 0.0, 1.7, 0.0], cylinders=8)
    base.update(kw)
    return Telemetry(**base)


class GearByteTests(unittest.TestCase):
    def test_neutral_is_not_sent_as_reverse(self):
        self.assertEqual(forza_gear_byte(-1), 0)          # reverse
        self.assertEqual(forza_gear_byte(0), 11)          # neutral
        self.assertEqual(forza_gear_byte(11), 11)         # neutral as the 2026-09-10 logs stored it
        self.assertEqual(forza_gear_byte(12), 11)
        for g in range(1, 11):
            self.assertEqual(forza_gear_byte(g), g)

    def test_every_gear_round_trips_through_the_parser(self):
        parser = ForzaSource(port=0)
        for kind in ("horizon", "motorsport"):
            for g in (-1, 0, 1, 5, 10):
                self.assertEqual(parser.parse(pack_forza(frame(gear=g), kind)).gear, g, (kind, g))
            self.assertEqual(parser.parse(pack_forza(frame(gear=11), kind)).gear, 0)    # old-log neutral


class RawPacketTests(unittest.TestCase):
    def test_motorsport_packet_becomes_the_same_frame_in_horizon_layout(self):
        parser = ForzaSource(port=0)
        for g in (-1, 0, 3):
            ms = pack_forza(frame(gear=g), "motorsport")
            self.assertEqual(len(ms), 331)
            hz = horizon_from_raw(ms)
            self.assertEqual(len(hz), 324)
            a, b = parser.parse(ms), parser.parse(hz)
            self.assertEqual(a, b)                          # dataclass equality: every field
            self.assertEqual(hz[244 + 71:244 + 76], ms[232 + 71:232 + 76])     # pedals and gear byte
            self.assertEqual(hz[232:244], bytes(12))

    def test_horizon_packets_pass_unchanged_and_sled_is_refused(self):
        hz = pack_forza(frame(), "horizon")
        self.assertEqual(horizon_from_raw(hz), hz)
        self.assertIsNone(horizon_from_raw(pack_forza(frame(), "motorsport")[:232]))
        self.assertIsNone(horizon_from_raw(b"\x00" * 100))

    def test_raw_format_sends_the_stored_packet(self):
        t = frame()
        t.raw = pack_forza(t, "horizon")
        self.assertEqual(pack(t, "raw"), t.raw)
        with self.assertRaises(ValueError):
            pack(frame(), "raw")

    def test_kerb_values_above_one_survive(self):
        t = ForzaSource(port=0).parse(horizon_from_raw(pack_forza(frame(), "motorsport")))
        self.assertAlmostEqual(t.surface_rumble[0], 2.1, places=5)
        self.assertEqual(t.cylinders, 8)


if __name__ == "__main__":
    unittest.main()
