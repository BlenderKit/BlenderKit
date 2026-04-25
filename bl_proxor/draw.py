"""GPU drawing pipeline for Proxor Lite.

Builds GPU shader batches from PRX payload dicts and draws them to the viewport.
Self-contained - does not depend on the full ``proxor`` package.
"""

from __future__ import annotations

import contextlib
import copy
from array import array
from types import SimpleNamespace
from typing import Optional

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

# -- Constants --

TARGET_DIMENSIONS = 2
LINE_POINT_COUNT = 2
VECTOR_SIZE = 3
RGBA_CHANNELS = 4
RGB_CHANNELS = 3
SRGB_LINEAR_THRESHOLD = 0.0031308
SRGB_GAMMA_THRESHOLD = 0.04045

# Color mode tokens
COLOR_MODE_ORIGINAL = "ORIGINAL"
COLOR_MODE_RANDOM = "RANDOM"
COLOR_MODE_CUSTOM = "CUSTOM"

# Shading / lighting defaults
DEFAULT_LIGHT_DIR = (0.0, 0.0, 1.0)
DEFAULT_VIEW_DIR = (0.0, 0.0, 1.0)
DEFAULT_AMBIENT = 0.25
DEFAULT_DIFFUSE = 0.85
DEFAULT_SPECULAR = 0.25
DEFAULT_SHININESS = 10.0
SHADING_MODE_PHONG = "PHONG"
SHADING_MODE_FLAT = "FLAT"

# -- Shader cache --
# Populated lazily or explicitly via ``ensure_shaders()``.
_shader_cache: dict[str, gpu.types.GPUShader] = {}


def ensure_shaders() -> None:
    """Pre-compile and cache all GPU shaders used by the proxor draw pipeline.

    Safe to call repeatedly - already-compiled shaders are skipped.
    Must be called from the main thread with a valid GL context (e.g. during
    addon ``register()``).  No-op in background mode (no GPU context).
    """
    if bpy.app.background:
        return
    _get_cached_shader("smooth_color")
    _get_cached_shader("polyline_smooth_color")
    _get_cached_shader("uniform_color")
    _get_cached_shader("outline")
    if bpy.app.version >= (4, 5, 0):
        _get_cached_shader("ppc")
        _get_cached_shader("blinn")


def _get_cached_shader(name: str) -> Optional[gpu.types.GPUShader]:
    """Return a cached shader by *name*, compiling it on first access."""
    cached = _shader_cache.get(name)
    if cached is not None:
        return cached

    shader: Optional[gpu.types.GPUShader] = None
    if name == "smooth_color":
        builtin = "3D_SMOOTH_COLOR" if bpy.app.version < (4, 0, 0) else "SMOOTH_COLOR"
        shader = gpu.shader.from_builtin(builtin)
    elif name == "polyline_smooth_color":
        builtin = (
            "3D_POLYLINE_SMOOTH_COLOR"
            if bpy.app.version < (4, 0, 0)
            else "POLYLINE_SMOOTH_COLOR"
        )
        shader = gpu.shader.from_builtin(builtin)
    elif name == "uniform_color":
        if bpy.app.version < (4, 0, 0):
            shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
        elif bpy.app.version < (4, 5, 0):
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        else:
            info = _create_uniform_shader_info()
            if info is not None:
                shader = gpu.shader.create_from_info(info)
    elif name == "ppc":
        info = _create_ppc_shader_info()
        if info is not None:
            shader = gpu.shader.create_from_info(info)
    elif name == "blinn":
        info = _create_mesh_blinn_shader_info()
        if info is not None:
            shader = gpu.shader.create_from_info(info)
    elif name == "outline":
        if bpy.app.version < (4, 0, 0):
            shader = _create_outline_shader_legacy()
        else:
            info = _create_outline_shader_info()
            if info is not None:
                shader = gpu.shader.create_from_info(info)

    if shader is not None:
        _shader_cache[name] = shader
    return shader


def invalidate_shader_cache() -> None:
    """Clear all cached shaders (e.g. on unregister)."""
    _shader_cache.clear()


# -- Colour-space helpers --


def to_srgb(vertex_colors: np.ndarray) -> np.ndarray:
    """Convert linear RGB colours to sRGB."""
    return np.clip(
        np.where(
            vertex_colors < SRGB_LINEAR_THRESHOLD,
            12.92 * vertex_colors,
            1.055 * np.power(vertex_colors, 1.0 / 2.4) - 0.055,
        ),
        0,
        1,
    )


def to_linear(vertex_colors: np.ndarray) -> np.ndarray:
    """Convert sRGB colours to linear RGB."""
    return np.clip(
        np.where(
            vertex_colors >= SRGB_GAMMA_THRESHOLD,
            ((vertex_colors + 0.055) / 1.055) ** 2.4,
            vertex_colors / 12.92,
        ),
        0,
        1,
    )


