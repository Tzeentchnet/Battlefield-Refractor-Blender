from io import BytesIO
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

import numpy as np


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "bf2"
    / "bf2_road.py"
)
SPEC = importlib.util.spec_from_file_location("bf2_road", MODULE_PATH)
bf2_road = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bf2_road
SPEC.loader.exec_module(bf2_road)


def _road_bytes():
    data = bytearray()
    data.extend(struct.pack("<HH", 4, 1))
    data.extend(struct.pack("<3f", 10.0, 20.0, 30.0))
    data.extend(struct.pack("<f", 8.0))
    data.extend(struct.pack("<3f", 9.0, 19.0, 29.0))
    data.extend(struct.pack("<3f", 11.0, 21.0, 31.0))
    data.extend(struct.pack("<iI", 2, 3))
    vertices = (
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.2, 0.5),
        (1.0, 0.0, 0.0, 1.0, 0.0, 1.1, 0.2, 0.75),
        (0.0, 1.0, 0.0, 0.0, 1.0, 0.1, 1.2, 1.0),
    )
    data.extend(np.asarray(vertices, dtype="<f4").tobytes())
    data.extend(struct.pack("<I3H", 3, 0, 1, 2))
    data.extend(struct.pack("<I", 1))
    data.extend(struct.pack("<IIf3f", 0, 3, 4.0, 10.0, 20.0, 30.0))
    return bytes(data)


def _unversioned_road_bytes():
    data = bytearray()
    data.extend(struct.pack("<3f", 10.0, 20.0, 30.0))
    data.extend(struct.pack("<f", 8.0))
    data.extend(struct.pack("<3f", 9.0, 19.0, 29.0))
    data.extend(struct.pack("<3f", 11.0, 21.0, 31.0))
    data.extend(struct.pack("<I", 3))
    vertices = (
        (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.1, 0.2),
        (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.1, 0.2),
        (0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.1, 1.2),
    )
    data.extend(np.asarray(vertices, dtype="<f4").tobytes())
    data.extend(struct.pack("<I3H", 3, 0, 1, 2))
    return bytes(data)


class BF2RoadTests(unittest.TestCase):
    def test_loads_version_1_4_mesh(self):
        road = bf2_road.BF2Road.load_from("test", BytesIO(_road_bytes()))

        self.assertEqual(road.version, (1, 4))
        self.assertEqual(road.origin, (10.0, 20.0, 30.0))
        self.assertEqual(road.order, 2)
        np.testing.assert_array_equal(road.indices, (0, 1, 2))
        np.testing.assert_allclose(road.uv_secondary[2], (0.1, 1.2))
        np.testing.assert_allclose(road.alpha, (0.5, 0.75, 1.0))
        self.assertEqual(road.chunks[0].index_count, 3)

    def test_loads_unversioned_mesh(self):
        road = bf2_road.BF2Road.load_from(
            "legacy",
            BytesIO(_unversioned_road_bytes()),
        )

        self.assertEqual(road.version, (0, 0))
        self.assertEqual(road.order, 0)
        np.testing.assert_allclose(road.uv_primary[1], (1.0, 0.0))
        np.testing.assert_allclose(road.alpha, (1.0, 1.0, 1.0))

    def test_rejects_out_of_range_index(self):
        data = bytearray(_road_bytes())
        index_offset = 52 + 3 * 8 * 4 + 4
        struct.pack_into("<H", data, index_offset + 4, 9)

        with self.assertRaisesRegex(
            bf2_road.BF2RoadException, "outside the buffer"
        ):
            bf2_road.BF2Road.load_from("bad", BytesIO(data))

    def test_loads_compiled_material(self):
        stream = BytesIO(
            b"objects\\roads\\primary\n"
            b"objects\\roads\\secondary\r\n"
            + struct.pack("<3fI", 0.85, 200.0, 300.0, 5)
        )
        material = bf2_road.load_road_material("test", stream)

        self.assertEqual(
            material.texture_primary, "objects\\roads\\primary"
        )
        self.assertEqual(material.priority, 5)
        self.assertAlmostEqual(material.blend_factor, 0.85)


if __name__ == "__main__":
    unittest.main()
