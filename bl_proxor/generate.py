"""Mesh surface sampling and PRX payload generation for Proxor Lite.

Samples random points on mesh surfaces and packages them into the PRX
payload format that :mod:`bl_proxor.prx_format` can persist and
:mod:`bl_proxor.draw` can render.

Self-contained - does not depend on the full ``proxor`` package.
"""

from __future__ import annotations

import contextlib
import math
import random
from bisect import bisect_left

import bpy
import numpy as np
from mathutils import Matrix, Vector

# ===========================================================================
# Constants
# ===========================================================================

# -- General geometry --
TRIANGLE_VERTEX_COUNT = 3
VECTOR_LEN = 3
RGBA_LEN = 4

# -- Point sampling --
MAX_POINT_COUNT = 10000
MIN_POINT_COUNT = 500
POINT_DIVISOR = 100

# -- Marching cubes --
MARCHING_CUBES_MAX_GRID_CELLS = 8_000_000
MARCHING_CUBES_PADDING = 2.0
CPU_RECON_DEFAULT_VOXEL_SCALE = 0.7

# -- Mesh post-processing defaults --
_DECIMATION_RATIO_DEFAULT = 0.25  # 1.0 = keep all, 0.5 = halve triangle count
_REPROJECT_MAX_DIST_FACTOR = 1.2
_SMOOTH_ITERATIONS_DEFAULT = 10

# -- Coordinate transforms --
_PRX_TO_BLENDER = Matrix(
    (
        (0.01, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.01, 0.0),
        (0.0, 0.01, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ),
)
_BLENDER_TO_PRX = _PRX_TO_BLENDER.inverted()

# -- Density splatting kernels --
_RHOMBIC_SPLAT_OFFSETS = np.asarray(
    [
        (0, 0, 0),
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),
        (0, 0, -1),
        (1, 1, 0),
        (1, -1, 0),
        (-1, 1, 0),
        (-1, -1, 0),
        (1, 0, 1),
        (1, 0, -1),
        (-1, 0, 1),
        (-1, 0, -1),
        (0, 1, 1),
        (0, 1, -1),
        (0, -1, 1),
        (0, -1, -1),
    ],
    dtype=np.int32,
)
_RHOMBIC_SPLAT_WEIGHTS = np.asarray(
    [
        1.0,
        0.45,
        0.45,
        0.45,
        0.45,
        0.45,
        0.45,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
        0.28,
    ],
    dtype=np.float32,
)

# ===========================================================================
# Low-level math helpers
# ===========================================================================


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sample_point_on_triangle(v1: Vector, v2: Vector, v3: Vector) -> Vector:
    """Return a uniformly random point inside the triangle *v1*-*v2*-*v3*."""
    r1 = random.random()  # noqa: S311
    r2 = random.random()  # noqa: S311
    sqrt_r1 = math.sqrt(r1)
    u = 1.0 - sqrt_r1
    v = r2 * sqrt_r1
    w = 1.0 - u - v
    return (v1 * u) + (v2 * v) + (v3 * w)


def _triangle_world_area(tri, vertices, matrix_world) -> float:
    indices = getattr(tri, "vertices", ())
    if len(indices) != TRIANGLE_VERTEX_COUNT:
        return 0.0
    vertex_count = len(vertices)
    corners_local: list[Vector] = []
    for vertex_index in indices:
        if vertex_index < 0 or vertex_index >= vertex_count:
            return 0.0
        corners_local.append(Vector(vertices[vertex_index].co))
    if len(corners_local) != TRIANGLE_VERTEX_COUNT:
        return 0.0
    corners_world = [matrix_world @ corner for corner in corners_local]
    edge1 = corners_world[1] - corners_world[0]
    edge2 = corners_world[2] - corners_world[0]
    return edge1.cross(edge2).length * 0.5


def _estimate_point_spacing(points: list[list[float]]) -> float:
    if not points:
        return 0.0
    min_corner = [float("inf")] * VECTOR_LEN
    max_corner = [float("-inf")] * VECTOR_LEN
    for point in points:
        if not point or len(point) < VECTOR_LEN:
            continue
        for axis in range(VECTOR_LEN):
            value = float(point[axis])
            min_corner[axis] = min(min_corner[axis], value)
            max_corner[axis] = max(max_corner[axis], value)
    extent = [max_corner[i] - min_corner[i] for i in range(VECTOR_LEN)]
    diagonal = math.sqrt(sum(max(e, 0.0) ** 2 for e in extent))
    if diagonal <= 0.0:
        diagonal = 1.0
    point_count = max(len(points), 1)
    return diagonal / (point_count ** (1.0 / 3.0))


# ===========================================================================
# Source collection
# ===========================================================================


def _iter_mesh_descendants(obj):
    """Yield all MESH-type descendants of *obj* (breadth-first)."""
    from collections import deque

    queue: deque = deque(getattr(obj, "children", []))
    visited: set[int] = set()
    while queue:
        child = queue.popleft()
        pointer = child.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)
        for grandchild in getattr(child, "children", []):
            queue.append(grandchild)
        if getattr(child, "type", "") == "MESH":
            yield child


def collect_sources(
    obj,
    *,
    include_children: bool = True,
) -> list[tuple]:
    """Collect mesh sources from *obj* and optionally its children.

    Returns:
        List of ``(blender_object, transform_matrix_or_None)`` tuples.
    """
    sources: list[tuple] = []
    if obj is None:
        return sources
    if getattr(obj, "type", "") == "MESH":
        sources.append((obj, None))
    if not include_children:
        return sources
    try:
        parent_inv = obj.matrix_world.copy().inverted()
    except Exception:  # noqa: BLE001
        parent_inv = Matrix.Identity(4)
    for child in _iter_mesh_descendants(obj):
        try:
            matrix = parent_inv @ child.matrix_world
        except Exception:  # noqa: BLE001
            matrix = None
        sources.append((child, matrix))
    return sources


def _count_source_vertices(sources: list[tuple], depsgraph) -> int:
    """Count the total number of vertices across all source meshes."""
    total = 0
    for source_obj, _ in sources:
        try:
            obj_eval = source_obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            if mesh is not None:
                total += len(mesh.vertices)
                with contextlib.suppress(Exception):
                    obj_eval.to_mesh_clear()
        except Exception:  # noqa: BLE001, S110, PERF203
            pass
    return total


def _count_source_triangles(sources: list[tuple], depsgraph) -> int:
    """Count the total number of triangles across all source meshes."""
    total = 0
    for source_obj, _ in sources:
        try:
            obj_eval = source_obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            if mesh is not None:
                mesh.calc_loop_triangles()
                total += len(mesh.loop_triangles)
                with contextlib.suppress(Exception):
                    obj_eval.to_mesh_clear()
        except Exception:  # noqa: BLE001, S110, PERF203
            pass
    return total


def _estimate_object_surface_area(obj, depsgraph) -> float:
    if obj is None:
        return 0.0
    try:
        obj_eval = obj.evaluated_get(depsgraph)
    except Exception:  # noqa: BLE001
        return 0.0
    mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    if mesh is None:
        return 0.0
    try:
        mesh.calc_loop_triangles()
        loop_tris = getattr(mesh, "loop_triangles", [])
        vertices = getattr(mesh, "vertices", [])
        if not loop_tris or not vertices:
            return 0.0
        matrix_world = obj_eval.matrix_world.copy()
        total_area = 0.0
        for tri in loop_tris:
            area = _triangle_world_area(tri, vertices, matrix_world)
            if area > 0:
                total_area += area
        return total_area
    finally:
        with contextlib.suppress(Exception):
            obj_eval.to_mesh_clear()


def _allocate_samples_by_area(
    sources: list[tuple],
    sample_count: int,
    depsgraph,
) -> list[int]:
    """Distribute *sample_count* across *sources* proportional to surface area."""
    if not sources or sample_count <= 0:
        return [0 for _ in sources]
    areas = [
        max(_estimate_object_surface_area(src, depsgraph), 0.0) for src, _ in sources
    ]
    total_area = sum(areas)
    if total_area <= 0.0:
        areas = [1.0 for _ in sources]
        total_area = float(len(sources))
    remaining = sample_count
    allocations: list[int] = []
    for idx, area in enumerate(areas):
        sources_left = len(sources) - idx - 1
        if remaining <= 0:
            allocations.append(0)
            continue
        if idx == len(sources) - 1:
            share = remaining
        else:
            ratio = area / total_area if total_area > 0 else 0.0
            share = round(remaining * ratio)
            min_remaining = max(0, sources_left)
            max_share = max(0, remaining - min_remaining)
            if share <= 0 and remaining > sources_left:
                share = 1
            share = min(max_share, share) if max_share > 0 else 0
        allocations.append(max(0, share))
        remaining -= allocations[-1]
        total_area -= area
    if allocations and sum(allocations) < sample_count:
        diff = sample_count - sum(allocations)
        allocations[-1] += diff
    return allocations


