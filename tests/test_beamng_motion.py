"""BeamNG's built-in Motion Sim protocol merged with OutGauge, and the drive checker."""
import socket
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.beamng_check import axis_check, format_report, replay, report   # noqa: E402
from openshaker.sources.beamng import MOTION_SIZE, BeamNGSource                   # noqa: E402


def motion(vel=(0.0, 0.0, 0.0), acc=(0.0, 0.0, 0.0), rate=(0.0, 0.0, 0.0), up=(0.0, 0.0, 1.0)):
    return b"BNG1" + struct.pack("<21f", 0, 0, 0, *vel, *acc, *up, 0, 0, 0, *rate, 0, 0, 0)


def outgauge(wheel=0.0, rpm=3000.0, gear=3, throttle=0.0, brake=0.0):
    buf = bytearray(96)
    struct.pack_into("<b", buf, 10, gear + 1)
    struct.pack_into("<2f", buf, 12, wheel, rpm)
    struct.pack_into("<3f", buf, 48, throttle, brake, 0.0)
    return bytes(buf)


def free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class MergeTests(unittest.TestCase):
    def test_motion_packet_is_88_bytes(self):
        self.assertEqual(len(motion()), MOTION_SIZE)
        self.assertEqual(MOTION_SIZE, 88)

    def test_outgauge_and_motion_sim_merge(self):
        src = BeamNGSource(port=0)
        src.parse(outgauge(wheel=5.0, brake=1.0), now=10.0)
        t = src.parse(motion(vel=(12.0, 16.0, 0.0), acc=(1.0, -7.0, 0.5)), now=10.01)
        self.assertAlmostEqual(t.speed, 20.0, places=4)                     # ground speed, not wheel speed
        self.assertEqual((t.rpm, t.gear, t.brake), (3000.0, 3, 1.0))        # pedals and engine from OutGauge
        self.assertAlmostEqual(t.accel_lat, 1.0, places=5)
        self.assertAlmostEqual(t.accel_long, -7.0, places=5)
        self.assertAlmostEqual(t.accel_vert, 0.5, places=5)
        self.assertAlmostEqual(t.slip_ratio[0], (5.0 - 20.0) / 20.0 / 0.15, places=4)   # a lock-up
        self.assertTrue(t.extra["motion"])
        self.assertEqual(src.status, "OutGauge + Motion Sim")

    def test_outgauge_alone_says_how_to_turn_on_motion_sim(self):
        src = BeamNGSource(port=0)
        t = src.parse(outgauge(wheel=15.0), now=1.0)
        self.assertAlmostEqual(t.speed, 15.0)
        self.assertEqual((t.accel_long, t.slip_ratio[0]), (0.0, 0.0))
        self.assertIn("tick Motion Sim", src.status)

    def test_motion_sim_alone(self):
        src = BeamNGSource(port=0)
        t = src.parse(motion(vel=(0.0, 30.0, 0.0), acc=(0.0, 3.0, 0.0)), now=1.0)
        self.assertTrue(t.active)
        self.assertFalse(t.engine_running)
        self.assertAlmostEqual(t.speed, 30.0)
        self.assertAlmostEqual(t.accel_long, 3.0)
        self.assertIn("tick OutGauge", src.status)

    def test_a_stopped_motion_stream_is_dropped(self):
        src = BeamNGSource(port=0)
        src.parse(motion(vel=(0.0, 20.0, 0.0), acc=(0.0, 9.0, 0.0)), now=10.0)
        t = src.parse(outgauge(wheel=18.0), now=11.0)                       # Motion Sim went quiet a second ago
        self.assertAlmostEqual(t.speed, 18.0)
        self.assertEqual((t.accel_long, t.slip_ratio[0]), (0.0, 0.0))
        self.assertFalse(t.extra["motion"])

    def test_reversing_is_not_a_lockup(self):
        src = BeamNGSource(port=0)
        src.parse(outgauge(wheel=-10.0, gear=-1, brake=0.5), now=1.0)
        t = src.parse(motion(vel=(0.0, -10.0, 0.0)), now=1.01)
        self.assertAlmostEqual(t.slip_ratio[0], 0.0, places=4)

    def test_other_packets_are_ignored(self):
        src = BeamNGSource(port=0)
        self.assertIsNone(src.parse(b"XXXX" + bytes(84)))
        self.assertIsNone(src.parse(bytes(50)))


class SocketTests(unittest.TestCase):
    def _drive(self, src, send):
        src.start()
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        deadline = time.time() + 3.0
        tele = None
        try:
            while time.time() < deadline:
                send(out)
                time.sleep(0.02)
                tele = src.latest()
                if tele is not None and tele.extra.get("motion") and tele.rpm == 3000.0:
                    break
        finally:
            out.close()
            src.stop()
        return tele

    def test_both_protocols_on_one_port(self):
        port = free_port()
        src = BeamNGSource(port=port)

        def send(sock):
            sock.sendto(outgauge(wheel=20.0), ("127.0.0.1", port))
            sock.sendto(motion(vel=(0.0, 20.0, 0.0)), ("127.0.0.1", port))
        tele = self._drive(src, send)
        self.assertIsNone(src.error)
        self.assertTrue(tele is not None and tele.extra["motion"] and tele.rpm == 3000.0)

    def test_motion_sim_on_its_own_port(self):
        og_port, motion_port = free_port(), free_port()
        src = BeamNGSource(port=og_port, motion_port=motion_port)

        def send(sock):
            sock.sendto(outgauge(wheel=20.0), ("127.0.0.1", og_port))
            sock.sendto(motion(vel=(0.0, 20.0, 0.0)), ("127.0.0.1", motion_port))
        tele = self._drive(src, send)
        self.assertIsNone(src.error)
        self.assertTrue(tele is not None and tele.extra["motion"] and tele.rpm == 3000.0)


class CheckTests(unittest.TestCase):
    def drive(self):
        """10 s: accelerate at 6 m/s^2 for 5 s, then brake at 6 m/s^2 with the wheels locked for a second."""
        rows = []
        for k in range(2000):
            t = k * 0.005
            a = 6.0 if t < 5.0 else -6.0
            v = 6.0 * t if t < 5.0 else 30.0 - 6.0 * (t - 5.0)
            rows.append((t, motion(vel=(0.0, v, 0.0), acc=(0.3, a, 0.0))))
            if k % 3 == 0:
                locked = 6.0 <= t < 7.0
                rows.append((t + 0.001, outgauge(wheel=0.0 if locked else v, throttle=1.0 if a > 0 else 0.0,
                                                 brake=1.0 if a < 0 else 0.0)))
        return rows

    def test_axis_check_finds_the_longitudinal_axis(self):
        res = axis_check(replay(self.drive()))
        self.assertEqual(res["long_axis"], 1)
        self.assertEqual(res["long_sign"], 1.0)
        self.assertGreater(res["long"][1], 0.9)

    def test_report_counts_the_lockup_and_both_streams(self):
        r = report(replay(self.drive()))
        self.assertGreater(r["motion_share"], 0.95)
        self.assertGreater(r["outgauge_share"], 0.95)
        self.assertAlmostEqual(r["lock_s"], 1.0, delta=0.1)
        text = format_report(r)
        self.assertIn("matches", text)
        self.assertNotIn("NO MOTION SIM", text)


if __name__ == "__main__":
    unittest.main()
