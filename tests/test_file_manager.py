import sys
import tempfile
from pathlib import Path
import unittest
from zipfile import ZipFile


CORE_PATH = Path(__file__).parents[1] / "io_scene_bf2" / "core"
sys.path.insert(0, str(CORE_PATH))

from bf2.bf2_engine.file_manager import FileManager


class FileManagerTests(unittest.TestCase):
    def test_reads_archives_mounted_below_a_parent_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "Objects" / "Common_server.zip"
            archive.parent.mkdir(parents=True)
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("Shared/template.con", b"template")

            manager = FileManager([str(root)])
            try:
                manager.mountArchive(
                    "Objects/Common_server.zip",
                    r"Objects\Common",
                )

                self.assertEqual(
                    manager.getArchives("objects"),
                    ["objects/common_server.zip"],
                )
                self.assertEqual(
                    manager.getArchiveMounts("objects"),
                    [("objects/common", "objects/common_server.zip")],
                )
                self.assertEqual(
                    manager.readFile("Objects/Common/Shared/template.con"),
                    b"template",
                )
            finally:
                manager.unmoutAll()

    def test_does_not_match_a_similarly_prefixed_mount(self):
        manager = FileManager()
        manager._mounted_archives["objects_extra"] = ["extra.zip"]

        self.assertEqual(manager.getArchives("objects"), [])


if __name__ == "__main__":
    unittest.main()
