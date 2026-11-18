import bpy # type: ignore
from math import sqrt
import numpy as np

from .exceptions import ImportException
from .utils import file_name
from .utils.mesh import set_mesh_geometry


def make_water_plane(context, heightmap_size, water_level, name='WaterPlane'):
    off = heightmap_size / 2
    vertices = np.asarray(
        (
            (-off, -off, 0),
            (-off, off, 0),
            (off, off, 0),
            (off, -off, 0),
        ),
        dtype=np.float32,
    )

    mesh = bpy.data.meshes.new(name)
    set_mesh_geometry(mesh, vertices, ((0, 1, 2, 3),))

    water_uv_layer = mesh.uv_layers.new(name='UVMap')
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_vertices)
    loop_uvs = (vertices[loop_vertices, :2] + off) / heightmap_size
    water_uv_layer.data.foreach_set('uv', loop_uvs.ravel())

    obj = bpy.data.objects.new(name, mesh)
    obj.location.z = water_level
    context.scene.collection.objects.link(obj)
    return obj


def import_heightmap_from(context, data, name, bit_res=16, scale=(1, 1, 1)):
    data.seek(0, 2)
    file_size = data.tell()

    bytes_per_heixel = int(bit_res / 8)
    world_dim = int(sqrt(file_size / bytes_per_heixel))

    if file_size != world_dim * world_dim * bytes_per_heixel:
        raise ImportException("not a valid heightmap, file size is incorrect")
    if bytes_per_heixel not in (1, 2, 4, 8):
        raise ImportException(f"unsupported heightmap bit resolution: {bit_res}")

    data.seek(0, 0)
    raw_data = data.read()

    # center it
    offset_x = (world_dim - 1) * scale[0] / 2
    offset_y = (world_dim - 1) * scale[1] / 2

    raw_heights = np.frombuffer(
        raw_data,
        dtype=np.dtype(f'<u{bytes_per_heixel}'),
    ).reshape((world_dim, world_dim))
    x_coordinates = np.repeat(np.arange(world_dim, dtype=np.float32), world_dim)
    y_coordinates = np.tile(np.arange(world_dim, dtype=np.float32), world_dim)
    heights = raw_heights.T.ravel().astype(np.float32) * scale[2]
    vertices = np.column_stack(
        (
            x_coordinates * scale[0] - offset_x,
            y_coordinates * scale[1] - offset_y,
            heights,
        )
    )

    grid_x = np.repeat(np.arange(world_dim - 1), world_dim - 1)
    grid_y = np.tile(np.arange(world_dim - 1), world_dim - 1)
    index = grid_y * world_dim + grid_x
    alternate = (grid_y + grid_x) % bytes_per_heixel == 0
    faces = np.empty((len(index) * 2, 3), dtype=np.int32)
    faces[0::2] = np.column_stack(
        (
            index + 1,
            index,
            np.where(alternate, index + world_dim + 1, index + world_dim),
        )
    )
    faces[1::2] = np.column_stack(
        (
            index + world_dim + 1,
            np.where(alternate, index, index + 1),
            index + world_dim,
        )
    )

    mesh = bpy.data.meshes.new(name)
    set_mesh_geometry(mesh, vertices, faces)

    terrain_uv_layer = mesh.uv_layers.new(name='UVMap')
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_vertices)
    loop_coordinates = vertices[loop_vertices, :2]
    loop_coordinates[:, 0] = (
        (loop_coordinates[:, 0] + offset_x)
        / scale[0]
        / (world_dim - 1)
    )
    loop_coordinates[:, 1] = (
        (loop_coordinates[:, 1] + offset_y)
        / scale[1]
        / (world_dim - 1)
    )
    terrain_uv_layer.data.foreach_set('uv', loop_coordinates.ravel())

    obj = bpy.data.objects.new(name, mesh)
    context.scene.collection.objects.link(obj)
    return obj

def import_heightmap(context, fname, *args, **kwargs):
    with open(fname, "rb") as f:
        return import_heightmap_from(context, f, file_name(fname), *args, **kwargs)

# TODO
# def export_heightmap(obj, fname, world_size, y_scale=1.0):        
#         matrix_cpy = obj.matrix_world.copy()

#         obj.data.transform(obj.matrix_world)
#         obj.matrix_world = Matrix.Identity(4)

#         try:
#             with open(fname, "rb") as f:
#                 for y in range(0, world_size, 4):
#                     for x in range(0, world_size, 4):
#                         result, location, normal, index = obj.ray_cast([x, y, 1000], [0, 0, -1])
#                         height=0
#                         if result:
#                             height = min(max(location[2], 0), 256 * y_scale)
#                         int16 = round(65535 * height/ (256 * y_scale))
#                         int8_2 = int16 >> 8
#                         int8_1 = int16 & 255
#                         f.write(int.to_bytes(int8_1))
#                         f.write(int.to_bytes(int8_2))
#         except:
#             raise
#         finally:
#             obj.data.transform(matrix_cpy.inverted())
#             obj.matrix_world = matrix_cpy
