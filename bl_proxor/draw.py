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
TRIANGLE_VERTEX_COUNT = 3
VECTOR_SIZE = 3
RGBA_CHANNELS = 4
RGB_CHANNELS = 3
TRIANGLE_BATCH_LIMIT = 21840
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


def _apply_vertical_gradient(colors: np.ndarray, z_values: np.ndarray) -> np.ndarray:
    """Modulate RGB by vertical position (Z in Blender space).

    Bottom vertices get ``GRADIENT_LOW`` brightness, top get ``GRADIENT_HIGH``.
    """
    z_min = float(np.min(z_values))
    z_max = float(np.max(z_values))
    z_range = z_max - z_min
    if z_range < 1e-8:
        return colors
    t = (z_values - z_min) / z_range
    v_mult = GRADIENT_LOW + (GRADIENT_HIGH - GRADIENT_LOW) * t
    out = colors.copy()
    out[:, :RGB_CHANNELS] *= v_mult[:, np.newaxis]
    np.clip(out[:, :RGB_CHANNELS], 0.0, 1.0, out=out[:, :RGB_CHANNELS])
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
) -> tuple[Optional[list], bool]:
    if not raw:
        return None, False
    arr = np.array(raw, dtype="f")
    if arr.ndim != TARGET_DIMENSIONS or arr.shape[0] == 0:
        return None, False
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
    return arr.tolist(), True


def _prepare_point_normals_for_shader(
    normals_raw, expected: int
) -> Optional[list[list[float]]]:
    if not normals_raw or expected <= 0:
        return None
    nrm = np.array(normals_raw, dtype="f")
    if nrm.ndim != TARGET_DIMENSIONS or nrm.shape[0] == 0:
        return None
    if nrm.shape[1] > VECTOR_SIZE:
        nrm = nrm[:, :VECTOR_SIZE]
    if nrm.shape[1] < VECTOR_SIZE:
        nrm = np.concatenate(
            (nrm, np.zeros((nrm.shape[0], VECTOR_SIZE - nrm.shape[1]), dtype="f")),
            axis=1,
        )
    nrm[:, [1, 2]] = nrm[:, [2, 1]]
    if nrm.shape[0] < expected:
        repeats = (expected + nrm.shape[0] - 1) // nrm.shape[0]
        nrm = np.tile(nrm, (repeats, 1))[:expected]
    elif nrm.shape[0] > expected:
        nrm = nrm[:expected]
    lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
    with np.errstate(invalid="ignore"):
        nrm = np.divide(nrm, lengths, out=np.zeros_like(nrm), where=lengths != 0)
    return nrm.tolist()


# -- Batch builder --


