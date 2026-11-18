# Refractor 2 File Format Reference

This document describes the Battlefield 2/Refractor 2 asset formats consumed
or produced by Battlefield Refractor Blender. It is intended for tool authors
who need an implementation-oriented reference.

This is **not** an official DICE specification. The layouts below are derived
from the add-on's readers and writers, files encountered in Battlefield 2, and
the behavior required for round trips through the add-on. Unknown fields keep
neutral names rather than speculative meanings.

## Scope

| Format | Import | Export | Version written |
| --- | --- | --- | --- |
| Skeleton (`.ske`) | Yes | Yes | 2 |
| Animation (`.baf`) | Yes | Yes | 4 |
| StaticMesh (`.staticMesh`) | Yes | Yes | 11 |
| BundledMesh (`.bundledMesh`) | Yes | Yes | 10 |
| SkinnedMesh (`.skinnedMesh`) | Yes | Yes | 11 |
| Compiled road (`*_compiled.mesh`) | Yes | No | N/A |
| CollisionMesh (`.collisionMesh`) | Yes | Yes | 0.10 |
| Occluder planes (`.occ`) | Yes | Yes | 0.2 |
| Lightmap samples (`.samples`, `.samp_##`) | Header read; full data written | Yes | `SMP2` |
| DDS texture (`.dds`) | Blender-native | Yes | Legacy DDS |
| RAW heightmap (`.raw`) | Yes | No | N/A |
| Compiled terrain data (`terraindata.raw`) | Material header | No | `0x0001001A` |
| Refractor console scripts (`.con`) | Supported subset | ObjectTemplate subset | Text |

The source files linked at the end of each section are the authoritative
implementation when this document and the code disagree.

## Common conventions

### Byte order and scalar types

Battlefield 2 files covered here are little-endian. The current binary helper
uses Python's native `struct` byte order and therefore assumes a little-endian
host.

| Name in this document | Size | Meaning |
| --- | ---: | --- |
| `u8`, `i8` | 1 byte | Unsigned/signed integer |
| `u16`, `i16` | 2 bytes | Unsigned/signed integer |
| `u32`, `i32` | 4 bytes | Unsigned/signed integer |
| `f32` | 4 bytes | IEEE-754 single-precision float |
| `Vec3` | 12 bytes | Three `f32` values in X, Y, Z order |
| `Quat` | 16 bytes | Four `f32` values in X, Y, Z, W order |
| `Mat4` | 64 bytes | Sixteen `f32` values as four rows of four |

Unless stated otherwise, counts and indices are unsigned and indices are
zero-based.

### Strings

Most binary mesh strings use:

```text
u32 byte_count
u8  ascii_bytes[byte_count]
```

The count does not implicitly include a terminator, and the common string
reader does not strip one. Skeleton node names use a separate `u16` length and
normally include a trailing NUL byte inside that length.

Text formats and script commands are decoded as ASCII-compatible text. Tooling
should preserve ASCII output for maximum engine compatibility.

### Coordinate and texture conventions

The on-disk formats use Refractor coordinates. The add-on maps a BF2 vector to
Blender as:

```text
BF2 (x, y, z) -> Blender (x, z, y)
```

Swapping Y and Z changes handedness. Visible-mesh triangle winding is therefore
reversed during conversion. UV coordinates are converted as:

```text
BF2 (u, v) -> Blender (u, 1 - v)
```

Skeleton and animation quaternion handling also negates/conjugates vector
components as described in their sections. Matrix conversion is not a simple
component swap: the add-on transposes and inverts transforms around the axis
conversion. Tool authors should keep Refractor data in its native convention
internally and perform an explicit conversion at the application boundary.

See [`convert.py`](../io_scene_bf2/core/utils/convert.py) for the Blender
conversion rules.

## Skeleton (`.ske`)

### Supported version

The importer and exporter support version `2`.

### Layout

```text
u32 version                  // must be 2
u32 node_count

repeat node_count times:
    u16 name_byte_count
    u8  name[name_byte_count]
    i16 parent_index         // -1 identifies a root
    f32 rotation_x
    f32 rotation_y
    f32 rotation_z
    f32 rotation_w
    f32 position_x
    f32 position_y
    f32 position_z
```

Node IDs are implicit: a node's ID is its record index. A non-root
`parent_index` refers to one of those IDs. Files may contain more than one root.

