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


def draw_image(
    x: float,
    y: float,
    width: float,
    height: float,
    image: bpy.types.Image,
    transparency: float,
    crop: Tuple[float, float, float, float] = (0, 0, 1, 1),
    batch: Optional[gpu.types.GPUBatch] = None,
) -> Optional[gpu.types.GPUBatch]:
    """Draws an image at given location with given size.

    Returns:
        The batch object if successful, or None if the image is invalid.
    """
    try:
        image.name
    except Exception:
        bk_logger.warning("Image is invalid- draw function")
        return None

    image_shader = None
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

    if batch is None or image_shader is None or texture is None:
        return None

    gpu.state.blend_set("ALPHA")

    image_shader.bind()
    image_shader.uniform_sampler("image", texture)
    batch.draw(image_shader)

    return batch


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

    image_shader = None
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

        if app.version < (4, 0, 0):
            image_shader = gpu.shader.from_builtin("2D_IMAGE")
        else:
            image_shader = gpu.shader.from_builtin("IMAGE")
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
        gpu.state.blend_set("ALPHA")

        image_shader.bind()
        image_shader.uniform_sampler("image", texture)
        batch.draw(image_shader)

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

    if app.version >= (5, 0, 0):
        img.colorspace_settings.is_data = True

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
