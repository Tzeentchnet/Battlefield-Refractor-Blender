import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "game_paths.py"
)
SPEC = importlib.util.spec_from_file_location("game_paths", MODULE_PATH)
game_paths = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = game_paths
SPEC.loader.exec_module(game_paths)


class GamePathTests(unittest.TestCase):
    def test_collects_both_game_installs_and_additional_mods(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bf2_install = root / "Battlefield 2"
            bf2_mod = bf2_install / "mods" / "bf2"
            bf2142_install = root / "Battlefield 2142"
            bf2142_mod = bf2142_install / "mods" / "bf2142"
            additional_mod = root / "Project Reality"
            for directory in (bf2_mod, bf2142_mod, additional_mod):
                directory.mkdir(parents=True)

            result = game_paths.collect_mod_directories(
                {
                    game_paths.BF2_GAME.identifier: bf2_install,
                    game_paths.BF2142_GAME.identifier: bf2142_install,
                },
                (additional_mod, bf2_mod),
            )

            self.assertEqual(
                result,
                [
                    str(bf2_mod),
                    str(bf2142_mod),
                    str(additional_mod),
                ],
            )

    def test_ignores_missing_game_and_mod_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bf2_install = root / "Battlefield 2"
            bf2_install.mkdir()

            result = game_paths.collect_mod_directories(
                {
                    game_paths.BF2_GAME.identifier: bf2_install,
                    game_paths.BF2142_GAME.identifier: root / "Missing",
                },
                (root / "Missing mod",),
            )

            self.assertEqual(result, [])

    def test_prioritizes_the_mod_containing_the_selected_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bf2_mod = root / "Battlefield 2" / "mods" / "bf2"
            bf2142_mod = root / "Battlefield 2142" / "mods" / "bf2142"
            selected_asset = (
                bf2142_mod
                / "Objects"
                / "Vehicles"
                / "Meshes"
                / "vehicle.bundledmesh"
            )
            for directory in (bf2_mod, selected_asset.parent):
                directory.mkdir(parents=True)

            result = game_paths.prioritize_mod_directories(
                (str(bf2_mod), str(bf2142_mod)),
                selected_asset,
            )

            self.assertEqual(result, [str(bf2142_mod), str(bf2_mod)])

    def test_reports_a_missing_base_game_mod_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            error = game_paths.get_game_install_error(
                temp_dir,
                game_paths.BF2142_GAME,
            )

            self.assertIn(str(Path("mods") / "bf2142"), error)


if __name__ == "__main__":
    unittest.main()
