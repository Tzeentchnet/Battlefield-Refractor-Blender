from __future__ import annotations

import math
import os
import struct
import tempfile

import numpy as np


SUPPORTED_FORMATS = frozenset({"NONE", "DXT1", "DXT3", "DXT5"})

_DDSD_CAPS = 0x00000001
_DDSD_HEIGHT = 0x00000002
_DDSD_WIDTH = 0x00000004
_DDSD_PIXELFORMAT = 0x00001000
_DDSD_MIPMAPCOUNT = 0x00020000
_DDSD_LINEARSIZE = 0x00080000

_DDPF_ALPHAPIXELS = 0x00000001
_DDPF_FOURCC = 0x00000004
_DDPF_RGB = 0x00000040

_DDSCAPS_COMPLEX = 0x00000008
_DDSCAPS_TEXTURE = 0x00001000
_DDSCAPS_MIPMAP = 0x00400000

_BLOCK_BYTES = {
    "DXT1": 8,
    "DXT3": 16,
    "DXT5": 16,
}


def encode_dds(pixels, compression="DXT5", generate_mipmaps=True):
    """Encode Blender-ordered pixels into a legacy Battlefield 2 DDS file."""
    compression = compression.upper()
    if compression not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise ValueError(f"Unsupported DDS compression '{compression}', expected one of: {supported}")

    rgba = _as_rgba8(pixels)
    height, width, _ = rgba.shape

    # Blender exposes image rows from bottom to top. DDS stores the top row first.
    level = np.flipud(rgba)
    levels = [level]
    if generate_mipmaps:
        while level.shape[0] > 1 or level.shape[1] > 1:
            level = _downsample(level)
            levels.append(level)

    encoded_levels = [_encode_level(level, compression) for level in levels]
    header = _make_header(
        width,
        height,
        compression,
        len(encoded_levels),
        len(encoded_levels[0]),
    )
    return header + b"".join(encoded_levels)


def save_dds(filepath, pixels, compression="DXT5", generate_mipmaps=True):
    data = encode_dds(
        pixels,
        compression=compression,
        generate_mipmaps=generate_mipmaps,
    )

    filepath = os.path.abspath(filepath)
    output_dir = os.path.dirname(filepath)
    os.makedirs(output_dir, exist_ok=True)

    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(filepath)}.",
        suffix=".tmp",
        dir=output_dir,
    )
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary_path, filepath)
    except BaseException:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass
        raise

    return filepath


def _as_rgba8(pixels):
    array = np.asarray(pixels)
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    if array.ndim != 3 or array.shape[2] not in (1, 2, 3, 4):
        raise ValueError("Pixels must have shape (height, width, 1-4)")
    if array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("DDS images must have a positive width and height")

    if np.issubdtype(array.dtype, np.floating):
        array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
        array = np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    elif array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)

    channels = array.shape[2]
    if channels == 1:
        rgb = np.repeat(array, 3, axis=2)
        alpha = np.full((*array.shape[:2], 1), 255, dtype=np.uint8)
        array = np.concatenate((rgb, alpha), axis=2)
    elif channels == 2:
        rgb = np.repeat(array[:, :, :1], 3, axis=2)
        array = np.concatenate((rgb, array[:, :, 1:2]), axis=2)
    elif channels == 3:
        alpha = np.full((*array.shape[:2], 1), 255, dtype=np.uint8)
        array = np.concatenate((array, alpha), axis=2)

    return np.ascontiguousarray(array)