The exporter writes node names as ASCII with a trailing NUL included in
`name_byte_count`. The importer accepts the same representation and strips one
trailing NUL. A tool should not assume every third-party file includes it.

On import, the add-on negates the quaternion's X, Y, and Z components while
leaving W unchanged. The inverse operation is performed for export.

The importer expects at least one root and no trailing bytes after the final
node.

Implementation:
[`bf2_skeleton.py`](../io_scene_bf2/core/bf2/bf2_skeleton.py).

## Animation (`.baf`)

### Supported version

The importer and exporter support version `4`.

### Header

```text
u32 version                  // must be 4
u16 bone_count
u16 bone_ids[bone_count]
u32 frame_count
u8  position_precision
```

Each bone ID normally refers to the corresponding node index in the skeleton.
The file then contains one compressed record for each ID, in the same order.

### Per-bone record

```text
u16 data_size

repeat 7 component streams:
    u16 stream_word_count
    block blocks[...]        // until stream_word_count is consumed
```

The seven streams are ordered:

1. quaternion X
2. quaternion Y
3. quaternion Z
4. quaternion W
5. position X
6. position Y
7. position Z

`data_size` is the sum of the seven stream payload sizes measured in 16-bit
words. The current reader does not use this field to locate the next record;
each stream's own size controls parsing.

### Stream blocks

Each block begins with:

```text
u8 head
u8 block_word_count
```

`head & 0x80` is the RLE flag. `head & 0x7f` is the number of frames represented
by the block.

When the RLE flag is set, one `u16` value follows and is repeated for every
frame in the block. Otherwise, one `u16` value follows for each frame.
`block_word_count` includes the two control bytes as one 16-bit word, so it is:

```text
2                  for an RLE block
frame_count + 1    for a literal block
```

The exporter limits blocks to 126 frames and uses RLE for runs longer than five
values.

### Fixed-point values

Quaternion streams use precision `15`. Position streams use the global
`position_precision` byte. This implementation uses:

```text
scale = 32767 / 2^(15 - precision)
decoded = signed_value / scale
```

The signed-word mapping used by BF2 Animation support here is not normal
two's-complement conversion:

```text
decode: if word > 32767, word -= 65535
encode: if -32767 <= value < 0, value += 65535
```

Quaternion X, Y, and Z are negated between the compressed stream and the
in-memory quaternion; W is not. A compatible writer should therefore encode
`-x`, `-y`, `-z`, and `w` in the first four streams.

Every component stream must expand to no more than `frame_count` entries. The
importer also requires the final read position to equal the file size.

Implementation:
[`bf2_animation.py`](../io_scene_bf2/core/bf2/bf2_animation.py).

## Visible meshes

StaticMesh, BundledMesh, and SkinnedMesh share one container layout and differ
primarily in their LOD subtype data and material records.

### Versions

| Type | Current writer | Notes |
| --- | ---: | --- |
| StaticMesh | 11 | Version 11 materials include bounds |
| BundledMesh | 10 | LODs store a part count |
| SkinnedMesh | 11 | LODs store rigs and bind matrices |

The reader contains compatibility handling for older versions, including one
extra discarded `Vec3` after LOD bounds in versions 4 and 6. Writers should use
the current versions above.

### Container layout

```text
u32 zero_or_reserved
u32 version
u32 reserved_0
u32 reserved_1
u32 reserved_2
u8  reserved_flag

u32 geom_count
repeat geom_count times:
    u32 lod_count

u32 vertex_attribute_count
VertexAttribute attributes[vertex_attribute_count]

u32 primitive_type           // importer requires 4: triangle list
u32 vertex_stride            // bytes per interleaved vertex
u32 vertex_count
u8  vertex_buffer[vertex_stride * vertex_count]

u32 index_count
u16 index_buffer[index_count]

if StaticMesh or BundledMesh:
    u32 alpha_blend_face_set_count

LOD records for every Geom/LOD pair
Material records for every Geom/LOD pair
```

Geoms are commonly used for pristine/damaged states, but the format itself
only provides numbered groups. Some assets use them for first-person,
third-person, or other variants. Each Geom owns an ordered LOD list, where
LOD0 is normally the most detailed.

### Vertex declarations

Each declaration occupies eight bytes:

