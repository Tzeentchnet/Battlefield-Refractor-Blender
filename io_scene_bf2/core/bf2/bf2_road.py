from dataclasses import dataclass
import struct

import numpy as np


class BF2RoadException(Exception):
    pass


@dataclass(frozen=True)
class BF2RoadChunk:
    start_index: int
    index_count: int
    radius: float
    center: tuple[float, float, float]


@dataclass(frozen=True)
class BF2RoadMaterial:
    texture_primary: str
    texture_secondary: str
    blend_factor: float
    fade_off: tuple[float, float]
    priority: int


@dataclass(frozen=True)
class BF2Road:
    version: tuple[int, int]
    origin: tuple[float, float, float]
    radius: float
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    order: int
    positions: np.ndarray
    uv_primary: np.ndarray
    uv_secondary: np.ndarray
    alpha: np.ndarray
    indices: np.ndarray
    chunks: tuple[BF2RoadChunk, ...]

    @classmethod
    def load_from(cls, name, stream):
        data = stream.read()
        if len(data) < 44:
            raise BF2RoadException(f"RoadCompiled '{name}' has a truncated header")

        minor, major = struct.unpack_from("<HH", data, 0)
        unversioned = major != 1
        if unversioned:
            major = minor = 0
            offset = 0
        else:
            offset = 4
        if major not in (0, 1):
            raise BF2RoadException(
                f"RoadCompiled '{name}' uses unsupported version {major}.{minor}"
            )

        origin = struct.unpack_from("<3f", data, offset)
        offset += 12
        radius = struct.unpack_from("<f", data, offset)[0]
        offset += 4
        bounds_min = struct.unpack_from("<3f", data, offset)
        offset += 12
        bounds_max = struct.unpack_from("<3f", data, offset)
        offset += 12

        if unversioned or (major, minor) == (1, 0):
            order = 0
            vertex_count = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        else:
            order, vertex_count = struct.unpack_from("<iI", data, offset)
            offset += 8

        if unversioned:
            vertex_stride = 10
        elif (major, minor) <= (1, 2):
            vertex_stride = 14
        else:
            vertex_stride = 8

        vertex_bytes = vertex_count * vertex_stride * 4
        vertex_end = offset + vertex_bytes
        if vertex_end > len(data):
            raise BF2RoadException(
                f"RoadCompiled '{name}' declares {vertex_count} vertices "
                "outside the file"
            )

        vertices = np.frombuffer(
            data,
            dtype="<f4",
            count=vertex_count * vertex_stride,
            offset=offset,
        ).reshape((vertex_count, vertex_stride))
        positions = vertices[:, 0:3].copy()
        if unversioned or (major, minor) <= (1, 2):
            uv_primary = vertices[:, 6:8].copy()
            uv_secondary = vertices[:, 8:10].copy()
            alpha = np.ones(vertex_count, dtype=np.float32)
        else:
            uv_primary = vertices[:, 3:5].copy()
            uv_secondary = vertices[:, 5:7].copy()
            if (major, minor) >= (1, 3):
                alpha = vertices[:, 7].copy()
            else:
                alpha = np.ones(vertex_count, dtype=np.float32)
        offset = vertex_end

        if offset + 4 > len(data):
            raise BF2RoadException(f"RoadCompiled '{name}' has no index count")
        index_count = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        index_end = offset + index_count * 2
        if index_end > len(data):
            raise BF2RoadException(
                f"RoadCompiled '{name}' declares {index_count} indices "
                "outside the file"
            )
        indices = np.frombuffer(
            data,
            dtype="<u2",
            count=index_count,
            offset=offset,
        ).astype(np.int32)
        if indices.size and int(indices.max()) >= vertex_count:
            raise BF2RoadException(
                f"RoadCompiled '{name}' references a vertex outside the buffer"
            )
        usable_index_count = index_count - index_count % 3
        indices = indices[:usable_index_count]
        offset = index_end

        chunks = []
        if (major, minor) >= (1, 4):
            if offset + 4 > len(data):
                raise BF2RoadException(
                    f"RoadCompiled '{name}' has no chunk count"
                )
            chunk_count = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            chunk_end = offset + chunk_count * 24
            if chunk_end > len(data):
                raise BF2RoadException(
                    f"RoadCompiled '{name}' declares {chunk_count} chunks "
                    "outside the file"
                )
            for _ in range(chunk_count):
                start, count, chunk_radius, x, y, z = struct.unpack_from(
                    "<IIf3f", data, offset
                )
                offset += 24
                if start + count > index_count:
                    raise BF2RoadException(
                        f"RoadCompiled '{name}' chunk references indices "
                        "outside the buffer"
                    )
                chunks.append(
                    BF2RoadChunk(start, count, chunk_radius, (x, y, z))
                )

        return cls(
            version=(major, minor),
            origin=origin,
            radius=radius,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            order=order,
            positions=positions,
            uv_primary=uv_primary,
            uv_secondary=uv_secondary,
            alpha=alpha,
            indices=indices,
            chunks=tuple(chunks),
        )


def load_road_material(name, stream):
    primary = stream.readline().rstrip(b"\r\n")
    secondary = stream.readline().rstrip(b"\r\n")
    payload = stream.read()
    if not primary or not secondary or len(payload) < 16:
        raise BF2RoadException(
            f"RoadCompiled material '{name}' is truncated"
        )

    try:
        primary = primary.decode("ascii")
        secondary = secondary.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BF2RoadException(
            f"RoadCompiled material '{name}' has a non-ASCII texture path"
        ) from exc

    blend, fade_start, fade_end, priority = struct.unpack_from(
        "<3fI", payload, 0
    )
    return BF2RoadMaterial(
        texture_primary=primary,
        texture_secondary=secondary,
        blend_factor=blend,
        fade_off=(fade_start, fade_end),
        priority=priority,
    )
