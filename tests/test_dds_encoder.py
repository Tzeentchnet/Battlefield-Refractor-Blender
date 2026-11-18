import importlib.util
from pathlib import Path
import struct
import sys
import unittest

import numpy as np


MODULE_PATH = (
    Path(__file__).parents[1]
    / "io_scene_bf2"
    / "directx"
    / "dds_encoder.py"
)
SPEC = importlib.util.spec_from_file_location("dds_encoder", MODULE_PATH)
dds_encoder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dds_encoder
SPEC.loader.exec_module(dds_encoder)


class DDSEncoderTests(unittest.TestCase):
    def test_uncompressed_header_and_row_order(self):
        pixels = np.array(
            [
                [[255, 0, 0, 255], [0, 255, 0, 255]],
                [[0, 0, 255, 255], [255, 255, 255, 128]],
            ],
            dtype=np.uint8,
        )

        data = dds_encoder.encode_dds(
            pixels,
            compression="NONE",
            generate_mipmaps=False,
        )

        header = _parse_header(data)
        self.assertEqual((header["width"], header["height"]), (2, 2))
        self.assertEqual(header["fourcc"], b"\0\0\0\0")
        self.assertEqual(header["mip_count"], 1)
        self.assertEqual(header["linear_size"], 16)
        self.assertEqual(
            data[128:],
            bytes(
                (
                    255, 0, 0, 255,
                    255, 255, 255, 128,
                    0, 0, 255, 255,
                    0, 255, 0, 255,
                )
            ),
        )

    def test_full_bc1_mipmap_chain_size(self):
        pixels = np.zeros((4, 8, 4), dtype=np.uint8)
        pixels[:, :, 3] = 255

        data = dds_encoder.encode_dds(pixels, compression="DXT1")

        header = _parse_header(data)
        self.assertEqual(header["mip_count"], 4)
        self.assertEqual(header["linear_size"], 16)
        self.assertEqual(len(data), 128 + 16 + 8 + 8 + 8)

    def test_non_block_aligned_bc3_image_is_edge_padded(self):
        pixels = np.zeros((5, 7, 4), dtype=np.uint8)

        data = dds_encoder.encode_dds(
            pixels,
            compression="DXT5",
            generate_mipmaps=False,
        )

        header = _parse_header(data)
        self.assertEqual((header["width"], header["height"]), (7, 5))
        self.assertEqual(header["linear_size"], 64)
        self.assertEqual(len(data), 128 + 64)

    def test_bc_formats_preserve_uniform_color_and_alpha(self):
        color = np.array((41, 127, 213, 102), dtype=np.uint8)
        pixels = np.broadcast_to(color, (4, 4, 4)).copy()

        for compression, tolerance in (("DXT1", 8), ("DXT3", 17), ("DXT5", 8)):
            with self.subTest(compression=compression):
                source = pixels.copy()
                if compression == "DXT1":
                    source[:, :, 3] = 255
                data = dds_encoder.encode_dds(
                    source,
                    compression=compression,
                    generate_mipmaps=False,
                )
                decoded = _decode_first_block(data, compression)
                np.testing.assert_allclose(
                    decoded[0, 0, :3],
                    color[:3],
                    atol=8,
                )
                if compression == "DXT1":
                    self.assertEqual(decoded[0, 0, 3], 255)
                else:
                    self.assertLessEqual(
                        abs(int(decoded[0, 0, 3]) - int(color[3])),
                        tolerance,
                    )

    def test_bc1_transparency(self):
        pixels = np.full((4, 4, 4), 255, dtype=np.uint8)
        pixels[0, 0, 3] = 0

        data = dds_encoder.encode_dds(
            pixels,
            compression="DXT1",
            generate_mipmaps=False,
        )
        decoded = _decode_first_block(data, "DXT1")

        # The encoder flips Blender's bottom-up rows for DDS storage.
        self.assertEqual(decoded[3, 0, 3], 0)
        self.assertEqual(decoded[0, 0, 3], 255)

    def test_invalid_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported DDS compression"):
            dds_encoder.encode_dds(np.zeros((1, 1, 4)), compression="BC7")


def _parse_header(data):
    self_magic = data[:4]
    if self_magic != b"DDS ":
        raise AssertionError("Missing DDS magic")
    (
        _,
        flags,
        height,
        width,
        linear_size,
        _,
        mip_count,
    ) = struct.unpack_from("<7I", data, 4)
    return {
        "flags": flags,
        "height": height,
        "width": width,
        "linear_size": linear_size,
        "mip_count": mip_count,
        "fourcc": data[84:88],
    }


def _decode_565(value):
    return np.array(
        (
            ((value >> 11) & 0x1F) * 255 // 31,
            ((value >> 5) & 0x3F) * 255 // 63,
            (value & 0x1F) * 255 // 31,
        ),
        dtype=np.uint8,
    )


def _decode_color_block(block, allow_transparency):
    color0, color1, indices = struct.unpack("<HHI", block)
    endpoint0 = _decode_565(color0).astype(np.uint16)
    endpoint1 = _decode_565(color1).astype(np.uint16)
    palette = np.empty((4, 4), dtype=np.uint8)
    palette[0, :3] = endpoint0
    palette[1, :3] = endpoint1
    palette[:2, 3] = 255
    if allow_transparency and color0 <= color1:
        palette[2, :3] = (endpoint0 + endpoint1) // 2
        palette[2, 3] = 255
        palette[3] = 0
    else:
        palette[2, :3] = (2 * endpoint0 + endpoint1) // 3
        palette[3, :3] = (endpoint0 + 2 * endpoint1) // 3
        palette[2:, 3] = 255
    values = [(indices >> (index * 2)) & 0x3 for index in range(16)]
    return palette[values].reshape((4, 4, 4))


def _decode_first_block(data, compression):
    block = data[128:]
    if compression == "DXT1":
        return _decode_color_block(block[:8], allow_transparency=True)

    decoded = _decode_color_block(block[8:16], allow_transparency=False)
    if compression == "DXT3":
        alpha = int.from_bytes(block[:8], "little")
        for index in range(16):
            decoded[index // 4, index % 4, 3] = (
                (alpha >> (index * 4)) & 0xF
            ) * 17
        return decoded

    alpha0, alpha1 = block[0], block[1]
    palette = [alpha0, alpha1]
    if alpha0 > alpha1:
        palette.extend(
            ((8 - index) * alpha0 + (index - 1) * alpha1) // 7
            for index in range(2, 8)
        )
    else:
        palette.extend(
            ((6 - index) * alpha0 + (index - 1) * alpha1) // 5
            for index in range(2, 6)
        )
        palette.extend((0, 255))
    alpha_indices = int.from_bytes(block[2:8], "little")
    for index in range(16):
        decoded[index // 4, index % 4, 3] = palette[
            (alpha_indices >> (index * 3)) & 0x7
        ]
    return decoded


if __name__ == "__main__":
    unittest.main()
