"""ACE drives are logged byte-exact: the whole physics page, and every packet while logging."""
import mmap
import os
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.drivelog import tele_row                                   # noqa: E402
from openshaker.sources import ace                                          # noqa: E402
from openshaker.sources.ace import OFF, PHYSICS_BYTES, ACESource            # noqa: E402


def page(packet_id: int, rpm: int = 5000) -> bytes:
    data = bytearray(PHYSICS_BYTES)
    struct.pack_into("<i", data, OFF["packetId"], packet_id)
    struct.pack_into("<2i", data, OFF["gear"], 3, rpm)
    struct.pack_into("<f", data, OFF["speedKmh"], 72.0)
    data[700:704] = b"TAIL"                                  # something far into the page
    return bytes(data)


class AceLoggingTests(unittest.TestCase):
    def test_the_live_app_keeps_its_rate_and_a_logged_drive_catches_every_packet(self):
        src = ACESource(poll_hz=200, physics_names=("Local\\none",), graphics_names=("Local\\none",))
        self.assertAlmostEqual(src.poll_period(), 1 / 200)
        src.listeners.append(lambda tele: None)              # what --log attaches
        self.assertLessEqual(src.poll_period(), 1 / 333)
        self.assertAlmostEqual(src.poll_period(), 1 / ace.LOG_POLL_HZ)

    def test_each_frame_carries_the_whole_physics_page(self):
        name = f"Local\\acevo_pmf_physics_ostest_{os.getpid()}"      # a mapping of the test's own, not the game's
        mm = mmap.mmap(-1, 4096, tagname=name)
        self.addCleanup(mm.close)
        mm.seek(0)
        mm.write(page(1))
        frames = []
        src = ACESource(poll_hz=500, physics_names=(name,), graphics_names=("Local\\nonexistent_ostest",))
        src.listeners.append(frames.append)
        src.start()
        self.addCleanup(src.stop)
        deadline = time.time() + 3.0
        while not frames and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(frames, f"source never attached: {src.status} {src.error}")
        self.assertEqual(frames[0].raw, page(1))
        mm.seek(0)
        mm.write(page(2, rpm=6100))
        deadline = time.time() + 3.0
        while len(frames) < 2 and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(frames[-1].raw, page(2, rpm=6100))
        row = tele_row(frames[-1], 0.0)
        self.assertEqual(bytes.fromhex(row[-1]), page(2, rpm=6100), "the drive log's raw_hex is the page")


if __name__ == "__main__":
    unittest.main()
