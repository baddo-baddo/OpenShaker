"""Run from the project folder:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import mmap
import struct
import time
import unittest

import numpy as np

from openshaker import config
from openshaker.effects.base import onepole_lp
from openshaker.engine import HapticEngine
from openshaker.sources.ace import ACESource, OFF, parse_physics
from openshaker.sources.base import Source
from openshaker.sources.beamng import BeamNGSource
from openshaker.sources.forza import ForzaSource
from openshaker.telemetry import Telemetry


def forza_packet(size: int) -> bytes:
    buf = bytearray(size)
    struct.pack_into("<i", buf, 0, 1)                       # IsRaceOn
    struct.pack_into("<3f", buf, 8, 7500.0, 850.0, 4321.0)  # max, idle, current rpm
    struct.pack_into("<3f", buf, 20, 1.5, -0.5, 6.0)        # accel x y z
    struct.pack_into("<3f", buf, 32, 0.0, 0.0, 30.0)        # velocity
    struct.pack_into("<4f", buf, 68, 0.4, 0.45, 0.5, 0.55)  # susp normalized
    struct.pack_into("<4f", buf, 84, 0.1, 0.1, 2.0, 2.0)    # slip ratio
    struct.pack_into("<4i", buf, 116, 0, 1, 0, 1)           # rumble strip
    struct.pack_into("<4f", buf, 148, 0.2, 0.2, 0.2, 0.2)   # surface rumble
    struct.pack_into("<i", buf, 228, 8)                     # cylinders
    d = 244 if size == 324 else 232
    if size >= 324 or size == 331:
        struct.pack_into("<f", buf, d + 12, 33.3)           # speed m/s
        struct.pack_into("<5B", buf, d + 71, 255, 0, 0, 0, 3)  # accel brake clutch handbrake gear
    return bytes(buf)


class ForzaTests(unittest.TestCase):
    def test_horizon_324(self):
        src = ForzaSource(port=0)
        t = src.parse(forza_packet(324))
        self.assertEqual(src.kind, "horizon")
        self.assertTrue(t.active)
        self.assertAlmostEqual(t.rpm, 4321.0)
        self.assertAlmostEqual(t.max_rpm, 7500.0)
        self.assertAlmostEqual(t.speed, 33.3, places=4)
        self.assertAlmostEqual(t.throttle, 1.0)
        self.assertEqual(t.gear, 3)
        self.assertEqual(t.rumble_strip, [False, True, False, True])
        self.assertAlmostEqual(t.slip_ratio[2], 2.0)
        self.assertAlmostEqual(t.accel_long, 6.0)
        self.assertAlmostEqual(t.accel_lat, 1.5)
        self.assertEqual(t.cylinders, 8)

    def test_motorsport_331(self):
        src = ForzaSource(port=0)
        t = src.parse(forza_packet(331))
        self.assertEqual(src.kind, "motorsport")
        self.assertAlmostEqual(t.speed, 33.3, places=4)
        self.assertEqual(t.gear, 3)

    def test_sled_232_and_junk(self):
        src = ForzaSource(port=0)
        t = src.parse(forza_packet(232))
        self.assertEqual(src.kind, "sled")
        self.assertAlmostEqual(t.speed, 30.0, places=4)   # from velocity vector
        self.assertIsNone(src.parse(b"\x00" * 100))


class BeamNGTests(unittest.TestCase):
    def test_hapticonnect_136(self):
        buf = bytearray(136)
        struct.pack_into("<f", buf, 12, 4.0)                          # gear
        struct.pack_into("<4f", buf, 20, 20.0, 26.0, 20.0, 3200.0)    # speed, wheelspeed, air, rpm
        struct.pack_into("<i", buf, 36, 7000)
        struct.pack_into("<3f", buf, 68, 0.9, 0.0, 0.0)
        struct.pack_into("<4f", buf, 116, 0.5, 4.0, 0.1, 0.1)
        struct.pack_into("<i", buf, 132, 1)
        t = BeamNGSource(port=0).parse(bytes(buf))
        self.assertEqual(t.gear, 4)
        self.assertAlmostEqual(t.rpm, 3200.0)
        self.assertAlmostEqual(t.max_rpm, 7000.0)
        self.assertAlmostEqual(t.throttle, 0.9)
        self.assertGreater(t.slip_ratio[0], 1.5)      # 30% wheel overspeed => past grip limit
        self.assertTrue(t.active)

    def test_stock_96(self):
        buf = bytearray(96)
        struct.pack_into("<b", buf, 10, 3)
        struct.pack_into("<2f", buf, 12, 10.0, 2500.0)
        struct.pack_into("<2I", buf, 40, 0x766, (1 << 2) | (1 << 10))   # handbrake and ABS lit
        struct.pack_into("<3f", buf, 48, 0.25, 0.75, 1.0)
        struct.pack_into("<16s", buf, 60, b"Fuel 50%")                 # display text right after the pedals
        t = BeamNGSource(port=0).parse(bytes(buf))
        self.assertEqual(t.gear, 2)
        self.assertAlmostEqual(t.rpm, 2500.0)
        self.assertAlmostEqual(t.throttle, 0.25)
        self.assertAlmostEqual(t.brake, 0.75)
        self.assertAlmostEqual(t.clutch, 1.0)
        self.assertEqual(t.handbrake, 1.0)
        self.assertTrue(t.abs_active)
        self.assertFalse(t.tc_active)

    def test_stock_packet_from_a_real_drive(self):
        # sessions/beamng_drive_1, frame 2: standing in neutral, brake and clutch pressed, parking brake on
        head = ("000000006265616d00e001000000000000008c43000000000000c03f0ad7a33c000000000000c03f"
                "660700000400000000000000" "0000803f" "0000803f")
        t = BeamNGSource(port=0).parse(bytes.fromhex(head).ljust(96, b"\0"))
        self.assertEqual((t.throttle, t.brake, t.clutch), (0.0, 1.0, 1.0))
        self.assertEqual(t.handbrake, 1.0)
        self.assertAlmostEqual(t.rpm, 280.0)

    def test_hapticonnect_136_pedals_and_lights(self):
        buf = bytearray(136)
        struct.pack_into("<I", buf, 64, 1 << 10)                        # ABS lit
        struct.pack_into("<3f", buf, 68, 0.1, 0.6, 0.0)
        struct.pack_into("<i", buf, 132, 1)
        t = BeamNGSource(port=0).parse(bytes(buf))
        self.assertAlmostEqual(t.brake, 0.6)
        self.assertTrue(t.abs_active)
        self.assertEqual(t.handbrake, 0.0)
        struct.pack_into("<3f", buf, 68, 0.8, 0.0, 0.0)                 # off the brake, bit still lit
        self.assertFalse(BeamNGSource(port=0).parse(bytes(buf)).abs_active)

    def test_hapticonnect_mod_leaves_speed_empty(self):
        buf = bytearray(136)
        struct.pack_into("<4f", buf, 20, 0.0, 20.0, 20.0, 3000.0)       # speed unset; wheel = air speed
        struct.pack_into("<i", buf, 132, 1)
        t = BeamNGSource(port=0).parse(bytes(buf))
        self.assertAlmostEqual(t.speed, 20.0)
        self.assertAlmostEqual(t.slip_ratio[0], 0.0)                    # rolling freely, no fake wheelspin


def ace_physics_bytes(packet_id: int) -> bytes:
    buf = bytearray(800)
    struct.pack_into("<i", buf, OFF["packetId"], packet_id)
    struct.pack_into("<2f", buf, OFF["gas"], 0.75, 0.0)
    struct.pack_into("<2i", buf, OFF["gear"], 4, 5600)             # 4 => 3rd gear
    struct.pack_into("<f", buf, OFF["speedKmh"], 144.0)
    struct.pack_into("<3f", buf, OFF["accG"], 0.5, -0.1, 0.8)      # lat, vert, long in g
    struct.pack_into("<4f", buf, OFF["suspensionTravel"], 0.02, 0.02, 0.03, 0.03)
    struct.pack_into("<i", buf, OFF["currentMaxRpm"], 8200)
    struct.pack_into("<4f", buf, OFF["slipRatio"], 0.05, 0.05, 0.3, 0.3)
    struct.pack_into("<2i", buf, OFF["tcInAction"], 1, 0)
    struct.pack_into("<3i", buf, OFF["ignitionOn"], 1, 0, 1)
    struct.pack_into("<4f", buf, OFF["kerbVibration"], 0.4, 0.0, 0.1, 0.0)
    return bytes(buf)


class ACETests(unittest.TestCase):
    def test_parse_physics(self):
        t = parse_physics(ace_physics_bytes(1), evo=True, susp_scale_m=0.1, max_rpm_fallback=6000.0)
        self.assertEqual(t.gear, 3)
        self.assertAlmostEqual(t.rpm, 5600.0)
        self.assertAlmostEqual(t.max_rpm, 8200.0)
        self.assertAlmostEqual(t.speed, 40.0)
        self.assertAlmostEqual(t.throttle, 0.75)
        self.assertAlmostEqual(t.accel_long, 0.8 * 9.81, places=4)
        self.assertAlmostEqual(t.susp_travel[2], 0.3, places=5)
        self.assertAlmostEqual(t.slip_ratio[2], (0.3 - 0.05) / 0.15, places=4)   # re-zeroed true slip ratio
        self.assertTrue(t.tc_active)
        self.assertFalse(t.abs_active)
        self.assertTrue(t.engine_running)
        self.assertTrue(t.has_vib_hints)
        self.assertAlmostEqual(t.kerb_vib, 0.4)

    def test_shared_memory_roundtrip(self):
        """Create a fake game mapping and check the source attaches and publishes frames."""
        name = "Local\\acevo_pmf_physics_bktest"
        mm = mmap.mmap(-1, 4096, tagname=name)
        try:
            mm.seek(0)
            mm.write(ace_physics_bytes(1))
            src = ACESource(poll_hz=500, physics_names=(name,), graphics_names=("Local\\nonexistent_bktest",))
            src.start()
            try:
                deadline = time.time() + 3.0
                while src.latest() is None and time.time() < deadline:
                    time.sleep(0.02)
                first = src.latest()
                self.assertIsNotNone(first, f"source never attached: {src.status} {src.error}")
                self.assertAlmostEqual(first.rpm, 5600.0)
                mm.seek(0)
                mm.write(ace_physics_bytes(2))
                deadline = time.time() + 3.0
                while src.latest().seq == first.seq and time.time() < deadline:
                    time.sleep(0.02)
                self.assertGreater(src.latest().seq, first.seq)
                self.assertTrue(src.latest().active)
            finally:
                src.stop()
        finally:
            mm.close()


class FakeSource(Source):
    name = "fake"

    def push(self, **fields) -> Telemetry:
        t = Telemetry(active=True, rpm=4000.0, max_rpm=8000.0, idle_rpm=900.0, gear=2, speed=20.0)
        for k, v in fields.items():
            setattr(t, k, v)
        self.publish(t)
        return t


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(None)
        self.src = FakeSource()
        self.engine = HapticEngine(self.cfg, 48000, [self.src])

    def test_silent_without_telemetry(self):
        out = self.engine.render(480)
        self.assertEqual(out.shape, (480,))
        self.assertEqual(float(np.abs(out).max()), 0.0)

    def test_engine_tone_and_limits(self):
        self.src.push(throttle=1.0)
        peak = 0.0
        for _ in range(20):
            out = self.engine.render(480)
            self.assertTrue(np.all(np.isfinite(out)))
            peak = max(peak, float(np.abs(out).max()))
        self.assertGreater(peak, 0.1)
        self.assertLessEqual(peak, 1.0)

    def test_gear_shift_and_impact_trigger(self):
        self.src.push(gear=2)
        self.engine.render(480)
        time.sleep(0.02)
        self.src.push(gear=3, accel_long=-60.0)
        self.engine.render(480)
        names = {e.name for e in self.engine.effects if e.level > 0.05}
        self.assertIn("gear_shift", names)
        self.assertIn("impact", names)

    def test_stale_source_goes_silent(self):
        self.src.push(throttle=1.0)
        self.engine.render(480)
        self.engine.stale_after = 0.0
        time.sleep(0.01)
        for _ in range(60):          # ramps decay across a few blocks
            out = self.engine.render(480)
        self.assertLess(float(np.abs(out).max()), 1e-3)


class ForwardTests(unittest.TestCase):
    def test_outgauge_roundtrip_matches_hapticonnect_layout(self):
        from openshaker.forward import SIZE, pack_outgauge
        t = Telemetry(active=True, engine_running=True, rpm=5100.0, max_rpm=7600.0, gear=4, speed=31.0,
                      throttle=0.8, brake=0.1, clutch=0.0, accel_lat=2.0, accel_long=-3.0, accel_vert=0.5,
                      slip_ratio=[0.0, 0.0, 2.0, 2.0])
        pkt = pack_outgauge(t)
        self.assertEqual(len(pkt), 136)
        self.assertEqual(SIZE, 136)
        back = BeamNGSource(port=0).parse(pkt)
        self.assertEqual(back.gear, 4)
        self.assertAlmostEqual(back.rpm, 5100.0)
        self.assertAlmostEqual(back.max_rpm, 7600.0)
        self.assertAlmostEqual(back.speed, 31.0)
        self.assertAlmostEqual(back.throttle, 0.8, places=6)
        self.assertAlmostEqual(back.accel_long, -3.0, places=6)
        self.assertGreater(back.slip_ratio[0], 1.5)       # wheelspin survives the round trip
        self.assertTrue(back.active)


class ForzaPackTests(unittest.TestCase):
    def test_forza_packets_round_trip(self):
        from openshaker.forward import pack_forza
        t = Telemetry(active=True, engine_running=True, rpm=5100.0, max_rpm=7600.0, idle_rpm=900.0, gear=4,
                      speed=31.0, throttle=0.8, brake=0.1, accel_lat=2.0, accel_long=-3.0, accel_vert=0.5,
                      slip_ratio=[0.1, 0.1, 2.0, 2.0], slip_angle=[0.3] * 4, susp_travel=[0.4, 0.5, 0.6, 0.7],
                      rumble_strip=[False, True, False, True], surface_rumble=[0.3] * 4, cylinders=8)
        for kind, size in (("horizon", 324), ("motorsport", 331)):
            pkt = pack_forza(t, kind)
            self.assertEqual(len(pkt), size)
            back = ForzaSource(port=0).parse(pkt)
            self.assertAlmostEqual(back.rpm, 5100.0, places=3)
            self.assertEqual(back.gear, 4)
            self.assertAlmostEqual(back.speed, 31.0, places=3)
            self.assertAlmostEqual(back.throttle, 0.8, places=2)
            self.assertEqual(back.rumble_strip, [False, True, False, True])
            self.assertAlmostEqual(back.slip_ratio[2], 2.0, places=5)
            self.assertAlmostEqual(back.susp_travel[3], 0.7, places=5)
            self.assertAlmostEqual(back.accel_long, -3.0, places=5)
            self.assertEqual(back.cylinders, 8)


class DSPTests(unittest.TestCase):
    def test_onepole_matches_reference_loop(self):
        rng = np.random.default_rng(0)
        x = rng.standard_normal(1000)
        a, z = 0.01, 0.3
        y, _ = onepole_lp(x, a, z)
        ref = np.empty_like(x)
        s = z
        for i, v in enumerate(x):
            s = s + a * (v - s)
            ref[i] = s
        self.assertTrue(np.allclose(y, ref, atol=1e-9))


if __name__ == "__main__":
    unittest.main()
