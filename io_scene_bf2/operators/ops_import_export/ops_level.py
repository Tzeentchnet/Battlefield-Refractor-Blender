import os
from pathlib import Path

import bpy  # type: ignore
from bpy.props import BoolProperty, IntProperty, StringProperty  # type: ignore

from ..ops_prefs import get_mod_dirs
from ..utils import RegisterFactory
from ...core.tools.lightmapping.scene import load_level
from ...core.utils import Reporter
from .ops_common import ImporterBase


class IMPORT_OT_bf2_level(bpy.types.Operator, ImporterBase):
    bl_idname = 'bf2.level_import'
    bl_label = 'Import Battlefield Level'
    bl_description = (
        'Import a packed or unpacked Battlefield 2 or Battlefield 2142 level, '
        'including terrain, static objects, overgrowth, compiled roads, '
        'water, and lighting'
    )
    FILE_DESC = 'Level / Map'

    filter_glob: StringProperty(
        default='client.zip;server.zip;*.con',
        options={'HIDDEN'},
    )  # type: ignore

    load_static_objects: BoolProperty(
        name='Static Objects',
        description='Import placements from StaticObjects.con',
        default=True,
    )  # type: ignore

    load_overgrowth: BoolProperty(
        name='Overgrowth',
        description='Import placements from OvergrowthCollision.con',
        default=True,
    )  # type: ignore

    load_roads: BoolProperty(
        name='Compiled Roads',
        description='Import road meshes and materials from CompiledRoads.con',
        default=True,
    )  # type: ignore

    load_terrain: BoolProperty(
        name='Terrain',
        description='Import RAW heightmap terrain',
        default=True,
    )  # type: ignore

    load_surrounding_terrain: BoolProperty(
        name='Surrounding Terrain',
        description='Import all secondary heightmap clusters around the map',
        default=True,
    )  # type: ignore

    load_water: BoolProperty(
        name='Water',
        description='Create the map-wide water plane from level settings',
        default=True,
    )  # type: ignore

    load_lights: BoolProperty(
        name='Lighting',
        description='Import the sun and world lighting from Sky.con',
        default=True,
    )  # type: ignore

    max_lod_to_load: IntProperty(
        name='Maximum LOD Index',
        description=(
            'Highest lower-detail LOD to import; zero imports only the most '
            'detailed representation'
        ),
        default=0,
        min=0,
        max=6,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        cls.poll_message_set(
            'Configure a Battlefield 2 or Battlefield 2142 installation, or '
            'an additional mod directory, in add-on preferences'
        )
        return bool(get_mod_dirs(context))

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'load_static_objects')
        layout.prop(self, 'load_overgrowth')
        layout.prop(self, 'load_roads')
        layout.prop(self, 'max_lod_to_load')
        layout.separator()
        layout.prop(self, 'load_terrain')
        terrain = layout.column()
        terrain.enabled = self.load_terrain
        terrain.prop(self, 'load_surrounding_terrain')
        terrain.prop(self, 'load_water')
        layout.prop(self, 'load_lights')

    def _execute(self, context):
        selected_path = os.path.normpath(self.filepath)
        if os.path.isfile(selected_path):
            level_dir = os.path.dirname(selected_path)
        else:
            level_dir = selected_path
        if not os.path.isdir(level_dir):
            self.abort(
                f"Selected level path '{selected_path}' is not a directory "
                "or a file inside one"
            )

        mod_dirs = get_mod_dirs(context, level_dir)
        if not any(
            Path(level_dir).resolve().is_relative_to(Path(mod_dir).resolve())
            for mod_dir in mod_dirs
        ):
            self.abort(
                f"Level '{level_dir}' is not inside a configured game or mod "
                "directory"
            )

        result = load_level(
            context,
            level_dir,
            load_unpacked=None,
            load_static_objects=self.load_static_objects,
            load_overgrowth=self.load_overgrowth,
            load_heightmap=self.load_terrain,
            load_lights=self.load_lights,
            mod_dirs=mod_dirs,
            max_lod_to_load=self.max_lod_to_load,
            lm_skip_lod0_only=True,
            reporter=Reporter(self.report),
            load_roads=self.load_roads,
            load_all_heightmaps=self.load_surrounding_terrain,
            load_water=self.load_water,
            visual_lighting=True,
            prepare_lightmaps=False,
        )
        self.report(
            {'INFO'},
            (
                f"Imported {result['level_name']}: {result['objects']} object "
                f"placements, {result['roads']} roads, "
                f"{result['terrain_clusters']} terrain clusters"
            ),
        )


def init(rc: RegisterFactory):
    rc.reg_class(IMPORT_OT_bf2_level)


register, unregister = RegisterFactory.create(init)
