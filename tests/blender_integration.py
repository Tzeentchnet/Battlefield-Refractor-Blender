import argparse
from io import BytesIO
from pathlib import Path
import sys
import tempfile

import bpy
import numpy as np


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import io_scene_bf2
from io_scene_bf2.core.collision_mesh import import_collisionmesh
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
    COLLISION_COLLECTION_SUFFIX,
    NONVIS_PRFX,
    OCCLUDER_COLLECTION_SUFFIX,
    import_object_template,
)
from io_scene_bf2.core.utils import convert_to_dds, save_img_as_dds
from io_scene_bf2.core.utils.image import array_to_image, image_to_array
from io_scene_bf2.core.utils.mesh import set_mesh_geometry
from io_scene_bf2.directx.dds import DDSHeader
from io_scene_bf2.operators.ops_prefs import BF2AddonPreferences


def _make_test_pixels():
    pixels = np.zeros((8, 8, 4), dtype=np.float32)
    pixels[:4, :4] = (1.0, 0.0, 0.0, 1.0)
    pixels[:4, 4:] = (0.0, 1.0, 0.0, 0.0)
    pixels[4:, :4] = (0.0, 0.0, 1.0, 0.4)
    pixels[4:, 4:] = (1.0, 1.0, 1.0, 0.8)
    return pixels


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
        _assert_hidden_import_collections(bpy.context)

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
        bpy.data.objects.remove(heightmap, do_unlink=True)

        source = _make_test_pixels()
        image = bpy.data.images.new("DDSIntegrationSource", width=8, height=8, alpha=True)
        array_to_image(image, source)

        with tempfile.TemporaryDirectory() as temporary_dir:
            for compression in ("NONE", "DXT1", "DXT3", "DXT5"):
                filepath = Path(temporary_dir) / f"roundtrip_{compression}.dds"
                save_img_as_dds(image, str(filepath), compression)
                header = DDSHeader.read_from_file(filepath)
                if sum(size for _, _, _, size in header.get_mip_sizes()) != filepath.stat().st_size - 128:
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
