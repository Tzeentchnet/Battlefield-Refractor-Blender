from dataclasses import dataclass
import struct


class BF2TerrainException(Exception):
    pass


@dataclass(frozen=True)
class BF2TerrainMaterial:
    texture: str
    tri_planar: bool
    side_tiling: tuple[float, float]
    top_tiling: float
    y_offset: float
    environment_map: bool


@dataclass(frozen=True)
class BF2Terrain:
    version: int
    primary_world_scale: tuple[float, float, float]
    secondary_world_scale: tuple[float, float, float]
    lowest_height: float
    highest_height: float
    patch_size: int
    subdivide_patches: bool
    patches_per_side: int
    patch_colormap_size: int
    low_detailmap_size: int
    colormap_base_name: str
    detailmap_base_name: str
    low_detailmap_base_name: str
    lightmap_base_name: str
    far_side_tiling: tuple[float, float]
    far_top_tiling_hi: float
    far_top_tiling_low: float
    far_y_offset: float
    sun_color: tuple[float, float, float]
    gi_color: tuple[float, float, float]
    water_color: tuple[float, float, float]
    materials: tuple[BF2TerrainMaterial, ...]

    @classmethod
    def load_from(cls, name, stream):
        reader = _TerrainReader(name, stream.read())
        version = reader.u32()
        primary_world_scale = reader.vec3()
        secondary_world_scale = reader.vec3()
        reader.u32()
        highest_height = reader.f32()
        lowest_height = reader.f32()
        patch_size = reader.u32()
        subdivide_patches = bool(reader.u8())
        patches_per_side = reader.u32()
        patch_colormap_size = reader.u32()
        low_detailmap_size = reader.u32()
        texture_bases = tuple(reader.string() for _ in range(4))
        far_side_tiling = (reader.f32(), reader.f32())
        far_top_tiling_hi = reader.f32()
        far_top_tiling_low = reader.f32()
        far_y_offset = reader.f32()
        sun_color = reader.vec3()
        gi_color = reader.vec3()
        water_color = reader.vec3()

        material_count = reader.u32()
        if material_count > 64:
            raise BF2TerrainException(
                f"Terrain '{name}' declares an unreasonable material count "
                f'of {material_count}'
            )
        materials = []
        for _ in range(material_count):
            materials.append(
                BF2TerrainMaterial(
                    texture=reader.string(),
                    tri_planar=bool(reader.u8()),
                    side_tiling=(reader.f32(), reader.f32()),
                    top_tiling=reader.f32(),
                    y_offset=reader.f32(),
                    environment_map=bool(reader.u8()),
                )
            )

        return cls(
            version=version,
            primary_world_scale=primary_world_scale,
            secondary_world_scale=secondary_world_scale,
            lowest_height=lowest_height,
            highest_height=highest_height,
            patch_size=patch_size,
            subdivide_patches=subdivide_patches,
            patches_per_side=patches_per_side,
            patch_colormap_size=patch_colormap_size,
            low_detailmap_size=low_detailmap_size,
            colormap_base_name=texture_bases[0],
            detailmap_base_name=texture_bases[1],
            low_detailmap_base_name=texture_bases[2],
            lightmap_base_name=texture_bases[3],
            far_side_tiling=far_side_tiling,
            far_top_tiling_hi=far_top_tiling_hi,
            far_top_tiling_low=far_top_tiling_low,
            far_y_offset=far_y_offset,
            sun_color=sun_color,
            gi_color=gi_color,
            water_color=water_color,
            materials=tuple(materials),
        )


class _TerrainReader:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.offset = 0

    def _unpack(self, fmt):
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise BF2TerrainException(
                f"Terrain '{self.name}' is truncated at byte "
                f'{self.offset:#x}'
            )
        values = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return values[0] if len(values) == 1 else values

    def u8(self):
        return self._unpack('<B')

    def u32(self):
        return self._unpack('<I')

    def f32(self):
        return self._unpack('<f')

    def vec3(self):
        return self._unpack('<3f')

    def string(self):
        try:
            end = self.data.index(b'\n', self.offset)
        except ValueError as exc:
            raise BF2TerrainException(
                f"Terrain '{self.name}' has an unterminated string at byte "
                f'{self.offset:#x}'
            ) from exc
        value = self.data[self.offset:end].decode('latin-1')
        self.offset = end + 1
        return value
