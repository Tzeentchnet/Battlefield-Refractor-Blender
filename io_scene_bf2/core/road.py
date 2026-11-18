import os.path as path

import bpy  # type: ignore
import numpy as np

from .bf2.bf2_engine import FileManagerFileNotFound
from .bf2.bf2_road import (
    BF2Road,
    BF2RoadException,
    load_road_material,
)
from .material import load_texture_image
from .utils import DEFAULT_REPORTER, file_name
from .utils.mesh import set_mesh_geometry


def _texture_path(texture):
    return texture if path.splitext(texture)[1] else texture + '.dds'


def _make_road_material(name, road_material, texture_paths,
                        texture_data_loader, reporter):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.use_backface_culling_shadow = True
    material.surface_render_method = 'BLENDED'
    material['bf2_blend_factor'] = road_material.blend_factor
    material['bf2_fade_start'] = road_material.fade_off[0]
    material['bf2_fade_end'] = road_material.fade_off[1]
    material['bf2_priority'] = road_material.priority

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    shader.inputs['Roughness'].default_value = 0.65
    links.new(shader.outputs['BSDF'], output.inputs['Surface'])

    textures = []
    for index, (texture, uv_name) in enumerate((
        (road_material.texture_primary, 'UV0'),
        (road_material.texture_secondary, 'UV1'),
    )):
        uv = nodes.new('ShaderNodeUVMap')
        uv.uv_map = uv_name
        uv.location = (-600, -220 * index)
        texture_node = nodes.new('ShaderNodeTexImage')
        texture_node.location = (-400, -220 * index)
        texture_node.image = load_texture_image(
            _texture_path(texture),
            texture_paths=texture_paths,
            texture_data_loader=texture_data_loader,
        )
        if texture_node.image is None:
            reporter.warning(
                f"Road texture '{texture}' was not found in any texture source"
            )
        else:
            texture_node.image.alpha_mode = (
                'STRAIGHT' if index == 0 else 'NONE'
            )

        vector_output = uv.outputs['UV']
        if index == 0:
            separate = nodes.new('ShaderNodeSeparateXYZ')
            clamp = nodes.new('ShaderNodeClamp')
            clamp.inputs['Min'].default_value = 0.0
            clamp.inputs['Max'].default_value = 1.0
            combine = nodes.new('ShaderNodeCombineXYZ')
            links.new(vector_output, separate.inputs['Vector'])
            links.new(separate.outputs['X'], clamp.inputs['Value'])
            links.new(clamp.outputs['Result'], combine.inputs['X'])
            links.new(separate.outputs['Y'], combine.inputs['Y'])
            vector_output = combine.outputs['Vector']
        else:
            scale = nodes.new('ShaderNodeVectorMath')
            scale.operation = 'SCALE'
            scale.inputs['Scale'].default_value = 0.1
            links.new(vector_output, scale.inputs['Vector'])
            vector_output = scale.outputs['Vector']

        links.new(vector_output, texture_node.inputs['Vector'])
        textures.append(texture_node)

    mix = nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MIX'
    mix.inputs[0].default_value = min(
        max(road_material.blend_factor, 0.0),
        1.0,
    )
    links.new(textures[1].outputs['Color'], mix.inputs[1])
    links.new(textures[0].outputs['Color'], mix.inputs[2])
    links.new(mix.outputs['Color'], shader.inputs['Base Color'])

    vertex_alpha = nodes.new('ShaderNodeAttribute')
    vertex_alpha.attribute_name = 'road_alpha'
    vertex_alpha.attribute_type = 'GEOMETRY'
    texture_alpha = nodes.new('ShaderNodeMath')
    texture_alpha.operation = 'MULTIPLY'
    links.new(textures[0].outputs['Alpha'], texture_alpha.inputs[0])
    links.new(vertex_alpha.outputs['Fac'], texture_alpha.inputs[1])

    alpha_output = texture_alpha.outputs[0]
    fade_start, fade_end = road_material.fade_off
    if fade_end > fade_start:
        camera = nodes.new('ShaderNodeCameraData')
        fade = nodes.new('ShaderNodeMapRange')
        fade.clamp = True
        fade.inputs['From Min'].default_value = fade_start
        fade.inputs['From Max'].default_value = fade_end
        fade.inputs['To Min'].default_value = 1.0
        fade.inputs['To Max'].default_value = 0.0
        links.new(camera.outputs['View Distance'], fade.inputs['Value'])
        faded_alpha = nodes.new('ShaderNodeMath')
        faded_alpha.operation = 'MULTIPLY'
        links.new(alpha_output, faded_alpha.inputs[0])
        links.new(fade.outputs['Result'], faded_alpha.inputs[1])
        alpha_output = faded_alpha.outputs[0]
    links.new(alpha_output, shader.inputs['Alpha'])
    return material