```text
u16 flag
u16 byte_offset
u16 declaration_type
u16 declaration_usage
```

Known flags are `0` for a used element and `255` for an unused terminator.
BF2 files conventionally end the declaration list with an UNUSED element.

The current reader handles these Direct3D declaration types:

| Value | Name | Storage |
| ---: | --- | --- |
| 0 | `FLOAT1` | One `f32` |
| 1 | `FLOAT2` | Two `f32` |
| 2 | `FLOAT3` | Three `f32` |
| 3 | `FLOAT4` | Four `f32` |
| 4 | `D3DCOLOR` | Four `u8` values |
| 17 | `UNUSED` | No data |

Common usages are:

| Value | Meaning |
| ---: | --- |
| `0` | Position |
| `1` | Blend weight |
| `2` | Blend indices |
| `3` | Normal |
| `5` | Texture coordinate 0 |
| `6` | Tangent |
| `7` | Binormal |
| `0x105`, `0x205`, `0x305`, `0x405` | Texture coordinates 1 through 4 |

The high byte of BF2's texture-coordinate usage selects the channel. Element
offsets are relative to the start of each interleaved vertex; the declared
`vertex_stride` advances to the next vertex.

### LOD records

Every LOD begins with:

```text
Vec3 bounds_min
Vec3 bounds_max
```

Its subtype data then depends on the mesh:

**StaticMesh**

```text
u32 part_matrix_count
Mat4 part_matrices[part_matrix_count]
```

**BundledMesh**

```text
u32 part_count
```

**SkinnedMesh**

```text
u32 rig_count
repeat rig_count times:
    u32 bone_count
    repeat bone_count times:
        u32 bone_id
        Mat4 bind_matrix
```

Bone IDs correspond to skeleton node IDs and to the IDs referenced by blend
indices in the vertex buffer.

### Material records

Each LOD stores:

```text
u32 material_count
Material materials[material_count]
```

The common material payload is:

```text
if StaticMesh or BundledMesh:
    u32 alpha_mode

string fx_file
string technique
u32 map_count
string maps[map_count]

u32 vertex_start
u32 index_start
u32 index_count
u32 vertex_count
u32 unknown_0
u32 unknown_1

if StaticMesh version 11:
    Vec3 material_bounds_min
    Vec3 material_bounds_max
```

`vertex_start` and `vertex_count` select a range from the global vertex buffer.
`index_start` and `index_count` select a range from the global index buffer.
Indices in that range are local to the material's selected vertex range.
Triangle-list indices are grouped in threes.

Map strings are engine-relative texture names, commonly under `objects/...`.
They are references rather than embedded image data.

StaticMesh and BundledMesh alpha modes are:

| Value | Meaning |
| ---: | --- |
| 0 | No alpha mode |
| 1 | Alpha blend |
| 2 | Alpha test |

Alpha-blended materials use eight pre-sorted face sets. The global
`alpha_blend_face_set_count` and each material's index data account for those
sets. Tools that rewrite alpha-blended meshes must preserve or regenerate all
eight sets rather than treating the index segment as one ordinary triangle
list.

Implementations:

- [`bf2_visiblemesh.py`](../io_scene_bf2/core/bf2/bf2_mesh/bf2_visiblemesh.py)
- [`bf2_staticmesh.py`](../io_scene_bf2/core/bf2/bf2_mesh/bf2_staticmesh.py)
- [`bf2_bundledmesh.py`](../io_scene_bf2/core/bf2/bf2_mesh/bf2_bundledmesh.py)
- [`bf2_skinnedmesh.py`](../io_scene_bf2/core/bf2/bf2_mesh/bf2_skinnedmesh.py)

## Compiled roads (`*_compiled.mesh`)

Compiled roads use a separate triangle-mesh format rather than the visible-mesh
container above. Level placement comes from `CompiledRoads.con`; road material
settings come from the matching ObjectTemplate's `*_compiled.dat`.

### Versioned header

Versions encountered in retail Battlefield 2 maps store the minor word first:

```text
u16 version_minor
u16 version_major             // 1 in known versioned files
Vec3 origin                   // also used by the placement script
f32 radius
Vec3 bounds_min
Vec3 bounds_max
```

Version `1.0` then stores `u32 vertex_count`. Versions `1.2`, `1.3`, and `1.4`
store:

