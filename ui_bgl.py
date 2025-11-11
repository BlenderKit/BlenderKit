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

import blf
import gpu
import logging
from bpy import app
from gpu_extras.batch import batch_for_shader

bk_logger = logging.getLogger(__name__)

cached_images = {}
_cached_image_shader = None


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
    shader.uniform_float("color", color)
    gpu.state.blend_set("ALPHA")
    batch.draw(shader)


def draw_rect_2d(x, y, width, height, color, line_width=1):
    xmax = x + width
    ymax = y + height
    points = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1), (1, 2), (2, 3), (3, 0))

    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    else:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": points}, indices=indices)

    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(line_width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


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
void main()
{
    vec4 color = texture(image, uv);
    color.a *= transparency;
    fragColor = color;
}
"""


def create_image_shader():
    """Return a cached shader that supports transparency across Blender versions."""
    global _cached_image_shader

    if _cached_image_shader is not None:
        return _cached_image_shader

    shader = None

    if app.version >= (4, 5, 0):
        try:
            shader_info = gpu.types.GPUShaderCreateInfo()
            shader_info.vertex_in(0, "VEC2", "pos")
            shader_info.vertex_in(1, "VEC2", "texCoord")

            stage_iface = gpu.types.GPUStageInterfaceInfo("uv_iface")
            stage_iface.smooth("VEC2", "uv")
            shader_info.vertex_out(stage_iface)

            shader_info.push_constant("MAT4", "ModelViewProjectionMatrix")
            shader_info.push_constant("FLOAT", "transparency")
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
                    color.a *= transparency;
                    fragColor = color;
                }
            """
            )
            shader = gpu.shader.create_from_info(shader_info)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Failed to create image shader via create_info") from exc

    if shader is None:
        try:
            shader = gpu.types.GPUShader(VERTEX_SHADER_LEGACY, FRAGMENT_SHADER_LEGACY)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Failed to create image shader") from exc

    _cached_image_shader = shader
    return shader


def draw_image(
    x,
    y,
    width,
    height,
    image,
    transparency: float = 1.0,
    crop=(0, 0, 1, 1),
    batch=None,
):
    # draw_rect(x,y, width, height, (.5,0,0,.5))

    try:
        image.name
    except:
        print("Image is invalid- draw function")
        return

    image_shader = create_image_shader()
    texture = None

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
    # set floats
    image_shader.uniform_float("transparency", transparency)

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
