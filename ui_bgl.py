# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import math
import os
import logging
from typing import Optional, Tuple, Union

import blf
import bpy
from bpy import app

import gpu
from gpu_extras.batch import batch_for_shader

from .image_utils import IMG


bk_logger = logging.getLogger(__name__)

cached_images = {}

cached_gpu_textures = {}

_cached_image_shader: Optional[gpu.types.GPUShader] = None


VERTEX_SHADER_LEGACY = """
uniform mat4 ModelViewProjectionMatrix;
in vec2 pos;
in vec2 texCoord;
out vec2 uv;

void main()
{
    uv = texCoord;
    gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
}
"""


FRAGMENT_SHADER_LEGACY = """
in vec2 uv;
out vec4 fragColor;
uniform sampler2D image;
uniform float transparency;
uniform int color_space_mode;

vec3 linear_to_srgb(vec3 linear_color)
{
    vec3 cutoff = vec3(0.0031308);
    vec3 lower = linear_color * 12.92;
    vec3 higher = 1.055 * pow(max(linear_color, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
    return mix(lower, higher, step(cutoff, linear_color));
}

void main()
{
    vec4 color = texture(image, uv);
    if (color_space_mode == 1) {
        color.rgb = linear_to_srgb(color.rgb);
    }
    color.a *= transparency;
    fragColor = color;
}
"""


def create_image_shader_info():
    """Return GPU shader info for the runtime image shader."""
    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.vertex_in(0, "VEC2", "pos")
    shader_info.vertex_in(1, "VEC2", "texCoord")

    stage_iface = gpu.types.GPUStageInterfaceInfo("uv_iface")
    stage_iface.smooth("VEC2", "uv")
    shader_info.vertex_out(stage_iface)

    shader_info.push_constant("MAT4", "ModelViewProjectionMatrix")
    shader_info.push_constant("FLOAT", "transparency")
    shader_info.push_constant("INT", "color_space_mode")
    shader_info.sampler(0, "FLOAT_2D", "image")

    shader_info.fragment_out(0, "VEC4", "fragColor")
    shader_info.vertex_source(
        """
        void main()
        {
            uv = texCoord;
            gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
        }
    """
    )
    shader_info.fragment_source(
        """
        void main()
        {
            vec4 color = texture(image, uv);
            if (color_space_mode == 1) {
                vec3 cutoff = vec3(0.0031308);
                vec3 lower = color.rgb * 12.92;
                vec3 higher = 1.055 * pow(max(color.rgb, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
                color.rgb = mix(lower, higher, step(cutoff, color.rgb));
            }
            color.a *= transparency;
            fragColor = color;
        }
    """
    )
    return shader_info


def create_image_shader():
    """Return a cached shader that supports transparency across Blender versions.
    Features:
        - sRGB conversion for UI overlays
        - transparency
    """
    global _cached_image_shader

    if _cached_image_shader is not None:
        return _cached_image_shader

    shader = None

    create_info_supported = (
        hasattr(gpu, "shader")
        and hasattr(gpu.shader, "create_from_info")
        and hasattr(gpu.types, "GPUShaderCreateInfo")
    )

    if create_info_supported:
        try:
            shader_info = create_image_shader_info()
            shader = gpu.shader.create_from_info(shader_info)
        except Exception:  # noqa: BLE001
            bk_logger.exception("Failed to create image shader")
            shader = None

    if shader is None:
        try:
            shader = gpu.types.GPUShader(VERTEX_SHADER_LEGACY, FRAGMENT_SHADER_LEGACY)
        except Exception:  # noqa: BLE001
            bk_logger.exception("Failed to create image shader")

    if shader is None:
        # fallback to builtin shader
        # mainly for MacOS builds that have issues with custom shaders
        if app.version < (4, 0, 0):
            shader = gpu.shader.from_builtin("2D_IMAGE")
        else:
            shader = gpu.shader.from_builtin("IMAGE")

    _cached_image_shader = shader
    return shader


def _get_flat_shader_2d():
    if app.version < (4, 0, 0):
        shader_name = "2D_UNIFORM_COLOR"
    else:
        shader_name = "UNIFORM_COLOR"
    return gpu.shader.from_builtin(shader_name)


