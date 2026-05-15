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
import threading
from typing import Callable, Optional

import bpy
from bpy.props import StringProperty

from . import client_lib, client_tasks


bk_logger = logging.getLogger(__name__)


# Temporary filename produced by browsers when dragging a BlenderKit preview
# image. The browser always re-encodes the dropped preview to .webp, so we
# only ever see ``thumbnail_<uuid>.<anything>.webp``. Examples seen in the
# wild:
#   thumbnail_<uuid>.jpg.2048x2048_q85.jpg.webp   (model previews)
#   thumbnail_<uuid>.png.2048x2048_q85.png.webp   (with-alpha previews)
_THUMBNAIL_FILENAME_RE = re.compile(
    r"^thumbnail_(?P<file_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r".*\.webp$",
    re.IGNORECASE,
)


def _is_blenderkit_thumbnail_filename(filepath: str) -> bool:
    """Return True when *filepath* looks like a BlenderKit web-drag thumbnail."""
    return bool(_THUMBNAIL_FILENAME_RE.match(os.path.basename(filepath or "")))


def extract_thumbnail_file_id(filepath: str) -> Optional[str]:
    """Return the asset-file UUID embedded in a BlenderKit thumbnail filename.

    Returns ``None`` when the filename does not match the BlenderKit pattern.
    """
    m = _THUMBNAIL_FILENAME_RE.match(os.path.basename(filepath or ""))
    if not m:
        return None
    return m.group("file_id").lower()


class BLENDERKIT_OT_web_drop(bpy.types.Operator):
    """Place a BlenderKit asset dragged from the BlenderKit website."""

    bl_idname = "wm.blenderkit_web_drop"
    bl_label = "Place BlenderKit Asset"
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
        bk_logger.info("Web-drop: received file drop: %s", self.filepath)
        return {"CANCELLED"}
        if not _is_blenderkit_thumbnail_filename(self.filepath):
            # Not ours — let other handlers / default behaviour take over.
            return {"CANCELLED"}

        # Capture the viewport context now: by the time the async asset-file
        # lookup returns, Blender's automatic ``bpy.context`` may no longer
        # point at the original VIEW_3D region.
        file_id = extract_thumbnail_file_id(self.filepath)
        region = next(
            (r for r in context.area.regions if r.type == "WINDOW"),
            None,
        )
        if file_id and region is not None:
            _DROP_CONTEXTS[file_id] = {
                "window": context.window,
                "area": context.area,
                "region": region,
            }

        bk_logger.info(
            "Web-drop: placing BlenderKit thumbnail drop (%s); resolving "
            "asset-file %s -> assetBaseId via BlenderKit-Client.",
            os.path.basename(self.filepath),
            file_id,
        )
        request_asset_base_id_for_thumbnail(self.filepath)
        return {"FINISHED"}

    def execute(self, context):
        return {"FINISHED"}


# bpy.types.FileHandler was introduced in Blender 4.1. On older Blender the
# attribute does not exist, so referencing it at class-definition time would
# raise AttributeError at import. Define the FileHandler class only when the
# base type is actually available.
if hasattr(bpy.types, "FileHandler"):

    class BLENDERKIT_FH_web_drop(bpy.types.FileHandler):
        """File handler that catches image drops originating from blenderkit.com."""

        bl_idname = "BLENDERKIT_FH_web_drop"
        bl_label = "BlenderKit Web Drop"
        bl_import_operator = BLENDERKIT_OT_web_drop.bl_idname
        # Browsers always deliver BlenderKit previews as .webp temp files. Keep
        # the filter as narrow as possible so we never compete with regular
        # .jpg/.png/.jpeg image drops from the user's file manager.
        bl_file_extensions = ".webp;.png;.gif;.jpg;.jpeg"

        @classmethod
        def poll_drop(cls, context):
            # Only opt into the drop when the user has explicitly enabled
            # auto-import for recognized BlenderKit asset previews. Otherwise
            # we step out entirely and let Blender's default image-drop
            # behaviour (or any other handler) take over.
            if context.area is None or context.area.type != "VIEW_3D":
                return False
            try:
                prefs = context.preferences.addons[__package__].preferences
                return bool(getattr(prefs, "skip_web_drop_confirmation", False))
            except Exception:
                return False

    _CLASSES = (
        BLENDERKIT_OT_web_drop,
        BLENDERKIT_FH_web_drop,
    )
