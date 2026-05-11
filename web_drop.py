# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

"""Swallow BlenderKit website image drops so Blender does not import them.

The real "drag an asset from the website into Blender" flow runs entirely
through the bkclientjs library on the BlenderKit website:

1. On ``dragstart`` of an asset preview image, the website POSTs the asset's
   ``asset_base_id`` / ``asset_type`` to the local BlenderKit Client
   (``/bkclientjs/get_asset`` — the same endpoint used by the "Get this model"
   button).
2. The Client forwards the request to this addon, where
   :func:`asset_bar_op.handle_bkclientjs_get_asset` populates the search
   history and starts the ``view3d.asset_drag_drop`` modal.
3. The user's drag continues; when they release the mouse over the 3D
   viewport, Blender also delivers the browser's temporary preview thumbnail
   to us as a file drop. We don't need that file — the drag-drop modal is
   already running — so this :class:`bpy.types.FileHandler` simply consumes
   the drop silently to prevent Blender from importing the temp image as an
   empty / reference image / background image.

The thumbnail filename follows a fixed BlenderKit pattern, so we can detect
the drop with very high confidence and never interfere with unrelated image
drops.
"""

import logging
import os
import re

import bpy
from bpy.props import StringProperty


bk_logger = logging.getLogger(__name__)


# Temporary filename produced by browsers when dragging a BlenderKit preview
# image. Examples seen in the wild:
#   thumbnail_<uuid>.jpg.2048x2048_q85.jpg.webp   (model previews)
#   thumbnail_<uuid>.png.2048x2048_q85.png.webp   (with-alpha previews)
#   thumbnail_<uuid>.jpg.2048x2048_q85.jpg        (older browsers, no webp re-encode)
_THUMBNAIL_FILENAME_RE = re.compile(
    r"^thumbnail_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(?:jpe?g|png)\.\d+x\d+_q\d+\.(?:jpe?g|png)(?:\.webp)?$",
    re.IGNORECASE,
)


def _is_blenderkit_thumbnail_filename(filepath: str) -> bool:
    """Return True when *filepath* looks like a BlenderKit web-drag thumbnail."""
    return bool(_THUMBNAIL_FILENAME_RE.match(os.path.basename(filepath or "")))


class BLENDERKIT_OT_web_drop(bpy.types.Operator):
    """Absorb a BlenderKit website image drop (handled via bkclientjs)."""

    bl_idname = "wm.blenderkit_web_drop"
    bl_label = "BlenderKit Web Drop"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(  # type: ignore
        name="Dropped file",
        subtype="FILE_PATH",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        if not _is_blenderkit_thumbnail_filename(self.filepath):
            # Not ours — let other handlers / default behaviour take over.
            return {"CANCELLED"}
        bk_logger.info(
            "Web-drop: absorbed BlenderKit thumbnail drop (%s); "
            "bkclientjs is expected to drive the actual download.",
            os.path.basename(self.filepath),
        )
        # FINISHED with no side effects — Blender will not try any further
        # handler for this drop.
        return {"FINISHED"}

    def execute(self, context):
        return {"FINISHED"}


class BLENDERKIT_FH_web_drop(bpy.types.FileHandler):
    """File handler that catches image drops originating from blenderkit.com."""

    bl_idname = "BLENDERKIT_FH_web_drop"
    bl_label = "BlenderKit Web Drop"
    bl_import_operator = BLENDERKIT_OT_web_drop.bl_idname
    bl_file_extensions = ".webp;.jpg;.jpeg;.png"

    @classmethod
    def poll_drop(cls, context):
        # We cannot inspect the filepath here — Blender only hands it to the
        # operator on invoke. Accept image drops in the 3D viewport; the
        # operator's invoke() validates the filename and bails out cleanly
        # when it is not a BlenderKit thumbnail. With multiple matching
        # FileHandlers, Blender presents a menu so the user can choose.
        return context.area is not None and context.area.type == "VIEW_3D"


_CLASSES = (
    BLENDERKIT_OT_web_drop,
    BLENDERKIT_FH_web_drop,
)


def register():
    if not hasattr(bpy.types, "FileHandler"):
        # Blender < 4.1 — feature unavailable, silently skip.
        bk_logger.info("Web drop: bpy.types.FileHandler not available, skipping.")
        return
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    if not hasattr(bpy.types, "FileHandler"):
        return
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