```text
i32 order
u32 vertex_count
```

Version `1.0` and `1.2` vertices are 56 bytes:

```text
Vec3 position
Vec3 normal                   // not consumed by the game road vertex buffer
f32 primary_uv[2]
f32 secondary_uv[2]
f32 tangent_or_reserved[4]   // not consumed by the game road vertex buffer
```

Version `1.3` and newer vertices are 32 bytes:

```text
Vec3 position
f32 primary_uv[2]
f32 secondary_uv[2]
f32 alpha
```

### Legacy unversioned layout

Some retail maps contain an older file without version words. It starts
directly with `origin`, `radius`, and the two bounds vectors, followed by
`u32 vertex_count`. Its 40-byte vertices contain:

```text
Vec3 position
Vec3 normal
f32 primary_uv[2]
f32 secondary_uv[2]
```

The importer identifies this layout when the first four bytes are not a known
version header and reports it as version `0.0`.

### Indices and chunks

All layouts continue with:

```text
u32 index_count
u16 indices[index_count]
```

The renderer draws `floor(index_count / 3)` triangles, so a trailing incomplete
triangle is ignored. Indices are local to the road vertex buffer.

Version `1.4` and newer append:

```text
u32 chunk_count

repeat chunk_count times:
    u32 first_index
    u32 index_count
    f32 radius
    Vec3 center
```

Chunks support distance/frustum visibility in the game. Blender imports the
complete index buffer as one object.

### Compiled material data

`Roads/Splines/<template>_compiled.dat` contains two newline-terminated,
extensionless texture paths followed by 16 binary bytes:

```text
ascii primary_texture_path "\n"
ascii secondary_texture_path "\n"
f32 blend_factor
f32 fade_start
f32 fade_end
u32 priority
```

Blender creates `UV0` and `UV1`, stores per-vertex opacity in the
`road_alpha` point attribute, and preserves blend/fade/priority values as
material custom properties.

The retail `RoadCompiled.fx` path applies several behaviors that are not
obvious from the mesh:

- vertices are raised `0.01` metres along the game up axis before projection;
- the secondary texture samples `UV1 * 0.1`;
- the final color is `lerp(secondary, primary, blend_factor)`;
- primary U clamps while primary V and both secondary axes wrap;
- output opacity is primary texture alpha multiplied by vertex and
  camera-distance fade; and
- source-alpha blending is enabled while depth writes are disabled.

The Blender importer reproduces those rules with a transparent material and a
local Z lift. `priority` is retained as metadata; it is a road
compilation/intersection input and is not treated as an additional arbitrary Z
offset.

Implementations:

- [`bf2_road.py`](../io_scene_bf2/core/bf2/bf2_road.py)
- [`road.py`](../io_scene_bf2/core/road.py)

## CollisionMesh (`.collisionMesh`)

The exporter writes version `0.10`. Battlefield 2 assets commonly use versions
`0.9` and `0.10`; those are the interoperability targets for this add-on.

### Top-level hierarchy

```text
u32 version_major
u32 version_minor
u32 geom_part_count

repeat geom_part_count times:
    u32 geom_count
    repeat geom_count times:
        u32 collision_surface_count
        CollisionSurface surfaces[collision_surface_count]
```

The hierarchy is therefore GeomPart -> Geom -> collision surface. Collision
surface IDs have conventional meanings:

| Value | Surface |
| ---: | --- |
| 0 | Projectile |
| 1 | Vehicle |
| 2 | Soldier |
| 3 | AI |

### Collision surface

```text
u32 collision_type
u32 face_count

repeat face_count times:
    u16 vertex_0
    u16 vertex_1
    u16 vertex_2
    u16 material

u32 vertex_count
Vec3 vertices[vertex_count]
u16 vertex_materials[vertex_count]

Vec3 bounds_min
Vec3 bounds_max

u8 bsp_present_ascii         // ASCII '0' or '1'
if bsp_present_ascii == '1':
    BSP bsp

if version is 0.10:
    i32 face_adjacency[face_count]
```

Face material values index the ObjectTemplate collision-material mapping.
The per-vertex material array is also preserved by the format.

The BSP-presence marker is the ASCII byte `0x30` or `0x31`, not a numeric
integer byte.

### BSP block