def draw_rect(x, y, width, height, color):
    """Used for drawing 2D rectangle backgrounds."""
    xmax = x + width
    ymax = y + height
    points = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1, 2), (2, 3, 0))

    shader = _get_flat_shader_2d()
    batch = batch_for_shader(shader, "TRIS", {"pos": points}, indices=indices)

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_rect_outline(x, y, width, height, color, line_width=1.0):
    """Used for drawing 2D rectangle outlines."""
    xmax = x + width
    ymax = y + height
    coords = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1), (1, 2), (2, 3), (3, 0))

    shader = _get_flat_shader_2d()
    batch = batch_for_shader(shader, "LINES", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(line_width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_line2d(x1, y1, x2, y2, width, color):
    """Used for drawing line from dragged thumbnail to the 3D bounding box."""
    coords = ((x1, y1), (x2, y2))
    indices = ((0, 1),)

    shader = _get_flat_shader_2d()

    batch = batch_for_shader(shader, "LINES", {"pos": coords}, indices=indices)
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(max(1.0, width))
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _rounded_rect_outline(x, y, width, height, radius, segments=6):
    if width <= 0 or height <= 0:
        return []
    max_radius = max(0.0, min(width, height) / 2.0)

    if isinstance(radius, (tuple, list)):
        radii = list(radius)
    else:
        radii = [radius]
    if not radii:
        radii = [0.0]
    while len(radii) < 4:
        radii.append(radii[-1])
    radii = [max(0.0, min(float(value), max_radius)) for value in radii[:4]]

    r_tl, r_tr, r_br, r_bl = radii

    if all(r == 0.0 for r in radii):
        outline = [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
        ]
        outline.append(outline[0])
        return outline

    steps = max(1, int(segments))
    outline = []
    steps = max(1, int(segments))
    outline = []

    def emit_corner(cx, cy, start_angle, end_angle, radius_value, fallback_point):
        if radius_value <= 0.0:
            outline.append(fallback_point)
            return
        for step in range(steps + 1):
            t = step / steps
            angle = start_angle + (end_angle - start_angle) * t
            outline.append(
                (
                    cx + math.cos(angle) * radius_value,
                    cy + math.sin(angle) * radius_value,
                )
            )

    emit_corner(
        x + r_tl,
        y + height - r_tl,
        math.pi,
        math.pi / 2.0,
        r_tl,
        (x, y + height),
    )
    emit_corner(
        x + width - r_tr,
        y + height - r_tr,
        math.pi / 2.0,
        0.0,
        r_tr,
        (x + width, y + height),
    )
    emit_corner(
        x + width - r_br,
        y + r_br,
        0.0,
        -math.pi / 2.0,
        r_br,
        (x + width, y),
    )
    emit_corner(
        x + r_bl,
        y + r_bl,
        -math.pi / 2.0,
        -math.pi,
        r_bl,
        (x, y),
    )

    if outline and outline[0] != outline[-1]:
        outline.append(outline[0])
    return outline


def draw_rounded_rect_with_border(
    x,
    y,
    width,
    height,
    radius,
    fill_color,
    border_color=None,
    border_thickness=1.0,
):
    if width <= 0 or height <= 0:
        return
    outline = _rounded_rect_outline(x, y, width, height, radius)
    if not outline:
        return
    loop = outline[:-1] if len(outline) > 1 and outline[0] == outline[-1] else outline
    if len(loop) < 3:
        return
    shader = _get_flat_shader_2d()
    indices = [(0, idx, idx + 1) for idx in range(1, len(loop) - 1)]
    batch = batch_for_shader(shader, "TRIS", {"pos": loop}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", fill_color)
    batch.draw(shader)
    if border_color and border_thickness > 0:
        gpu.state.line_width_set(border_thickness)
        if outline[0] == outline[-1]:
            line_points = outline
        else:
            line_points = outline + [outline[0]]
        line_batch = batch_for_shader(shader, "LINE_STRIP", {"pos": line_points})
        shader.uniform_float("color", border_color)
        line_batch.draw(shader)
        gpu.state.line_width_set(1.0)


def draw_strikethrough_line(x_start, x_end, y, color, thickness):
    if x_end <= x_start:
        return
    draw_line2d(x_start, y, x_end, y, thickness, color)


def create_shader_info():
    """Added for Blender 4.5+ in which the gpu.shader.from_builtin("UNIFORM_COLOR") silently stopped working.
    Interestingly for draw_rect_3d UNIFORM_COLOR still works just fine.
    https://github.com/BlenderKit/BlenderKit/issues/1574
    """
    if app.version < (4, 5, 0):
        return bk_logger.warning("Unexpected call to create_shader_info()!")
    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.vertex_in(0, "VEC3", "pos")
    shader_info.push_constant("MAT4", "ModelViewProjectionMatrix")
    shader_info.push_constant("VEC4", "color")
    shader_info.fragment_out(0, "VEC4", "fragColor")
    shader_info.vertex_source(
        """
        void main() {
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
        }
    """
    )
    shader_info.fragment_source(
        """
        void main() {
            fragColor = color;
        }
    """
    )
    return shader_info


def draw_lines(vertices, indices, color):
    """Used for drawing 3D bounding box."""
    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    elif app.version < (4, 5, 0):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    else:
        shader_info = create_shader_info()
        shader = gpu.shader.create_from_info(shader_info)

    batch = batch_for_shader(shader, "LINES", {"pos": vertices}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_rect_3d(coords, color):
    """Used for drawing 3D rectangle backgrounds."""
    indices = [(0, 1, 2), (2, 3, 0)]
    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    else:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _resolve_color_space_mode() -> int:
    """Return shader color conversion mode for the current drawing context.

    area over non-3D means UI overlay, so we need to apply sRGB conversion."""
    area = getattr(bpy.context, "area", None)
    if area is None:
        return 0

    # Blender 5.0+ node editors already expect linear data, so avoid extra conversion there
    node_editor_types = {"NODE_EDITOR", "VIEW_3D"}

    if area.type in node_editor_types:
        return 0

    return 1


def draw_image_runtime(
    x: float,
    y: float,
    width: float,
    height: float,
    image: Union[bpy.types.Image, IMG],
    transparency: Optional[float] = 1.0,
    crop: Tuple[float, float, float, float] = (0, 0, 1, 1),
    batch: Optional[gpu.types.GPUBatch] = None,
) -> Optional[gpu.types.GPUBatch]:
    """Draws an image at given location with given size.

    Returns:
        The batch object if successful, or None if the image is invalid.
    """
    if not image.name or not image.filepath:
        return None

    image_shader = create_image_shader()

    texture = None
    ci = cached_images.get(image.filepath + "GPU_TEXTURE")
    if ci is not None:
        if (
            ci["x"] == x
            and ci["y"] == y
            and ci["width"] == width
            and ci["height"] == height
        ):
            batch = ci["batch"]
            image_shader = ci["image_shader"]
            texture = ci["texture"]

    if not batch:
        coords = [(x, y), (x + width, y), (x, y + height), (x + width, y + height)]

        uvs = [
            (crop[0], crop[1]),
            (crop[2], crop[1]),
            (crop[0], crop[3]),
            (crop[2], crop[3]),
        ]

        indices = [(0, 1, 2), (2, 1, 3)]

        batch = batch_for_shader(
            image_shader, "TRIS", {"pos": coords, "texCoord": uvs}, indices=indices
        )

        texture = path_to_gpu_texture(image.filepath)

        # tell shader to use the image that is bound to image unit 0
        cached_images[image.filepath + "GPU_TEXTURE"] = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "batch": batch,
            "image_shader": image_shader,
            "texture": texture,
        }

    if batch is None:
        return None

    if image_shader and texture:
        color_space_mode = _resolve_color_space_mode()

        gpu.state.blend_set("ALPHA")

        image_shader.bind()
        image_shader.uniform_sampler("image", texture)

        # may not be available in simple shader
        try:
            # set floats
            image_shader.uniform_float("transparency", transparency)

            # set color space mode
            image_shader.uniform_int("color_space_mode", color_space_mode)
            batch.draw(image_shader)
        except Exception:
            pass

    return batch


def path_to_gpu_texture(path: str) -> Optional[gpu.types.GPUTexture]:
    """Convert a Blender image to a GPU texture.

    Returns:
        The GPU texture if successful, or None if the image is invalid.
    """
    # check if exists and is file [prevent exception for missing files]
    if path in cached_gpu_textures:
        return cached_gpu_textures[path]

    if not os.path.exists(path) or not os.path.isfile(path):
        # do not spam log with warnings, just return None
        return None
    img = bpy.data.images.load(path, check_existing=False)
    img.gl_load()

    tex = gpu.texture.from_image(img)
    cached_gpu_textures[path] = tex

    # # Clean up Blender image
    bpy.data.images.remove(img)
    return tex


def get_text_size(font_id=0, text="", text_size=16, dpi=72):
    if app.version < (4, 0, 0):
        blf.size(font_id, text_size, dpi)
    else:
        blf.size(font_id, text_size)
    return blf.dimensions(font_id, text)


def draw_text(text, x, y, size, color=(1, 1, 1, 0.5), halign="LEFT", valign="TOP"):
    font_id = 1
    if type(text) != str:
        text = str(text)
    blf.color(font_id, color[0], color[1], color[2], color[3])
    if app.version < (4, 0, 0):
        blf.size(font_id, size, 72)
    else:
        blf.size(font_id, size)
    if halign != "LEFT":
        width, height = blf.dimensions(font_id, text)
        if halign == "RIGHT":
            x -= width
        elif halign == "CENTER":
            x -= width // 2
        if valign == "CENTER":
            y -= height // 2
        # bottom could be here but there's no reason for it
    blf.position(font_id, x, y, 0)

    blf.draw(font_id, text)
