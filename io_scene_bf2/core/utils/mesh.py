import numpy as np


def set_mesh_geometry(mesh, vertices, faces):
    vertices = np.asarray(vertices, dtype=np.float32)
    if vertices.size == 0:
        vertices = vertices.reshape((0, 3))
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("Vertices must have shape (count, 3)")

    faces = np.asarray(faces, dtype=np.int32)
    if faces.size == 0:
        faces = faces.reshape((0, 0))
    if faces.ndim != 2:
        raise ValueError("Faces must have shape (count, vertices_per_face)")
    if faces.shape[0] and faces.shape[1] < 3:
        raise ValueError("Faces must contain at least three vertices")
    if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
        raise ValueError("Face references a vertex outside the mesh")
    if mesh.vertices or mesh.loops or mesh.polygons:
        raise ValueError("Mesh geometry must be empty before batch creation")

    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set("co", vertices.ravel())

    if len(faces):
        vertices_per_face = faces.shape[1]
        mesh.loops.add(faces.size)
        mesh.loops.foreach_set("vertex_index", faces.ravel())

        mesh.polygons.add(len(faces))
        mesh.polygons.foreach_set(
            "loop_start",
            np.arange(len(faces), dtype=np.int32) * vertices_per_face,
        )
        mesh.polygons.foreach_set(
            "loop_total",
            np.full(len(faces), vertices_per_face, dtype=np.int32),
        )

    mesh.update(calc_edges=True)


def prepare_mesh_faces(face_records, load_backfaces=True):
    faces = []
    material_indices = []
    double_sided_faces = set()
    skipped_faces = 0
    seen_faces = {}

    for vertices, material_index in face_records:
        vertices = tuple(vertices)
        if len(vertices) != 3 or len(set(vertices)) != 3:
            skipped_faces += 1
            continue

        key = tuple(sorted(vertices))
        previous = seen_faces.get(key)
        if previous is None:
            face_index = len(faces)
            faces.append(vertices)
            material_indices.append(material_index)
            seen_faces[key] = (vertices, face_index, material_index)
            continue

        if not load_backfaces:
            skipped_faces += 1
            continue

        previous_vertices, face_index, previous_material = previous
        if not _has_opposite_winding(vertices, previous_vertices):
            skipped_faces += 1
            continue
        if material_index != previous_material:
            raise ValueError(
                "Found double-sided face with a different material on each side"
            )
        double_sided_faces.add(face_index)

    return faces, material_indices, double_sided_faces, skipped_faces


def _has_opposite_winding(first, second):
    for offset in range(3):
        if first[offset:] + first[:offset] == second:
            return False
    return True