def _apply_color_profile(rgb: np.ndarray, color_type: str) -> np.ndarray:
    if color_type == "sRGB":
        return to_srgb(rgb)
    if color_type == "Linear":
        return to_linear(rgb)
    return rgb


# -- Gradient helpers --

GRADIENT_LOW = 0.35
GRADIENT_HIGH = 1.0
# Width of the alpha transition band as a fraction of mesh height.
GRADIENT_BAND_WIDTH = 0.10
# Permanent hologram alpha: alpha at top of mesh even when fully revealed (vis_pct=100).
# Bottom of mesh always has alpha=1.0; top fades to this value.
GRADIENT_ALPHA_TOP = 0.45


def _apply_vertical_gradient(
    colors: np.ndarray, z_values: np.ndarray, vis_pct: float = 100.0
) -> np.ndarray:
    """Modulate RGB brightness and alpha by vertical position (Z in Blender space).

    Alpha is the product of two independent layers:
    - **Hologram alpha**: bottom=1.0, top=GRADIENT_ALPHA_TOP, always active.
      Gives the mesh a ghost/hologram look even when fully revealed.
    - **Reveal alpha**: smoothstep band that sweeps upward with *vis_pct* (0-100).
      Below the band -> 1 (visible), above the band -> 0 (hidden).

    At vis_pct=100 the band is above the mesh so reveal_alpha=1 everywhere,
    leaving only the hologram gradient visible (top is semi-transparent).
    At vis_pct=0 the band is below the mesh so the whole mesh is hidden.
    """
    z_min = float(np.min(z_values))
    z_max = float(np.max(z_values))
    z_range = z_max - z_min
    if z_range < 1e-8:
        return colors
    t = (z_values - z_min) / z_range  # 0=bottom, 1=top
    # RGB brightness gradient (darker at bottom, brighter at top).
    v_mult = GRADIENT_LOW + (GRADIENT_HIGH - GRADIENT_LOW) * t
    # Layer 1: permanent hologram alpha (1.0 at bottom, GRADIENT_ALPHA_TOP at top).
    hologram_alpha = 1.0 + (GRADIENT_ALPHA_TOP - 1.0) * t
    # Layer 2: reveal band sweeps from below mesh (vis_pct=0) to above (vis_pct=100).
    half = GRADIENT_BAND_WIDTH * 0.5
    band_center = -half + (vis_pct / 100.0) * (1.0 + GRADIENT_BAND_WIDTH)
    band_low = band_center - half
    band_high = band_center + half
    band_span = max(band_high - band_low, 1e-8)
    s = np.clip((t - band_low) / band_span, 0.0, 1.0)
    reveal_alpha = 1.0 - (
        s * s * (3.0 - 2.0 * s)
    )  # smoothstep, opaque below → transparent above
    # Final alpha: hologram * reveal.
    alpha = hologram_alpha * reveal_alpha
    out = colors.copy()
    out[:, :RGB_CHANNELS] *= v_mult[:, np.newaxis]
    np.clip(out[:, :RGB_CHANNELS], 0.0, 1.0, out=out[:, :RGB_CHANNELS])
    out[:, 3] = alpha
    return out


# -- Shader factories --


def _create_uniform_shader_info():
    if bpy.app.version < (4, 5, 0):
        return None
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("VEC4", "color")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        "void main() { gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0); }"
    )
    info.fragment_source("void main() { fragColor = color; }")
    return info


def _create_ppc_shader_info(size_uniform: bool = True):
    """Per-point colour shader for Blender >= 4.5."""
    if bpy.app.version < (4, 5, 0):
        return None
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC4", "vcol")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    if size_uniform:
        info.push_constant("FLOAT", "pointSize")

    iface = gpu.types.GPUStageInterfaceInfo("v_iface")
    iface.smooth("VEC4", "vcol_out")
    info.vertex_out(iface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        f"""
        void main() {{
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
            {"gl_PointSize = pointSize;" if size_uniform else ""}
            vcol_out = vcol;
        }}
    """,
    )
    info.fragment_source("void main() { fragColor = vcol_out; }")
    return info


