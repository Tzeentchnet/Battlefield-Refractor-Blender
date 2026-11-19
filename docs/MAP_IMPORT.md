# Level and Map Import

Battlefield Refractor Blender can build a complete visual/editor scene from a
Battlefield 2 or Battlefield 2142 level. It reads both untouched packed levels
and unpacked mod levels without requiring the user to extract retail archives
first.

This workflow imports visual content. It does not convert a level into a
playable Blender project or recreate the complete Refractor 2 runtime.

## Requirements

- Blender 5.2 or newer.
- Battlefield Refractor Blender installed and enabled.
- A Battlefield 2 or Battlefield 2142 installation configured under
  `Edit > Preferences > Add-ons > Battlefield Refractor Blender`, or an
  additional mod directory configured there.
- The selected level must be inside one of the configured game or mod
  directories.

For the retail games, configure the folder containing the game executable.
The add-on uses the corresponding base asset directory:

```text
<Battlefield 2 installation>/mods/bf2
<Battlefield 2142 installation>/mods/bf2142
```

Add dependency mods as additional paths when a custom level references their
objects or textures.

### Battlefield 2142

Stock BF2142 levels are under:

```text
<Battlefield 2142 installation>/mods/bf2142/Levels
```

BF2142 mounts its object archives below category paths such as
`Objects\Common` and `Objects\Vehicles`. The importer resolves these nested
mounts and the retail Northern Strike `*_bp1_*` archives automatically through
`ClientArchives.con` and `ServerArchives.con`.

See [Battlefield 2142 notes](BF2142.md) for material and re-export caveats.

## Starting an import

1. Choose `File > Import > Battlefield 2 / 2142 > Level / Map`.
2. Select one of the following:
   - the level directory;
   - `client.zip`;
   - `server.zip`; or
   - a `.con` file inside an unpacked level.
3. Review the import options.
4. Select **Import Battlefield Level**.

The importer detects packed and unpacked layouts automatically.

### Packed levels

A packed level directory must contain both:

```text
client.zip
server.zip
```

The importer mounts these archives at the level's logical Refractor path. It
also loads the configured mod's server and client archives so ObjectTemplates,
visible meshes, and shared textures can be resolved.

### Unpacked levels

An unpacked level is detected by the presence of `Heightdata.con`. Resources
are read from the configured game and mod directories and the level directory.
Individual ObjectTemplate workflows may still require neighboring resources
to be extracted, but complete packed-level import does not.

## Import options

| Option | Default | Result |
| --- | --- | --- |
| Static Objects | On | Imports placements from `StaticObjects.con`, including supported bundled child objects. |
| Overgrowth | On | Imports placements described by `Overgrowth/OvergrowthCollision.con`. |
| Compiled Roads | On | Imports supported `RoadCompiled` meshes and their material data. |
| Maximum LOD Index | 0 | Imports Geom0/LOD0 by default. A higher value includes additional visible LODs up to that index. |
| Terrain | On | Imports RAW heightmap geometry. |
| Surrounding Terrain | On | Imports the eight lower-resolution tiles around the playable primary tile. |
| Water | On | Creates one plane over the complete heightmap cluster at the configured sea level. |
| Lighting | On | Creates a sun and configures the Blender World from parsed level lighting. |

Turning off **Terrain** also disables the surrounding-terrain and water
controls in the dialog. Water is derived from the heightmap cluster and is
therefore not imported independently.

## Scene organization

The visual importer creates these collections when their content is enabled:

| Collection | Content |
| --- | --- |
| `StaticObjects` | Instantiated ObjectTemplates that use normal lightmap handling. |
| `StaticObjects_SkipLightmaps` | Instances whose source configuration skips lightmaps. |
| `Roads` | Placed compiled road meshes. |
| `Heightmaps` | The primary terrain and any imported secondary terrain tiles. |
| `Water` | The map-wide water plane. |
| `Lights` | The map sun. |

Meshes shared by many placements are imported once and instantiated where
possible. This substantially reduces duplicated mesh data, but a large retail
map can still contain thousands of objects and several million polygons.

## Terrain

### Geometry

`Heightdata.con` defines the cluster layout, source RAW files, bit depth,
horizontal and vertical scales, and sea level. Stock Battlefield 2 maps
normally use a 3x3 cluster:

```text
secondary  secondary  secondary
secondary   primary   secondary
secondary  secondary  secondary
```

The primary tile is normally a 16-bit heightmap. The eight surrounding tiles
are normally lower-resolution 8-bit heightmaps. Each tile is centered around
its own origin and translated by:

```text
cluster offset * HeightmapCluster heightmap size
```

