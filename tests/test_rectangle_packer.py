import importlib.util
from pathlib import Path
import random
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "core"
    / "utils"
    / "rectangle_packer.py"
)
SPEC = importlib.util.spec_from_file_location("rectangle_packer", MODULE_PATH)
rectangle_packer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rectangle_packer
SPEC.loader.exec_module(rectangle_packer)


class RectanglePackerTests(unittest.TestCase):
    def test_packs_every_rectangle_without_overlap(self):
        rectangles = [
            (32, 16, "a"),
            (16, 32, "b"),
            (16, 16, "c"),
            (8, 24, "d"),
        ]

        bins = rectangle_packer.pack_rectangles(
            rectangles,
            (64, 64),
            max_bins=1,
        )

        self.assertEqual(len(bins), 1)
        self.assertEqual({rect.rid for rect in bins[0]}, {"a", "b", "c", "d"})
        _assert_valid_bin(self, bins[0])

    def test_uses_additional_bins_when_needed(self):
        bins = rectangle_packer.pack_rectangles(
            [(8, 8, index) for index in range(5)],
            (16, 16),
            max_bins=2,
        )

        self.assertEqual([len(bin_) for bin_ in bins], [4, 1])
        for bin_ in bins:
            _assert_valid_bin(self, bin_)

    def test_rejects_unpacked_rectangles(self):
        with self.assertRaisesRegex(rectangle_packer.PackingError, "could not be packed"):
            rectangle_packer.pack_rectangles(
                [(8, 8, index) for index in range(5)],
                (16, 16),
                max_bins=1,
            )

    def test_supports_rotation_when_requested(self):
        with self.assertRaises(rectangle_packer.PackingError):
            rectangle_packer.pack_rectangles(
                [(12, 8, "rotated")],
                (8, 12),
            )

        bins = rectangle_packer.pack_rectangles(
            [(12, 8, "rotated")],
            (8, 12),
            allow_rotation=True,
        )
        self.assertEqual((bins[0].rectangles[0].width, bins[0].rectangles[0].height), (8, 12))

    def test_finds_small_power_of_two_bin(self):
        bin_ = rectangle_packer.pack_rectangles_power_of_two(
            [(17, 9, "a"), (8, 20, "b"), (7, 7, "c")]
        )

        self.assertEqual(bin_.width & (bin_.width - 1), 0)
        self.assertEqual(bin_.height & (bin_.height - 1), 0)
        self.assertEqual({rect.rid for rect in bin_}, {"a", "b", "c"})
        _assert_valid_bin(self, bin_)

    def test_output_is_deterministic(self):
        rectangles = [(8, 8, index) for index in range(8)]
        first = rectangle_packer.pack_rectangles(rectangles, (16, 16), max_bins=2)
        second = rectangle_packer.pack_rectangles(rectangles, (16, 16), max_bins=2)
        self.assertEqual(first, second)

    def test_randomized_batches_remain_valid(self):
        generator = random.Random(0xBF2)
        rectangles = [
            (generator.randint(4, 48), generator.randint(4, 48), index)
            for index in range(250)
        ]

        bins = rectangle_packer.pack_rectangles(
            rectangles,
            (128, 128),
            max_bins=50,
        )

        self.assertEqual(
            {rectangle.rid for bin_ in bins for rectangle in bin_},
            set(range(len(rectangles))),
        )
        for bin_ in bins:
            _assert_valid_bin(self, bin_)


def _assert_valid_bin(test_case, bin_):
    rectangles = list(bin_)
    for rectangle in rectangles:
        test_case.assertGreaterEqual(rectangle.x, 0)
        test_case.assertGreaterEqual(rectangle.y, 0)
        test_case.assertLessEqual(rectangle.x + rectangle.width, bin_.width)
        test_case.assertLessEqual(rectangle.y + rectangle.height, bin_.height)

    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1:]:
            overlaps = not (
                first.x + first.width <= second.x
                or second.x + second.width <= first.x
                or first.y + first.height <= second.y
                or second.y + second.height <= first.y
            )
            test_case.assertFalse(overlaps, f"{first} overlaps {second}")


if __name__ == "__main__":
    unittest.main()