def _create_mesh_blinn_shader_info():
    """Blinn-Phong lit mesh shader for Blender >= 4.5."""
    if bpy.app.version < (4, 5, 0):
        return None
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC3", "normal")
    info.vertex_in(2, "VEC4", "vcol")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("MAT3", "NormalMatrix")
    info.typedef_source(
        """
        struct ProxorLightingData {
            vec4 light_dir;
            vec4 view_dir;
            vec4 shading_factors;
        };
    """
    )
    info.uniform_buf(0, "ProxorLightingData", "LightingData")
    iface = gpu.types.GPUStageInterfaceInfo("v_iface")
    iface.smooth("VEC4", "vcol_out")
    iface.smooth("VEC3", "normal_out")
    info.vertex_out(iface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main() {
            vec3 normal_view = normalize(NormalMatrix * normal);
            vcol_out = vcol;
            normal_out = normal_view;
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
        }
    """
    )
    info.fragment_source(
        """
        void main() {
            vec3 n = normalize(normal_out);
            vec3 light_dir = normalize(LightingData.light_dir.xyz);
            vec3 view_dir = normalize(LightingData.view_dir.xyz);
            float diff = max(dot(n, light_dir), 0.0);
            vec3 halfway_dir = normalize(light_dir + view_dir);
            float spec = pow(max(dot(n, halfway_dir), 0.0), LightingData.shading_factors.w);
            vec3 albedo = vcol_out.rgb;
            float ambient = LightingData.shading_factors.x;
            float diffuse = LightingData.shading_factors.y;
            float specular_strength = LightingData.shading_factors.z;
            vec3 lit = albedo * (ambient + diffuse * diff);
            vec3 specular = vec3(specular_strength * spec);
            vec3 final_rgb = clamp(lit + specular, 0.0, 1.0);
            fragColor = vec4(final_rgb, vcol_out.a);
        }
    """
    )
    return info


def _create_outline_shader_info():
    """Back-face silhouette outline shader (Blender >= 4.0).

    Expands back-face vertices along their clip-space normals to create a
    screen-space outline ring that mimics Blender's selection highlight.
    Draw this pass BEFORE the mesh (front-face) pass with FRONT face culling
    so only the expanded rim outside the mesh silhouette is visible.
    """
    if bpy.app.version < (4, 0, 0):
        return None
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC3", "normal")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("FLOAT", "outlineWidth")
    info.push_constant("VEC4", "outlineColor")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main() {
            vec4 clip_pos = ModelViewProjectionMatrix * vec4(pos, 1.0);
            // Project the normal into clip space XY to get expansion direction.
            // Multiplying by clip_pos.w converts the NDC offset to clip space,
            // giving a constant screen-space width regardless of depth.
            vec4 clip_nrm = ModelViewProjectionMatrix * vec4(normal, 0.0);
            vec2 n = normalize(clip_nrm.xy + vec2(1e-8, 0.0));
            clip_pos.xy += n * outlineWidth * clip_pos.w;
            gl_Position = clip_pos;
        }
    """
    )
    info.fragment_source(
        """
        void main() {
            fragColor = outlineColor;
        }
    """
    )
    return info


_OUTLINE_VERT_LEGACY = """
uniform mat4 ModelViewProjectionMatrix;
uniform float outlineWidth;
in vec3 pos;
in vec3 normal;
void main() {
    vec4 clip_pos = ModelViewProjectionMatrix * vec4(pos, 1.0);
    vec4 clip_nrm = ModelViewProjectionMatrix * vec4(normal, 0.0);
    vec2 n = normalize(clip_nrm.xy + vec2(1e-8, 0.0));
    clip_pos.xy += n * outlineWidth * clip_pos.w;
    gl_Position = clip_pos;
}
"""

_OUTLINE_FRAG_LEGACY = """
uniform vec4 outlineColor;
out vec4 fragColor;
void main() {
    fragColor = outlineColor;
}
"""


def _create_outline_shader_legacy() -> Optional[gpu.types.GPUShader]:
    """Back-face silhouette outline shader for Blender < 4.0.

    Uses the legacy ``GPUShader(vertex_source, fragment_source)`` constructor,
    which is the only shader creation path available before the
    ``gpu.shader.create_from_info`` API was introduced in Blender 4.0.
    """
    try:
        return gpu.types.GPUShader(_OUTLINE_VERT_LEGACY, _OUTLINE_FRAG_LEGACY)
    except Exception:
        return None


# -- Colour resolution helpers --


def _resolve_uniform_color(
    color_mode: str, ctx
) -> Optional[tuple[float, float, float, float]]:
    """Return an override RGBA if *color_mode* requires one, else ``None``."""
    if color_mode == COLOR_MODE_ORIGINAL:
        return None
    if color_mode == COLOR_MODE_CUSTOM:
        c = getattr(ctx, "custom_color", None)
        if c is None:
            return None
        if len(c) >= RGBA_CHANNELS:
            return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
        if len(c) >= RGB_CHANNELS:
            return (float(c[0]), float(c[1]), float(c[2]), 1.0)
        return None
    if color_mode == COLOR_MODE_RANDOM:
        return getattr(ctx, "random_color", None)
    return None