# ===========================================================================
# Texture / material colour sampling
# ===========================================================================


def _find_tex_image_upstream(node, visited: set | None = None) -> "bpy.types.Image | None":
    """Recursively walk upstream from *node* to find the first TEX_IMAGE."""
    if visited is None:
        visited = set()
    if id(node) in visited:
        return None
    visited.add(id(node))
    if node.type == "TEX_IMAGE" and node.image is not None:
        return node.image
    for inp in node.inputs:
        if inp.is_linked:
            upstream = inp.links[0].from_node
            result = _find_tex_image_upstream(upstream, visited)
            if result is not None:
                return result
    return None


def _find_diffuse_image(obj) -> "bpy.types.Image | None":
    """Walk material slots to find the first Base Color texture image."""
    for slot in getattr(obj, "material_slots", []):
        mat = slot.material
        if mat is None or not getattr(mat, "use_nodes", False):
            continue
        tree = getattr(mat, "node_tree", None)
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            base_input = node.inputs.get("Base Color")
            if base_input is None or not base_input.is_linked:
                continue
            from_node = base_input.links[0].from_node
            result = _find_tex_image_upstream(from_node)
            if result is not None:
                return result
    return None


def _build_image_pixel_cache(image: "bpy.types.Image") -> tuple["np.ndarray", int, int]:
    """Return ``(pixels_rgba, width, height)`` with pixel data as a NumPy array."""
    w, h = image.size[0], image.size[1]
    if w <= 0 or h <= 0:
        return np.zeros((0,), dtype=np.float32), 0, 0
    raw = image.pixels[:]
    if len(raw) < w * h * RGBA_LEN:
        return np.zeros((0,), dtype=np.float32), 0, 0
    px = np.array(raw, dtype=np.float32).reshape(h, w, RGBA_LEN)
    return px, w, h


def _sample_texture_at_uv(
    px_cache: "np.ndarray",
    width: int,
    height: int,
    u: float,
    v: float,
) -> list[float]:
    """Sample RGBA from cached pixel data at the given UV coordinate."""
    if width <= 0 or height <= 0:
        return [0.8, 0.8, 0.8, 1.0]
    x = int((u % 1.0) * width) % width
    y = int((v % 1.0) * height) % height
    rgba = px_cache[y, x]
    # Store at half intensity to match PRX convention (draw code multiplies by 2)
    return [_clamp01(float(rgba[0]) * 0.5), _clamp01(float(rgba[1]) * 0.5),
            _clamp01(float(rgba[2]) * 0.5), _clamp01(float(rgba[3]))]


def _interpolate_uv(
    uv0: "Vector",
    uv1: "Vector",
    uv2: "Vector",
    bary_u: float,
    bary_v: float,
    bary_w: float,
) -> tuple[float, float]:
    """Interpolate UV coordinates using barycentric weights."""
    return (
        float(uv0[0]) * bary_u + float(uv1[0]) * bary_v + float(uv2[0]) * bary_w,
        float(uv0[1]) * bary_u + float(uv1[1]) * bary_v + float(uv2[1]) * bary_w,
    )


# ===========================================================================
# Surface sampling
# ===========================================================================


def _sample_uniform_surface_points(
    obj,
    count: int,
    *,
    depsgraph,
    include_normals: bool = False,
    include_colors: bool = False,
) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    """Sample *count* random points on the surface of *obj*.

    Returns:
        ``(positions, normals, colors)`` where positions/normals are
        ``[x, y, z]`` in the object's local space and colors are
        ``[r, g, b, a]`` sampled from the diffuse texture (if available).
    """
    if obj is None or count <= 0:
        return [], [], []
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    if mesh is None:
        return [], [], []
    try:
        mesh.calc_loop_triangles()
        loop_tris = getattr(mesh, "loop_triangles", [])
        if not loop_tris:
            return [], [], []
        vertices = getattr(mesh, "vertices", [])
        matrix_world = obj_eval.matrix_world.copy()
        cumulative: list[float] = []
        triangles_local: list[tuple[Vector, Vector, Vector]] = []
        triangle_normals: list[Vector] = []
        triangle_uvs: list[tuple | None] = []
        total_area = 0.0

        # Prepare UV and texture data for colour sampling
        uv_layer = None
        px_cache = None
        tex_w = tex_h = 0
        if include_colors:
            uv_layer_obj = getattr(mesh, "uv_layers", None)
            uv_layer = getattr(uv_layer_obj, "active", None)
            image = _find_diffuse_image(obj_eval) or _find_diffuse_image(obj)
            if image is not None and uv_layer is not None:
                px_cache, tex_w, tex_h = _build_image_pixel_cache(image)
                if tex_w <= 0:
                    px_cache = None

        for tri in loop_tris:
            indices = getattr(tri, "vertices", ())
            if len(indices) != TRIANGLE_VERTEX_COUNT:
                continue
            try:
                corners_local = [Vector(vertices[idx].co) for idx in indices]
            except Exception:  # noqa: BLE001, S112
                continue
            corners_world = [matrix_world @ corner for corner in corners_local]
            edge1 = corners_world[1] - corners_world[0]
            edge2 = corners_world[2] - corners_world[0]
            area = edge1.cross(edge2).length * 0.5
            if area <= 0.0:
                continue

            edge_local_1 = corners_local[1] - corners_local[0]
            edge_local_2 = corners_local[2] - corners_local[0]
            normal_local = edge_local_1.cross(edge_local_2)
            if normal_local.length_squared > 0:
                normal_local.normalize()
            else:
                normal_local = Vector((0.0, 0.0, 1.0))

            total_area += area
            cumulative.append(total_area)
            triangles_local.append((corners_local[0], corners_local[1], corners_local[2]))
            triangle_normals.append(normal_local)

            # Store per-triangle UVs for interpolation
            if uv_layer is not None and px_cache is not None:
                loops = getattr(tri, "loops", ())
                if len(loops) == TRIANGLE_VERTEX_COUNT:
                    triangle_uvs.append((
                        uv_layer.data[loops[0]].uv.copy(),
                        uv_layer.data[loops[1]].uv.copy(),
                        uv_layer.data[loops[2]].uv.copy(),
                    ))
                else:
                    triangle_uvs.append(None)

        if total_area <= 0.0 or not triangles_local:
            return [], [], []

        samples: list[list[float]] = []
        normals_out: list[list[float]] = []
        colors_out: list[list[float]] = []
        for _idx in range(count):
            r1 = random.random()  # noqa: S311
            r2 = random.random()  # noqa: S311
            sqrt_r1 = math.sqrt(r1)
            bary_u = 1.0 - sqrt_r1
            bary_v = r2 * sqrt_r1
            bary_w = 1.0 - bary_u - bary_v

            target = random.uniform(0.0, total_area)  # noqa: S311
            tri_index = bisect_left(cumulative, target)
            if tri_index >= len(triangles_local):
                tri_index = len(triangles_local) - 1
            tri = triangles_local[tri_index]
            point = (tri[0] * bary_u) + (tri[1] * bary_v) + (tri[2] * bary_w)
            samples.append([float(point.x), float(point.y), float(point.z)])
            if include_normals and triangle_normals:
                normal_vec = triangle_normals[tri_index]
                normals_out.append([float(normal_vec.x), float(normal_vec.y), float(normal_vec.z)])
            if include_colors and px_cache is not None and tri_index < len(triangle_uvs):
                tri_uv = triangle_uvs[tri_index]
                if tri_uv is not None:
                    u, v = _interpolate_uv(tri_uv[0], tri_uv[1], tri_uv[2], bary_u, bary_v, bary_w)
                    colors_out.append(_sample_texture_at_uv(px_cache, tex_w, tex_h, u, v))
                else:
                    colors_out.append([0.8, 0.8, 0.8, 1.0])
        return samples, normals_out, colors_out
    finally:
        with contextlib.suppress(Exception):
            obj_eval.to_mesh_clear()


# ===========================================================================
# Transform and coordinate helpers
# ===========================================================================


