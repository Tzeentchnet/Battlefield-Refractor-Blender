import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "import_settings.py"
)
SPEC = importlib.util.spec_from_file_location("import_settings", MODULE_PATH)
import_settings = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = import_settings
SPEC.loader.exec_module(import_settings)


class ImportSettingsTests(unittest.TestCase):
    def test_off_imports_only_primary_index(self):
        self.assertTrue(
            import_settings.should_import_index(0, import_settings.IMPORT_MODE_OFF)
        )
        self.assertFalse(
            import_settings.should_import_index(1, import_settings.IMPORT_MODE_OFF)
        )

    def test_on_imports_all_indices_without_hiding(self):
        self.assertTrue(
            import_settings.should_import_index(3, import_settings.IMPORT_MODE_ON)
        )
        self.assertFalse(
            import_settings.should_hide_index(3, import_settings.IMPORT_MODE_ON)
        )

    def test_nonzero_primary_index(self):
        self.assertTrue(
            import_settings.should_import_index(
                1,
                import_settings.IMPORT_MODE_OFF,
                primary_index=1,
            )
        )
        self.assertFalse(
            import_settings.should_import_index(
                0,
                import_settings.IMPORT_MODE_OFF,
                primary_index=1,
            )
        )
        self.assertFalse(
            import_settings.should_hide_index(
                1,
                import_settings.IMPORT_MODE_HIDDEN,
                primary_index=1,
            )
        )
        self.assertTrue(
            import_settings.should_hide_index(
                0,
                import_settings.IMPORT_MODE_HIDDEN,
                primary_index=1,
            )
        )

    def test_selects_first_geom_with_best_part_coverage(self):
        self.assertEqual(
            import_settings.select_primary_index(
                {1, 2, 3},
                ({0}, {0, 1, 2, 3}, {0, 1}),
            ),
            1,
        )
        self.assertEqual(
            import_settings.select_primary_index(
                {1},
                ({0, 1}, {0, 1}),
            ),
            0,
        )

    def test_hidden_imports_and_hides_secondary_indices(self):
        self.assertTrue(
            import_settings.should_import_index(
                2,
                import_settings.IMPORT_MODE_HIDDEN,
            )
        )
        self.assertTrue(
            import_settings.should_hide_index(
                2,
                import_settings.IMPORT_MODE_HIDDEN,
            )
        )
        self.assertFalse(
            import_settings.should_hide_index(
                0,
                import_settings.IMPORT_MODE_HIDDEN,
            )
        )

    def test_rejects_invalid_modes_and_indices(self):
        with self.assertRaisesRegex(ValueError, "Invalid import mode"):
            import_settings.validate_import_mode("INVALID")
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            import_settings.should_import_index(-1, import_settings.IMPORT_MODE_ON)


if __name__ == "__main__":
    unittest.main()