else:
    _CLASSES = ()


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


# ---------------------------------------------------------------------------
# Asset-file UUID -> assetBaseId lookup
# ---------------------------------------------------------------------------
#
# The browser only gives us a thumbnail file (and therefore the asset-file
# UUID embedded in its name) — not the asset_base_id we need to download the
# asset. We resolve that via the BlenderKit-Client endpoint /asset_files/get
# which calls GET /api/v1/asset-files/<file_id>/ on the server.
#
# Callers register a callback with :func:`request_asset_base_id_for_thumbnail`
# and the response is dispatched here from ``timer.handle_task`` via
# :func:`handle_get_asset_file_task`.

# file_id -> list of pending callbacks (callback signature: cb(result, error))
_PENDING_LOOKUPS: dict[str, list[Callable[[Optional[dict], Optional[str]], None]]] = {}
_PENDING_LOOKUPS_LOCK = threading.Lock()

# file_id -> viewport context captured at drop time so we can replay the
# drag-drop modal once the async lookup returns. Stored on the main thread
# from BLENDERKIT_OT_web_drop.invoke() and consumed (popped) on the main
# thread from _start_drag_for_asset(); no locking required.
_DROP_CONTEXTS: dict[str, dict] = {}


def request_asset_base_id_for_thumbnail(
    thumbnail_filepath_or_id: str,
    callback: Optional[Callable[[Optional[dict], Optional[str]], None]] = None,
) -> Optional[str]:
    """Resolve a BlenderKit thumbnail file to its parent asset metadata.

    Accepts either a full thumbnail filepath / filename (as delivered by a
    web drop) or a bare asset-file UUID. If *callback* is provided it will
    be invoked from the main thread once the BlenderKit-Client returns the
    response: ``callback(result_dict, error_message)`` — exactly one of the
    two arguments will be non-None.

    Returns the extracted file_id (so callers can correlate), or ``None`` if
    the input did not look like a BlenderKit thumbnail and no request was
    fired.
    """
    file_id = extract_thumbnail_file_id(thumbnail_filepath_or_id)
    if file_id is None:
        # Maybe the caller already passed a bare UUID.
        bare = (thumbnail_filepath_or_id or "").strip().lower()
        if re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            bare,
        ):
            file_id = bare
        else:
            bk_logger.warning(
                "request_asset_base_id_for_thumbnail: not a BlenderKit thumbnail "
                "or UUID: %r",
                thumbnail_filepath_or_id,
            )
            return None

    if callback is not None:
        with _PENDING_LOOKUPS_LOCK:
            _PENDING_LOOKUPS.setdefault(file_id, []).append(callback)

    try:
        resp = client_lib.get_asset_file(file_id)
        if resp.status_code != 200:
            bk_logger.warning(
                "asset-file lookup: client returned %s for %s: %s",
                resp.status_code,
                file_id,
                resp.text[:200],
            )
    except Exception as e:  # network / client offline
        bk_logger.warning("asset-file lookup failed for %s: %s", file_id, e)
        # Drain the callback so the caller is not left waiting forever.
        cbs: list[Callable[[Optional[dict], Optional[str]], None]] = []
        with _PENDING_LOOKUPS_LOCK:
            cbs = _PENDING_LOOKUPS.pop(file_id, [])
        for cb in cbs:
            try:
                cb(None, str(e))
            except Exception:
                bk_logger.exception("asset-file lookup callback raised")
    return file_id