def _load_road_material(file_manager, road_object):
    template = road_object.template
    template_dir = (
        path.dirname(template.location)
        if template.location
        else 'objects/roads/splines'
    )
    geometry_name = template.geom or template.name
    material_path = path.join(
        template_dir,
        f'{geometry_name}_compiled.dat',
    )
    stream = file_manager.readFile(material_path, as_stream=True)
    return material_path, load_road_material(geometry_name, stream)


def import_compiled_roads(context, road_objects, file_manager, collection,
                          matrix_getter, texture_paths=(),
                          texture_data_loader=None, reporter=DEFAULT_REPORTER):
    material_cache = {}
    imported = []

    for road_object in road_objects:
        source_file = road_object.geometry_file
        if not source_file:
            continue
        try:
            stream = file_manager.readFile(source_file, as_stream=True)
            road = BF2Road.load_from(source_file, stream)
        except (FileManagerFileNotFound, BF2RoadException) as exc:
            reporter.error(f"Failed to load compiled road '{source_file}': {exc}")
            continue

        positions = road.positions[:, (0, 2, 1)]
        positions[:, 2] += 0.01
        faces = road.indices.reshape((-1, 3))[:, ::-1]
        mesh_name = file_name(source_file)
        mesh = bpy.data.meshes.new(mesh_name)
        set_mesh_geometry(mesh, positions, faces)

        loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get('vertex_index', loop_vertices)
        for uv_name, source_uvs in (
            ('UV0', road.uv_primary),
            ('UV1', road.uv_secondary),
        ):
            uv_layer = mesh.uv_layers.new(name=uv_name)
            loop_uvs = source_uvs[loop_vertices].copy()
            loop_uvs[:, 1] = 1.0 - loop_uvs[:, 1]
            uv_layer.data.foreach_set('uv', loop_uvs.ravel())

        alpha = mesh.attributes.new(
            name='road_alpha',
            type='FLOAT',
            domain='POINT',
        )
        alpha.data.foreach_set(
            'value',
            np.clip(road.alpha, 0.0, 1.0),
        )
        if len(mesh.polygons):
            mesh.polygons.foreach_set(
                'use_smooth',
                np.ones(len(mesh.polygons), dtype=np.bool_),
            )

        try:
            material_path, road_material = _load_road_material(
                file_manager,
                road_object,
            )
            material = material_cache.get(material_path.lower())
            if material is None:
                material = _make_road_material(
                    f'{road_object.template.name}_road',
                    road_material,
                    texture_paths,
                    texture_data_loader,
                    reporter,
                )
                material_cache[material_path.lower()] = material
            mesh.materials.append(material)
        except (FileManagerFileNotFound, BF2RoadException) as exc:
            reporter.warning(
                f"Compiled road '{source_file}' has no usable material: {exc}"
            )

        obj = bpy.data.objects.new(mesh_name, mesh)
        collection.objects.link(obj)
        obj.matrix_world = matrix_getter(road_object)
        obj['bf2_source_mesh'] = source_file
        obj['bf2_road_template'] = road_object.template.name
        obj['bf2_road_version'] = f'{road.version[0]}.{road.version[1]}'
        obj['bf2_road_order'] = road.order
        obj['bf2_road_radius'] = road.radius
        obj['bf2_vertical_offset'] = 0.01
        imported.append(obj)

    return imported