```text
Vec3 bounds_min
Vec3 bounds_max
u32 node_count
BSPNode nodes[node_count]
u32 face_reference_count
u16 face_references[face_reference_count]
```

A node contains:

```text
f32 split_plane
u32 packed_flags
u32 front_value
u32 back_value
```

`packed_flags` uses:

| Bits | Meaning |
| --- | --- |
| 0-1 | Split axis |
| 2 | Front side is a leaf |
| 3 | Back side is a leaf |
| 16-23 | Front leaf face count |
| 24-31 | Back leaf face count |

Split axes are `0` for a plane parallel to ZY, `1` for XZ, and `2` for XY. For
a leaf side, its value is an offset into `face_references`; otherwise it is a
child node index. Each face reference is a `u16` index into the surface's face
array.

Implementation:
[`bf2_collmesh.py`](../io_scene_bf2/core/bf2/bf2_collmesh.py).

## Occluder planes (`.occ`)

Occluders are plain text. The first line must begin with:

```text
OCCLUDERPLANESv0.2
```

Zero or more groups follow:

```text
GROUP
<plane_count>
<vertex_index_0> <vertex_index_1> <vertex_index_2> <vertex_index_3>
... one line per plane
<vertex_count>
<x> <y> <z>
... one line per vertex
```

Every plane is a quad and must contain exactly four integer indices. Every
vertex line must contain exactly three floating-point values. Indices are
zero-based and local to their group.

Example:

```text
OCCLUDERPLANESv0.2
GROUP
1
0 1 2 3
4
0 0 0
1 0 0
1 0 1
0 0 1
```

Implementation:
[`bf2_occluder_planes.py`](../io_scene_bf2/core/bf2/bf2_occluder_planes.py).

## Lightmap samples (`.samples`, `.samp_##`)

The complete `SMP2` layout written by the add-on is:

```text
u8 magic[4]                 // ASCII "SMP2"
u32 width
u32 height

repeat width * height times:
    Vec3 position
    Vec3 direction
    i32 face_index          // -1 means no assigned face

u32 face_count
repeat face_count times:
    repeat 3 triangle vertices:
        Vec3 position
        Vec3 normal
```

There is no separate sample count; it is derived from `width * height`. The
exporter requires both dimensions to be powers of two.

The current level loader reads only the magic and dimensions when it needs an
existing lightmap size. The exporter writes the full sample and triangle
payload shown above.

Implementation:
[`bf2_samples.py`](../io_scene_bf2/core/bf2/bf2_mesh/bf2_samples.py).

## DDS textures (`.dds`)