def handle_get_asset_file_task(task: "client_tasks.Task"):
    """Dispatched from ``timer.handle_task`` for task_type ``asset_files/get``.

    Forwards the result (or error) to any callbacks registered through
    :func:`request_asset_base_id_for_thumbnail` for this file_id. If no
    callback was registered we just log the resolved assetBaseId — useful
    when the lookup was triggered manually from the console.
    """
    if task.status not in ("finished", "error"):
        return

    # The Go client echoes the requested file id back in the result so we
    # can route to the right pending callback. Fall back to the task payload
    # for safety.
    file_id = None
    if isinstance(task.result, dict):
        file_id = task.result.get("file_id")
    if not file_id and isinstance(getattr(task, "data", None), dict):
        file_id = task.data.get("file_id")
    if file_id:
        file_id = file_id.lower()

    cbs: list[Callable[[Optional[dict], Optional[str]], None]] = []
    if file_id:
        with _PENDING_LOOKUPS_LOCK:
            cbs = _PENDING_LOOKUPS.pop(file_id, [])

    if task.status == "error":
        bk_logger.warning("asset-file lookup failed for %s: %s", file_id, task.message)
        for cb in cbs:
            try:
                cb(None, task.message)
            except Exception:
                bk_logger.exception("asset-file lookup callback raised")
        return

    result = task.result if isinstance(task.result, dict) else {}
    asset_base_id = result.get("assetBaseId") or (
        # The /asset-files/ endpoint may nest the asset under "asset".
        (result.get("asset") or {}).get("assetBaseId")
        if isinstance(result.get("asset"), dict)
        else None
    )

    # Kick off the actual drag-drop flow if the Client supplied the full
    # asset record (it does this automatically after resolving the
    # assetBaseId — see GetAssetFile in client/main.go).
    asset_data = result.get("asset_data")
    if isinstance(asset_data, dict) and asset_data.get("assetBaseId"):
        _start_drag_for_asset(asset_data, file_id)

    if not cbs:
        if not isinstance(asset_data, dict):
            bk_logger.info(
                "asset-file %s resolved to assetBaseId=%s (no asset_data in result)",
                file_id,
                asset_base_id,
            )
        return

    for cb in cbs:
        try:
            cb(result, None)
        except Exception:
            bk_logger.exception("asset-file lookup callback raised")


def _start_drag_for_asset(asset_data: dict, file_id: Optional[str] = None) -> None:
    """Replay the asset-bar drag-drop modal for *asset_data*.

    Appends a single-result history step so ``view3d.asset_drag_drop`` can
    pick the asset up by ``asset_search_index=0``, then invokes the modal
    inside the viewport context captured at drop time (otherwise
    ``context.region`` is ``None`` when this runs from the async task
    handler). The user finishes placement with a mouse click in the
    viewport — the modal then triggers the normal download.
    """
    # Import locally to avoid a circular import at module load time.
    from . import search

    try:
        parsed = search.parse_result(asset_data)
    except Exception:
        bk_logger.exception("web-drop: parse_result failed for asset_data")
        return
    if not parsed:
        bk_logger.warning(
            "web-drop: parse_result returned empty for assetBaseId=%s",
            asset_data.get("assetBaseId"),
        )
        return

    asset_type = (asset_data.get("assetType") or "").upper()
    search.append_history_step(
        search_keywords=f"asset_base_id:{asset_data['assetBaseId']}",
        search_results=[parsed],
        asset_type=asset_type,
        search_results_orig={"results": [asset_data], "count": 1},
    )
    try:
        search.load_preview(parsed)
    except Exception:
        bk_logger.exception("web-drop: load_preview failed")

    drop_ctx = _DROP_CONTEXTS.pop(file_id, None) if file_id else None
    if drop_ctx is None:
        # Fallback: find any open VIEW_3D area.
        drop_ctx = _find_viewport_context()
    if drop_ctx is None:
        bk_logger.warning(
            "web-drop: no VIEW_3D region available to start drag modal for %s",
            asset_data.get("assetBaseId"),
        )
        return

    try:
        with bpy.context.temp_override(**drop_ctx):
            bpy.ops.view3d.asset_drag_drop(  # type: ignore[attr-defined]
                "INVOKE_DEFAULT",
                asset_search_index=0,
            )
    except Exception:
        bk_logger.exception("web-drop: failed to invoke view3d.asset_drag_drop")


def _find_viewport_context() -> Optional[dict]:
    """Return ``{window, area, region}`` for the first open VIEW_3D WINDOW region."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return None
    for win in wm.windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return {"window": win, "area": area, "region": region}
    return None