def _uniform_color_array(color: tuple, count: int, color_type: str) -> np.ndarray:
    rgb = np.array([[color[0], color[1], color[2]]], dtype="f")
    rgb = _apply_color_profile(rgb, color_type)
    alpha = color[3] if len(color) > RGB_CHANNELS else 1.0
    return np.concatenate(
        (np.repeat(rgb, count, axis=0), np.full((count, 1), alpha, dtype="f")),
        axis=1,
    )


def _prepare_mesh_colors(raw: Optional[list], color_type: str) -> Optional[np.ndarray]:
    if not raw:
        return None
    arr = np.array(raw, dtype="f")
    if (
        arr.ndim != TARGET_DIMENSIONS
        or arr.shape[0] == 0
        or arr.shape[1] < RGB_CHANNELS
    ):
        return None
    rgb = _apply_color_profile(arr[:, :RGB_CHANNELS] * 2, color_type)
    return np.concatenate((rgb, np.ones((arr.shape[0], 1), dtype="f")), axis=1)


def _prepare_point_colors(
    raw: Optional[list], color_type: str
) -> tuple[Optional[np.ndarray], bool]:
    if not raw:
        return None, False
    arr = np.asarray(raw, dtype="f")
    if arr.ndim != TARGET_DIMENSIONS or arr.shape[0] == 0:
        return None, False
    # Ensure we own the buffer before mutating (np.asarray may share memory).
    arr = arr.copy()
    channels = min(arr.shape[1], RGB_CHANNELS)
    if channels:
        arr[:, :channels] *= 2
    if arr.shape[1] < RGBA_CHANNELS:
        arr = np.concatenate(
            (arr, np.ones((arr.shape[0], RGBA_CHANNELS - arr.shape[1]), dtype="f")),
            axis=1,
        )
    elif arr.shape[1] > RGBA_CHANNELS:
        arr = arr[:, :RGBA_CHANNELS]
    arr[:, :RGB_CHANNELS] = _apply_color_profile(arr[:, :RGB_CHANNELS], color_type)
    return arr, True


# -- Geometry transform helpers --


def _transform_positions(pos_raw, scale: float) -> Optional[np.ndarray]:
    """Convert raw position list to an axis-swapped, scaled float32 array.

    Returns ``None`` if the data is malformed or empty. The returned array is
    always a new buffer safe to mutate downstream.
    """
    if not pos_raw:
        return None
    arr = np.asarray(pos_raw, dtype="f")
    if arr.ndim != TARGET_DIMENSIONS or arr.shape[0] == 0 or arr.shape[1] < VECTOR_SIZE:
        return None
    if arr.shape[1] > VECTOR_SIZE:
        arr = arr[:, :VECTOR_SIZE]
    else:
        arr = arr.copy()  # ensure we own the buffer before mutating
    arr[:, [1, 2]] = arr[:, [2, 1]]
    arr *= 0.01 * float(scale)
    return arr


def _transform_normals(nrm_raw, expected_count: int) -> Optional[np.ndarray]:
    """Axis-swap and normalize a raw normal list; pad/trim to *expected_count*."""
    if not nrm_raw or expected_count <= 0:
        return None
    arr = np.asarray(nrm_raw, dtype="f")
    if arr.ndim != TARGET_DIMENSIONS or arr.shape[0] != expected_count:
        return None
    if arr.shape[1] > VECTOR_SIZE:
        arr = arr[:, :VECTOR_SIZE]
    else:
        arr = arr.copy()
    arr[:, [1, 2]] = arr[:, [2, 1]]
    lengths = np.linalg.norm(arr, axis=1, keepdims=True)
    with np.errstate(invalid="ignore"):
        np.divide(arr, lengths, out=arr, where=lengths != 0)
    return arr


def _get_mvp() -> Matrix:
    """Return the current GPU model-view-projection matrix."""
    get_mv = getattr(gpu.matrix, "get_model_view_matrix", None)
    get_proj = getattr(gpu.matrix, "get_projection_matrix", None)
    mv = get_mv() if get_mv else Matrix.Identity(4)
    proj = get_proj() if get_proj else Matrix.Identity(4)
    return proj @ mv


# -- Batch builder --


