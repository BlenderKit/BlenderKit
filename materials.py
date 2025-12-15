"""Collection of blender materials."""

from __future__ import annotations

import logging

from typing import Any

import bpy


bk_logger = logging.getLogger(__name__)


FOUR_LEN = 4
THREE_LEN = 3


def _as_float(v: Any) -> float:
    try:
        if isinstance(v, (tuple, list)):
            # average components
            return float(sum(map(float, v)) / max(1, len(v)))
        return float(v)
    except TypeError:
        return 0.0


def _as_vec3(v: Any) -> tuple[float, float, float]:
    try:
        if isinstance(v, (tuple, list)):  # noqa: SIM108
            vals = list(map(float, v))
        else:
            vals = [float(v)]
        if len(vals) >= THREE_LEN:  # noqa: SIM108
            vals = vals[:THREE_LEN]
        else:
            vals = [*vals, 0.0, 0.0, 0.0][:THREE_LEN]
        return float(vals[0]), float(vals[1]), float(vals[2])
    except TypeError:
        return (0.0, 0.0, 0.0)


def _as_rgba(v: Any) -> tuple[float, float, float, float]:
    try:
        if isinstance(v, (tuple, list)):  # noqa: SIM108
            vals = list(map(float, v))
        else:
            vals = [float(v)]
        if len(vals) >= FOUR_LEN:
            vals = vals[:FOUR_LEN]
        elif len(vals) == THREE_LEN:
            vals = [vals[0], vals[1], vals[2], 1.0]
        else:
            # gray with alpha 1
            vals = [vals[0], vals[0], vals[0], 1.0]
        return float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3])
    except TypeError:
        return (0.0, 0.0, 0.0, 1.0)


def _set_value_safer(
    target_socket: bpy.types.NodeSocket, value: Any
) -> None:  # noqa: C901
    """Set a node socket default_value safely, converting shape/type as needed.

    Pass the NodeSocket itself, not its .default_value.
    """
    if target_socket is None:
        bk_logger.warning("Target socket is None.")
        return
    if not hasattr(target_socket, "default_value"):
        bk_logger.warning(
            "Socket %r has no default_value.",
            getattr(target_socket, "name", target_socket),
        )
        return

    stype = getattr(target_socket, "type", "VALUE")

    # Coerce by socket type
    if stype in ("RGBA",):
        coerced = _as_rgba(value)
    elif stype in ("VECTOR", "XYZ"):
        coerced = _as_vec3(value)
    elif stype in ("VALUE", "INT", "BOOLEAN"):
        coerced = _as_float(value)
    else:
        coerced = value

    # Assign; if Blender array, assign per component
    try:
        target_socket.default_value = coerced  # type: ignore[assignment]
    except TypeError:
        try:
            dv = target_socket.default_value
            if isinstance(coerced, (tuple, list)) and hasattr(dv, "__len__"):
                for i, c in enumerate(coerced):
                    try:
                        dv[i] = float(c)
                    except (TypeError, IndexError):
                        bk_logger.warning(
                            "Failed to set component %d on socket %r",
                            i,
                            getattr(target_socket, "name", target_socket),
                        )  # noqa: E501
            else:
                # last resort: try float cast
                target_socket.default_value = float(coerced)  # type: ignore[assignment]
        except Exception:
            bk_logger.exception(
                "Failed to set value on socket %r",
                getattr(target_socket, "name", target_socket),
            )


def _find_socket(
    sockets: bpy.types.NodeInputs,
    *,
    name: str | None = None,
    fallback_index: int | None = None,
) -> bpy.types.NodeSocket | None:
    """Return a node socket by name when possible, falling back to an index."""

    if name:
        lowered = name.lower()
        try:
            candidate = sockets[name]
            if candidate is not None:
                return candidate
        except (KeyError, TypeError, ValueError):
            pass
        finder = getattr(sockets, "find", None)
        if callable(finder):
            idx = finder(name)
            if idx >= 0:
                try:
                    return sockets[idx]
                except (IndexError, TypeError):
                    pass
        for socket in sockets:
            socket_name = getattr(socket, "name", "")
            if socket_name and socket_name.lower() == lowered:
                return socket
            identifier = getattr(socket, "identifier", "")
            if identifier and identifier.lower() == lowered:
                return socket
    if fallback_index is not None:
        try:
            return sockets[fallback_index]
        except (IndexError, TypeError):
            return None
    return None


