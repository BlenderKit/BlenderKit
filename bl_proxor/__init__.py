"""bl_proxor \u2013 lightweight PRX viewer and generator, integrated into BlenderKit.

Generates, saves, loads, and displays PRX/PRXC proxor data in the viewport
via GPU drawing.  Used as a preview proxy during model drag-and-drop instead
of the default green bounding box when a .prxc file is available for the asset.
"""

from __future__ import annotations

from . import draw, generate, prx_format


def register() -> None:
    """Register the bl_proxor submodule."""
    draw.ensure_shaders()


def unregister() -> None:
    """Unregister the bl_proxor submodule."""
    draw.invalidate_shader_cache()
