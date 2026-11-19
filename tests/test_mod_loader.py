import sys
import tempfile
from io import StringIO
from pathlib import Path
import unittest
from zipfile import ZipFile


ADDON_PATH = Path(__file__).parents[1] / "io_scene_bf2"
sys.path.insert(0, str(ADDON_PATH))

from core.bf2.bf2_engine import ObjectTemplate
from core.mod_loader import ModLoader


class ModLoaderTests(unittest.TestCase):
    def test_loads_object_templates_from_nested_archive_mounts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mod_directory = Path(temp_dir)
            archive = mod_directory / "Objects" / "Common_server.zip"
            archive.parent.mkdir(parents=True)
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "Shared/Template.con",
                    "ObjectTemplate.create SimpleObject nested_template\n",
                )
            (mod_directory / "ServerArchives.con").write_text(
                "fileManager.mountArchive "
                "Objects/Common_server.zip Objects\\Common\n",
                encoding="ascii",
            )

            loader = ModLoader(str(mod_directory), use_cache=False)
            try:
                loader.reload_all()

                manager = loader.engine.get_manager(ObjectTemplate)
                self.assertIn("nested_template", manager.templates)
            finally:
                loader.engine.file_manager.unmoutAll()

    def test_preserves_bundle_skeleton_metadata_in_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mod_directory = Path(temp_dir)
            archive = mod_directory / "Objects_server.zip"
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "Vehicles/Walker/Walker.con",
                    "\n".join((
                        "ObjectTemplate.create PlayerControlObject Walker",
                        "ObjectTemplate.bundleSkeleton Walker.ske",
                        "ObjectTemplate.boneIndex 0",
                        "ObjectTemplate.addTemplate Walker_leg",
                        "ObjectTemplate.create SimpleObject Walker_leg",
                        "ObjectTemplate.boneIndex 1",
                        "",
                    )),
                )
            (mod_directory / "ServerArchives.con").write_text(
                "fileManager.mountArchive Objects_server.zip Objects\n",
                encoding="ascii",
            )

            for _ in range(2):
                loader = ModLoader(str(mod_directory), use_cache=True)
                try:
                    loader.reload_all()
                    manager = loader.engine.get_manager(ObjectTemplate)
                    walker = manager.templates["walker"]
                    leg = manager.templates["walker_leg"]

                    self.assertEqual(walker.bundle_skeleton, "Walker.ske")
                    self.assertEqual(walker.bone_index, 0)
                    self.assertEqual(leg.bone_index, 1)

                    manager.add_bundle_childs(walker)
                    script = StringIO()
                    walker.make_script(script)
                    self.assertIn(
                        "ObjectTemplate.bundleSkeleton Walker.ske",
                        script.getvalue(),
                    )
                    self.assertIn(
                        "ObjectTemplate.boneIndex 1",
                        script.getvalue(),
                    )
                finally:
                    loader.engine.file_manager.unmoutAll()


if __name__ == "__main__":
    unittest.main()