DDS is a Microsoft container rather than a Refractor-specific format. See the
[Microsoft DDS programming guide](https://learn.microsoft.com/windows/win32/direct3ddds/dx-graphics-dds-pguide)
for the general 128-byte legacy header and optional DX10 extension.

Blender 5.2 loads imported DDS files directly. The add-on's header reader can
inspect both legacy FourCC and DX10/DXGI headers, but actual image decoding is
delegated to Blender.

The exporter intentionally writes legacy, Battlefield-compatible DDS files:

| Export option | Payload |
| --- | --- |
| `NONE` | 32-bit BGRA with RGBA channel masks |
| `DXT1` | BC1/DXT1, 8 bytes per 4x4 block |
| `DXT3` | BC2/DXT3, 16 bytes per 4x4 block |
| `DXT5` | BC3/DXT5, 16 bytes per 4x4 block |

Output begins with `DDS `, followed by the 124-byte legacy header. Compressed
files put `DXT1`, `DXT3`, or `DXT5` in the pixel format's FourCC. No DX10
extension is written.

The encoder writes the top image row first, creates a complete mip chain down
to 1x1, and pads incomplete compression blocks by repeating edge pixels.
Uncompressed payloads are stored in B, G, R, A byte order.

Implementations:

- [`dds_encoder.py`](../io_scene_bf2/directx/dds_encoder.py)
- [`dds.py`](../io_scene_bf2/directx/dds.py)

## RAW heightmaps (`.raw`)

RAW terrain heightmaps have no header. Their dimensions and sample width come
from the file size and the associated `Heightdata.con` commands.

For a configured bit resolution:

```text
bytes_per_sample = bit_resolution / 8
dimension = sqrt(file_size / bytes_per_sample)
```

The file is accepted only when:

- `bytes_per_sample` is 1, 2, 4, or 8;
- the data describes a square `dimension * dimension` grid; and
- every sample is an unsigned little-endian integer.

The add-on reshapes the samples as a square array and transposes it before
creating Blender vertices. Heights are multiplied directly by the configured
Z scale; X and Y grid spacing use the configured horizontal scale. The terrain
is centered around the origin.

Each grid cell uses one fixed anti-diagonal. Given:

```text
a = (x,     y)
b = (x + 1, y)
c = (x,     y + 1)
d = (x + 1, y + 1)
```

the two triangles, including Blender winding, are `(b, a, c)` and `(d, b, c)`.
The shared edge is therefore `b-c`. Refractor does not alternate this diagonal
in a checkerboard. Compiled retail roads fitted against the heightfield match
this fixed topology; alternating diagonals introduce millimetre-to-centimetre
surface errors even when the RAW samples and scale are unchanged.

`Heightdata.con` supplies values through commands such as:

```text
HeightmapCluster.create <name>
HeightmapCluster.setClusterSize <size>
HeightmapCluster.setHeightmapSize <size>
HeightmapCluster.addHeightmap <type> <offset_x> <offset_z>
Heightmap.setSize <x> <y>
Heightmap.setScale <x/y/z>
Heightmap.setBitResolution <bits>
Heightmap.loadHeightData <path>
Heightmap.loadMaterialData <path>
HeightmapCluster.setSeaWaterLevel <height>
```

The general level importer loads the complete configured cluster. Stock maps
normally use one primary heightmap at `(0, 0)` plus eight lower-resolution
secondary heightmaps in a 3x3 arrangement. Each tile is centered and translated
by:

```text
tile_world_offset = cluster_offset * HeightmapCluster.heightmap_size
```

The water plane spans
`cluster_size * heightmap_size` in both horizontal dimensions and is placed at
`setSeaWaterLevel`. The lightmapping-specific loader intentionally retains its
primary-heightmap-only workflow.

### Editable terrain settings

`Terrain.con` supplies the texture bases used by editable terrain:

```text
Terrain.detailmapBaseName <path>/tx
Terrain.lowDetailmapBaseName <path>/tx
Terrain.colormapBaseName <path>/tx
Terrain.lightmapBaseName <path>/tx
Terrain.farSideTiling <x/y>
Terrain.farTopTilingHi <value>
Terrain.farTopTilingLow <value>
Terrain.farYOffset <value>
```

### Compiled terrain material header

The level-root `terraindata.raw` is not a heightmap. Its compiled header
duplicates terrain dimensions and supplies material data that may not be
present in loose `Terrain.con`. Retail files observed by this project use
version `0x0001001A`:

```text
u32 version
Vec3 primary_world_scale
Vec3 secondary_world_scale
u32 reserved_or_flags
f32 highest_height
f32 lowest_height
u32 patch_size
u8 subdivide_patches
u32 patches_per_side
u32 patch_colormap_size
u32 low_detailmap_size

ascii colormap_base_name "\n"
ascii detailmap_base_name "\n"
ascii low_detailmap_base_name "\n"
ascii lightmap_base_name "\n"

f32 far_side_tiling[2]
f32 far_top_tiling_hi
f32 far_top_tiling_low
f32 far_y_offset
Vec3 sun_color
Vec3 gi_color
Vec3 water_color

u32 material_count
repeat material_count times:
    ascii detail_texture "\n"
    u8 tri_planar
    f32 side_tiling[2]
    f32 top_tiling
    f32 y_offset
    u8 environment_map
```

Patch and secondary-terrain blocks follow this header. The add-on currently
stops after the material records because geometry comes from the RAW
heightmaps and the visual material can be reconstructed from the referenced
DDS resources.

The primary terrain divides color, detail, low-detail, and light maps into
patch textures such as `tx00x00.dds`. A patch has up to two detail charts:

| Detail chart | Red | Green | Blue |
| --- | --- | --- | --- |
| `txCCxRR_1.dds` | Material 0 | Material 1 | Material 2 |
| `txCCxRR_2.dds` | Material 3 | Material 4 | Material 5 |

Charts may be absent when none of their three materials is used, and retail
maps contain both 128- and 256-pixel charts. The importer resamples each chart
to half the configured colormap patch size and builds two non-color RGB
atlases. Colormap patches are stitched at their configured size. If a
colormap patch is absent, its corresponding minimap region fills the atlas;
an absent mask chart contributes zero weights.

For colormap `C`, detail texture samples `D_i`, and chart channels `w_i`, the
near-detail approximation is:

```text
w = clamp(sum(w_i), 0, 1)
detail = 2 * (sum(w_i * D_i) + (1 - w) * 0.5)
result = C * detail
```

This matches the shader's neutral-centered detail modulation while leaving
lighting to Blender. A material marked tri-planar uses its main detail texture
for the top projection and `<detail_texture>_side.dds` for the two slope
projections, weighted by the absolute normalized surface-normal components.
The primary texture is the side fallback when that optional image is absent.
The `environment_map` flag is parsed and preserved but is not yet rendered.

### Surrounding-terrain textures

Stock levels also contain one colormap and one low-detail component map for
each of the eight surrounding heightmaps:

| Cluster offset | Colormap | Low-detail component |
| --- | --- | --- |
| `(-1, -1)` | `Colormaps/tx_s0.dds` | `LowDetailmaps/tx_s0.dds` |
| `(0, -1)` | `Colormaps/tx_s1.dds` | `LowDetailmaps/tx_s1.dds` |
| `(1, -1)` | `Colormaps/tx_s2.dds` | `LowDetailmaps/tx_s2.dds` |
| `(-1, 0)` | `Colormaps/tx_s3.dds` | `LowDetailmaps/tx_s3.dds` |
| `(1, 0)` | `Colormaps/tx_s4.dds` | `LowDetailmaps/tx_s4.dds` |
| `(-1, 1)` | `Colormaps/tx_s5.dds` | `LowDetailmaps/tx_s5.dds` |
| `(0, 1)` | `Colormaps/tx_s6.dds` | `LowDetailmaps/tx_s6.dds` |
| `(1, 1)` | `Colormaps/tx_s7.dds` | `LowDetailmaps/tx_s7.dds` |

The `_s0` through `_s7` ordering matches the secondary
`HeightmapCluster.addHeightmap` command order used by stock levels. The eight
colormaps form a continuous outer landscape around the primary map.

The low-detail component maps and the level-root `LowDetailTexture.dds` are
inputs to Refractor's far-terrain shader, not standalone color textures. In
the game's `Shared_PS_STNormal` path:

- the component map's red channel controls interpolation between a neutral
  value and the top-projected blue channel of `LowDetailTexture.dds`;
- its blue channel controls interpolation between a neutral value and a
  normal-weighted triplanar sample; and
- the result modulates the colormap before output.

Consequently, displaying `LowDetailTexture.dds` or a component map directly as
diffuse color produces false saturated colors. Tools that do not reproduce the
full shader should use the authored `tx_s#.dds` colormap as the secondary
terrain's overview color rather than inventing a neutral material or stretching
the primary minimap across the 3x3 cluster.

Implementations:

- [`bf2_terrain.py`](../io_scene_bf2/core/bf2/bf2_terrain.py)
- [`terrain.py`](../io_scene_bf2/core/terrain.py)
- [`heightmap.py`](../io_scene_bf2/core/heightmap.py)

## Refractor console scripts (`.con`)

Refractor `.con` files are command scripts, not declarative asset containers.
Battlefield 2 supports more commands and language behavior than this add-on
needs. Tool authors should not treat the subset below as a complete engine
grammar.

### Lexical behavior used by the add-on

- Commands are case-insensitive.
- Unquoted arguments are separated by whitespace.
- Double quotes preserve spaces in one argument.
- `rem` comments one line.
- `beginrem` and `endrem` delimit a comment block.
- `run` and `include` execute another script relative to the current source.
- `if`, `elseif`, and `endif` have limited string comparison support.
- Vectors are slash-separated, for example `1.0/2.0/3.0`.
- A 4x4 transform is encoded as four bracketed slash-separated rows, for
  example `[...][...][...][...]`.

The add-on intentionally implements only enough of `const` and `var` for
encountered files. It does not implement the full Refractor expression,
assignment, branching, and output semantics.

### ObjectTemplate commands

The importer consumes these object relationships and properties:

```text
ObjectTemplate.create <type> <name>
ObjectTemplate.active <name>
ObjectTemplate.activeSafe <type> <name>
ObjectTemplate.geometry <geometry_template>
ObjectTemplate.geometryPart <index>
ObjectTemplate.collisionMesh <collision_template>
ObjectTemplate.collisionPart <index>
ObjectTemplate.mapMaterial <index> <name> <unknown>
ObjectTemplate.addTemplate <child_template>
ObjectTemplate.setPosition <x/y/z>
ObjectTemplate.setRotation <x/y/z>
ObjectTemplate.hasCollisionPhysics <0_or_1>
ObjectTemplate.hasMobilePhysics <0_or_1>
ObjectTemplate.physicsType <name_or_number>
ObjectTemplate.anchor <x/y/z>
ObjectTemplate.creator <name>
ObjectTemplate.saveInSeparateFile <0_or_1>
```

`setPosition` and `setRotation` apply to the most recently added child.
Collision material mappings connect `.collisionMesh` material IDs to Refractor
material names.

### Geometry and collision templates

```text
GeometryTemplate.create <type> <name>
GeometryTemplate.active <name>
GeometryTemplate.doNotGenerateLightmaps <0_or_1>
CollisionManager.createTemplate <name>
```

Recognized geometry types include `StaticMesh`, `BundledMesh`, `SkinnedMesh`,
`MeshParticleMesh`, `RoadCompiled`, and `DebugSphereMesh`. For the first three,
the referenced mesh is conventionally resolved as:

```text
<script directory>/Meshes/<template name>.<mesh extension>
```

Collision templates similarly resolve to:

```text
<script directory>/Meshes/<template name>.collisionMesh
```

When a raw ObjectTemplate file is imported, the add-on does not follow
`run`/`include` directives. Required ObjectTemplate, GeometryTemplate, and
CollisionManager definitions must therefore be available in the selected
script itself for that workflow.

### Level object placement

The level loader also recognizes:

```text
Object.create <object_template>
Object.absolutePosition <x/y/z>
Object.rotation <x/y/z>
Object.absoluteTransformation <matrix>
Object.layer <integer>
Object.isOvergrowth <0_or_1>
Object.setLightSourceMask <integer>
Object.geometry.loadMesh <compiled_road_path>
LightManager.sunDirection <x/y/z>
LightManager.skyColor <r/g/b>
LightManager.ambientColor <r/g/b>
LightManager.sunColor <r/g/b>
Renderer.waterColor <r/g/b>
Renderer.waterSpecularColor <r/g/b/a>
Renderer.waterSpecularPower <value>
Terrain.waterSunIntensity <value>
```

Animation declarations consumed by the parser include
`AnimationSystem.createAnimation`, `looping`, `length`, and
`ignoreMotherOrientation`.

Implementation:
[`bf2_engine`](../io_scene_bf2/core/bf2/bf2_engine/).

## Paths, case, and archives

Battlefield 2 content is usually split between client and server ZIP archives
and addressed through engine-relative paths such as `Objects/...` and
`Textures/...`.

Interoperable tools should:

- accept `/` and `\` in script references;
- resolve paths case-insensitively, including names inside ZIP archives;
- normalize `.` and `..` components before lookup;
- search relative to the including script before mounted mod roots;
- preserve the client/server distinction when repackaging a mod; and
- avoid embedding machine-specific absolute paths in output files.

The complete-level workflow mounts mod and level ZIP archives directly.
Archive-backed DDS resources are copied into a content-addressed local cache,
loaded through Blender's native DDS support, and packed into the `.blend`.
Individual-file ObjectTemplate workflows still expect neighboring resources to
exist on disk.

Implementation:
[`file_manager.py`](../io_scene_bf2/core/bf2/bf2_engine/file_manager.py).

## Interoperability checklist

When implementing a new reader or writer:

1. Decode all binary integers and floats as little-endian.
2. Validate versions, counts, buffer ranges, and index bounds before
   allocating.
3. Preserve unknown/reserved fields when editing an existing file.
4. Treat Geom and LOD meanings as asset conventions, not hard-coded semantics.
5. Keep index-buffer values local to each visible-mesh material vertex range.
6. Apply coordinate, winding, UV, and quaternion conversions consistently.
7. Resolve Refractor paths case-insensitively.
8. Test against both an original Battlefield 2 asset and a file exported by
   this add-on.
9. Reject truncated data and unexpected trailing bytes where the format has a
   strict end.