def _set_socket_value(
    sockets: bpy.types.NodeInputs,
    name: str,
    fallback_index: int,
    value: Any,
) -> None:
    """Set a socket value looking up by name when available."""

    socket = _find_socket(sockets, name=name, fallback_index=fallback_index)
    if socket is None:
        logger.warning(
            "Socket '%s' (fallback index %d) not found", name, fallback_index
        )
        return
    _set_value_safer(socket, value)


def _set_principled_bsdf_defaults(bsdf_node: bpy.types.Node) -> None:
    """Set Principled BSDF node inputs to default values."""

    sockets = bsdf_node.inputs
    _set_socket_value(sockets, "Base Color", 0, (0.8, 0.8, 0.8, 1.0))
    _set_socket_value(sockets, "Metallic", 1, 0.0)
    _set_socket_value(sockets, "Roughness", 2, 0.5)
    _set_socket_value(sockets, "IOR", 3, 1.45)
    _set_socket_value(sockets, "Alpha", 4, 1.0)
    _set_socket_value(sockets, "Normal", 5, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Subsurface Weight", 7, 0.0)
    _set_socket_value(sockets, "Subsurface Radius", 8, (1.0, 0.2, 0.1))
    _set_socket_value(sockets, "Subsurface Scale", 9, 1.0)
    _set_socket_value(sockets, "Subsurface Anisotropy", 11, 0.0)
    _set_socket_value(sockets, "Specular IOR Level", 12, 0.5)
    _set_socket_value(sockets, "Specular Tint", 13, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Anisotropic", 14, 0.0)
    _set_socket_value(sockets, "Anisotropic Rotation", 15, 0.0)
    _set_socket_value(sockets, "Tangent", 16, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Transmission Weight", 17, 0.0)
    _set_socket_value(sockets, "Coat Weight", 18, 0.0)
    _set_socket_value(sockets, "Coat Roughness", 19, 0.03)
    _set_socket_value(sockets, "Coat IOR", 20, 1.5)
    _set_socket_value(sockets, "Coat Tint", 21, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Coat Normal", 22, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Sheen Weight", 23, 0.0)
    _set_socket_value(sockets, "Sheen Roughness", 24, 0.5)
    _set_socket_value(sockets, "Sheen Tint", 25, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Emission Color", 26, (0.0, 0.0, 0.0, 1.0))
    _set_socket_value(sockets, "Emission Strength", 27, 0.0)


def bkit_wireframe() -> bpy.types.Material:  # noqa: PLR0915
    """Initialize bkit wireframe node group."""
    if "bkit wireframe" in bpy.data.materials:
        return bpy.data.materials["bkit wireframe"]
    mat = bpy.data.materials.new(name="bkit wireframe")
    mat.use_nodes = True

    bkit_wireframe = mat.node_tree

    # Start with a clean node tree
    for node in list(bkit_wireframe.nodes):
        bkit_wireframe.nodes.remove(node)

    # Initialize bkit_wireframe nodes
    material_output_001 = bkit_wireframe.nodes.new("ShaderNodeOutputMaterial")
    material_output_001.name = "Material Output.001"
    material_output_001.is_active_output = True
    material_output_001.target = "ALL"
    # Displacement
    material_output_001.inputs[2].default_value = (0.0, 0.0, 0.0)

    wireframe = bkit_wireframe.nodes.new("ShaderNodeWireframe")
    wireframe.name = "Wireframe"
    wireframe.use_pixel_size = True
    wireframe.inputs[0].default_value = 1.0

    object_info = bkit_wireframe.nodes.new("ShaderNodeObjectInfo")
    object_info.name = "Object Info"

    principled_bsdf = bkit_wireframe.nodes.new("ShaderNodeBsdfPrincipled")
    principled_bsdf.name = "Principled BSDF"
    principled_bsdf.distribution = "MULTI_GGX"
    principled_bsdf.subsurface_method = "RANDOM_WALK"
    sockets = principled_bsdf.inputs
    _set_socket_value(sockets, "Base Color", 0, (0.0, 0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Metallic", 1, 0.0)
    _set_socket_value(sockets, "Roughness", 2, 0.5)
    _set_socket_value(sockets, "IOR", 3, 1.5)
    _set_socket_value(sockets, "Normal", 5, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Subsurface Weight", 7, 0.0)
    _set_socket_value(sockets, "Subsurface Radius", 8, (1.0, 0.2, 0.1))
    _set_socket_value(sockets, "Subsurface Scale", 9, 0.05)
    _set_socket_value(sockets, "Subsurface Anisotropy", 11, 0.0)
    _set_socket_value(sockets, "Specular IOR Level", 12, 0.5)
    _set_socket_value(sockets, "Specular Tint", 13, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Anisotropic", 14, 0.0)
    _set_socket_value(sockets, "Anisotropic Rotation", 15, 0.0)
    _set_socket_value(sockets, "Tangent", 16, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Transmission Weight", 17, 0.0)
    _set_socket_value(sockets, "Coat Weight", 18, 0.0)
    _set_socket_value(sockets, "Coat Roughness", 19, 0.03)
    _set_socket_value(sockets, "Coat IOR", 20, 1.5)
    _set_socket_value(sockets, "Coat Tint", 21, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Coat Normal", 22, (0.0, 0.0, 0.0))
    _set_socket_value(sockets, "Sheen Weight", 23, 0.0)
    _set_socket_value(sockets, "Sheen Roughness", 24, 0.5)
    _set_socket_value(sockets, "Sheen Tint", 25, (1.0, 1.0, 1.0, 1.0))
    _set_socket_value(sockets, "Emission Strength", 27, 1.0)

    white_noise_texture = bkit_wireframe.nodes.new("ShaderNodeTexWhiteNoise")
    white_noise_texture.name = "White Noise Texture"
    white_noise_texture.noise_dimensions = "1D"

    math = bkit_wireframe.nodes.new("ShaderNodeMath")
    math.name = "Math"
    math.operation = "MULTIPLY"
    math.use_clamp = False
    math.inputs[1].default_value = 100.0

    hue_saturation_value = bkit_wireframe.nodes.new("ShaderNodeHueSaturation")
    hue_saturation_value.name = "Hue/Saturation/Value"
    _set_value_safer(hue_saturation_value.inputs[1], 1.0)  # Saturation
    _set_value_safer(hue_saturation_value.inputs[2], 1.0)  # Value
    _set_value_safer(hue_saturation_value.inputs[3], 1.0)  # Fac
    _set_value_safer(hue_saturation_value.inputs[4], (1.0, 0.0, 0.0, 1.0))  # Color

    invert_color = bkit_wireframe.nodes.new("ShaderNodeInvert")
    invert_color.name = "Invert Color"
    _set_value_safer(invert_color.inputs[1], (0.0, 0.0, 0.0, 1.0))  # Color

    mix_shader = bkit_wireframe.nodes.new("ShaderNodeMixShader")
    mix_shader.name = "Mix Shader"

    translucent_bsdf = bkit_wireframe.nodes.new("ShaderNodeBsdfTranslucent")
    translucent_bsdf.name = "Translucent BSDF"
    _set_value_safer(translucent_bsdf.inputs[0], (0.8, 0.8, 0.8, 0.0))  # Color
    _set_value_safer(translucent_bsdf.inputs[1], (0.0, 0.0, 0.0))  # Normal

    geometry = bkit_wireframe.nodes.new("ShaderNodeNewGeometry")
    geometry.name = "Geometry"

    wire_rgb = bkit_wireframe.nodes.new("ShaderNodeRGB")
    wire_rgb.name = "wire_RGB"
    _set_value_safer(wire_rgb.outputs[0], (0.25, 0.5, 0.36, 1.0))  # Output Color

    custom_wire_color = bkit_wireframe.nodes.new("ShaderNodeValue")
    custom_wire_color.name = "custom_wire_color"
    _set_value_safer(custom_wire_color.outputs[0], 0.0)

    mix = bkit_wireframe.nodes.new("ShaderNodeMix")
    mix.name = "Mix"
    mix.blend_type = "MIX"
    mix.clamp_factor = True
    mix.clamp_result = False
    mix.data_type = "RGBA"
    mix.factor_mode = "UNIFORM"

    # Set locations
    material_output_001.location = (1210, 1130)
    wireframe.location = (26, 948)
    object_info.location = (-440, 832)
    principled_bsdf.location = (646, 1116)
    white_noise_texture.location = (-11, 757)
    math.location = (-229, 801)
    hue_saturation_value.location = (191, 693)
    invert_color.location = (252, 955)
    mix_shader.location = (954, 1268)
    translucent_bsdf.location = (938, 1042)
    geometry.location = (694, 1453)
    wire_rgb.location = (196, 507)
    custom_wire_color.location = (197, 785)
    mix.location = (426, 853)

    # Set dimensions
    material_output_001.width, material_output_001.height = 140.0, 100.0
    wireframe.width, wireframe.height = 140.0, 100.0
    object_info.width, object_info.height = 140.0, 100.0
    principled_bsdf.width, principled_bsdf.height = 240.0, 100.0
    white_noise_texture.width, white_noise_texture.height = 140.0, 100.0
    math.width, math.height = 140.0, 100.0
    hue_saturation_value.width, hue_saturation_value.height = 150.0, 100.0
    invert_color.width, invert_color.height = 140.0, 100.0
    mix_shader.width, mix_shader.height = 140.0, 100.0
    translucent_bsdf.width, translucent_bsdf.height = 140.0, 100.0
    geometry.width, geometry.height = 140.0, 100.0
    wire_rgb.width, wire_rgb.height = 140.0, 100.0
    custom_wire_color.width, custom_wire_color.height = 140.0, 100.0
    mix.width, mix.height = 140.0, 100.0

    # Initialize bkit_wireframe links

    # invert_color.Color -> principled_bsdf.Alpha
    alpha_socket = _find_socket(principled_bsdf.inputs, name="Alpha", fallback_index=4)
    if alpha_socket is not None:
        bkit_wireframe.links.new(invert_color.outputs[0], alpha_socket)
    # math.Value -> white_noise_texture.W
    bkit_wireframe.links.new(math.outputs[0], white_noise_texture.inputs[1])
    # object_info.Random -> math.Value
    bkit_wireframe.links.new(object_info.outputs[5], math.inputs[0])
    # white_noise_texture.Value -> hue_saturation_value.Hue
    bkit_wireframe.links.new(
        white_noise_texture.outputs[0], hue_saturation_value.inputs[0]
    )
    # mix.Result -> principled_bsdf.Emission Color
    emission_color_socket = _find_socket(
        principled_bsdf.inputs, name="Emission Color", fallback_index=26
    )
    if emission_color_socket is not None:
        bkit_wireframe.links.new(mix.outputs[2], emission_color_socket)
    # wireframe.Fac -> invert_color.Fac
    bkit_wireframe.links.new(wireframe.outputs[0], invert_color.inputs[0])
    # mix_shader.Shader -> material_output_001.Surface
    bkit_wireframe.links.new(mix_shader.outputs[0], material_output_001.inputs[0])
    # principled_bsdf.BSDF -> mix_shader.Shader
    bkit_wireframe.links.new(principled_bsdf.outputs[0], mix_shader.inputs[1])
    # translucent_bsdf.BSDF -> mix_shader.Shader
    bkit_wireframe.links.new(translucent_bsdf.outputs[0], mix_shader.inputs[2])
    # geometry.Backfacing -> mix_shader.Fac
    bkit_wireframe.links.new(geometry.outputs[6], mix_shader.inputs[0])
    # hue_saturation_value.Color -> mix.A
    bkit_wireframe.links.new(hue_saturation_value.outputs[0], mix.inputs[6])
    # wire_rgb.Color -> mix.B
    bkit_wireframe.links.new(wire_rgb.outputs[0], mix.inputs[7])
    # custom_wire_color.Value -> mix.Factor
    bkit_wireframe.links.new(custom_wire_color.outputs[0], mix.inputs[0])

    return mat
