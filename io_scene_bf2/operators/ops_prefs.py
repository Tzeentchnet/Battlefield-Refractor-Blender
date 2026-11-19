import os

import bpy # type: ignore
from bpy.props import StringProperty, CollectionProperty, EnumProperty, IntProperty # type: ignore

from .utils import RegisterFactory
from ..core.game_paths import (
    BF2_GAME,
    BF2142_GAME,
    collect_mod_directories,
    get_game_install_error,
)
from ..core.import_settings import IMPORT_MODE_ITEMS, IMPORT_MODE_OFF
from .. import __package__ as ADDON_PACKAGE

def _absolute_path(path):
    return bpy.path.abspath(path) if path else ""


def get_mod_dirs(context, source_path=""):
    preferences = get_addon_preferences(context)
    game_install_directories = {
        BF2_GAME.identifier: _absolute_path(
            preferences.bf2_install_directory
        ),
        BF2142_GAME.identifier: _absolute_path(
            preferences.bf2142_install_directory
        ),
    }
    additional_mod_directories = [
        _absolute_path(prop.mod_directory)
        for prop in preferences.mod_directories
        if prop.mod_directory
    ]
    return collect_mod_directories(
        game_install_directories,
        additional_mod_directories,
        _absolute_path(source_path),
    )


def get_addon_preferences(context):
    return context.preferences.addons[ADDON_PACKAGE].preferences

class BF2_OT_bf2_mod_path_add(bpy.types.Operator):
    bl_idname = "bf2.mod_path_add"
    bl_label = "Add additional mod directory slot"
    bl_description = "Add a mod directory outside the configured game installations"

    def execute(self, context):
        get_addon_preferences(context).mod_directories.add()
        return {'FINISHED'}

class BF2_OT_bf2_mod_path_remove(bpy.types.Operator):
    bl_idname = "bf2.mod_path_remove"
    bl_label = "Remove additional mod directory slot"
    bl_description = "Removes this mod directory path"

    path_index: IntProperty() # type: ignore

    def execute(self, context):
        get_addon_preferences(context).mod_directories.remove(self.path_index)
        return {'FINISHED'}

class ModPathCollection(bpy.types.PropertyGroup):
    mod_directory: StringProperty (
            name="Additional mod directory",
            subtype="DIR_PATH"
        ) # type: ignore

class BF2AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_PACKAGE

    bf2_install_directory: StringProperty(
        name="Battlefield 2",
        description="Battlefield 2 installation folder",
        subtype="DIR_PATH",
    ) # type: ignore
    bf2142_install_directory: StringProperty(
        name="Battlefield 2142",
        description="Battlefield 2142 installation folder",
        subtype="DIR_PATH",
    ) # type: ignore
    mod_directories: CollectionProperty(type=ModPathCollection) # type: ignore
    import_collision_meshes: EnumProperty(
        name="Import Collision Meshes",
        description="Default behavior for CollisionMeshes referenced by ObjectTemplates",
        items=IMPORT_MODE_ITEMS,
        default=IMPORT_MODE_OFF,
    ) # type: ignore
    import_occluders: EnumProperty(
        name="Import Occluders",
        description="Default behavior for companion occlusion mesh files referenced by ObjectTemplate imports",
        items=IMPORT_MODE_ITEMS,
        default=IMPORT_MODE_OFF,
    ) # type: ignore
    import_lods: EnumProperty(
        name="Import LODs",
        description="Default behavior for LOD1 and lower-detail LODs; Off imports only LOD0",
        items=IMPORT_MODE_ITEMS,
        default=IMPORT_MODE_OFF,
    ) # type: ignore
    import_damage_states: EnumProperty(
        name="Import Damage States",
        description="Default behavior for additional Geoms; Off imports only the primary state",
        items=IMPORT_MODE_ITEMS,
        default=IMPORT_MODE_OFF,
    ) # type: ignore

    @classmethod
    def register(cls):
        debug_set_mod_path()

    def draw(self, context):
        layout = self.layout
        layout.label(text="Game installations")
        installations = layout.box()
        for game, property_name in (
            (BF2_GAME, "bf2_install_directory"),
            (BF2142_GAME, "bf2142_install_directory"),
        ):
            installations.prop(self, property_name)
            install_directory = getattr(self, property_name)
            error = get_game_install_error(
                _absolute_path(install_directory),
                game,
            )
            if error:
                installations.label(text=error, icon='ERROR')

        layout.label(text="Shared import defaults")
        import_defaults = layout.box()
        import_defaults.prop(self, "import_collision_meshes")
        import_defaults.prop(self, "import_occluders")
        import_defaults.prop(self, "import_lods")
        import_defaults.prop(self, "import_damage_states")

        layout.label(text="Additional mod directories")
        for i, prop in enumerate(self.mod_directories):
            row = layout.row()
            row.prop(prop, 'mod_directory', text='', expand=True)
            op = row.operator(BF2_OT_bf2_mod_path_remove.bl_idname, text='', icon='REMOVE')
            op.path_index = i

        row = layout.row()
        row.operator(BF2_OT_bf2_mod_path_add.bl_idname, icon='ADD')

# ----------------------------------------------------------

def is_debug_enabled():
    import sys
    try:
        if sys.gettrace() is not None:
            return True
    except AttributeError:
        pass
    try:
        if sys.monitoring.get_tool(sys.monitoring.DEBUGGER_ID) is not None:
            return True
    except AttributeError:
        pass
    return False

# in debug mode only, having to set this up everytime add-on is reloaded is annoying af
def debug_set_mod_path():
    if not is_debug_enabled():
        return
    prefs = get_addon_preferences(bpy.context)
    bf2_install_directory = r'D:\Battlefield 2'
    if (
        not prefs.bf2_install_directory
        and not get_game_install_error(bf2_install_directory, BF2_GAME)
    ):
        prefs.bf2_install_directory = bf2_install_directory
        print(
            f"DEBUG: Auto-configured Battlefield 2 install "
            f"{bf2_install_directory}"
        )

    if len(prefs.mod_directories) != 0:
        return
    additional_mod_directories = [
        r'D:\Battlefield 2\mods\fh2',
        # r'D:\Project Reality\mods\pr'
    ]
    for path in additional_mod_directories:
        if not os.path.isdir(path):
            continue
        item = prefs.mod_directories.add()
        item.mod_directory = path
        print(f"DEBUG: Auto-configured additional mod path {path}")

# ----------------------------------------------------------

def init(rc : RegisterFactory):
    rc.reg_class(ModPathCollection)
    rc.reg_class(BF2AddonPreferences)
    rc.reg_class(BF2_OT_bf2_mod_path_remove)
    rc.reg_class(BF2_OT_bf2_mod_path_add)

register, unregister = RegisterFactory.create(init)