class ProxorLiteDrawBuilder:
    """Build GPU-ready draw data from a PRX payload dict."""

    # -- mesh --

    @staticmethod
    def _mesh_colors_with_override(color_data, ctx, vertex_count: int):
        base = _prepare_mesh_colors(color_data, ctx.mesh_color_type)
        mode = getattr(ctx, "mesh_color_mode", COLOR_MODE_ORIGINAL)
        override = _resolve_uniform_color(mode, ctx)
        if override is not None:
            return _uniform_color_array(override, vertex_count, ctx.mesh_color_type)
        return base

    def _build_mesh_shader(self, mesh_data, vertex_count, ctx):
        normals = mesh_data.get("nrm")
        shading_mode = getattr(ctx, "mesh_shading_mode", SHADING_MODE_PHONG)
        use_blinn = (
            shading_mode == SHADING_MODE_PHONG
            and bool(normals)
            and bpy.app.version >= (4, 5, 0)
        )
        lighting = None

        if use_blinn:
            nrm_np = np.array(normals, dtype="f")
            if nrm_np.ndim == TARGET_DIMENSIONS and nrm_np.shape[0] == vertex_count:
                if nrm_np.shape[1] > VECTOR_SIZE:
                    nrm_np = nrm_np[:, :VECTOR_SIZE]
                nrm_np[:, [1, 2]] = nrm_np[:, [2, 1]]
                lengths = np.linalg.norm(nrm_np, axis=1, keepdims=True)
                with np.errstate(invalid="ignore"):
                    nrm_np = np.divide(
                        nrm_np, lengths, out=np.zeros_like(nrm_np), where=lengths != 0
                    )
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
                    return shader, True, lighting, nrm_np
            use_blinn = False

        return _get_cached_shader("smooth_color"), False, None, None

    def _prepare_mesh_draw(self, mesh_data, ctx):
        if not mesh_data or not mesh_data.get("pos"):
            return None
        verts = np.array(mesh_data["pos"], dtype="f")
        if (
            verts.ndim != TARGET_DIMENSIONS
            or verts.shape[0] == 0
            or verts.shape[1] < VECTOR_SIZE
        ):
            return None
        if verts.shape[1] > VECTOR_SIZE:
            verts = verts[:, :VECTOR_SIZE]
        verts[:, [1, 2]] = verts[:, [2, 1]]
        verts = verts * 0.01 * ctx.scale

        colors = self._mesh_colors_with_override(mesh_data.get("col"), ctx, len(verts))
        if colors is None or colors.shape[0] != verts.shape[0]:
            return None

        # Apply vertical gradient
        if getattr(ctx, "use_gradient", True):
            colors = _apply_vertical_gradient(colors, verts[:, 2])

        visibility = getattr(ctx, "mesh_visibility", 1.0)
        if visibility < 1.0:
            colors = colors.copy()
            colors[:, 3] *= visibility

        # Z-clip: keep only triangles with at least one vertex below cutoff
        vis_pct = getattr(ctx, "visibility_input", 100)
        if vis_pct < 100 and len(verts) >= TRIANGLE_VERTEX_COUNT:
            verts, colors, mesh_data = self._z_clip_mesh(
                verts,
                colors,
                mesh_data,
                vis_pct,
                ctx,
            )
            if verts is None or len(verts) == 0:
                return None

        shader, use_blinn, lighting, normal_data = self._build_mesh_shader(
            mesh_data, len(verts), ctx
        )

        attrs: dict = {"pos": verts}
        if use_blinn and normal_data is not None:
            attrs["normal"] = normal_data
            attrs["vcol"] = colors
        else:
            attrs["color"] = colors

        indices = np.arange(len(verts), dtype=np.int32).reshape((-1, 3))
        batches = [batch_for_shader(shader, "TRIS", attrs, indices=indices)]
        return {
            "batches": batches,
            "shader": shader,
            "blinn": use_blinn,
            "lighting": lighting,
        }

    @staticmethod
    def _z_clip_mesh(verts, colors, mesh_data, vis_pct, _ctx):
        """Remove triangles above the Z cutoff determined by *vis_pct*."""
        z_vals = verts[:, 2]
        z_min = float(np.min(z_vals))
        z_max = float(np.max(z_vals))
        z_range = z_max - z_min
        if z_range < 1e-8:
            if vis_pct <= 0:
                return None, None, mesh_data
            return verts, colors, mesh_data
        cutoff = z_min + z_range * (vis_pct / 100.0)
        # Triangles: groups of 3 vertices — keep if any vertex is below cutoff
        tri_verts = verts.reshape(-1, TRIANGLE_VERTEX_COUNT, VECTOR_SIZE)
        tri_cols = colors.reshape(-1, TRIANGLE_VERTEX_COUNT, colors.shape[1])
        mask = np.any(tri_verts[:, :, 2] <= cutoff, axis=1)
        if not np.any(mask):
            return None, None, mesh_data
        verts = tri_verts[mask].reshape(-1, VECTOR_SIZE)
        colors = tri_cols[mask].reshape(-1, colors.shape[1])
        # Also clip normals in mesh_data for shader rebuild
        normals = mesh_data.get("nrm")
        if normals and len(normals) == len(mask) * TRIANGLE_VERTEX_COUNT:
            nrm_np = np.array(normals, dtype="f").reshape(
                -1, TRIANGLE_VERTEX_COUNT, VECTOR_SIZE
            )
            mesh_data = dict(mesh_data)
            mesh_data["nrm"] = nrm_np[mask].reshape(-1, VECTOR_SIZE).tolist()
        return verts, colors, mesh_data

    # -- lines --

    def _prepare_line_draw(self, line_data, ctx):
        if not line_data or not line_data.get("pos"):
            return None
        pts = np.array(line_data["pos"], dtype="f")
        if pts.ndim != TARGET_DIMENSIONS or pts.shape[0] == 0:
            return None
        if pts.shape[1] > VECTOR_SIZE:
            pts = pts[:, :VECTOR_SIZE]
        pts[:, [1, 2]] = pts[:, [2, 1]]
        pts = pts * 0.01 * ctx.scale

        # Z-clip: keep line segments where at least one endpoint is below cutoff
        vis_pct = getattr(ctx, "visibility_input", 100)
        if vis_pct < 100 and len(pts) >= LINE_POINT_COUNT:
            z_vals = pts[:, 2]
            z_min = float(np.min(z_vals))
            z_max = float(np.max(z_vals))
            z_range = z_max - z_min
            if z_range >= 1e-8:
                cutoff = z_min + z_range * (vis_pct / 100.0)
                seg_pts = pts.reshape(-1, LINE_POINT_COUNT, VECTOR_SIZE)
                mask = np.any(seg_pts[:, :, 2] <= cutoff, axis=1)
                if not np.any(mask):
                    return None
                pts = seg_pts[mask].reshape(-1, VECTOR_SIZE)
            elif vis_pct <= 0:
                return None

        indices = np.arange(len(pts), dtype=np.int32).reshape(-1, LINE_POINT_COUNT)

        color_type = ctx.line_color_type
        mode = getattr(ctx, "line_color_mode", COLOR_MODE_ORIGINAL)
        override = _resolve_uniform_color(mode, ctx)
        if override is not None:
            colors = _uniform_color_array(override, len(pts), color_type).tolist()
        else:
            raw = line_data.get("col")
            if raw is None:
                base = np.full((len(pts), RGB_CHANNELS), 0.5, dtype="f")
            else:
                base = np.array(raw, dtype="f") * 2
                if base.ndim != TARGET_DIMENSIONS or base.shape[0] == 0:
                    base = np.full((len(pts), RGB_CHANNELS), 0.5, dtype="f")
            if len(base) != len(pts):
                base = np.repeat(base, LINE_POINT_COUNT, axis=0)
            base = _apply_color_profile(base[:, :RGB_CHANNELS], color_type)
            colors = np.concatenate(
                (base, np.ones((len(base), 1), dtype="f")), axis=1
            ).tolist()

        shader = _get_cached_shader("polyline_smooth_color")
        batch = batch_for_shader(
            shader, "LINES", {"pos": pts, "color": colors}, indices=indices
        )
        return {"batch": batch, "shader": shader}

    # -- points --

    def _prepare_point_draw(self, point_data, ctx):
        if not point_data or not point_data.get("pos"):
            return None
        pts = np.array(point_data["pos"], dtype="f")
        if (
            pts.ndim != TARGET_DIMENSIONS
            or pts.shape[0] == 0
            or pts.shape[1] < VECTOR_SIZE
        ):
            return None
        if pts.shape[1] > VECTOR_SIZE:
            pts = pts[:, :VECTOR_SIZE]
        pts[:, [1, 2]] = pts[:, [2, 1]]
        pts = pts * 0.01 * ctx.scale

        point_colors, has_colors = _prepare_point_colors(
            point_data.get("col"), ctx.mesh_color_type
        )
        mode = getattr(ctx, "point_color_mode", COLOR_MODE_ORIGINAL)
        override = _resolve_uniform_color(mode, ctx)
        if override is not None:
            point_colors = _uniform_color_array(
                override, len(pts), ctx.mesh_color_type
            ).tolist()
            has_colors = True

        # Apply vertical gradient to point colours
        if (
            getattr(ctx, "use_gradient", True)
            and has_colors
            and point_colors is not None
        ):
            pc_np = np.array(point_colors, dtype="f")
            pc_np = _apply_vertical_gradient(pc_np, pts[:, 2])
            point_colors = pc_np.tolist()

        visibility = getattr(ctx, "point_visibility", 1.0)
        if visibility < 1.0 and has_colors and point_colors is not None:
            point_colors = [
                (
                    [c[0], c[1], c[2], c[3] * visibility]
                    if len(c) >= 4
                    else [*c, visibility]
                )
                for c in point_colors
            ]

        # Z-clip: keep only points below cutoff
        vis_pct = getattr(ctx, "visibility_input", 100)
        if vis_pct < 100:
            z_vals = pts[:, 2]
            z_min = float(np.min(z_vals))
            z_max = float(np.max(z_vals))
            z_range = z_max - z_min
            if z_range >= 1e-8:
                cutoff = z_min + z_range * (vis_pct / 100.0)
                mask = z_vals <= cutoff
                if not np.any(mask):
                    return None
                pts = pts[mask]
                if has_colors and point_colors is not None:
                    point_colors = [c for c, m in zip(point_colors, mask) if m]
            elif vis_pct <= 0:
                return None

        pts_list = pts.tolist()

        attrs: dict = {"pos": pts_list}
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
        if getattr(ctx, "mesh_visibility", 1.0) > 0:
            mesh = self._prepare_mesh_draw(raw_data.get("mesh"), ctx)
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
        self._draw_data = (
            self._builder.build_draw_data(proxor_data, self.draw_ctx)
            if proxor_data
            else None
        )

    def rebuild(self) -> None:
        """Rebuild GPU batches from cached raw data using current draw_ctx."""
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
            if self._draw_data is None:
                return
            ctx = self.draw_ctx
            # Z-clip at 0% hides everything
            if getattr(ctx, "visibility_input", 100) <= 0:
                return
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
        gpu.state.depth_mask_set(True)
        gpu.state.blend_set("ALPHA")
        shader = mesh["shader"]
        use_blinn = mesh.get("blinn", False)
        lighting = mesh.get("lighting")
        with self._push_matrix():
            if use_blinn and lighting:
                self._configure_mesh_lighting(shader, lighting)
            for batch in mesh.get("batches") or []:
                if batch is not None:
                    batch.draw(shader)
        gpu.state.depth_mask_set(False)
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
        get_proj = getattr(gpu.matrix, "get_projection_matrix", None)
        mv = get_mv() if get_mv else Matrix.Identity(4)
        proj = get_proj() if get_proj else Matrix.Identity(4)
        mvp = proj @ mv
        mv3 = mv.to_3x3()
        try:
            normal_matrix = mv3.inverted().transposed()
        except Exception:  # noqa: BLE001
            normal_matrix = mv3.copy()
        shader.bind()
        shader.uniform_float("ModelViewProjectionMatrix", mvp)
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