class ProxorLiteDrawBuilder:
    """Build GPU-ready draw data from a PRX payload dict."""

    # -- mesh --

    @staticmethod
    def _mesh_colors_with_override(color_data, ctx, vertex_count: int):
        mode = getattr(ctx, "mesh_color_mode", COLOR_MODE_ORIGINAL)
        override = _resolve_uniform_color(mode, ctx)
        if override is not None:
            # Skip decoding the per-vertex colours — they would be discarded.
            return _uniform_color_array(override, vertex_count, ctx.mesh_color_type)
        return _prepare_mesh_colors(color_data, ctx.mesh_color_type)

    @staticmethod
    def _build_mesh_shader(normals: Optional[np.ndarray], ctx):
        """Pick mesh shader based on shading mode + normals availability.

        *normals* must already be axis-swapped and normalized (see
        :func:`_transform_normals`). Returns ``(shader, use_blinn, lighting)``.
        """
        shading_mode = getattr(ctx, "mesh_shading_mode", SHADING_MODE_PHONG)
        if (
            shading_mode == SHADING_MODE_PHONG
            and normals is not None
            and bpy.app.version >= (4, 5, 0)
        ):
            shader = _get_cached_shader("blinn")
            if shader is not None:
                lighting = {
                    "light_dir": DEFAULT_LIGHT_DIR,
                    "view_dir": DEFAULT_VIEW_DIR,
                    "ambient": DEFAULT_AMBIENT,
                    "diffuse": DEFAULT_DIFFUSE,
                    "specular": DEFAULT_SPECULAR,
                    "shininess": DEFAULT_SHININESS,
                    "_ubo": None,
                }
                return shader, True, lighting
        return _get_cached_shader("smooth_color"), False, None

    def _prepare_mesh_draw(self, mesh_data, verts: np.ndarray, normals, ctx):
        """Build the mesh batch from pre-transformed *verts* and *normals*."""
        colors = self._mesh_colors_with_override(mesh_data.get("col"), ctx, len(verts))
        if colors is None or colors.shape[0] != verts.shape[0]:
            return None

        # Apply vertical gradient (returns a new array, safe to mutate).
        if getattr(ctx, "use_gradient", True):
            colors = _apply_vertical_gradient(
                colors, verts[:, 2], getattr(ctx, "visibility_input", 100)
            )

        visibility = getattr(ctx, "mesh_visibility", 1.0)
        if visibility < 1.0:
            colors[:, 3] *= visibility  # gradient already returned a fresh buffer

        shader, use_blinn, lighting = self._build_mesh_shader(normals, ctx)
        attrs: dict = {"pos": verts}
        if use_blinn and normals is not None:
            attrs["normal"] = normals
            attrs["vcol"] = colors
        else:
            attrs["color"] = colors

        indices = np.arange(len(verts), dtype=np.int32).reshape((-1, 3))
        batch = batch_for_shader(shader, "TRIS", attrs, indices=indices)
        return {
            "batches": [batch],
            "shader": shader,
            "blinn": use_blinn,
            "lighting": lighting,
        }

    # -- lines --

    def _prepare_line_draw(self, line_data, ctx):
        if not line_data:
            return None
        pts = _transform_positions(line_data.get("pos"), ctx.scale)
        if pts is None:
            return None

        indices = np.arange(len(pts), dtype=np.int32).reshape(-1, LINE_POINT_COUNT)
        color_type = ctx.line_color_type
        override = _resolve_uniform_color(
            getattr(ctx, "line_color_mode", COLOR_MODE_ORIGINAL), ctx
        )
        if override is not None:
            colors = _uniform_color_array(override, len(pts), color_type)
        else:
            raw = line_data.get("col")
            base = None
            if raw is not None:
                base = np.asarray(raw, dtype="f") * 2
                if base.ndim != TARGET_DIMENSIONS or base.shape[0] == 0:
                    base = None
            if base is None:
                base = np.full((len(pts), RGB_CHANNELS), 0.5, dtype="f")
            elif len(base) != len(pts):
                base = np.repeat(base, LINE_POINT_COUNT, axis=0)
            base = _apply_color_profile(base[:, :RGB_CHANNELS], color_type)
            colors = np.concatenate((base, np.ones((len(base), 1), dtype="f")), axis=1)

        shader = _get_cached_shader("polyline_smooth_color")
        batch = batch_for_shader(
            shader, "LINES", {"pos": pts, "color": colors}, indices=indices
        )
        return {"batch": batch, "shader": shader}

    # -- points --

    def _prepare_point_draw(self, point_data, ctx):
        if not point_data:
            return None
        pts = _transform_positions(point_data.get("pos"), ctx.scale)
        if pts is None:
            return None

        point_colors, has_colors = _prepare_point_colors(
            point_data.get("col"), ctx.mesh_color_type
        )
        override = _resolve_uniform_color(
            getattr(ctx, "point_color_mode", COLOR_MODE_ORIGINAL), ctx
        )
        if override is not None:
            point_colors = _uniform_color_array(override, len(pts), ctx.mesh_color_type)
            has_colors = True
        elif has_colors and point_colors is not None:
            point_colors = np.asarray(point_colors, dtype="f")

        if has_colors and point_colors is not None:
            if getattr(ctx, "use_gradient", True):
                point_colors = _apply_vertical_gradient(
                    point_colors, pts[:, 2], getattr(ctx, "visibility_input", 100)
                )
            visibility = getattr(ctx, "point_visibility", 1.0)
            if visibility < 1.0:
                # _apply_vertical_gradient returns a fresh buffer; if gradient was
                # skipped we need our own copy before mutating.
                if not getattr(ctx, "use_gradient", True):
                    point_colors = point_colors.copy()
                point_colors[:, 3] *= visibility

        attrs: dict = {"pos": pts}
        shader, color_key, default_color = self._configure_point_shader(has_colors, ctx)
        if has_colors and point_colors is not None and color_key:
            attrs[color_key] = point_colors
        batch = batch_for_shader(shader, "POINTS", attrs)
        return {
            "batch": batch,
            "shader": shader,
            "has_colors": has_colors,
            "color": default_color,
        }

    @staticmethod
    def _configure_point_shader(has_colors: bool, ctx):
        if has_colors:
            if bpy.app.version >= (4, 5, 0):
                shader = _get_cached_shader("ppc")
                if shader is not None:
                    return shader, "vcol", None
            shader = _get_cached_shader("smooth_color")
            return shader, "color", None
        shader = _get_cached_shader("uniform_color")
        rgb = np.array([[0.8, 0.8, 0.8]], dtype="f")
        rgb = _apply_color_profile(rgb, ctx.mesh_color_type)
        return shader, None, (*rgb[0].tolist(), 1.0)

    # -- text --

    def _prepare_text_draw(self, text_data, ctx):
        if not text_data:
            return None
        text_draw = copy.copy(text_data)
        for i, p in enumerate(text_draw["pos"]):
            text_draw["pos"][i] = [
                p[0] * 0.01 * ctx.scale,
                p[2] * 0.01 * ctx.scale,
                p[1] * 0.01 * ctx.scale,
            ]
        for i, c in enumerate(text_draw["col"]):
            text_draw["col"][i] = [*c, 1]
        return text_draw

    # -- outline --

    @staticmethod
    def _prepare_outline_draw(verts: np.ndarray, normals: np.ndarray):
        """Build a back-face outline batch from already-transformed arrays.

        Returns a batch dict (same schema as mesh), or ``None`` if the outline
        shader is unavailable.
        """
        shader = _get_cached_shader("outline")
        if shader is None:
            return None
        indices = np.arange(len(verts), dtype=np.int32).reshape((-1, 3))
        batch = batch_for_shader(
            shader, "TRIS", {"pos": verts, "normal": normals}, indices=indices
        )
        return {"batches": [batch], "shader": shader}

    # -- public API --

    def build_draw_data(self, raw_data: dict, ctx) -> Optional[dict]:
        """Convert a parsed PRX payload to GPU-ready draw data.

        Args:
            raw_data: The ``data`` section of a PRX payload.
            ctx: A namespace carrying scale, visibility, and colour settings.

        Returns:
            A dict with ``mesh``, ``points``, ``line``, ``text`` sub-dicts, or ``None``.
        """
        if not raw_data:
            return None
        draw: dict = {}

        # Mesh and outline share the same transformed verts/normals.
        mesh_data = raw_data.get("mesh")
        mesh_verts: Optional[np.ndarray] = None
        mesh_normals: Optional[np.ndarray] = None
        want_mesh = getattr(ctx, "mesh_visibility", 1.0) > 0
        want_outline = want_mesh and getattr(ctx, "use_outline", False)
        if (want_mesh or want_outline) and mesh_data:
            mesh_verts = _transform_positions(mesh_data.get("pos"), ctx.scale)
            if mesh_verts is not None:
                mesh_normals = _transform_normals(mesh_data.get("nrm"), len(mesh_verts))

        if want_mesh and mesh_verts is not None:
            mesh = self._prepare_mesh_draw(mesh_data, mesh_verts, mesh_normals, ctx)
            if mesh:
                draw["mesh"] = mesh

        if (
            getattr(ctx, "point_visibility", 1.0) > 0
            and getattr(ctx, "point_size", 1.0) > 0
        ):
            points = self._prepare_point_draw(raw_data.get("points"), ctx)
            if points:
                draw["points"] = points

        if getattr(ctx, "line_thickness", 1.0) > 0:
            line = self._prepare_line_draw(raw_data.get("line"), ctx)
            if line:
                draw["line"] = line

        if want_outline and mesh_verts is not None and mesh_normals is not None:
            outline = self._prepare_outline_draw(mesh_verts, mesh_normals)
            if outline:
                draw["outline"] = outline

        text = self._prepare_text_draw(raw_data.get("text"), ctx)
        if text:
            draw["text"] = text
        return draw if draw else None


