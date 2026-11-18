import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "utils"
    / "mesh.py"
)
SPEC = importlib.util.spec_from_file_location("mesh_utils", MODULE_PATH)
mesh_utils = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mesh_utils
SPEC.loader.exec_module(mesh_utils)


class PrepareMeshFacesTests(unittest.TestCase):
    def test_keeps_unique_faces_and_materials(self):
        result = mesh_utils.prepare_mesh_faces(
            [
                ((0, 1, 2), 3),
                ((2, 3, 0), 7),
            ]
        )
        faces, materials, backfaces, skipped = result
        self.assertEqual(faces, [(0, 1, 2), (2, 3, 0)])
        self.assertEqual(materials, [3, 7])
        self.assertEqual(backfaces, set())
        self.assertEqual(skipped, 0)

    def test_marks_opposite_winding_as_double_sided(self):
        faces, materials, backfaces, skipped = mesh_utils.prepare_mesh_faces(
            [
                ((0, 1, 2), 1),
                ((2, 1, 0), 1),
            ]
        )
        self.assertEqual(faces, [(0, 1, 2)])
        self.assertEqual(materials, [1])
        self.assertEqual(backfaces, {0})
        self.assertEqual(skipped, 0)

    def test_skips_duplicate_and_degenerate_faces(self):
        faces, _, backfaces, skipped = mesh_utils.prepare_mesh_faces(
            [
                ((0, 1, 2), 0),
                ((1, 2, 0), 0),
                ((0, 0, 1), 0),
            ]
        )
        self.assertEqual(faces, [(0, 1, 2)])
        self.assertEqual(backfaces, set())
        self.assertEqual(skipped, 2)

    def test_rejects_material_mismatch_on_backface(self):
        with self.assertRaisesRegex(ValueError, "different material"):
            mesh_utils.prepare_mesh_faces(
                [
                    ((0, 1, 2), 0),
                    ((2, 1, 0), 1),
                ]
            )


if __name__ == "__main__":
    unittest.main()