def _apply_transform_to_vectors(
    vectors: list[list[float]] | None, matrix: Matrix | None
) -> None:
    if not vectors or matrix is None:
        return
    for idx, vec in enumerate(vectors):
        if not vec or len(vec) < VECTOR_LEN:
            continue
        x, y, z = vec[:3]
        transformed = matrix @ Vector((x, y, z, 1.0))
        vectors[idx] = [
            float(transformed.x),
            float(transformed.y),
            float(transformed.z),
        ]


def _apply_transform_to_payload(payload: dict | None, matrix: Matrix | None) -> None:
    if not payload or matrix is None:
        return
    legacy = payload.get("legacy") if isinstance(payload, dict) else None
    if not isinstance(legacy, dict):
        return
    for key in ("mesh", "line", "points", "text"):
        section = legacy.get(key)
        if not isinstance(section, dict):
            continue
        _apply_transform_to_vectors(section.get("pos"), matrix)


def _convert_normals_to_prx(normals: list[list[float]] | None) -> None:
    """Swap Y/Z in normals to convert from Blender to PRX coordinate space."""
    if not normals:
        return
    for idx, normal in enumerate(normals):
        if not normal or len(normal) < VECTOR_LEN:
            continue
        x, y, z = normal[:VECTOR_LEN]
        normals[idx] = [float(x), float(z), float(y)]


def _transform_point_list(
    points: list[list[float]],
    normals: list[list[float]],
    matrix: Matrix | None,
) -> tuple[list[list[float]], list[list[float]]]:
    if matrix is None:
        return points, normals
    transformed_points: list[list[float]] = []
    transformed_normals: list[list[float]] = []
    try:
        normal_matrix = matrix.inverted_safe().transposed().to_3x3()
    except Exception:  # noqa: BLE001
        normal_matrix = matrix.to_3x3()
    for point in points:
        vec = matrix @ Vector((float(point[0]), float(point[1]), float(point[2]), 1.0))
        transformed_points.append([float(vec.x), float(vec.y), float(vec.z)])
    if normals and normal_matrix is not None:
        for normal in normals:
            norm_vec = normal_matrix @ Vector(
                (float(normal[0]), float(normal[1]), float(normal[2]))
            )
            if norm_vec.length_squared > 0:
                norm_vec.normalize()
            transformed_normals.append(
                [float(norm_vec.x), float(norm_vec.y), float(norm_vec.z)]
            )
    elif normals:
        transformed_normals = [list(normal) for normal in normals]
    return transformed_points, transformed_normals


# ===========================================================================
# Colour and payload helpers
# ===========================================================================


def _resolve_object_color(obj) -> tuple[float, float, float, float]:
    color = getattr(obj, "color", None)
    if color and len(color) >= VECTOR_LEN:
        alpha = float(color[3]) if len(color) > VECTOR_LEN else 1.0
        return (
            _clamp01(color[0]),
            _clamp01(color[1]),
            _clamp01(color[2]),
            _clamp01(alpha),
        )
    return (0.8, 0.8, 0.8, 1.0)


def _build_payload_point_colors(
    point_count: int,
    point_colors: list[list[float]] | None,
    default_rgba: tuple[float, float, float, float],
) -> list[list[float]]:
    if point_count <= 0:
        return []
    if not point_colors:
        return [list(default_rgba) for _ in range(point_count)]
    colors: list[list[float]] = []
    for idx in range(point_count):
        if idx < len(point_colors):
            entry = point_colors[idx]
            if entry and len(entry) >= RGBA_LEN:
                colors.append(
                    [
                        _clamp01(entry[0]),
                        _clamp01(entry[1]),
                        _clamp01(entry[2]),
                        _clamp01(entry[3]),
                    ]
                )
                continue
        colors.append(list(default_rgba))
    return colors


def _build_payload_point_normals(
    point_count: int,
    point_normals: list[list[float]] | None,
) -> list[list[float]]:
    if point_count <= 0 or not point_normals:
        return []
    normals: list[list[float]] = []
    for idx in range(point_count):
        if idx < len(point_normals):
            entry = point_normals[idx]
            if entry and len(entry) >= VECTOR_LEN:
                normals.append([float(entry[0]), float(entry[1]), float(entry[2])])
                continue
        normals.append([0.0, 0.0, 1.0])
    _convert_normals_to_prx(normals)
    return normals


# ===========================================================================
# Marching cubes iso-surface extraction
# ===========================================================================


def _compute_vertex_normals_from_triangles(
    points_np: np.ndarray,
    triangles: list[tuple[int, int, int]],
) -> list[list[float]]:
    normals = np.zeros_like(points_np)
    for i0, i1, i2 in triangles:
        v0 = points_np[i0]
        v1 = points_np[i1]
        v2 = points_np[i2]
        face_normal = np.cross(v1 - v0, v2 - v0)
        if not np.any(face_normal):
            continue
        normals[i0] += face_normal
        normals[i1] += face_normal
        normals[i2] += face_normal
    lengths = np.linalg.norm(normals, axis=1)
    nonzero = lengths > 0
    normals[nonzero] = normals[nonzero] / lengths[nonzero, None]
    if np.any(~nonzero):
        normals[~nonzero] = np.array([0.0, 0.0, 1.0])
    return [[float(vec[0]), float(vec[1]), float(vec[2])] for vec in normals]