Every heightfield cell uses Refractor's fixed anti-diagonal, from the
positive-X corner to the positive-Y corner. Alternating the diagonal produces
small but visible mismatches against compiled roads, even when the height
samples themselves are correct. Samples are retained as unsigned source
values until their configured scale is applied to NumPy `float32` vertices;
16-bit RAW quantization, not Blender floating-point precision, is the limiting
height resolution on stock maps.

### Primary terrain materials

The visual map importer reads the compiled `terraindata.raw` header and
reconstructs the playable terrain's near-detail material:

- patch colormaps such as `Colormaps/tx00x00.dds` are stitched into one
  map-wide atlas;
- `Detailmaps/txCCxRR_1.dds` supplies the RGB weights for materials 0-2;
- `Detailmaps/txCCxRR_2.dds` supplies the RGB weights for materials 3-5;
- the six texture names and tiling values come from `terraindata.raw`; and
- layers marked tri-planar use `<texture>_side.dds` on slopes, with the main
  detail texture as a fallback if no side image exists.

The masks form an approximately normalized partition after their source DDS
quantization. Detail textures are neutral-centered: the importer adds neutral
`0.5` for any unassigned mask weight, doubles the weighted result, then
multiplies it by the colormap. This preserves the game's detail modulation
without baking game lighting into Blender's Principled shader.

Generated colormap and mask atlases use the local texture cache and are packed
into the saved `.blend`. Missing colormap patches use the matching region from
`Hud/Minimap/ingameMap.dds`; missing mask charts contribute zero weight.
Failure to read the compiled terrain header or any complete colormap set is
reported explicitly and falls back to the minimap overview material.

### Surrounding-terrain materials

Each surrounding tile uses its map-authored `Colormaps/tx_s0.dds` through
`tx_s7.dds` image. `Terrain.con` supplies the colormap base path. If it is
absent, the importer uses the conventional `<level>/Colormaps/tx` base.
Missing secondary colormaps produce an explicit warning and use a neutral
fallback material.

The secondary texture ordering follows the stock heightmap ordering:

| Cluster offset | Texture |
| --- | --- |
| `(-1, -1)` | `tx_s0.dds` |
| `(0, -1)` | `tx_s1.dds` |
| `(1, -1)` | `tx_s2.dds` |
| `(-1, 0)` | `tx_s3.dds` |
| `(1, 0)` | `tx_s4.dds` |
| `(-1, 1)` | `tx_s5.dds` |
| `(0, 1)` | `tx_s6.dds` |
| `(1, 1)` | `tx_s7.dds` |

These images form the intended continuous outer landscape. They must not be
replaced by a stretched copy of the playable-area minimap.

The original game additionally changes terrain with camera distance through
`LowDetailmaps/tx_s#.dds`, `LowDetailTexture.dds`, surface normals, and the
far-terrain tiling values in `Terrain.con`. Those resources are shader inputs,
not ordinary diffuse images. The importer reconstructs the near primary
detail layers but does not yet reproduce the exact low-detail distance
transition. Surrounding Blender materials therefore use their authored
colormaps directly.

### Water

The water plane covers:

```text
cluster size * heightmap size
```

in both horizontal dimensions and is placed at
`HeightmapCluster.setSeaWaterLevel`. Its visual color and specular settings
come from the parsed level renderer configuration where available.

The source game uses more complex water rendering and coastline behavior.
Blender receives a single editing/overview surface rather than a complete
Refractor water simulation.

## Compiled roads

Road placements come from `CompiledRoads.con`. Geometry is read from
`*_compiled.mesh`, and material settings come from the corresponding
`*_compiled.dat`.

The importer supports the retail layouts encountered in:

- unversioned compiled roads;
- versions 1.0, 1.2, 1.3, and 1.4;
- both road UV sets;
- primary-texture alpha multiplied by vertex alpha;
- the compiled blend factor with secondary UVs scaled by `0.1`;
- the primary sampler's clamped U axis and wrapped V axis;
- camera-distance fade from the compiled material;
- source-alpha rendering without road depth writes;
- Refractor's `0.01` metre up-axis lift; and
- version 1.4 chunk tables.

Some level archives contain stale or unreferenced compiled road files. Only
roads referenced by the placement configuration are added to the scene.
The one-centimetre lift and fixed terrain diagonal keep fitted roads above the
terrain without inventing per-template offsets from the material priority.

## Lighting

With **Lighting** enabled, the importer reads `Sky.con` and related renderer
commands to create:

- a Blender Sun light with the level's direction and color; and
- World background/ambient values suitable for visual inspection.

Sky domes, animated sky layers, volumetric fog, and the exact Refractor
lighting model are not recreated.

## Archive textures and portability

DDS files inside archives are loaded through Blender's native DDS support:

1. The bytes are read from the mounted BF2 archive.
2. A content hash identifies the resource.
3. A physical DDS copy is stored under the user's local
   `Battlefield Refractor Blender/textures` cache.
4. Blender loads that DDS and packs it into the `.blend`.

The cached file lets Blender retain a valid source path, while packing makes a
saved scene portable. Moving or clearing the cache should not remove textures
already packed into a saved Blender file.

Blender may report that some DDS images cannot remain GPU-compressed and are
being held as uncompressed image data. This does not by itself indicate an
import failure.

## Source metadata

The importer stores provenance as Blender custom properties.

Scene properties include:

- `bf2_level_name`;
- `bf2_level_path`;
- `bf2_level_packed`;
- `bf2_level_object_count`;
- `bf2_level_road_count`; and
- `bf2_level_terrain_count`.

Terrain objects include:

- `bf2_cluster_offset`;
- `bf2_source_heightmap`;
- `bf2_primary_heightmap`; and
- `bf2_compiled_terrain` and `bf2_terrain_material_count` on the primary tile;
- `bf2_secondary_colormap` for surrounding tiles.

Generated terrain images carry `bf2_generated_texture`,
`bf2_generated_hash`, `bf2_source_base`, and missing-tile counts. Compiled-road
objects carry `bf2_vertical_offset` in addition to source/version metadata.
Water and materials also retain relevant source and level settings. These
values are useful to scripts that need to identify imported data without
depending only on object names.

## Performance guidance

Full retail maps are large. For faster inspection:

- leave **Maximum LOD Index** at `0`;
- disable overgrowth when vegetation is not needed;
- disable static objects for terrain-only work;
- disable surrounding terrain for playable-area-only work; and
- save the imported result once loading completes so later sessions can open
  the `.blend` directly.

Primary terrain atlas dimensions scale with the map patch count. For example,
a 4x4 map with 512-pixel colormap patches creates a 2048-pixel colormap atlas,
while an 8x8 map creates a 4096-pixel atlas. Two half-resolution RGB mask
atlases are generated as well.

Run the import in Blender's foreground UI when possible. During a large import
the interface may appear idle while archive-backed meshes and textures are
being processed.

## Python API

The operator is available as:

```python
bpy.ops.bf2.level_import(
    filepath=r"F:\Games\Battlefield 2\mods\bf2\Levels\Strike_at_Karkand\client.zip",
    load_static_objects=True,
    load_overgrowth=True,
    load_roads=True,
    load_terrain=True,
    load_surrounding_terrain=True,
    load_water=True,
    load_lights=True,
    max_lod_to_load=0,
)
```

The configured add-on preferences are still used to resolve mod roots and
dependencies.

Internal tools can call `load_level` from
`io_scene_bf2.core.tools.lightmapping.scene`, but that function is an
implementation API and may change between releases.

## Current limitations

The importer does not currently reconstruct:

- gameplay rules and game modes;
- spawn points and control-point behavior;
- AI/navigation data;
- collision-only meshes and occluders as part of level import;
- particle, sound, and effect systems;
- destruction logic;
- terrain lightmaps and the exact camera-distance low-detail transition;
- terrain detail-material environment maps;
- exact Refractor lighting and fog inside the terrain shader;
- sky domes and animated sky layers; or
- Refractor fog volumes.

Use the individual asset importers when collision or occlusion data is needed.
The add-on's lightmapping workflow remains separate from the general visual
map-import workflow.

## Troubleshooting

### The level importer is disabled

Configure at least one game installation or additional mod directory in the
add-on preferences.

### The selected level is rejected

The level must be inside a configured game or mod directory. A packed level
must contain both `client.zip` and `server.zip`; an unpacked level must
contain `Heightdata.con`.

### Objects are missing

Add every dependency mod to the preferences. The importer can resolve only
archives and directories reachable through the configured mod list.

### Surrounding terrain is neutral

Check the import report for missing `Colormaps/tx_s#.dds` warnings. Verify that
the map's client data contains the configured secondary colormaps and that
`Terrain.con` points to the correct colormap base.

### Terrain is present but looks different from the game

Confirm that the primary terrain material has `bf2_terrain_version` and that
the generated `DefaultTerrain_Color`, `DefaultTerrain_Mask1`, and
`DefaultTerrain_Mask2` images are packed. A minimap-only material means the
compiled terrain header or its colormap patches could not be loaded; inspect
the import warnings.

The near detail layers should match the authored material masks, but Blender
will still differ at distance because the game combines component maps,
`LowDetailTexture.dds`, terrain normals, lightmaps, environment maps, lighting,
and fog. The importer intentionally does not display a component map or
low-detail texture as ordinary diffuse color.
