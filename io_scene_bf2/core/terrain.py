import hashlib
import os
import os.path as path

import bpy  # type: ignore
import numpy as np

from ..directx.dds_encoder import save_dds
from .material import get_texture_cache_dir, load_texture_image
from .utils import DEFAULT_REPORTER
from .utils.image import image_to_array


def _texture_path(texture):
    return texture if path.splitext(texture)[1] else texture + '.dds'


def _load_texture_pixels(texture_file, texture_paths, texture_data_loader):
    image = load_texture_image(
        texture_file,
        texture_paths=texture_paths,
        texture_data_loader=texture_data_loader,
    )
    if image is None:
        return None

    original_color_space = image.colorspace_settings.name
    try:
        image.colorspace_settings.name = 'Non-Color'
        pixels = image_to_array(image).copy()
    finally:
        if image.users == 0:
            bpy.data.images.remove(image)
        else:
            image.colorspace_settings.name = original_color_space
    return pixels


def _resize_pixels(pixels, target_size):
    height, width, _ = pixels.shape
    if (width, height) == (target_size, target_size):
        return pixels

    source_x = np.linspace(0.0, width - 1, target_size)
    source_y = np.linspace(0.0, height - 1, target_size)
    x0 = np.floor(source_x).astype(np.int32)
    y0 = np.floor(source_y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    x_factor = (source_x - x0)[np.newaxis, :, np.newaxis]
    y_factor = (source_y - y0)[:, np.newaxis, np.newaxis]

    top = (
        pixels[y0[:, np.newaxis], x0[np.newaxis, :]]
        * (1.0 - x_factor)
        + pixels[y0[:, np.newaxis], x1[np.newaxis, :]] * x_factor
    )
    bottom = (
        pixels[y1[:, np.newaxis], x0[np.newaxis, :]]
        * (1.0 - x_factor)
        + pixels[y1[:, np.newaxis], x1[np.newaxis, :]] * x_factor
    )
    return top * (1.0 - y_factor) + bottom * y_factor


def _minimap_fallback_tile(minimap, column, row, patches_per_side,
                           target_size):
    height, width, _ = minimap.shape
    x0 = round(column * width / patches_per_side)
    x1 = round((column + 1) * width / patches_per_side)
    y0 = round(row * height / patches_per_side)
    y1 = round((row + 1) * height / patches_per_side)
    return _resize_pixels(minimap[y0:y1, x0:x1], target_size)


def _build_terrain_atlas(name, base_name, patches_per_side, tile_size,
                         suffix, compression, texture_paths,
                         texture_data_loader, color_space,
                         fallback_texture=None, reporter=DEFAULT_REPORTER):
    atlas_size = patches_per_side * tile_size
    atlas = np.zeros((atlas_size, atlas_size, 4), dtype=np.float32)
    atlas[:, :, 3] = 1.0
    fallback = None
    missing_tiles = []
    loaded_tile_count = 0

    for row in range(patches_per_side):
        for column in range(patches_per_side):
            texture_file = (
                f'{base_name}{column:02d}x{row:02d}{suffix}.dds'
            )
            tile = _load_texture_pixels(
                texture_file,
                texture_paths,
                texture_data_loader,
            )
            if tile is None:
                missing_tiles.append((column, row))
                if fallback_texture:
                    if fallback is None:
                        fallback = _load_texture_pixels(
                            fallback_texture,
                            texture_paths,
                            texture_data_loader,
                        )
                    if fallback is not None:
                        tile = _minimap_fallback_tile(
                            fallback,
                            column,
                            row,
                            patches_per_side,
                            tile_size,
                        )
            else:
                loaded_tile_count += 1

            if tile is None:
                continue
            tile = _resize_pixels(tile, tile_size)
            y0 = row * tile_size
            x0 = column * tile_size
            atlas[y0:y0 + tile_size, x0:x0 + tile_size] = tile

    if loaded_tile_count == 0:
        return None

    if missing_tiles and fallback_texture:
        reporter.warning(
            f"Terrain atlas '{name}' is missing {len(missing_tiles)} source "
            'tiles; the map overview texture fills those regions'
        )

    digest = hashlib.sha256()
    digest.update(name.encode('utf-8'))
    digest.update(memoryview(atlas))
    digest = digest.hexdigest()[:20]
    cache_dir = get_texture_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = path.join(cache_dir, f'{digest}_{name}.dds')
    if not path.isfile(cache_path):
        save_dds(cache_path, atlas, compression=compression)

    image = bpy.data.images.load(cache_path, check_existing=True)
    image.pack()
    image.name = f'{name}.dds'
    image.alpha_mode = 'NONE'
    image.colorspace_settings.name = color_space
    image['bf2_generated_texture'] = name
    image['bf2_generated_hash'] = digest
    image['bf2_source_base'] = base_name
    image['bf2_missing_tile_count'] = len(missing_tiles)
    return image


def _image_node(nodes, image, label, location):
    node = nodes.new('ShaderNodeTexImage')
    node.image = image
    node.label = label
    node.extension = 'REPEAT'
    node.location = location
    return node


def _scaled_uv(node_tree, uv_output, scale, location):
    node = node_tree.nodes.new('ShaderNodeVectorMath')
    node.operation = 'SCALE'
    node.inputs['Scale'].default_value = scale
    node.location = location
    node_tree.links.new(uv_output, node.inputs['Vector'])
    return node.outputs['Vector']


def _normal_weights(node_tree, geometry):
    separate = node_tree.nodes.new('ShaderNodeSeparateXYZ')
    node_tree.links.new(geometry.outputs['Normal'], separate.inputs['Vector'])
    absolute = []
    for output in ('X', 'Y', 'Z'):
        node = node_tree.nodes.new('ShaderNodeMath')
        node.operation = 'ABSOLUTE'
        node_tree.links.new(separate.outputs[output], node.inputs[0])
        absolute.append(node)

    sum_xy = node_tree.nodes.new('ShaderNodeMath')
    sum_xy.operation = 'ADD'
    node_tree.links.new(absolute[0].outputs[0], sum_xy.inputs[0])
    node_tree.links.new(absolute[1].outputs[0], sum_xy.inputs[1])
    total = node_tree.nodes.new('ShaderNodeMath')
    total.operation = 'ADD'
    node_tree.links.new(sum_xy.outputs[0], total.inputs[0])
    node_tree.links.new(absolute[2].outputs[0], total.inputs[1])

    weights = []
    for node in absolute:
        divide = node_tree.nodes.new('ShaderNodeMath')
        divide.operation = 'DIVIDE'
        node_tree.links.new(node.outputs[0], divide.inputs[0])
        node_tree.links.new(total.outputs[0], divide.inputs[1])
        weights.append(divide.outputs[0])
    return weights


def _side_projection(node_tree, position, horizontal_axis,
                     horizontal_scale, vertical_scale, y_offset):
    separate = node_tree.nodes.new('ShaderNodeSeparateXYZ')
    node_tree.links.new(position, separate.inputs['Vector'])

    horizontal = node_tree.nodes.new('ShaderNodeMath')
    horizontal.operation = 'MULTIPLY'
    horizontal.inputs[1].default_value = horizontal_scale
    node_tree.links.new(
        separate.outputs[horizontal_axis],
        horizontal.inputs[0],
    )
    vertical = node_tree.nodes.new('ShaderNodeMath')
    vertical.operation = 'MULTIPLY'
    vertical.inputs[1].default_value = vertical_scale
    node_tree.links.new(separate.outputs['Z'], vertical.inputs[0])
    if y_offset:
        offset = node_tree.nodes.new('ShaderNodeMath')
        offset.operation = 'ADD'
        offset.inputs[1].default_value = y_offset
        node_tree.links.new(vertical.outputs[0], offset.inputs[0])
        vertical_output = offset.outputs[0]
    else:
        vertical_output = vertical.outputs[0]

    combine = node_tree.nodes.new('ShaderNodeCombineXYZ')
    node_tree.links.new(horizontal.outputs[0], combine.inputs['X'])
    node_tree.links.new(vertical_output, combine.inputs['Y'])
    return combine.outputs['Vector']


def _weighted_color(node_tree, color, weight):
    scale = node_tree.nodes.new('ShaderNodeVectorMath')
    scale.operation = 'SCALE'
    node_tree.links.new(color, scale.inputs['Vector'])
    node_tree.links.new(weight, scale.inputs['Scale'])
    return scale.outputs['Vector']


def _add_colors(node_tree, left, right):
    add = node_tree.nodes.new('ShaderNodeVectorMath')
    add.operation = 'ADD'
    node_tree.links.new(left, add.inputs[0])
    node_tree.links.new(right, add.inputs[1])
    return add.outputs['Vector']


def _detail_color(node_tree, uv_output, geometry, normal_weights,
                  terrain, terrain_material, image, side_image, index):
    nodes = node_tree.nodes
    top_vector = _scaled_uv(
        node_tree,
        uv_output,
        terrain.patches_per_side * terrain_material.top_tiling,
        (-900, -450 - index * 160),
    )
    top = _image_node(
        nodes,
        image,
        f'BF2 Detail {index}',
        (-650, -450 - index * 160),
    )
    node_tree.links.new(top_vector, top.inputs['Vector'])
    if not terrain_material.tri_planar:
        return top.outputs['Color']

    patch_world_size = (
        terrain.patch_size * terrain.primary_world_scale[0]
    )
    horizontal_scale = terrain_material.side_tiling[0] / patch_world_size
    vertical_scale = terrain_material.side_tiling[1] / patch_world_size
    x_vector = _side_projection(
        node_tree,
        geometry.outputs['Position'],
        'Y',
        horizontal_scale,
        vertical_scale,
        terrain_material.y_offset,
    )
    y_vector = _side_projection(
        node_tree,
        geometry.outputs['Position'],
        'X',
        horizontal_scale,
        vertical_scale,
        terrain_material.y_offset,
    )
    x_side = _image_node(
        nodes,
        side_image,
        f'BF2 Detail {index} X Side',
        (-400, -450 - index * 160),
    )
    y_side = _image_node(
        nodes,
        side_image,
        f'BF2 Detail {index} Y Side',
        (-150, -450 - index * 160),
    )
    node_tree.links.new(x_vector, x_side.inputs['Vector'])
    node_tree.links.new(y_vector, y_side.inputs['Vector'])

    x_color = _weighted_color(
        node_tree,
        x_side.outputs['Color'],
        normal_weights[0],
    )
    y_color = _weighted_color(
        node_tree,
        y_side.outputs['Color'],
        normal_weights[1],
    )
    top_color = _weighted_color(
        node_tree,
        top.outputs['Color'],
        normal_weights[2],
    )
    return _add_colors(
        node_tree,
        _add_colors(node_tree, x_color, y_color),
        top_color,
    )


def make_primary_terrain_material(
        name, terrain, overview_texture_file, texture_paths=(),
        texture_data_loader=None, reporter=DEFAULT_REPORTER):
    colormap = _build_terrain_atlas(
        f'{name}_Color',
        terrain.colormap_base_name,
        terrain.patches_per_side,
        terrain.patch_colormap_size,
        '',
        'DXT1',
        texture_paths,
        texture_data_loader,
        'sRGB',
        fallback_texture=overview_texture_file,
        reporter=reporter,
    )
    if colormap is None:
        return None

    mask_size = max(1, terrain.patch_colormap_size // 2)
    masks = tuple(
        _build_terrain_atlas(
            f'{name}_Mask{chart}',
            terrain.detailmap_base_name,
            terrain.patches_per_side,
            mask_size,
            f'_{chart}',
            'NONE',
            texture_paths,
            texture_data_loader,
            'Non-Color',
            reporter=reporter,
        )
        for chart in (1, 2)
    )

    if name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[name])
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material['bf2_terrain_version'] = terrain.version
    material['bf2_patch_size'] = terrain.patch_size
    material['bf2_patches_per_side'] = terrain.patches_per_side
    material['bf2_colormap_atlas'] = colormap.name

    node_tree = material.node_tree
    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (900, 0)
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    shader.location = (650, 0)
    shader.inputs['Roughness'].default_value = 1.0
    shader.inputs['Specular IOR Level'].default_value = 0.0
    links.new(shader.outputs['BSDF'], output.inputs['Surface'])

    uv = nodes.new('ShaderNodeUVMap')
    uv.uv_map = 'UVMap'
    uv.location = (-1200, 300)
    geometry = nodes.new('ShaderNodeNewGeometry')
    geometry.location = (-1200, -250)
    normal_weights = _normal_weights(node_tree, geometry)

    color_node = _image_node(
        nodes,
        colormap,
        'BF2 Terrain Colormap Atlas',
        (-350, 350),
    )
    color_node.extension = 'EXTEND'
    links.new(uv.outputs['UV'], color_node.inputs['Vector'])

    mask_channels = []
    for chart, mask in enumerate(masks):
        if mask is None:
            for _ in range(3):
                zero = nodes.new('ShaderNodeValue')
                zero.outputs[0].default_value = 0.0
                mask_channels.append(zero.outputs[0])
            continue
        mask_node = _image_node(
            nodes,
            mask,
            f'BF2 Terrain Material Mask {chart + 1}',
            (-900, 100 - chart * 220),
        )
        mask_node.extension = 'EXTEND'
        links.new(uv.outputs['UV'], mask_node.inputs['Vector'])
        separate = nodes.new('ShaderNodeSeparateColor')
        separate.mode = 'RGB'
        links.new(mask_node.outputs['Color'], separate.inputs['Color'])
        mask_channels.extend(
            separate.outputs[channel]
            for channel in ('Red', 'Green', 'Blue')
        )

    detail_sum = None
    mask_sum = None
    for index, terrain_material in enumerate(terrain.materials[:6]):
        texture_file = _texture_path(terrain_material.texture)
        image = load_texture_image(
            texture_file,
            texture_paths=texture_paths,
            texture_data_loader=texture_data_loader,
        )
        if image is None:
            reporter.warning(
                f"Terrain detail texture '{texture_file}' was not found"
            )
            neutral = nodes.new('ShaderNodeRGB')
            neutral.outputs['Color'].default_value = (0.5, 0.5, 0.5, 1.0)
            detail_color = neutral.outputs['Color']
        else:
            image.alpha_mode = 'NONE'
            side_image = image
            if terrain_material.tri_planar:
                side_texture = _texture_path(
                    terrain_material.texture + '_side'
                )
                side_image = load_texture_image(
                    side_texture,
                    texture_paths=texture_paths,
                    texture_data_loader=texture_data_loader,
                ) or image
                side_image.alpha_mode = 'NONE'
            detail_color = _detail_color(
                node_tree,
                uv.outputs['UV'],
                geometry,
                normal_weights,
                terrain,
                terrain_material,
                image,
                side_image,
                index,
            )

        material[f'bf2_detail_{index}_texture'] = terrain_material.texture
        material[f'bf2_detail_{index}_top_tiling'] = (
            terrain_material.top_tiling
        )
        weighted = _weighted_color(
            node_tree,
            detail_color,
            mask_channels[index],
        )
        detail_sum = (
            weighted
            if detail_sum is None
            else _add_colors(node_tree, detail_sum, weighted)
        )
        if mask_sum is None:
            mask_sum = mask_channels[index]
        else:
            add_mask = nodes.new('ShaderNodeMath')
            add_mask.operation = 'ADD'
            links.new(mask_sum, add_mask.inputs[0])
            links.new(mask_channels[index], add_mask.inputs[1])
            mask_sum = add_mask.outputs[0]

    if detail_sum is None:
        links.new(color_node.outputs['Color'], shader.inputs['Base Color'])
        return material

    clamp = nodes.new('ShaderNodeClamp')
    clamp.inputs['Min'].default_value = 0.0
    clamp.inputs['Max'].default_value = 1.0
    links.new(mask_sum, clamp.inputs['Value'])
    gap = nodes.new('ShaderNodeMath')
    gap.operation = 'SUBTRACT'
    gap.inputs[0].default_value = 1.0
    links.new(clamp.outputs['Result'], gap.inputs[1])
    half_gap = nodes.new('ShaderNodeMath')
    half_gap.operation = 'MULTIPLY'
    half_gap.inputs[1].default_value = 0.5
    links.new(gap.outputs[0], half_gap.inputs[0])
    neutral = nodes.new('ShaderNodeCombineXYZ')
    for component in ('X', 'Y', 'Z'):
        links.new(half_gap.outputs[0], neutral.inputs[component])
    completed_detail = _add_colors(
        node_tree,
        detail_sum,
        neutral.outputs['Vector'],
    )
    doubled_detail = nodes.new('ShaderNodeVectorMath')
    doubled_detail.operation = 'SCALE'
    doubled_detail.inputs['Scale'].default_value = 2.0
    links.new(completed_detail, doubled_detail.inputs['Vector'])
    final_color = nodes.new('ShaderNodeVectorMath')
    final_color.operation = 'MULTIPLY'
    links.new(color_node.outputs['Color'], final_color.inputs[0])
    links.new(doubled_detail.outputs['Vector'], final_color.inputs[1])
    links.new(final_color.outputs['Vector'], shader.inputs['Base Color'])
    return material
