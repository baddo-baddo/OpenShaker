"""Trackmania's surface table, pinned to the numbers in Openplanet's header (EPlugSurfaceMaterialId)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.effects.racing import SurfaceEffect                  # noqa: E402
from openshaker.sources.trackmania import SURFACES, surface_name     # noqa: E402

DRIVABLE = ["Concrete", "Pavement", "Grass", "Ice", "Metal", "Sand", "Dirt", "DirtRoad", "Rubber", "SlidingRubber",
            "Rock", "Wood", "Asphalt", "WetDirtRoad", "WetAsphalt", "WetPavement", "WetGrass", "Snow", "ResonantMetal",
            "MetalTrans", "Stone", "SlidingWood", "Tech", "TechArmor", "TechSafe", "TechGround", "Forest", "Wheat",
            "PavementStair", "TechMagnetic", "TechSuperMagnetic", "TechMagneticAccel", "MetalFence", "RubberBand",
            "Gravel", "RoadIce", "RoadSynthetic", "Green", "Plastic"]


class SurfaceTableTests(unittest.TestCase):
    def test_ids_match_openplanet(self):
        expected = {0: "Concrete", 2: "Grass", 3: "Ice", 6: "Dirt", 16: "Asphalt", 21: "Snow", 22: "ResonantMetal",
                    39: "Tech", 45: "TechGround", 49: "Forest", 69: "Gravel", 74: "RoadIce", 75: "RoadSynthetic",
                    76: "Green", 77: "Plastic", 80: "XXX_Null"}
        for material, name in expected.items():
            self.assertEqual(surface_name(material), name, material)
        self.assertEqual(len(SURFACES), 81)

    def test_unknown_ids_are_labelled_not_guessed(self):
        self.assertEqual(surface_name(81), "id 81")
        self.assertEqual(surface_name(-1), "id -1")

    def test_every_drivable_surface_has_a_texture(self):
        self.assertEqual([s for s in DRIVABLE if s not in SurfaceEffect.TEXTURES], [])
        self.assertEqual([s for s in DRIVABLE if s not in SURFACES], [], "texture names must be real surfaces")

    def test_loose_surfaces_are_rougher_than_roads(self):
        tex = SurfaceEffect.TEXTURES
        for rough in ("Dirt", "Gravel", "Grass", "Forest"):
            for smooth in ("Asphalt", "Tech", "RoadSynthetic"):
                self.assertGreater(tex[rough][1], tex[smooth][1], (rough, smooth))


if __name__ == "__main__":
    unittest.main()
