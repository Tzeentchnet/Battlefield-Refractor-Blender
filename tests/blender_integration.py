import argparse
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import struct

import bpy
from mathutils import Matrix
import numpy as np


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import io_scene_bf2
from io_scene_bf2.core.collision_mesh import import_collisionmesh
from io_scene_bf2.core.bf2.bf2_engine import BF2Engine
from io_scene_bf2.core.bf2.bf2_terrain import (
    BF2Terrain,
    BF2TerrainMaterial,
)
from io_scene_bf2.core.heightmap import import_heightmap_from
from io_scene_bf2.core.import_settings import IMPORT_MODE_HIDDEN, IMPORT_MODE_OFF
from io_scene_bf2.core.mesh import (
    DAMAGE_STATE_COLLECTION_SUFFIX,
    LOD_COLLECTION_SUFFIX,
    import_bundledmesh,
    import_staticmesh,
    organize_mesh_hierarchy,
)
from io_scene_bf2.core.object_template import (
    BUNDLE_BONE_INDEX_PROPERTY,
    BUNDLE_SKELETON_CONSTRAINT,
    BUNDLE_SKELETON_PROPERTY,
    COLLISION_COLLECTION_SUFFIX,
    GeomPartInfo,
    NONVIS_PRFX,
    OCCLUDER_COLLECTION_SUFFIX,
    _apply_bundle_skeleton_constraints,
    _create_object_template,
    import_object_template,
)
from io_scene_bf2.core.road import import_compiled_roads
from io_scene_bf2.core.terrain import make_primary_terrain_material
from io_scene_bf2.core.utils import convert_to_dds, save_img_as_dds
from io_scene_bf2.core.utils.image import array_to_image, image_to_array
from io_scene_bf2.core.utils.mesh import set_mesh_geometry
from io_scene_bf2.core.tools.lightmapping.scene import (
    SECONDARY_TERRAIN_COLORMAP_INDEX,
)
from io_scene_bf2.directx.dds_encoder import save_dds
from io_scene_bf2.operators.ops_prefs import BF2AddonPreferences


def _make_test_pixels():
    pixels = np.zeros((8, 8, 4), dtype=np.float32)
    pixels[:4, :4] = (1.0, 0.0, 0.0, 1.0)
    pixels[:4, 4:] = (0.0, 1.0, 0.0, 0.0)
    pixels[4:, :4] = (0.0, 0.0, 1.0, 0.4)
    pixels[4:, 4:] = (1.0, 1.0, 1.0, 0.8)
    return pixels


