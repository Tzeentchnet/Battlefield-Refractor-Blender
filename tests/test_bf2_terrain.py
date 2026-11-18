from io import BytesIO
import importlib.util
from pathlib import Path
import struct
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "bf2"
    / "bf2_terrain.py"
)
SPEC = importlib.util.spec_from_file_location("bf2_terrain", MODULE_PATH)
bf2_terrain = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bf2_terrain
SPEC.loader.exec_module(bf2_terrain)


def _terrain_bytes():
    data = bytearray()
    data.extend(struct.pack("<I", 0x0001001A))
    data.extend(struct.pack("<3f", 2.0, 0.00457764, 2.0))
    data.extend(struct.pack("<3f", 4.0, 1.17188, 4.0))
    data.extend(struct.pack("<I2f", 0xCDCDCDCD, 192.0, 8.0))
    data.extend(struct.pack("<IBIII", 128, 1, 4, 512, 512))
    for value in (
        "Levels/Test/Colormaps/tx",
        "Levels/Test/Detailmaps/tx",
        "Levels/Test/LowDetailmaps/tx",
        "Levels/Test/Lightmaps/tx",
    ):
        data.extend(value.encode("latin-1") + b"\n")
    data.extend(struct.pack("<5f", 5.0, 5.0, 24.0, 4.0, 0.0))
    data.extend(struct.pack("<3f", 0.75, 0.71, 0.57))
    data.extend(struct.pack("<3f", 0.73, 0.64, 0.33))
    data.extend(struct.pack("<3f", 0.33, 0.28, 0.16))
    data.extend(struct.pack("<I", 1))
    data.extend(b"common\\terrain\\detail_rock04\n")
    data.extend(struct.pack("<B4fB", 1, 32.0, 16.0, 50.0, 0.0, 0))
    return bytes(data)


class BF2TerrainTests(unittest.TestCase):
    def test_loads_compiled_terrain_header_and_materials(self):
        terrain = bf2_terrain.BF2Terrain.load_from(
            "test",
            BytesIO(_terrain_bytes()),
        )

        self.assertEqual(terrain.version, 0x0001001A)
        self.assertEqual(terrain.patch_size, 128)
        self.assertEqual(terrain.patches_per_side, 4)
        self.assertEqual(
            terrain.colormap_base_name,
            "Levels/Test/Colormaps/tx",
        )
        self.assertEqual(len(terrain.materials), 1)
        self.assertTrue(terrain.materials[0].tri_planar)
        self.assertEqual(terrain.materials[0].side_tiling, (32.0, 16.0))
        self.assertEqual(terrain.materials[0].top_tiling, 50.0)

    def test_rejects_truncated_material(self):
        with self.assertRaisesRegex(
            bf2_terrain.BF2TerrainException,
            "truncated",
        ):
            bf2_terrain.BF2Terrain.load_from(
                "short",
                BytesIO(_terrain_bytes()[:-3]),
            )


if __name__ == "__main__":
    unittest.main()
