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

import logging
from typing import Optional, Sequence, Tuple

import blf
from bpy import app

import gpu
from gpu_extras.batch import batch_for_shader

bk_logger = logging.getLogger(__name__)


def draw_rect(x, y, width, height, color):
    xmax = x + width
    ymax = y + height
    points = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1, 2), (2, 3, 0))

    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    else:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": points}, indices=indices)

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_line2d(x1, y1, x2, y2, width, color):
    """Used for drawing line from dragged thumbnail to the 3D bounding box."""
    coords = ((x1, y1), (x2, y2))
    indices = ((0, 1),)

    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    elif app.version < (4, 5, 0):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    else:
        shader_info = create_shader_info()
        shader = gpu.shader.create_from_info(shader_info)

    batch = batch_for_shader(shader, "LINES", {"pos": coords}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


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


def create_shader_ppc_info(size_uniform: bool = True):
    """Create a per-point color POINTS shader supporting Blender 4.5 and 5.0+.

    Blender < 4.5: return None (use built-in smooth color shaders).
    Blender 4.5 <= v < 5.0: use legacy GPUShaderCreateInfo API (vertex_out with (loc, type, name)).
    Blender 5.0+: use new API (vertex_out(name), fragment_in(name)) and declare GLSL in/out explicitly.
    In both custom paths we provide a uniform pointSize via push constant when size_uniform is True.
    Attribute names: pos (vec3), vcol (vec4).
    Varying name: vcol_out.
    """
    if app.version < (4, 5, 0):
        return None

    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC4", "vcol")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    if size_uniform:
        info.push_constant("FLOAT", "pointSize")

    is_new_api = app.version >= (5, 0, 0)
    if is_new_api:
        # Blender 5.0+: use stage interfaces
        iface = gpu.types.GPUStageInterfaceInfo("v_iface")
        iface.smooth("VEC4", "vcol_out")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(
            f"""
            void main() {{
                gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
                {'gl_PointSize = pointSize;' if size_uniform else ''}
                vcol_out = vcol;
            }}
        """
        )
        info.fragment_source(
            """
            void main() {
                fragColor = vcol_out;
            }
        """
        )
    else:
        # Legacy 4.5 API: vertex_out/location/type; fragment_out only; varying passed automatically.
        info.vertex_out(0, "VEC4", "vcol_out")
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(
            f"""
            void main() {{
                gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
                {'gl_PointSize = pointSize;' if size_uniform else ''}
                vcol_out = vcol;
            }}
        """
        )
        info.fragment_source(
            """
            void main() {
                fragColor = vcol_out;
            }
        """
        )
    return info


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
    indices = [(0, 1, 2), (2, 3, 0)]
    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    else:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.blend_set("ALPHA")
    batch.draw(shader)


cached_images = {}


def draw_image(x, y, width, height, image, transparency, crop=(0, 0, 1, 1), batch=None):
    # draw_rect(x,y, width, height, (.5,0,0,.5))

    try:
        image.name
    except:
        print("Image is invalid- draw function")
        return

    ci = cached_images.get(image.filepath)
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

        if app.version < (4, 0, 0):
            image_shader = gpu.shader.from_builtin("2D_IMAGE")
        else:
            image_shader = gpu.shader.from_builtin("IMAGE")
        batch = batch_for_shader(
            image_shader, "TRIS", {"pos": coords, "texCoord": uvs}, indices=indices
        )
        texture = gpu.texture.from_image(image)
        # tell shader to use the image that is bound to image unit 0
        cached_images[image.filepath] = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "batch": batch,
            "image_shader": image_shader,
            "texture": texture,
        }
    # send image to gpu if it isn't there already
    if image.gl_load():
        raise Exception()

    # texture = gpu.texture.from_image(image)
    gpu.state.blend_set("ALPHA")
    image_shader.bind()
    image_shader.uniform_sampler("image", texture)
    batch.draw(image_shader)

    return batch


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


def draw_points(
    points: Sequence[Tuple[float, float, float]],
    size=1.0,
    color=(1, 1, 1, 0.5),
    colors: Optional[Sequence[Tuple[float, float, float, float]]] = None,
    matrix=None,
):
    """Draw multiple points at given locations with given size and color."""
    if len(points) == 0:
        return
    # Static type-friendly check for optional colors
    cols_len = len(colors) if colors is not None else 0
    use_vertex_colors = cols_len > 0

    # If per-point colors are provided, build a shader that accepts vertex color
    # and pass both attributes. Otherwise, use the uniform color shader.
    if use_vertex_colors:
        # Ensure equal lengths
        n = min(len(points), cols_len)
        if n == 0:
            return
        pts = points[:n]
        # mypy/pylance: colors is not None here due to use_vertex_colors
        cols = colors[:n]  # type: ignore[index]

        if app.version < (4, 0, 0):
            shader = gpu.shader.from_builtin("3D_SMOOTH_COLOR")
            batch = batch_for_shader(shader, "POINTS", {"pos": pts, "color": cols})
        elif app.version < (4, 5, 0):
            # 4.0 - 4.4: built-in SMOOTH_COLOR (point size may be ignored)
            shader = gpu.shader.from_builtin("SMOOTH_COLOR")
            batch = batch_for_shader(shader, "POINTS", {"pos": pts, "color": cols})
        else:
            # 4.5+ including 5.x: custom shader for reliable gl_PointSize
            shader_info = create_shader_ppc_info()
            if shader_info is None:
                shader = gpu.shader.from_builtin("SMOOTH_COLOR")
                batch = batch_for_shader(shader, "POINTS", {"pos": pts, "color": cols})
            else:
                shader = gpu.shader.create_from_info(shader_info)
                batch = batch_for_shader(shader, "POINTS", {"pos": pts, "vcol": cols})
    else:
        if app.version < (4, 0, 0):
            shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
        elif app.version < (4, 5, 0):
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        else:
            shader_info = create_shader_info()
            shader = gpu.shader.create_from_info(shader_info)
        batch = batch_for_shader(shader, "POINTS", {"pos": points})
    gpu.state.blend_set("ALPHA")
    gpu.state.point_size_set(size)
    shader.bind()

    # Bind uniforms for uniform-color path only
    if not use_vertex_colors:
        shader.uniform_float("color", color)
    else:
        # For custom 4.5+/5.x shader provide point size via uniform (try in case of built-in fallback)
        if app.version >= (4, 5, 0):
            try:
                shader.uniform_float("pointSize", size)
            except Exception:
                pass

    if matrix is not None:
        # Apply an additional transform for this draw only, without disturbing
        # the current projection/view matrices.
        try:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(matrix)
                batch.draw(shader)
            return
        except Exception:
            pass

    batch.draw(shader)