def _dds_payload_size(filepath, compression):
    with open(filepath, "rb") as dds_file:
        header = dds_file.read(128)
    if len(header) != 128 or header[:4] != b"DDS ":
        raise AssertionError(f"{compression}: invalid legacy DDS header")

    height, width = struct.unpack_from("<II", header, 12)
    mipmap_count = max(1, struct.unpack_from("<I", header, 28)[0])
    block_size = {"DXT1": 8, "DXT3": 16, "DXT5": 16}.get(compression)

    payload_size = 0
    for _ in range(mipmap_count):
        if block_size is None:
            payload_size += width * height * 4
        else:
            payload_size += max(1, (width + 3) // 4) * max(
                1,
                (height + 3) // 4,
            ) * block_size
        width = max(1, width // 2)
        height = max(1, height // 2)
    return payload_size


def _road_bytes():
    data = bytearray()
    data.extend(struct.pack("<HH", 4, 1))
    data.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
    data.extend(struct.pack("<f", 1.0))
    data.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
    data.extend(struct.pack("<3f", 1.0, 1.0, 0.0))
    data.extend(struct.pack("<iI", 0, 3))
    data.extend(
        np.asarray(
            (
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.2, 0.5),
                (1.0, 0.0, 0.0, 1.0, 0.0, 1.1, 0.2, 0.75),
                (0.0, 1.0, 0.0, 0.0, 1.0, 0.1, 1.2, 1.0),
            ),
            dtype="<f4",
        ).tobytes()
    )
    data.extend(struct.pack("<I3H", 3, 0, 1, 2))
    data.extend(struct.pack("<I", 0))
    return bytes(data)


class _MemoryFileManager:
    def __init__(self, files):
        self.files = {
            name.replace("\\", "/").lower(): data
            for name, data in files.items()
        }

    def readFile(self, filename, as_stream=False):
        data = self.files[filename.replace("\\", "/").lower()]
        return BytesIO(data) if as_stream else data


def _assert_road_import(temporary_dir, pixels):
    for name in ("primary", "secondary"):
        save_dds(
            str(Path(temporary_dir) / f"{name}.dds"),
            pixels,
            compression="DXT5",
        )
    material_data = (
        b"primary\nsecondary\n"
        + struct.pack("<3fI", 0.85, 200.0, 300.0, 1)
    )
    file_manager = _MemoryFileManager(
        {
            "Levels/Test/Roads/test.mesh": _road_bytes(),
            "objects/roads/splines/highway_compiled.dat": material_data,
        }
    )
    road_object = SimpleNamespace(
        geometry_file="Levels/Test/Roads/test.mesh",
        template=SimpleNamespace(
            location="objects/roads/splines/highway.con",
            geom="highway",
            name="highway",
        ),
    )
    collection = bpy.data.collections.new("RoadIntegration")
    bpy.context.scene.collection.children.link(collection)
    roads = import_compiled_roads(
        bpy.context,
        (road_object,),
        file_manager,
        collection,
        lambda _road: Matrix.Identity(4),
        texture_paths=(temporary_dir,),
    )
    if len(roads) != 1:
        raise AssertionError("Synthetic compiled road was not imported")
    road = roads[0]
    if not np.allclose(
        [vertex.co.z for vertex in road.data.vertices],
        (0.01, 0.01, 1.01),
    ):
        raise AssertionError("Compiled road did not receive the 1 cm lift")
    if road.get("bf2_vertical_offset") != 0.01:
        raise AssertionError("Compiled road offset metadata is missing")

    material = road.data.materials[0]
    if material.surface_render_method != "BLENDED":
        raise AssertionError("Compiled road is not using alpha blending")
    texture_nodes = {
        node.image.name: node
        for node in material.node_tree.nodes
        if node.type == "TEX_IMAGE" and node.image
    }
    primary = texture_nodes["primary.dds"]
    secondary = texture_nodes["secondary.dds"]
    mix = next(
        node for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeMixRGB"
    )
    color_sources = {
        link.to_socket: link.from_node
        for link in material.node_tree.links
        if link.to_node == mix
    }
    if (
        color_sources.get(mix.inputs[1]) != secondary
        or color_sources.get(mix.inputs[2]) != primary
    ):
        raise AssertionError("Compiled road texture blend order is reversed")
    if primary.image.alpha_mode != "STRAIGHT":
        raise AssertionError("Compiled road primary alpha is disabled")
    if not any(
        node.bl_idname == "ShaderNodeVectorMath"
        and node.operation == "SCALE"
        and np.isclose(node.inputs["Scale"].default_value, 0.1)
        for node in material.node_tree.nodes
    ):
        raise AssertionError("Compiled road secondary UV scale is missing")
    if not any(
        link.from_node == primary
        and link.from_socket == primary.outputs["Alpha"]
        for link in material.node_tree.links
    ):
        raise AssertionError("Compiled road primary texture alpha is unused")

    bpy.data.objects.remove(road, do_unlink=True)
    bpy.data.collections.remove(collection)


def _assert_detailed_terrain_material(temporary_dir):
    temporary_dir = Path(temporary_dir)
    color = np.full((8, 8, 4), (0.4, 0.3, 0.2, 1.0), dtype=np.float32)
    mask1 = np.zeros((4, 4, 4), dtype=np.float32)
    mask1[:, :, 0] = 1.0
    mask1[:, :, 3] = 1.0
    mask2 = np.zeros((4, 4, 4), dtype=np.float32)
    mask2[:, :, 3] = 1.0
    detail = np.full((8, 8, 4), (0.6, 0.5, 0.4, 1.0), dtype=np.float32)
    for filename, image in (
        ("color_00x00.dds", color),
        ("mask_00x00_1.dds", mask1),
        ("mask_00x00_2.dds", mask2),
        ("overview.dds", color),
        ("detail.dds", detail),
        ("detail_side.dds", detail),
    ):
        save_dds(
            str(temporary_dir / filename),
            image,
            compression="NONE",
        )

    terrain = BF2Terrain(
        version=0x1001A,
        primary_world_scale=(2.0, 2.0, 0.1),
        secondary_world_scale=(2.0, 2.0, 0.1),
        lowest_height=0.0,
        highest_height=100.0,
        patch_size=4,
        subdivide_patches=False,
        patches_per_side=1,
        patch_colormap_size=8,
        low_detailmap_size=4,
        colormap_base_name="color_",
        detailmap_base_name="mask_",
        low_detailmap_base_name="low_",
        lightmap_base_name="light_",
        far_side_tiling=(2.0, 2.0),
        far_top_tiling_hi=4.0,
        far_top_tiling_low=2.0,
        far_y_offset=0.0,
        sun_color=(1.0, 1.0, 1.0),
        gi_color=(0.2, 0.2, 0.2),
        water_color=(0.1, 0.2, 0.3),
        materials=(
            BF2TerrainMaterial(
                texture="detail",
                tri_planar=True,
                side_tiling=(2.0, 4.0),
                top_tiling=8.0,
                y_offset=0.0,
                environment_map=False,
            ),
        ),
    )
    material = make_primary_terrain_material(
        "TerrainIntegration",
        terrain,
        str(temporary_dir / "overview.dds"),
        texture_paths=(str(temporary_dir),),
    )
    if material is None:
        raise AssertionError("Detailed terrain material was not created")
    if material.get("bf2_terrain_version") != terrain.version:
        raise AssertionError("Detailed terrain metadata is missing")
    generated = [
        node.image
        for node in material.node_tree.nodes
        if node.type == "TEX_IMAGE"
        and node.image
        and node.image.get("bf2_generated_texture")
    ]
    if len(generated) != 3 or not all(
        image.packed_file is not None for image in generated
    ):
        raise AssertionError("Generated terrain atlases are not packed")
    if not any(
        image.colorspace_settings.name == "Non-Color"
        and image.get("bf2_generated_texture", "").endswith(("Mask1", "Mask2"))
        for image in generated
    ):
        raise AssertionError("Terrain material masks are not non-color data")
    if not any(
        node.type == "NEW_GEOMETRY"
        for node in material.node_tree.nodes
    ):
        raise AssertionError("Tri-planar terrain projection is missing")


def _assert_roundtrip(source, loaded, compression):
    if source.shape != loaded.shape:
        raise AssertionError(
            f"{compression}: shape changed from {source.shape} to {loaded.shape}"
        )

    color_delta = np.abs(source[:, :, :3] - loaded[:, :, :3])
    if compression == "DXT1":
        color_delta = color_delta[source[:, :, 3] >= 0.5]
    color_error = np.max(color_delta)
    color_tolerance = 1.0 / 255.0 if compression == "NONE" else 0.04
    if color_error > color_tolerance:
        raise AssertionError(
            f"{compression}: maximum color error {color_error:.6f} exceeds "
            f"{color_tolerance:.6f}"
        )

    if compression == "DXT1":
        expected_alpha = (source[:, :, 3] >= 0.5).astype(np.float32)
        alpha_tolerance = 0.0
    else:
        expected_alpha = source[:, :, 3]
        alpha_tolerance = 1.0 / 15.0 if compression == "DXT3" else 0.02
    alpha_error = np.max(np.abs(expected_alpha - loaded[:, :, 3]))
    if alpha_error > alpha_tolerance + 1e-6:
        raise AssertionError(
            f"{compression}: maximum alpha error {alpha_error:.6f} exceeds "
            f"{alpha_tolerance:.6f}"
        )


def _assert_import_preferences():
    install_directories = tuple(
        BF2AddonPreferences.bl_rna.properties[name].default
        for name in (
            "bf2_install_directory",
            "bf2142_install_directory",
        )
    )
    if install_directories != ("", ""):
        raise AssertionError(
            f"Unexpected game install defaults: {install_directories}"
        )

    modes = tuple(
        BF2AddonPreferences.bl_rna.properties[name].default
        for name in (
            "import_collision_meshes",
            "import_occluders",
            "import_lods",
            "import_damage_states",
        )
    )
    if modes != (IMPORT_MODE_OFF,) * 4:
        raise AssertionError(f"Unexpected import preference defaults: {modes}")


def _assert_terrain_settings():
    engine = BF2Engine()
    commands = (
        "Terrain.patchSize 128",
        "Terrain.subdividePatches 1",
        "Terrain.primaryWorldScale 2/0.00457764/2",
        "Terrain.secondaryWorldScale 4/1.17188/4",
        "Terrain.patchColormapSize 512",
        "Terrain.lowDetailmapSize 512",
        "Terrain.detailmapBaseName Levels/Test/Detailmaps/tx",
        "Terrain.lowDetailmapBaseName Levels/Test/LowDetailmaps/tx",
        "Terrain.colormapBaseName Levels/Test/Colormaps/tx",
        "Terrain.lightmapBaseName Levels/Test/Lightmaps/tx",
        "Terrain.farSideTiling 5/5",
        "Terrain.farTopTilingHi 24",
        "Terrain.farTopTilingLow 4",
        "Terrain.farYOffset 0",
        "Terrain.init",
    )
    for command in commands:
        engine.main_console.exec(command)

    terrain = engine.terrain_settings
    if (
        terrain.patch_size,
        terrain.subdivide_patches,
        terrain.primary_world_scale,
        terrain.secondary_world_scale,
        terrain.patch_colormap_size,
        terrain.low_detailmap_size,
        terrain.colormap_base_name,
        terrain.far_side_tiling,
        terrain.far_top_tiling_hi,
        terrain.far_top_tiling_low,
        terrain.far_y_offset,
    ) != (
        128,
        True,
        (2.0, 0.00457764, 2.0),
        (4.0, 1.17188, 4.0),
        512,
        512,
        "Levels/Test/Colormaps/tx",
        (5.0, 5.0),
        24.0,
        4.0,
        0.0,
    ):
        raise AssertionError("Terrain.con settings were not parsed correctly")

    expected_colormaps = {
        (-1, -1): 0,
        (0, -1): 1,
        (1, -1): 2,
        (-1, 0): 3,
        (1, 0): 4,
        (-1, 1): 5,
        (0, 1): 6,
        (1, 1): 7,
    }
    if SECONDARY_TERRAIN_COLORMAP_INDEX != expected_colormaps:
        raise AssertionError("Secondary-terrain colormap ordering changed")


def _assert_hidden_import_collections(context):
    root = bpy.data.objects.new("ImportPolicyIntegration", None)
    geom0 = bpy.data.objects.new("G0__ImportPolicyIntegration", None)
    geom1 = bpy.data.objects.new("G1__ImportPolicyIntegration", None)
    lod00 = bpy.data.objects.new("G0L0__ImportPolicyIntegration", None)
    lod01 = bpy.data.objects.new("G0L1__ImportPolicyIntegration", None)
    lod10 = bpy.data.objects.new("G1L0__ImportPolicyIntegration", None)
    lod11 = bpy.data.objects.new("G1L1__ImportPolicyIntegration", None)
    objects = (root, geom0, geom1, lod00, lod01, lod10, lod11)

    for obj in objects:
        context.scene.collection.objects.link(obj)
    geom0.parent = root
    geom1.parent = root
    lod00.parent = geom0
    lod01.parent = geom0
    lod10.parent = geom1
    lod11.parent = geom1

    organize_mesh_hierarchy(
        context,
        root,
        root.name,
        lod_mode=IMPORT_MODE_HIDDEN,
        damage_state_mode=IMPORT_MODE_HIDDEN,
    )

    lod_collection = bpy.data.collections.get(root.name + LOD_COLLECTION_SUFFIX)
    damage_collection = bpy.data.collections.get(
        root.name + DAMAGE_STATE_COLLECTION_SUFFIX
    )
    if lod_collection is None or damage_collection is None:
        raise AssertionError("Hidden import collections were not created")
    if not all(
        (
            lod_collection.hide_viewport,
            lod_collection.hide_render,
            damage_collection.hide_viewport,
            damage_collection.hide_render,
        )
    ):
        raise AssertionError("Hidden import collection visibility is enabled")
    if lod01.users_collection[:] != (lod_collection,):
        raise AssertionError("Secondary LOD was not moved to the LOD collection")
    if geom1.users_collection[:] != (damage_collection,):
        raise AssertionError("Damage-state Geom was not moved to its collection")
    if lod10.users_collection[:] != (damage_collection,):
        raise AssertionError("Damage-state hierarchy was not kept together")
    if lod11.users_collection[:] != (lod_collection,):
        raise AssertionError(
            "Lower damage-state LOD was not kept independently controllable"
        )
    if lod00.users_collection[:] != (context.scene.collection,):
        raise AssertionError("Primary LOD was moved out of the scene collection")

    for obj in reversed(objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(lod_collection)
    bpy.data.collections.remove(damage_collection)


def _assert_bundle_skeleton_constraints(context):
    armature = bpy.data.armatures.new("BundleSkeletonIntegration")
    rig = bpy.data.objects.new("BundleSkeletonIntegration", armature)
    context.scene.collection.objects.link(rig)
    rig["bf2_bones"] = ["root", "leg"]
    context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    root_bone = armature.edit_bones.new("root")
    root_bone.head = (0.0, 0.0, 0.0)
    root_bone.tail = (0.0, 0.0, 1.0)
    leg_bone = armature.edit_bones.new("leg")
    leg_bone.head = (0.5, 0.0, 0.5)
    leg_bone.tail = (0.5, 0.0, -0.5)
    leg_bone.parent = root_bone
    bpy.ops.object.mode_set(mode="OBJECT")

    hierarchy_root = bpy.data.objects.new("BundleHierarchyIntegration", None)
    part = bpy.data.objects.new("G0L0__BundlePartIntegration", None)
    child = bpy.data.objects.new("BundleChildIntegration", None)
    for obj in (hierarchy_root, part, child):
        context.scene.collection.objects.link(obj)
    part.parent = hierarchy_root
    part.location = (0.5, 0.0, 0.5)
    child.parent = part
    child.location = (0.0, 0.0, -0.5)
    context.view_layer.update()

    part_bind_matrix = part.matrix_world.copy()
    child_bind_matrix = child.matrix_world.copy()
    _apply_bundle_skeleton_constraints(
        rig,
        ((part, 1),),
        SimpleNamespace(warning=lambda _message: None),
    )
    context.view_layer.update()
    if not np.allclose(part.matrix_world, part_bind_matrix, atol=1e-6):
        raise AssertionError("Bundle skeleton constraint changed the bind pose")
    constraint = part.constraints.get(BUNDLE_SKELETON_CONSTRAINT)
    if (
        constraint is None
        or constraint.target != rig
        or constraint.subtarget != "leg"
    ):
        raise AssertionError("Bundle skeleton constraint target is incorrect")

    part.bf2_object_type = "SimpleObject"
    part[BUNDLE_SKELETON_PROPERTY] = "BundleSkeletonIntegration.ske"
    part[BUNDLE_BONE_INDEX_PROPERTY] = 1
    exported_template = _create_object_template(
        GeomPartInfo(0, True, part),
        {},
    )
    if (
        exported_template.bundle_skeleton
        != "BundleSkeletonIntegration.ske"
        or exported_template.bone_index != 1
    ):
        raise AssertionError("Bundle skeleton export metadata was not preserved")

    pose_bone = rig.pose.bones["leg"]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler.y = 0.5
    context.view_layer.update()
    if np.allclose(part.matrix_world, part_bind_matrix, atol=1e-4):
        raise AssertionError("Bundle skeleton part did not follow its bone")
    if np.allclose(child.matrix_world, child_bind_matrix, atol=1e-4):
        raise AssertionError("Bundle skeleton child hierarchy did not follow its part")

    for obj in (child, part, hierarchy_root, rig):
        bpy.data.objects.remove(obj, do_unlink=True)


def _assert_hidden_object_template_import(context, con_filepath):
    root = import_object_template(
        context,
        str(con_filepath),
        collision_mesh_mode=IMPORT_MODE_HIDDEN,
        occluder_mode=IMPORT_MODE_HIDDEN,
        lod_mode=IMPORT_MODE_HIDDEN,
        damage_state_mode=IMPORT_MODE_HIDDEN,
        import_rig_mode="OFF",
        silent=True,
    )

    collision_collection = bpy.data.collections.get(
        root.name.removeprefix("StaticMesh_") + COLLISION_COLLECTION_SUFFIX
    )
    if collision_collection is None:
        raise AssertionError("Hidden ObjectTemplate CollisionMesh collection is missing")
    if not collision_collection.hide_viewport or not collision_collection.hide_render:
        raise AssertionError("CollisionMesh collection is visible")
    if not any(
        obj.name.startswith(NONVIS_PRFX)
        for obj in collision_collection.objects
    ):
        raise AssertionError("CollisionMesh hierarchy was not moved to its collection")

    occluder_collection = bpy.data.collections.get(
        root.name.removeprefix("StaticMesh_") + OCCLUDER_COLLECTION_SUFFIX
    )
    if occluder_collection is None:
        raise AssertionError("Hidden ObjectTemplate occluder collection is missing")
    if not occluder_collection.hide_viewport or not occluder_collection.hide_render:
        raise AssertionError("Occluder collection is visible")
    if not any(obj.type == "MESH" for obj in occluder_collection.objects):
        raise AssertionError("Companion occluder was not imported")

    lod_collections = [
        collection
        for collection in bpy.data.collections
        if collection.name.endswith(LOD_COLLECTION_SUFFIX)
    ]
    if not lod_collections:
        raise AssertionError("ObjectTemplate lower LOD collection is missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dds", type=Path)
    parser.add_argument("--game-staticmesh", type=Path)
    parser.add_argument("--game-bundledmesh", type=Path)
    parser.add_argument("--game-collisionmesh", type=Path)
    parser.add_argument("--game-object-template", type=Path)
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    io_scene_bf2.register()
    try:
        _assert_import_preferences()
        _assert_terrain_settings()
        _assert_hidden_import_collections(bpy.context)
        _assert_bundle_skeleton_constraints(bpy.context)

        mesh = bpy.data.meshes.new("BatchGeometryIntegration")
        set_mesh_geometry(
            mesh,
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ),
            ((0, 1, 2), (0, 2, 3)),
        )
        if (len(mesh.vertices), len(mesh.edges), len(mesh.polygons)) != (4, 5, 2):
            raise AssertionError("Blender mesh batch creation returned unexpected geometry")
        bpy.data.meshes.remove(mesh)

        heightmap = import_heightmap_from(
            bpy.context,
            BytesIO(np.arange(16, dtype="<u2").tobytes()),
            "HeightmapIntegration",
            bit_res=16,
        )
        if (
            len(heightmap.data.vertices),
            len(heightmap.data.polygons),
            len(heightmap.data.uv_layers["UVMap"].data),
        ) != (16, 18, 54):
            raise AssertionError("NumPy heightmap import returned unexpected geometry")
        if [
            tuple(polygon.vertices)
            for polygon in heightmap.data.polygons[:4]
        ] != [
            (1, 0, 4),
            (5, 1, 4),
            (5, 4, 8),
            (9, 5, 8),
        ]:
            raise AssertionError("Heightmap does not use BF2's fixed diagonal")
        bpy.data.objects.remove(heightmap, do_unlink=True)

        source = _make_test_pixels()
        image = bpy.data.images.new("DDSIntegrationSource", width=8, height=8, alpha=True)
        array_to_image(image, source)

        with tempfile.TemporaryDirectory() as temporary_dir:
            _assert_road_import(temporary_dir, source)
            _assert_detailed_terrain_material(temporary_dir)
            for compression in ("NONE", "DXT1", "DXT3", "DXT5"):
                filepath = Path(temporary_dir) / f"roundtrip_{compression}.dds"
                save_img_as_dds(image, str(filepath), compression)
                if _dds_payload_size(filepath, compression) != filepath.stat().st_size - 128:
                    raise AssertionError(f"{compression}: DDS mip sizes do not match the payload")

                loaded_image = bpy.data.images.load(str(filepath), check_existing=False)
                try:
                    loaded_image.colorspace_settings.name = "Non-Color"
                    loaded = image_to_array(loaded_image)
                    _assert_roundtrip(source, loaded, compression)
                finally:
                    bpy.data.images.remove(loaded_image)

            tga_path = Path(temporary_dir) / "file_conversion.tga"
            image.file_format = "TARGA"
            image.filepath_raw = str(tga_path)
            image.save(filepath=str(tga_path))
            convert_to_dds(str(tga_path), temporary_dir, "DXT5")
            if not (Path(temporary_dir) / "file_conversion.dds").is_file():
                raise AssertionError("File-based DDS conversion did not create output")

        if arguments.game_dds:
            game_image = bpy.data.images.load(str(arguments.game_dds), check_existing=False)
            try:
                if min(game_image.size) <= 0:
                    raise AssertionError(
                        f"Failed to load Battlefield 2 DDS: {arguments.game_dds}"
                    )
            finally:
                bpy.data.images.remove(game_image)

        if arguments.game_staticmesh:
            root = import_staticmesh(
                bpy.context,
                str(arguments.game_staticmesh),
                silent=True,
            )
            imported_meshes = [
                child.data
                for child in root.children_recursive
                if child.type == "MESH"
            ]
            if not imported_meshes or not any(mesh.polygons for mesh in imported_meshes):
                raise AssertionError(
                    f"Failed to import Battlefield 2 StaticMesh: {arguments.game_staticmesh}"
                )
            if not any(len(geom.children) > 1 for geom in root.children):
                raise AssertionError(
                    "ON import policy did not preserve lower StaticMesh LODs"
                )

            lod0_root = import_staticmesh(
                bpy.context,
                str(arguments.game_staticmesh),
                name="ImportPolicyLod0",
                lod_mode=IMPORT_MODE_OFF,
                damage_state_mode=IMPORT_MODE_OFF,
                silent=True,
            )
            if len(lod0_root.children) != 1 or len(lod0_root.children[0].children) != 1:
                raise AssertionError(
                    "OFF import policy did not limit the StaticMesh to Geom0/LOD0"
                )

        if arguments.game_bundledmesh:
            bundled_root = import_bundledmesh(
                bpy.context,
                str(arguments.game_bundledmesh),
                name="ImportPolicyBundledHidden",
                lod_mode=IMPORT_MODE_HIDDEN,
                damage_state_mode=IMPORT_MODE_HIDDEN,
                silent=True,
            )
            if len(bundled_root.children) < 2:
                raise AssertionError(
                    "Real BundledMesh fixture does not contain additional Geoms"
                )
            if bpy.data.collections.get(
                bundled_root.name + DAMAGE_STATE_COLLECTION_SUFFIX
            ) is None:
                raise AssertionError(
                    "HIDDEN import policy did not create a damage-state collection"
                )
            if bpy.data.collections.get(
                bundled_root.name + LOD_COLLECTION_SUFFIX
            ) is None:
                raise AssertionError(
                    "HIDDEN import policy did not create a lower-LOD collection"
                )

        if arguments.game_collisionmesh:
            root = import_collisionmesh(
                bpy.context,
                str(arguments.game_collisionmesh),
            )
            imported_meshes = [
                child.data
                for child in root.children_recursive
                if child.type == "MESH"
            ]
            if not imported_meshes or not any(mesh.polygons for mesh in imported_meshes):
                raise AssertionError(
                    "Failed to import Battlefield 2 CollisionMesh: "
                    f"{arguments.game_collisionmesh}"
                )

        if arguments.game_object_template:
            _assert_hidden_object_template_import(
                bpy.context,
                arguments.game_object_template,
            )

        bpy.data.images.remove(image)
    finally:
        io_scene_bf2.unregister()

    print("BF2_BLENDER_INTEGRATION_OK")


if __name__ == "__main__":
    main()