def _downsample(level):
    height, width, _ = level.shape
    target_height = max(1, height // 2)
    target_width = max(1, width // 2)

    y0 = np.arange(target_height) * 2
    y1 = np.minimum(y0 + 1, height - 1)
    x0 = np.arange(target_width) * 2
    x1 = np.minimum(x0 + 1, width - 1)

    values = (
        level[y0[:, None], x0[None, :]].astype(np.uint16)
        + level[y0[:, None], x1[None, :]].astype(np.uint16)
        + level[y1[:, None], x0[None, :]].astype(np.uint16)
        + level[y1[:, None], x1[None, :]].astype(np.uint16)
    )
    return ((values + 2) // 4).astype(np.uint8)


def _encode_level(level, compression):
    if compression == "NONE":
        return np.ascontiguousarray(level[:, :, (2, 1, 0, 3)]).tobytes()

    chunks = []
    for blocks in _iter_block_batches(level):
        if compression == "DXT1":
            encoded = _encode_color_blocks(blocks, allow_transparency=True)
        elif compression == "DXT3":
            encoded = _encode_bc2_blocks(blocks)
        else:
            encoded = _encode_bc3_blocks(blocks)
        chunks.append(encoded.tobytes())
    return b"".join(chunks)


def _iter_block_batches(level, batch_block_rows=32):
    height, width, _ = level.shape
    padded_height = math.ceil(height / 4) * 4
    padded_width = math.ceil(width / 4) * 4
    padded = np.pad(
        level,
        ((0, padded_height - height), (0, padded_width - width), (0, 0)),
        mode="edge",
    )

    block_rows = padded_height // 4
    block_columns = padded_width // 4
    for row_start in range(0, block_rows, batch_block_rows):
        row_count = min(batch_block_rows, block_rows - row_start)
        chunk = padded[row_start * 4:(row_start + row_count) * 4]
        blocks = (
            chunk.reshape(row_count, 4, block_columns, 4, 4)
            .transpose(0, 2, 1, 3, 4)
            .reshape(-1, 16, 4)
        )
        yield blocks


def _principal_axis_endpoints(blocks, included):
    rgb = blocks[:, :, :3].astype(np.float32)
    weights = included.astype(np.float32)
    counts = weights.sum(axis=1)
    safe_counts = np.maximum(counts, 1.0)
    means = (rgb * weights[:, :, np.newaxis]).sum(axis=1) / safe_counts[:, np.newaxis]
    centered = (rgb - means[:, np.newaxis, :]) * weights[:, :, np.newaxis]
    covariance = np.einsum("npi,npj->nij", centered, centered)
    covariance /= safe_counts[:, np.newaxis, np.newaxis]

    _, eigenvectors = np.linalg.eigh(covariance)
    axes = eigenvectors[:, :, -1]
    projections = np.einsum("npi,ni->np", rgb, axes)
    low_indices = np.argmin(np.where(included, projections, np.inf), axis=1)
    high_indices = np.argmax(np.where(included, projections, -np.inf), axis=1)

    block_indices = np.arange(len(blocks))
    low = blocks[block_indices, low_indices, :3].copy()
    high = blocks[block_indices, high_indices, :3].copy()
    empty = counts == 0
    low[empty] = 0
    high[empty] = 0
    return high, low


def _rgb_to_565(rgb):
    rgb = rgb.astype(np.uint32)
    red = (rgb[:, 0] * 31 + 127) // 255
    green = (rgb[:, 1] * 63 + 127) // 255
    blue = (rgb[:, 2] * 31 + 127) // 255
    return ((red << 11) | (green << 5) | blue).astype(np.uint16)


def _rgb_from_565(colors):
    colors = colors.astype(np.uint32)
    red = ((colors >> 11) & 0x1F) * 255
    green = ((colors >> 5) & 0x3F) * 255
    blue = (colors & 0x1F) * 255
    return np.stack(
        (
            (red + 15) // 31,
            (green + 31) // 63,
            (blue + 15) // 31,
        ),
        axis=1,
    ).astype(np.uint8)


def _encode_color_blocks(blocks, allow_transparency):
    opaque_pixels = blocks[:, :, 3] >= 128
    transparent_blocks = (
        np.any(~opaque_pixels, axis=1)
        if allow_transparency
        else np.zeros(len(blocks), dtype=bool)
    )
    included = np.where(transparent_blocks[:, np.newaxis], opaque_pixels, True)

    high, low = _principal_axis_endpoints(blocks, included)
    color0 = _rgb_to_565(high)
    color1 = _rgb_to_565(low)

    opaque_blocks = ~transparent_blocks
    swap = (opaque_blocks & (color0 < color1)) | (transparent_blocks & (color0 > color1))
    color0, color1 = (
        np.where(swap, color1, color0),
        np.where(swap, color0, color1),
    )

    equal_opaque = opaque_blocks & (color0 == color1)
    increment = equal_opaque & (color0 < np.iinfo(np.uint16).max)
    color0 = np.where(increment, color0 + 1, color0).astype(np.uint16)
    color1 = np.where(equal_opaque & ~increment, color1 - 1, color1).astype(np.uint16)

    endpoint0 = _rgb_from_565(color0).astype(np.uint16)
    endpoint1 = _rgb_from_565(color1).astype(np.uint16)
    palette = np.empty((len(blocks), 4, 3), dtype=np.uint8)
    palette[:, 0] = endpoint0
    palette[:, 1] = endpoint1

    palette[:, 2] = np.where(
        opaque_blocks[:, np.newaxis],
        (2 * endpoint0 + endpoint1 + 1) // 3,
        (endpoint0 + endpoint1) // 2,
    )
    palette[:, 3] = np.where(
        opaque_blocks[:, np.newaxis],
        (endpoint0 + 2 * endpoint1 + 1) // 3,
        0,
    )

    rgb = blocks[:, :, :3].astype(np.int32)
    delta = rgb[:, :, np.newaxis, :] - palette[:, np.newaxis, :, :].astype(np.int32)
    distances = np.einsum("npci,npci->npc", delta, delta)
    distances[:, :, 3] = np.where(
        transparent_blocks[:, np.newaxis] & opaque_pixels,
        np.iinfo(distances.dtype).max,
        distances[:, :, 3],
    )
    indices = np.argmin(distances, axis=2).astype(np.uint32)
    indices = np.where(transparent_blocks[:, np.newaxis] & ~opaque_pixels, 3, indices)

    shifts = (np.arange(16, dtype=np.uint32) * 2)[np.newaxis, :]
    packed_indices = np.bitwise_or.reduce(indices << shifts, axis=1)

    output = np.empty((len(blocks), 8), dtype=np.uint8)
    output[:, 0] = color0 & 0xFF
    output[:, 1] = color0 >> 8
    output[:, 2] = color1 & 0xFF
    output[:, 3] = color1 >> 8
    for byte_index in range(4):
        output[:, 4 + byte_index] = packed_indices >> (byte_index * 8)
    return output


def _encode_bc2_blocks(blocks):
    alpha = blocks[:, :, 3].astype(np.uint16)
    alpha4 = ((alpha * 15 + 127) // 255).astype(np.uint64)
    shifts = (np.arange(16, dtype=np.uint64) * 4)[np.newaxis, :]
    packed_alpha = np.bitwise_or.reduce(alpha4 << shifts, axis=1)

    output = np.empty((len(blocks), 16), dtype=np.uint8)
    for byte_index in range(8):
        output[:, byte_index] = packed_alpha >> (byte_index * 8)
    output[:, 8:] = _encode_color_blocks(blocks, allow_transparency=False)
    return output


def _encode_bc3_blocks(blocks):
    alpha = blocks[:, :, 3]
    alpha0 = alpha.max(axis=1).astype(np.uint16)
    alpha1 = alpha.min(axis=1).astype(np.uint16)

    equal = alpha0 == alpha1
    nonzero = equal & (alpha0 > 0)
    alpha1 = np.where(nonzero, alpha0 - 1, alpha1)
    alpha0 = np.where(equal & ~nonzero, 1, alpha0)

    palette = np.empty((len(blocks), 8), dtype=np.uint16)
    palette[:, 0] = alpha0
    palette[:, 1] = alpha1
    for index in range(2, 8):
        palette[:, index] = (
            (8 - index) * alpha0
            + (index - 1) * alpha1
            + 3
        ) // 7

    delta = alpha.astype(np.int16)[:, :, np.newaxis] - palette.astype(np.int16)[:, np.newaxis, :]
    indices = np.argmin(delta.astype(np.int32) ** 2, axis=2).astype(np.uint64)
    shifts = (np.arange(16, dtype=np.uint64) * 3)[np.newaxis, :]
    packed_indices = np.bitwise_or.reduce(indices << shifts, axis=1)

    output = np.empty((len(blocks), 16), dtype=np.uint8)
    output[:, 0] = alpha0
    output[:, 1] = alpha1
    for byte_index in range(6):
        output[:, 2 + byte_index] = packed_indices >> (byte_index * 8)
    output[:, 8:] = _encode_color_blocks(blocks, allow_transparency=False)
    return output


def _make_header(width, height, compression, mip_count, top_level_size):
    flags = (
        _DDSD_CAPS
        | _DDSD_HEIGHT
        | _DDSD_WIDTH
        | _DDSD_PIXELFORMAT
        | _DDSD_LINEARSIZE
    )
    caps = _DDSCAPS_TEXTURE
    if mip_count > 1:
        flags |= _DDSD_MIPMAPCOUNT
        caps |= _DDSCAPS_COMPLEX | _DDSCAPS_MIPMAP

    header = bytearray()
    header.extend(b"DDS ")
    header.extend(
        struct.pack(
            "<7I11I",
            124,
            flags,
            height,
            width,
            top_level_size,
            0,
            mip_count,
            *([0] * 11),
        )
    )

    if compression == "NONE":
        header.extend(
            struct.pack(
                "<II4sIIIII",
                32,
                _DDPF_RGB | _DDPF_ALPHAPIXELS,
                b"\0\0\0\0",
                32,
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0xFF000000,
            )
        )
    else:
        header.extend(
            struct.pack(
                "<II4sIIIII",
                32,
                _DDPF_FOURCC,
                compression.encode("ascii"),
                0,
                0,
                0,
                0,
                0,
            )
        )

    header.extend(struct.pack("<5I", caps, 0, 0, 0, 0))
    if len(header) != 128:
        raise AssertionError(f"Invalid DDS header size: {len(header)}")
    return bytes(header)