def _weld_close_vertices(
    vertices: np.ndarray,
    triangles: list[tuple[int, int, int]],
    tolerance: float,
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Merge vertices closer than *tolerance* and remap triangle indices."""
    if len(vertices) == 0 or not triangles:
        return vertices, triangles
    inv_tol = 1.0 / max(tolerance, 1e-12)
    quantized = np.round(vertices * inv_tol).astype(np.int64)
    _, inverse, counts = np.unique(
        quantized, axis=0, return_inverse=True, return_counts=True
    )
    n_unique = len(counts)
    new_verts = np.zeros((n_unique, 3), dtype=np.float64)
    np.add.at(new_verts, inverse, vertices.astype(np.float64))
    new_verts /= np.maximum(counts, 1)[:, None]
    new_triangles = []
    for i0, i1, i2 in triangles:
        a, b, c = int(inverse[i0]), int(inverse[i1]), int(inverse[i2])
        if b not in (a, c) and a != c:
            new_triangles.append((a, b, c))
    return new_verts.astype(vertices.dtype), new_triangles


def _fix_face_orientations(
    vertices: np.ndarray,
    triangles: list[tuple[int, int, int]],
    density: np.ndarray,
    grid_min: np.ndarray,
    voxel_size: float,
) -> list[tuple[int, int, int]]:
    """Flip triangles whose normals point inward (toward higher density)."""
    if not triangles or len(vertices) == 0:
        return triangles
    tri_arr = np.asarray(triangles, dtype=np.int32)
    v0 = vertices[tri_arr[:, 0]]
    v1 = vertices[tri_arr[:, 1]]
    v2 = vertices[tri_arr[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)
    centroids = (v0 + v1 + v2) / 3.0
    dims = np.array(density.shape, dtype=np.int32)
    center_offset = float(voxel_size) * 0.5
    grad = np.gradient(density, voxel_size)
    grid_pos = (centroids - grid_min - center_offset) / voxel_size
    gi = np.clip(np.round(grid_pos).astype(np.int32), [0, 0, 0], dims - 1)
    gx = grad[0][gi[:, 0], gi[:, 1], gi[:, 2]]
    gy = grad[1][gi[:, 0], gi[:, 1], gi[:, 2]]
    gz = grad[2][gi[:, 0], gi[:, 1], gi[:, 2]]
    dot = face_normals[:, 0] * gx + face_normals[:, 1] * gy + face_normals[:, 2] * gz
    should_flip = dot > 0.0
    result = tri_arr.copy()
    temp = result[should_flip, 1].copy()
    result[should_flip, 1] = result[should_flip, 2]
    result[should_flip, 2] = temp
    return [(int(r[0]), int(r[1]), int(r[2])) for r in result]


def _surface_from_scalar_field(
    field: np.ndarray,
    grid_min: np.ndarray,
    voxel_size: float,
    level: float,
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    center_offset = float(voxel_size) * 0.5
    try:
        from skimage import measure  # type: ignore[import-untyped]

        verts, faces, _normals, _values = measure.marching_cubes(
            field.astype(np.float32),
            level=float(level),
            spacing=(float(voxel_size), float(voxel_size), float(voxel_size)),
        )
        if faces.size > 0:
            verts_world = verts + grid_min + center_offset
            tris = [
                (int(face[0]), int(face[1]), int(face[2])) for face in faces.tolist()
            ]
            return verts_world, tris
    except Exception:  # noqa: BLE001, S110
        pass  # Fall through to marching tetrahedra fallback

    return _build_marching_tetrahedra_mesh(field, grid_min, voxel_size, float(level))


def _build_marching_tetrahedra_mesh(
    field: np.ndarray,
    grid_min: np.ndarray,
    voxel_size: float,
    level: float,
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    nx, ny, nz = field.shape
    if nx < 2 or ny < 2 or nz < 2:
        return np.zeros((0, 3), dtype=np.float64), []

    cube_corner_offsets = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0),
            (0.0, 1.0, 1.0),
        ],
        dtype=np.float64,
    )
    tet_corner_ids = (
        (0, 5, 1, 6),
        (0, 1, 2, 6),
        (0, 2, 3, 6),
        (0, 3, 7, 6),
        (0, 7, 4, 6),
        (0, 4, 5, 6),
    )

    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    vertex_map: dict[tuple[int, int, int], int] = {}

    def _vertex_id(point: np.ndarray) -> int:
        key = (
            round(point[0] * 1_000_000),
            round(point[1] * 1_000_000),
            round(point[2] * 1_000_000),
        )
        cached = vertex_map.get(key)
        if cached is not None:
            return cached
        idx = len(vertices)
        vertices.append((float(point[0]), float(point[1]), float(point[2])))
        vertex_map[key] = idx
        return idx

    def _interp(p1: np.ndarray, p2: np.ndarray, v1: float, v2: float) -> np.ndarray:
        denom = v2 - v1
        t = 0.5 if abs(denom) < 1e-08 else (level - v1) / denom
        t = max(0.0, min(1.0, float(t)))
        return p1 + (p2 - p1) * t

    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                cube_vals = np.asarray(
                    [
                        field[i, j, k],
                        field[i + 1, j, k],
                        field[i + 1, j + 1, k],
                        field[i, j + 1, k],
                        field[i, j, k + 1],
                        field[i + 1, j, k + 1],
                        field[i + 1, j + 1, k + 1],
                        field[i, j + 1, k + 1],
                    ],
                    dtype=np.float64,
                )
                if float(np.max(cube_vals)) < level or float(np.min(cube_vals)) > level:
                    continue

                base = np.asarray((float(i), float(j), float(k)), dtype=np.float64)
                cube_pos = base + cube_corner_offsets

                for t0, t1, t2, t3 in tet_corner_ids:
                    ids = (t0, t1, t2, t3)
                    pos = [cube_pos[idx] for idx in ids]
                    vals = [float(cube_vals[idx]) for idx in ids]
                    inside = [v >= level for v in vals]
                    inside_count = sum(inside)
                    if inside_count in {0, 4}:
                        continue

                    if inside_count in {1, 3}:
                        if inside_count == 1:
                            ip = inside.index(True)
                            outside_ids = [x for x in range(4) if x != ip]
                            p0 = _interp(
                                pos[ip],
                                pos[outside_ids[0]],
                                vals[ip],
                                vals[outside_ids[0]],
                            )
                            p1 = _interp(
                                pos[ip],
                                pos[outside_ids[1]],
                                vals[ip],
                                vals[outside_ids[1]],
                            )
                            p2 = _interp(
                                pos[ip],
                                pos[outside_ids[2]],
                                vals[ip],
                                vals[outside_ids[2]],
                            )
                            triangles.append(
                                (_vertex_id(p0), _vertex_id(p1), _vertex_id(p2))
                            )
                        else:
                            op = inside.index(False)
                            inside_ids = [x for x in range(4) if x != op]
                            p0 = _interp(
                                pos[op],
                                pos[inside_ids[0]],
                                vals[op],
                                vals[inside_ids[0]],
                            )
                            p1 = _interp(
                                pos[op],
                                pos[inside_ids[1]],
                                vals[op],
                                vals[inside_ids[1]],
                            )
                            p2 = _interp(
                                pos[op],
                                pos[inside_ids[2]],
                                vals[op],
                                vals[inside_ids[2]],
                            )
                            triangles.append(
                                (_vertex_id(p0), _vertex_id(p2), _vertex_id(p1))
                            )
                        continue

                    in_ids = [x for x, s in enumerate(inside) if s]
                    out_ids = [x for x, s in enumerate(inside) if not s]
                    p00 = _interp(
                        pos[in_ids[0]],
                        pos[out_ids[0]],
                        vals[in_ids[0]],
                        vals[out_ids[0]],
                    )
                    p01 = _interp(
                        pos[in_ids[0]],
                        pos[out_ids[1]],
                        vals[in_ids[0]],
                        vals[out_ids[1]],
                    )
                    p10 = _interp(
                        pos[in_ids[1]],
                        pos[out_ids[0]],
                        vals[in_ids[1]],
                        vals[out_ids[0]],
                    )
                    p11 = _interp(
                        pos[in_ids[1]],
                        pos[out_ids[1]],
                        vals[in_ids[1]],
                        vals[out_ids[1]],
                    )
                    triangles.append(
                        (_vertex_id(p00), _vertex_id(p01), _vertex_id(p10))
                    )
                    triangles.append(
                        (_vertex_id(p01), _vertex_id(p11), _vertex_id(p10))
                    )

    if not vertices or not triangles:
        return np.zeros((0, 3), dtype=np.float64), []

    verts_np = np.asarray(vertices, dtype=np.float64)
    verts_world = grid_min + (verts_np * float(voxel_size)) + (float(voxel_size) * 0.5)
    return verts_world, triangles


# ===========================================================================
# BVH tree and surface smooth+snap
# ===========================================================================


def _build_source_bvh(sources, depsgraph):
    """Build a combined BVHTree from all source mesh objects.

    Vertices are placed in the coordinate space of the first source
    (root object local space) to match the marching-cubes output.
    """
    from mathutils.bvhtree import BVHTree

    all_verts: list[Vector] = []
    all_tris: list[tuple[int, int, int]] = []
    offset = 0
    for source_obj, transform in sources:
        try:
            obj_eval = source_obj.evaluated_get(depsgraph)
        except Exception:  # noqa: BLE001, S112
            continue
        mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        if mesh is None:
            continue
        try:
            mesh.calc_loop_triangles()
            loop_tris = getattr(mesh, "loop_triangles", [])
            vertices = getattr(mesh, "vertices", [])
            if not loop_tris or not vertices:
                continue
            for vert in vertices:
                co = Vector(vert.co)
                if transform is not None:
                    co = transform @ co
                all_verts.append(co)
            for tri in loop_tris:
                indices = getattr(tri, "vertices", ())
                if len(indices) == TRIANGLE_VERTEX_COUNT:
                    all_tris.append(
                        (
                            indices[0] + offset,
                            indices[1] + offset,
                            indices[2] + offset,
                        )
                    )
            offset += len(vertices)
        finally:
            with contextlib.suppress(Exception):
                obj_eval.to_mesh_clear()

    if not all_verts or not all_tris:
        return None
    return BVHTree.FromPolygons(all_verts, all_tris)


def _build_vertex_adjacency(
    num_verts: int,
    triangles: list[tuple[int, int, int]],
) -> list[list[int]]:
    """Return per-vertex neighbour lists from an indexed triangle list."""
    adj: list[set[int]] = [set() for _ in range(num_verts)]
    for i0, i1, i2 in triangles:
        adj[i0].update((i1, i2))
        adj[i1].update((i0, i2))
        adj[i2].update((i0, i1))
    return [list(s) for s in adj]


def _smooth_and_snap_to_surface(
    vertices_np: np.ndarray,
    triangles: list[tuple[int, int, int]],
    bvh_tree,
    snap_distance: float,
    iterations: int,
) -> np.ndarray:
    """Iteratively Laplacian-smooth the mesh and lock vertices that reach the source surface.

    Algorithm:
      1. Build vertex adjacency from triangles.
      2. For up to *iterations* rounds:
         a. For every **unlocked** vertex, move it toward the average of
            its neighbours (Laplacian smoothing, factor 0.5).
         b. For every **unlocked** vertex, query ``bvh_tree.find_nearest``.
            If the closest surface point is within *snap_distance*, snap the
            vertex there and mark it **locked**.
         c. Stop early if all vertices are locked.
      3. Return the modified vertex array.
    """
    num_verts = len(vertices_np)
    if num_verts == 0 or iterations <= 0:
        return vertices_np

    adj = _build_vertex_adjacency(num_verts, triangles)
    result = vertices_np.astype(np.float64).copy()
    locked = np.zeros(num_verts, dtype=bool)

    smooth_factor = 0.5

    for _iteration in range(iterations):
        # -- Laplacian smooth unlocked vertices --
        new_pos = result.copy()
        for idx in range(num_verts):
            if locked[idx]:
                continue
            neighbours = adj[idx]
            if not neighbours:
                continue
            avg = np.mean(result[neighbours], axis=0)
            new_pos[idx] = result[idx] + smooth_factor * (avg - result[idx])
        result = new_pos

        # -- Snap unlocked vertices that are close to the surface --
        any_unlocked = False
        for idx in range(num_verts):
            if locked[idx]:
                continue
            origin = Vector(result[idx].tolist())
            nearest, _normal, _face_idx, _dist = bvh_tree.find_nearest(
                origin, snap_distance
            )
            if nearest is not None:
                result[idx] = [nearest.x, nearest.y, nearest.z]
                locked[idx] = True
            else:
                any_unlocked = True

        if not any_unlocked:
            break

    return result


# ===========================================================================
# Mesh decimation - QEM edge-collapse
# ===========================================================================


def _build_face_quadrics(
    verts: np.ndarray,
    triangles: list[tuple[int, int, int]],
    n_verts: int,
) -> np.ndarray:
    """Compute per-vertex quadric matrices from incident face planes."""
    quadrics = np.zeros((n_verts, 4, 4), dtype=np.float64)
    for _ti, (a, b, c) in enumerate(triangles):
        n = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        n /= ln
        d = -np.dot(n, verts[a])
        plane = np.array([n[0], n[1], n[2], d])
        kp = np.outer(plane, plane)
        quadrics[a] += kp
        quadrics[b] += kp
        quadrics[c] += kp
    return quadrics


def _qem_optimal_pos_and_cost(
    va: int,
    vb: int,
    verts: np.ndarray,
    quadrics: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Return the optimal collapse position and its quadric error cost."""
    q_sum = quadrics[va] + quadrics[vb]
    a_mat = q_sum[:3, :3]
    b_vec = -q_sum[:3, 3]
    mid = (verts[va] + verts[vb]) * 0.5
    det = np.linalg.det(a_mat)
    if abs(det) > 1e-12:
        opt = np.linalg.solve(a_mat, b_vec)
        max_dist = np.linalg.norm(verts[va] - verts[vb]) * 2.0
        if np.linalg.norm(opt - mid) > max_dist:
            opt = mid
    else:
        opt = mid
    v4 = np.array([opt[0], opt[1], opt[2], 1.0])
    cost = float(v4 @ q_sum @ v4)
    return opt, max(cost, 0.0)


def _try_collapse(
    va: int,
    vb: int,
    new_pos: np.ndarray,
    affected: list[int],
    tri_arr: np.ndarray,
    verts: np.ndarray,
    old_normals: dict[int, np.ndarray],
) -> tuple[bool, list[int]]:
    """Trial-test an edge collapse; return (ok, degenerate_tri_indices)."""
    saved = verts[va].copy()
    verts[va] = new_pos
    collapse_ok = True
    degenerate: list[int] = []
    for ti in affected:
        a, b, c = tri_arr[ti]
        ra = va if a == vb else a
        rb = va if b == vb else b
        rc = va if c == vb else c
        if ra in (rb, rc) or rb == rc:
            degenerate.append(ti)
            continue
        if ti in old_normals:
            trial_n = np.cross(verts[rb] - verts[ra], verts[rc] - verts[ra])
            ln = np.linalg.norm(trial_n)
            if ln > 1e-12:
                trial_n /= ln
                if float(np.dot(old_normals[ti], trial_n)) < 0.0:
                    collapse_ok = False
                    break
    if not collapse_ok:
        verts[va] = saved
    return collapse_ok, degenerate


def _compact_mesh(
    verts: np.ndarray,
    tri_arr: np.ndarray,
    vert_alive: np.ndarray,
    tri_alive: np.ndarray,
    dtype: np.dtype,
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Compact vertex/triangle arrays, removing dead entries."""
    n_verts = len(verts)
    remap = np.full(n_verts, -1, dtype=np.int32)
    new_idx = 0
    for i in range(n_verts):
        if vert_alive[i]:
            remap[i] = new_idx
            new_idx += 1
    new_verts = verts[vert_alive]
    new_tris: list[tuple[int, int, int]] = []
    for ti in range(len(tri_arr)):
        if not tri_alive[ti]:
            continue
        a, b, c = int(tri_arr[ti][0]), int(tri_arr[ti][1]), int(tri_arr[ti][2])
        ra, rb, rc = int(remap[a]), int(remap[b]), int(remap[c])
        if ra >= 0 and rb >= 0 and rc >= 0 and rb not in (ra, rc) and ra != rc:
            new_tris.append((ra, rb, rc))
    return new_verts.astype(dtype), new_tris


def _decimate_mesh(
    vertices: np.ndarray,
    triangles: list[tuple[int, int, int]],
    ratio: float,
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Reduce triangle count using Quadric Error Metrics (QEM).

    *ratio* is the fraction of triangles to **keep** (1.0 = no change,
    0.5 = keep half).

    Uses Garland-Heckbert quadric error metrics so that flat regions are
    decimated first while sharp features, edges, and volume are preserved.
    Collapses that would flip a neighbouring face normal are rejected.
    """
    import heapq

    ratio = max(0.01, min(1.0, float(ratio)))
    target = max(4, int(len(triangles) * ratio))
    if len(triangles) <= target:
        return vertices, triangles

    verts = vertices.astype(np.float64).copy()
    n_verts = len(verts)

    tri_alive = np.ones(len(triangles), dtype=bool)
    vert_alive = np.ones(n_verts, dtype=bool)
    tri_arr = np.array(triangles, dtype=np.int32)

    vert_tris: list[set[int]] = [set() for _ in range(n_verts)]
    for ti, (a, b, c) in enumerate(triangles):
        vert_tris[a].add(ti)
        vert_tris[b].add(ti)
        vert_tris[c].add(ti)

    quadrics = _build_face_quadrics(verts, triangles, n_verts)

    def _face_normal(ti: int) -> np.ndarray:
        a, b, c = tri_arr[ti]
        return np.cross(verts[b] - verts[a], verts[c] - verts[a])

    # -- Build priority queue ------------------------------------------------
    generation = np.zeros(n_verts, dtype=np.int32)
    heap: list[tuple[float, int, int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for a, b, c in triangles:
        for e in ((a, b), (b, c), (a, c)):
            edge = (min(e[0], e[1]), max(e[0], e[1]))
            if edge not in seen_edges:
                seen_edges.add(edge)
                _, cost = _qem_optimal_pos_and_cost(edge[0], edge[1], verts, quadrics)
                heapq.heappush(
                    heap,
                    (
                        cost,
                        int(generation[edge[0]] + generation[edge[1]]),
                        edge[0],
                        edge[1],
                    ),
                )

    alive_count = int(np.sum(tri_alive))

    # -- Iterative collapse --------------------------------------------------
    while alive_count > target and heap:
        _cost, gen, va, vb = heapq.heappop(heap)
        if not vert_alive[va] or not vert_alive[vb]:
            continue
        if gen != int(generation[va] + generation[vb]):
            continue

        new_pos, _ = _qem_optimal_pos_and_cost(va, vb, verts, quadrics)

        affected = [ti for ti in (vert_tris[va] | vert_tris[vb]) if tri_alive[ti]]
        old_normals: dict[int, np.ndarray] = {}
        for ti in affected:
            n = _face_normal(ti)
            ln = np.linalg.norm(n)
            if ln > 1e-12:
                old_normals[ti] = n / ln

        collapse_ok, degenerate = _try_collapse(
            va,
            vb,
            new_pos,
            affected,
            tri_arr,
            verts,
            old_normals,
        )
        if not collapse_ok:
            continue

        # Accept collapse
        for ti in degenerate:
            tri_alive[ti] = False
            alive_count -= 1
        vert_alive[vb] = False
        quadrics[va] = quadrics[va] + quadrics[vb]
        generation[va] += 1

        for ti in affected:
            if not tri_alive[ti]:
                continue
            row = tri_arr[ti]
            for col in range(3):
                if row[col] == vb:
                    row[col] = va

        vert_tris[va] = vert_tris[va] | vert_tris[vb]
        vert_tris[vb] = set()

        # Push updated edges from va
        neighbours: set[int] = set()
        for ti in vert_tris[va]:
            if tri_alive[ti]:
                for col in range(3):
                    v = int(tri_arr[ti][col])
                    if v != va and vert_alive[v]:
                        neighbours.add(v)
        for vn in neighbours:
            _, c = _qem_optimal_pos_and_cost(va, vn, verts, quadrics)
            heapq.heappush(
                heap,
                (c, int(generation[va] + generation[vn]), min(va, vn), max(va, vn)),
            )

    return _compact_mesh(verts, tri_arr, vert_alive, tri_alive, vertices.dtype)


# ===========================================================================
# Mesh reconstruction pipeline
# ===========================================================================


def _build_cpu_marching_cubes_mesh(
    points: list[list[float]],
    color: tuple[float, float, float, float],
    voxel_scale: float = CPU_RECON_DEFAULT_VOXEL_SCALE,
    bvh_tree=None,
    reproject_factor: float = _REPROJECT_MAX_DIST_FACTOR,
    smooth_iterations: int = _SMOOTH_ITERATIONS_DEFAULT,
    decimation_ratio: float = _DECIMATION_RATIO_DEFAULT,
    point_colors: list[list[float]] | None = None,
) -> dict[str, list[list[float]]]:
    """Build a mesh from a point cloud via marching cubes reconstruction.

    Pipeline: density field -> iso-surface -> fix normals -> weld ->
    smooth+snap -> decimate -> flat output.

    Returns ``{"pos": [...], "col": [...], "nrm": [...],
    "wire_pos": [...], "wire_col": [...]}`` in the flat (non-indexed)
    format expected by the PRX payload.
    """
    if len(points) < TRIANGLE_VERTEX_COUNT:
        return {"pos": [], "col": [], "nrm": []}

    pts = np.asarray(points, dtype=np.float64)
    spacing = max(_estimate_point_spacing(points), 1e-6)

    # Map 0-1 detail slider to voxel size via log interpolation
    coarse_mult = 2.0
    fine_mult = 0.12
    detail = max(0.0, min(1.0, float(voxel_scale)))
    voxel_mult = coarse_mult * ((fine_mult / coarse_mult) ** detail)
    voxel_size = max(spacing * voxel_mult, 1e-6)
    pad = spacing * MARCHING_CUBES_PADDING
    grid_min = pts.min(axis=0) - pad
    grid_max = pts.max(axis=0) + pad

    def _compute_dims(cell_size: float) -> np.ndarray:
        return np.maximum(
            4, np.ceil((grid_max - grid_min) / cell_size).astype(np.int32) + 3
        )

    dims = _compute_dims(voxel_size)
    while int(np.prod(dims, dtype=np.int64)) > MARCHING_CUBES_MAX_GRID_CELLS:
        voxel_size *= 1.2
        dims = _compute_dims(voxel_size)

    # -- Build density field via rhombic splatting --
    density = np.zeros((int(dims[0]), int(dims[1]), int(dims[2])), dtype=np.float32)
    grid_idx = np.floor((pts - grid_min) / voxel_size).astype(np.int32)
    grid_idx = np.clip(grid_idx, [0, 0, 0], dims - 1)

    for offset, weight in zip(_RHOMBIC_SPLAT_OFFSETS, _RHOMBIC_SPLAT_WEIGHTS):
        shifted = grid_idx + offset
        valid = (
            (shifted[:, 0] >= 0)
            & (shifted[:, 1] >= 0)
            & (shifted[:, 2] >= 0)
            & (shifted[:, 0] < dims[0])
            & (shifted[:, 1] < dims[1])
            & (shifted[:, 2] < dims[2])
        )
        if not np.any(valid):
            continue
        idx = shifted[valid]
        np.add.at(density, (idx[:, 0], idx[:, 1], idx[:, 2]), float(weight))

    if np.max(density) <= 0.0:
        return {"pos": [], "col": [], "nrm": []}

    # -- Normalise and smooth density --
    density = np.sqrt(density)
    density = density / max(float(np.max(density)), 1e-6)

    padded = np.pad(density, 1, mode="edge")
    density = (
        padded[1:-1, 1:-1, 1:-1] * 4.0
        + padded[2:, 1:-1, 1:-1]
        + padded[:-2, 1:-1, 1:-1]
        + padded[1:-1, 2:, 1:-1]
        + padded[1:-1, :-2, 1:-1]
        + padded[1:-1, 1:-1, 2:]
        + padded[1:-1, 1:-1, :-2]
    ) / 10.0

    active = density[density > 0.0]
    if active.size < TRIANGLE_VERTEX_COUNT:
        return {"pos": [], "col": [], "nrm": []}

    # -- Determine iso-level --
    point_densities = density[grid_idx[:, 0], grid_idx[:, 1], grid_idx[:, 2]]
    min_point_density = float(np.min(point_densities))
    level = max(min_point_density * 0.75, 1e-4)

    # -- Extract iso-surface --
    vertices_np, triangles = _surface_from_scalar_field(
        density, grid_min, voxel_size, level
    )
    if len(triangles) == 0:
        return {"pos": [], "col": [], "nrm": []}

    # -- Post-process mesh --
    triangles = _fix_face_orientations(
        vertices_np, triangles, density, grid_min, voxel_size
    )
    vertices_np, triangles = _weld_close_vertices(
        vertices_np, triangles, voxel_size * 0.05
    )

    if not triangles:
        return {"pos": [], "col": [], "nrm": []}

    # Smooth and snap vertices onto source mesh surface
    if bvh_tree is not None:
        snap_dist = voxel_size * reproject_factor
        vertices_np = _smooth_and_snap_to_surface(
            vertices_np,
            triangles,
            bvh_tree,
            snap_dist,
            smooth_iterations,
        )

    # Decimate mesh
    if decimation_ratio < 1.0:
        vertices_np, triangles = _decimate_mesh(
            vertices_np, triangles, decimation_ratio
        )
        if not triangles:
            return {"pos": [], "col": [], "nrm": []}

    # -- Convert indexed mesh to flat triangle list --
    vertex_normals = _compute_vertex_normals_from_triangles(
        np.array(vertices_np, dtype=np.float32), triangles
    )
    rgb = [float(color[0]), float(color[1]), float(color[2])]

    # Build per-vertex color via closest-point transfer from sampled points
    use_point_colors = point_colors is not None and len(point_colors) == len(points)
    vertex_colors: list[list[float]] | None = None
    if use_point_colors:
        from mathutils.kdtree import KDTree  # noqa: PLC0415

        kd = KDTree(len(points))
        for i, pt in enumerate(points):
            kd.insert(pt, i)
        kd.balance()
        pc_arr = point_colors
        mesh_verts = vertices_np.tolist()
        vertex_colors = [None] * len(mesh_verts)
        for vi, mv in enumerate(mesh_verts):
            _, idx, _ = kd.find(mv)
            vertex_colors[vi] = pc_arr[idx]

    positions: list[list[float]] = []
    colors: list[list[float]] = []
    normals: list[list[float]] = []
    verts_list = vertices_np.tolist()
    for i0, i1, i2 in triangles:
        for idx in (i0, i1, i2):
            vert = verts_list[idx]
            positions.append([float(vert[0]), float(vert[1]), float(vert[2])])
            if vertex_colors is not None:
                vc = vertex_colors[idx]
                colors.append(vc[:VECTOR_LEN])
            else:
                colors.append(rgb[:])
            normals.append(vertex_normals[idx])

    # -- Extract wireframe edges --
    edge_set: set[tuple[int, int]] = set()
    for i0, i1, i2 in triangles:
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            edge_set.add((min(a, b), max(a, b)))
    wire_positions: list[list[float]] = []
    wire_colors: list[list[float]] = []
    for a, b in edge_set:
        va = verts_list[a]
        vb = verts_list[b]
        wire_positions.append([float(va[0]), float(va[1]), float(va[2])])
        wire_positions.append([float(vb[0]), float(vb[1]), float(vb[2])])
        if vertex_colors is not None:
            wire_colors.append(vertex_colors[a][:VECTOR_LEN])
            wire_colors.append(vertex_colors[b][:VECTOR_LEN])
        else:
            wire_colors.append(rgb[:])
            wire_colors.append(rgb[:])

    return {
        "pos": positions,
        "col": colors,
        "nrm": normals,
        "wire_pos": wire_positions,
        "wire_col": wire_colors,
    }


# ===========================================================================
# High-level API
# ===========================================================================


def generate_proxor(
    obj,
    *,
    include_children: bool = True,
    include_normals: bool = True,
    voxel_scale: float = CPU_RECON_DEFAULT_VOXEL_SCALE,
    reproject_factor: float = _REPROJECT_MAX_DIST_FACTOR,
    smooth_iterations: int = _SMOOTH_ITERATIONS_DEFAULT,
    decimation_ratio: float = _DECIMATION_RATIO_DEFAULT,
    context=None,
) -> dict | None:
    """Generate a PRX payload dict from a Blender object.

    Point count is derived automatically from the source vertex count
    divided by ``POINT_DIVISOR`` (capped at ``MAX_POINT_COUNT``).

    A marching-cubes mesh is reconstructed from the sampled point cloud.

    Args:
        obj: The Blender mesh object to sample.
        include_children: Whether to include child meshes.
        include_normals: Whether to compute per-point normals.
        voxel_scale: Voxel detail for marching cubes (0 = coarse, 1 = fine).
        reproject_factor: Snap distance as fraction of voxel size.
        smooth_iterations: Number of smooth-and-snap iterations.
        decimation_ratio: Fraction of triangles to keep (1.0 = all).
        context: Optional Blender context override.

    Returns:
        A full PRX payload dict ready for ``prx_format.write_prx()``
        or ``draw.ProxorLiteDrawHandler.set_payload()``, or ``None``
        if sampling fails.
    """
    if obj is None:
        return None

    ctx = context or bpy.context
    try:
        depsgraph = ctx.evaluated_depsgraph_get()
    except Exception:  # noqa: BLE001
        depsgraph = bpy.context.evaluated_depsgraph_get()

    sources = collect_sources(obj, include_children=include_children)
    if not sources:
        return None

    # Derive point count from total source vertex count
    total_verts = _count_source_vertices(sources, depsgraph)
    point_count = min(
        max(total_verts // POINT_DIVISOR, MIN_POINT_COUNT), MAX_POINT_COUNT
    )

    # Allocate samples across sources by relative surface area
    allocations = _allocate_samples_by_area(sources, point_count, depsgraph)

    aggregated_points: list[list[float]] = []
    aggregated_normals: list[list[float]] = []
    aggregated_colors: list[list[float]] = []

    for (source_obj, transform), requested in zip(sources, allocations):
        if requested <= 0:
            continue
        samples, normals, sampled_colors = _sample_uniform_surface_points(
            source_obj,
            requested,
            depsgraph=depsgraph,
            include_normals=include_normals,
            include_colors=True,
        )
        if not samples:
            continue
        transformed_points, transformed_normals = _transform_point_list(
            samples, normals, transform
        )
        aggregated_points.extend(transformed_points)
        aggregated_normals.extend(transformed_normals)
        aggregated_colors.extend(sampled_colors)

    if not aggregated_points:
        return None

    color = _resolve_object_color(obj)
    point_colors = aggregated_colors if aggregated_colors else None
    colors = _build_payload_point_colors(len(aggregated_points), point_colors, color)
    raw_normals = aggregated_normals if include_normals else None
    point_normals = _build_payload_point_normals(len(aggregated_points), raw_normals)

    points_section: dict = {"pos": aggregated_points, "col": colors}
    if point_normals:
        points_section["nrm"] = point_normals

    # Count source triangles to compare against generated mesh later
    source_tri_count = _count_source_triangles(sources, depsgraph)

    # Build BVH tree from source meshes for reprojection
    bvh_tree = _build_source_bvh(sources, depsgraph)

    # Marching cubes mesh reconstruction from the sampled point cloud
    mesh_section = _build_cpu_marching_cubes_mesh(
        aggregated_points,
        color,
        voxel_scale,
        bvh_tree,
        reproject_factor,
        smooth_iterations,
        decimation_ratio,
        point_colors=aggregated_colors if aggregated_colors else None,
    )

    # If generated mesh has more triangles than the source, use source directly
    generated_tri_count = len(mesh_section.get("pos", [])) // 3
    if source_tri_count > 0 and generated_tri_count >= source_tri_count:
        return generate_proxor_direct(
            obj,
            include_children=include_children,
            include_normals=include_normals,
            context=context,
        )

    _convert_normals_to_prx(mesh_section.get("nrm"))

    # Extract wireframe lines from mesh reconstruction
    wire_pos = mesh_section.pop("wire_pos", [])
    wire_col = mesh_section.pop("wire_col", [])
    line_section = {"pos": wire_pos, "col": wire_col}

    payload = {
        "objects": [],
        "legacy": {
            "mesh": mesh_section,
            "line": line_section,
            "points": points_section,
            "text": {"pos": [], "col": [], "str": []},
        },
    }
    _apply_transform_to_payload(payload, _BLENDER_TO_PRX)
    return payload


def generate_proxor_multi(
    objects: list,
    *,
    include_normals: bool = True,
    voxel_scale: float = CPU_RECON_DEFAULT_VOXEL_SCALE,
    reproject_factor: float = _REPROJECT_MAX_DIST_FACTOR,
    smooth_iterations: int = _SMOOTH_ITERATIONS_DEFAULT,
    decimation_ratio: float = _DECIMATION_RATIO_DEFAULT,
    context=None,
) -> dict | None:
    """Generate a single PRX payload from multiple Blender objects.

    Collects mesh sources from all provided objects (without recursing
    into children, since the full object list is already provided),
    then runs the same sampling and reconstruction pipeline as
    ``generate_proxor``.

    Args:
        objects: List of Blender objects to include.
        include_normals: Whether to compute per-point normals.
        voxel_scale: Voxel detail for marching cubes.
        reproject_factor: Snap distance as fraction of voxel size.
        smooth_iterations: Number of smooth-and-snap iterations.
        decimation_ratio: Fraction of triangles to keep.
        context: Optional Blender context override.

    Returns:
        A full PRX payload dict or ``None`` if no mesh data found.
    """
    if not objects:
        return None

    ctx = context or bpy.context
    try:
        depsgraph = ctx.evaluated_depsgraph_get()
    except Exception:  # noqa: BLE001
        depsgraph = bpy.context.evaluated_depsgraph_get()

    # Collect all mesh sources from provided objects (no child recursion)
    sources: list[tuple] = []
    for obj in objects:
        if obj is None:
            continue
        if getattr(obj, "type", "") == "MESH":
            sources.append((obj, None))

    if not sources:
        return None

    # Derive point count from total source vertex count
    total_verts = _count_source_vertices(sources, depsgraph)
    point_count = min(
        max(total_verts // POINT_DIVISOR, MIN_POINT_COUNT), MAX_POINT_COUNT
    )

    # Allocate samples across sources by relative surface area
    allocations = _allocate_samples_by_area(sources, point_count, depsgraph)

    aggregated_points: list[list[float]] = []
    aggregated_normals: list[list[float]] = []
    aggregated_colors: list[list[float]] = []

    for (source_obj, transform), requested in zip(sources, allocations):
        if requested <= 0:
            continue
        samples, normals, sampled_colors = _sample_uniform_surface_points(
            source_obj,
            requested,
            depsgraph=depsgraph,
            include_normals=include_normals,
            include_colors=True,
        )
        if not samples:
            continue
        transformed_points, transformed_normals = _transform_point_list(
            samples, normals, transform
        )
        aggregated_points.extend(transformed_points)
        aggregated_normals.extend(transformed_normals)
        aggregated_colors.extend(sampled_colors)

    if not aggregated_points:
        return None

    color = _resolve_object_color(objects[0])
    point_colors = aggregated_colors if aggregated_colors else None
    colors = _build_payload_point_colors(len(aggregated_points), point_colors, color)
    raw_normals = aggregated_normals if include_normals else None
    point_normals = _build_payload_point_normals(len(aggregated_points), raw_normals)

    points_section: dict = {"pos": aggregated_points, "col": colors}
    if point_normals:
        points_section["nrm"] = point_normals

    # Build BVH tree from source meshes for reprojection
    bvh_tree = _build_source_bvh(sources, depsgraph)

    # Marching cubes mesh reconstruction from the sampled point cloud
    mesh_section = _build_cpu_marching_cubes_mesh(
        aggregated_points,
        color,
        voxel_scale,
        bvh_tree,
        reproject_factor,
        smooth_iterations,
        decimation_ratio,
        point_colors=aggregated_colors if aggregated_colors else None,
    )
    _convert_normals_to_prx(mesh_section.get("nrm"))

    # Extract wireframe lines from mesh reconstruction
    wire_pos = mesh_section.pop("wire_pos", [])
    wire_col = mesh_section.pop("wire_col", [])
    line_section = {"pos": wire_pos, "col": wire_col}

    payload = {
        "objects": [],
        "legacy": {
            "mesh": mesh_section,
            "line": line_section,
            "points": points_section,
            "text": {"pos": [], "col": [], "str": []},
        },
    }
    _apply_transform_to_payload(payload, _BLENDER_TO_PRX)
    return payload


# ===========================================================================
# Direct mesh conversion (no sampling / marching cubes)
# ===========================================================================

_FAKE_AO_BOTTOM = 0.35
_FAKE_AO_TOP = 0.95


def _fake_ao_color_from_normal(normal) -> list[float]:
    """Generate a fake ambient-occlusion grey from the vertex normal Z component."""
    z_value = float(normal[2]) if len(normal) > 2 else 0.0
    z_clamped = max(-1.0, min(1.0, z_value))
    strength = (z_clamped + 1.0) * 0.5
    value = _FAKE_AO_BOTTOM + strength * (_FAKE_AO_TOP - _FAKE_AO_BOTTOM)
    return [value, value, value, 1.0]


def _resolve_loop_color(
    mesh,
    loop_idx: int,
    vertex_idx: int,
    uv_layer=None,
    texture_cache: tuple | None = None,
) -> list[float]:
    """Return per-loop RGBA from texture, vertex colors, color attributes, or fake AO."""
    # Try diffuse texture sampling via UV
    if uv_layer is not None and texture_cache is not None:
        px_cache, tex_w, tex_h = texture_cache
        if tex_w > 0 and tex_h > 0:
            uv = uv_layer.data[loop_idx].uv
            return _sample_texture_at_uv(px_cache, tex_w, tex_h, float(uv[0]), float(uv[1]))
    # Try legacy vertex_colors
    layer = getattr(getattr(mesh, "vertex_colors", None), "active", None)
    if layer and layer.data:
        color = list(layer.data[loop_idx].color[:RGBA_LEN])
        if len(color) < RGBA_LEN:
            color.extend([1.0] * (RGBA_LEN - len(color)))
        return [_clamp01(c) for c in color]
    # Try color_attributes
    color_attributes = getattr(mesh, "color_attributes", None)
    if color_attributes:
        attribute = getattr(color_attributes, "active", None)
        if (
            attribute
            and attribute.domain == "CORNER"
            and attribute.data_type in {"BYTE_COLOR", "FLOAT_COLOR"}
        ):
            color = list(attribute.data[loop_idx].color[:RGBA_LEN])
            if len(color) < RGBA_LEN:
                color.extend([1.0] * (RGBA_LEN - len(color)))
            return [_clamp01(c) for c in color]
    # Fallback: fake AO from vertex normal
    normal = mesh.vertices[vertex_idx].normal
    return _fake_ao_color_from_normal(normal)


def _collect_direct_mesh_data(
    mesh,
    combined_matrix: Matrix,
    linear_matrix: Matrix,
    *,
    include_normals: bool = True,
    include_colors: bool = True,
    source_obj=None,
) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    """Read triangle face data directly from a Blender mesh.

    Returns:
        (positions, normals, colors) – flat lists with 3 entries per triangle.
    """
    positions: list[list[float]] = []
    normals: list[list[float]] = []
    colors: list[list[float]] = []

    # Prepare texture cache for colour sampling
    uv_layer = None
    texture_cache = None
    if include_colors:
        uv_layer_obj = getattr(mesh, "uv_layers", None)
        uv_layer = getattr(uv_layer_obj, "active", None)
        if uv_layer is not None and source_obj is not None:
            image = _find_diffuse_image(source_obj)
            if image is not None:
                texture_cache = _build_image_pixel_cache(image)
                if texture_cache[1] <= 0:
                    texture_cache = None

    for tri in getattr(mesh, "loop_triangles", []):
        for loop_idx in tri.loops:
            loop = mesh.loops[loop_idx]
            vertex_idx = loop.vertex_index
            vertex = mesh.vertices[vertex_idx]

            pos = combined_matrix @ vertex.co.to_4d()
            positions.append(list(pos[:VECTOR_LEN]))

            if include_normals:
                transformed_normal = (linear_matrix @ vertex.normal).normalized()
                normals.append(list(transformed_normal))

            if include_colors:
                colors.append(_resolve_loop_color(mesh, loop_idx, vertex_idx, uv_layer, texture_cache))

    return positions, normals, colors


def _collect_direct_line_data(
    mesh,
    combined_matrix: Matrix,
) -> list[list[float]]:
    """Read edge wireframe data directly from a Blender mesh.

    Returns:
        Flat list of positions – 2 entries per edge segment.
    """
    vertex_positions = {
        v.index: list((combined_matrix @ v.co.to_4d())[:VECTOR_LEN])
        for v in mesh.vertices
    }
    segments: list[list[float]] = []
    for edge in mesh.edges:
        v1, v2 = edge.vertices
        p1 = vertex_positions.get(v1)
        p2 = vertex_positions.get(v2)
        if p1 and p2 and p1 != p2:
            segments.append(p1)
            segments.append(p2)
    return segments


def generate_proxor_direct(
    obj,
    *,
    include_children: bool = True,
    include_normals: bool = True,
    include_colors: bool = True,
    context=None,
) -> dict | None:
    """Generate a PRX payload by reading mesh geometry directly.

    Unlike :func:`generate_proxor` this does **not** sample random surface
    points or run marching-cubes reconstruction.  Instead it reads the
    actual vertices, faces, normals, and colours from the Blender mesh
    and packages them into the standard payload dict.

    Args:
        obj: The Blender mesh object to convert.
        include_children: Whether to include child meshes.
        include_normals: Whether to include per-vertex normals.
        include_colors: Whether to include per-vertex colours.
        context: Optional Blender context override.

    Returns:
        A full PRX payload dict ready for ``prx_format.write_prx()``
        or ``draw.ProxorLiteDrawHandler.set_payload()``, or ``None``
        if the object has no mesh data.
    """
    if obj is None:
        return None

    ctx = context or bpy.context
    try:
        depsgraph = ctx.evaluated_depsgraph_get()
    except Exception:  # noqa: BLE001
        depsgraph = bpy.context.evaluated_depsgraph_get()

    sources = collect_sources(obj, include_children=include_children)
    if not sources:
        return None

    all_positions: list[list[float]] = []
    all_normals: list[list[float]] = []
    all_colors: list[list[float]] = []
    all_line_positions: list[list[float]] = []

    for source_obj, transform in sources:
        try:
            obj_eval = source_obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        except Exception:  # noqa: BLE001
            continue
        if mesh is None:
            continue

        try:
            mesh.calc_loop_triangles()

            # Build combined transform: optional parent-relative × identity
            if transform is not None:
                combined_matrix = transform
            else:
                combined_matrix = Matrix.Identity(4)

            linear_matrix = combined_matrix.to_3x3()

            positions, normals, colors = _collect_direct_mesh_data(
                mesh,
                combined_matrix,
                linear_matrix,
                include_normals=include_normals,
                include_colors=include_colors,
                source_obj=source_obj,
            )
            all_positions.extend(positions)
            all_normals.extend(normals)
            all_colors.extend(colors)

            line_positions = _collect_direct_line_data(mesh, combined_matrix)
            all_line_positions.extend(line_positions)

        finally:
            with contextlib.suppress(Exception):
                obj_eval.to_mesh_clear()

    if not all_positions:
        return None

    # Build mesh section
    mesh_section: dict = {"pos": all_positions}
    if include_colors and all_colors:
        mesh_section["col"] = all_colors
    else:
        color = _resolve_object_color(obj)
        mesh_section["col"] = [list(color[:VECTOR_LEN])] * len(all_positions)
    if include_normals and all_normals:
        _convert_normals_to_prx(all_normals)
        mesh_section["nrm"] = all_normals

    # Build line section (flat pairs of positions, uniform color)
    color = _resolve_object_color(obj)
    line_col = (
        [list(color[:VECTOR_LEN])] * (len(all_line_positions) // 2)
        if all_line_positions
        else []
    )
    line_section: dict = {"pos": all_line_positions, "col": line_col}

    # Build empty points section (no sampling needed)
    points_section: dict = {"pos": [], "col": []}

    payload = {
        "objects": [],
        "legacy": {
            "mesh": mesh_section,
            "line": line_section,
            "points": points_section,
            "text": {"pos": [], "col": [], "str": []},
        },
    }
    _apply_transform_to_payload(payload, _BLENDER_TO_PRX)
    return payload


__all__ = [
    "collect_sources",
    "generate_proxor",
    "generate_proxor_direct",
    "generate_proxor_multi",
]