# -- Viewport draw handler --


def default_draw_context(**overrides) -> SimpleNamespace:
    """Return a default draw-context namespace.

    All display parameters live here.  Override any of them via *overrides*.
    """
    ctx = SimpleNamespace(
        scale=1.0,
        mesh_visibility=1.0,
        mesh_color_mode=COLOR_MODE_RANDOM,
        mesh_color_type="sRGB",
        mesh_shading_mode=SHADING_MODE_PHONG,
        point_visibility=1.0,
        point_size=3.0,
        point_color_mode=COLOR_MODE_RANDOM,
        line_thickness=1.0,
        line_color_mode=COLOR_MODE_RANDOM,
        line_color_type="sRGB",
        random_color=(0.6, 0.6, 0.6, 1.0),
        custom_color=None,
        use_gradient=True,
        visibility_input=100,
        use_outline=False,
        outline_color=(1.0, 0.65, 0.0, 1.0),
        outline_width=0.004,
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


class ProxorLiteDrawHandler:
    """Manages a single Proxor draw entry in the viewport.

    Usage::

        handler = ProxorLiteDrawHandler()
        handler.set_payload(prx_data, matrix_world)
        handler.install()       # registers the viewport draw callback
        handler.remove()        # unregisters
    """

    def __init__(self) -> None:
        self._handle = None
        self._draw_data: Optional[dict] = None
        self._raw_data: Optional[dict] = None
        self._matrix: Matrix = Matrix.Identity(4)
        self._builder = ProxorLiteDrawBuilder()
        self.draw_ctx: SimpleNamespace = default_draw_context()
        self._built_vis_pct: float = 100.0

    # -- public --

    def set_payload(
        self,
        proxor_data: Optional[dict],
        matrix: Optional[Matrix] = None,
    ) -> None:
        """Rebuild GPU batches from *proxor_data*.

        Args:
            proxor_data: The ``data`` section of a PRX payload.
            matrix: World-space transform to apply while drawing.
        """
        self._raw_data = proxor_data
        self._matrix = matrix or Matrix.Identity(4)
        self._built_vis_pct = getattr(self.draw_ctx, "visibility_input", 100)
        self._draw_data = (
            self._builder.build_draw_data(proxor_data, self.draw_ctx)
            if proxor_data
            else None
        )

    def rebuild(self) -> None:
        """Rebuild GPU batches from cached raw data using current draw_ctx."""
        self._built_vis_pct = getattr(self.draw_ctx, "visibility_input", 100)
        if self._raw_data is not None:
            self._draw_data = self._builder.build_draw_data(
                self._raw_data, self.draw_ctx
            )
        else:
            self._draw_data = None

    def install(self) -> None:
        """Register the viewport draw callback (idempotent)."""
        if self._handle is not None:
            return
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (None,), "WINDOW", "POST_VIEW"
        )

    def remove(self) -> None:
        """Unregister the viewport draw callback."""
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            self._handle = None

    @property
    def is_active(self) -> bool:
        """Whether the handler is currently installed."""
        return self._handle is not None

    # -- internal draw --

    @contextlib.contextmanager
    def _push_matrix(self):
        gpu.matrix.push()
        multiply_fn = getattr(gpu.matrix, "multiply_matrix", None) or getattr(
            gpu.matrix, "multiply", None
        )
        try:
            if multiply_fn is not None:
                multiply_fn(self._matrix)
            else:
                loc = self._matrix.to_translation()
                rot = self._matrix.to_euler()
                scl = self._matrix.to_scale()
                gpu.matrix.translate(loc)
                gpu.matrix.rotate(rot.x, 1.0, 0.0, 0.0)
                gpu.matrix.rotate(rot.y, 0.0, 1.0, 0.0)
                gpu.matrix.rotate(rot.z, 0.0, 0.0, 1.0)
                gpu.matrix.scale((scl.x, scl.y, scl.z))
            yield
        finally:
            gpu.matrix.pop()

    def _draw_callback(self, _context):
        try:
            ctx = self.draw_ctx
            vis_pct = getattr(ctx, "visibility_input", 100)
            if self._raw_data is not None and vis_pct != self._built_vis_pct:
                self.rebuild()
            if self._draw_data is None:
                return
            if ctx.mesh_visibility > 0 and getattr(ctx, "use_outline", False):
                self._draw_outline()
            if ctx.mesh_visibility > 0:
                self._draw_mesh()
            if ctx.line_thickness > 0:
                self._draw_lines()
            if ctx.point_visibility > 0 and ctx.point_size > 0:
                self._draw_points()
        except Exception:  # noqa: BLE001
            # Prevent GPU errors or stale references from crashing Blender
            pass

    def _draw_mesh(self):
        mesh = self._draw_data.get("mesh") if self._draw_data else None
        if not mesh:
            return
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)  # transparent frags must not write depth
        gpu.state.blend_set("ALPHA")
        gpu.state.face_culling_set("BACK")  # cull back faces to avoid double-blending
        shader = mesh["shader"]
        use_blinn = mesh.get("blinn", False)
        lighting = mesh.get("lighting")
        with self._push_matrix():
            if use_blinn and lighting:
                self._configure_mesh_lighting(shader, lighting)
            for batch in mesh.get("batches") or []:
                if batch is not None:
                    batch.draw(shader)
        gpu.state.face_culling_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")

    def _draw_lines(self):
        line = self._draw_data.get("line") if self._draw_data else None
        if not line:
            return
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(True)
        shader = line["shader"]
        thickness = getattr(self.draw_ctx, "line_thickness", 1.0) or 1.5
        shader.uniform_float("lineWidth", thickness)
        with self._push_matrix():
            line["batch"].draw(shader)
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")

    def _draw_points(self):
        pts = self._draw_data.get("points") if self._draw_data else None
        if not pts:
            return
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(True)
        gpu.state.blend_set("ALPHA")
        shader = pts["shader"]
        size = max(getattr(self.draw_ctx, "point_size", 3.0), 0.1)
        gpu.state.point_size_set(size)
        shader.bind()
        with contextlib.suppress(Exception):
            shader.uniform_float("pointSize", size)
        if not pts["has_colors"] and pts["color"] is not None:
            shader.uniform_float("color", pts["color"])
        with self._push_matrix():
            pts["batch"].draw(shader)
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")

    def _draw_outline(self):
        outline = self._draw_data.get("outline") if self._draw_data else None
        if not outline:
            return
        shader = outline["shader"]
        if shader is None:
            return
        ctx = self.draw_ctx
        outline_color = getattr(ctx, "outline_color", (1.0, 0.65, 0.0, 1.0))
        outline_width = float(getattr(ctx, "outline_width", 0.004))
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        gpu.state.face_culling_set("FRONT")  # show only back faces (rim)
        with self._push_matrix():
            shader.bind()
            shader.uniform_float("ModelViewProjectionMatrix", _get_mvp())
            shader.uniform_float("outlineWidth", outline_width)
            shader.uniform_float("outlineColor", outline_color)
            for batch in outline.get("batches") or []:
                if batch is not None:
                    batch.draw(shader)
        gpu.state.face_culling_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")

    # -- lighting helpers --

    @staticmethod
    def _lighting_block_payload(lighting):
        ld = lighting.get("light_dir", DEFAULT_LIGHT_DIR)
        vd = lighting.get("view_dir", DEFAULT_VIEW_DIR)
        return array(
            "f",
            (
                ld[0],
                ld[1],
                ld[2],
                0.0,
                vd[0],
                vd[1],
                vd[2],
                0.0,
                float(lighting.get("ambient", DEFAULT_AMBIENT)),
                float(lighting.get("diffuse", DEFAULT_DIFFUSE)),
                float(lighting.get("specular", DEFAULT_SPECULAR)),
                float(lighting.get("shininess", DEFAULT_SHININESS)),
            ),
        )

    @classmethod
    def _configure_mesh_lighting(cls, shader, lighting):
        get_mv = getattr(gpu.matrix, "get_model_view_matrix", None)
        mv = get_mv() if get_mv else Matrix.Identity(4)
        mv3 = mv.to_3x3()
        try:
            normal_matrix = mv3.inverted().transposed()
        except Exception:  # noqa: BLE001
            normal_matrix = mv3.copy()
        shader.bind()
        shader.uniform_float("ModelViewProjectionMatrix", _get_mvp())
        shader.uniform_float("NormalMatrix", normal_matrix)
        if bpy.app.version >= (4, 5, 0):
            data = cls._lighting_block_payload(lighting)
            ubo = lighting.get("_ubo")
            if ubo is None:
                ubo = gpu.types.GPUUniformBuf(data)
                lighting["_ubo"] = ubo
            else:
                ubo.update(data)
            shader.uniform_block("LightingData", ubo)


__all__ = [
    "COLOR_MODE_CUSTOM",
    "COLOR_MODE_ORIGINAL",
    "COLOR_MODE_RANDOM",
    "ProxorLiteDrawBuilder",
    "ProxorLiteDrawHandler",
    "default_draw_context",
    "ensure_shaders",
    "invalidate_shader_cache",
]
