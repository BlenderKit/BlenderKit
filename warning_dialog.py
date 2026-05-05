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
# ##### END GPL LICENSE BLOCK #####

"""Reusable in-viewport warning dialog drawn with bl_ui_widgets.

The dialog is rendered as a centered panel with a title, a body of text
lines and an arbitrary list of buttons. It is intentionally generic - the
caller registers a :class:`WarningSpec` with a unique ``kind`` and provides
button definitions. Use :func:`show_warning_dialog` to display a
previously registered warning.

A specific use case is gating the asset bar when running on a Microsoft
Store install of Blender (sandboxed, breaks BlenderKit-Client / unpacking
/ background Blender features). The helpers
:func:`is_microsoft_store_blender`, :func:`should_block_for_ms_store` and
:func:`show_ms_store_warning` implement that gate. The acceptance state is
persisted in the addon preferences as ``accepted_ms_store_warning`` and is
also surfaced under "Experimental settings" so it can be reset for
debugging.
"""

import logging
import os
import sys
from typing import Callable, Dict, List, Optional

import bpy
from bpy.props import StringProperty

from .bl_ui_widgets.bl_ui_button import BL_UI_Button
from .bl_ui_widgets.bl_ui_drag_panel import BL_UI_Drag_Panel
from .bl_ui_widgets.bl_ui_draw_op import BL_UI_OT_draw_operator
from .bl_ui_widgets.bl_ui_image import BL_UI_Image
from .bl_ui_widgets.bl_ui_label import BL_UI_Label

bk_logger = logging.getLogger(__name__)

# Top-level addon package - used to look up addon preferences.
_ADDON_PACKAGE = __package__


# ---------------------------------------------------------------------------
# Microsoft Store Blender detection
# ---------------------------------------------------------------------------


def is_microsoft_store_blender() -> bool:
    """Return True if Blender appears to be installed via the Microsoft Store.

    Microsoft Store apps live under the per-user ``WindowsApps`` folder which
    is sandboxed (read-only locations, no child process spawn). That breaks
    several BlenderKit features: launching the BlenderKit-Client binary from
    outside the addon, writing to the user ``blenderkit_data`` folder and
    spawning background Blender processes for thumbnails / unpacking.
    """
    if sys.platform != "win32":
        return False
    candidates = []
    try:
        candidates.append(bpy.app.binary_path or "")
    except Exception:
        pass
    candidates.append(sys.executable or "")
    try:
        candidates.append(os.path.dirname(sys.executable or ""))
    except Exception:
        pass
    for path in candidates:
        if path and "windowsapps" in path.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Warning registry
# ---------------------------------------------------------------------------


# Button color roles, used by the dialog to pick a sensible default style.
BUTTON_PRIMARY = "primary"  # main / destructive call to action
BUTTON_DEFAULT = "default"  # neutral
BUTTON_LINK = "link"  # secondary: opens an URL or similar

_BUTTON_STYLES = {
    BUTTON_PRIMARY: {
        "bg": (0.85, 0.45, 0.10, 1.0),
        "hover": (1.00, 0.55, 0.15, 1.0),
        "fg": (1.0, 1.0, 1.0, 1.0),
    },
    BUTTON_DEFAULT: {
        "bg": (0.18, 0.18, 0.18, 1.0),
        "hover": (0.28, 0.28, 0.28, 1.0),
        "fg": (0.95, 0.95, 0.95, 1.0),
    },
    BUTTON_LINK: {
        "bg": (0.10, 0.30, 0.55, 1.0),
        "hover": (0.15, 0.42, 0.75, 1.0),
        "fg": (1.0, 1.0, 1.0, 1.0),
    },
}


class WarningButton:
    """A single button on a warning dialog.

    ``callback`` receives no arguments. If ``close`` is True (the default),
    the dialog is finished after the callback runs; pass ``close=False`` for
    buttons that just open an URL but should keep the dialog visible.
    """

    def __init__(
        self,
        label: str,
        callback: Optional[Callable[[], None]] = None,
        *,
        style: str = BUTTON_DEFAULT,
        close: bool = True,
    ):
        self.label = label
        self.callback = callback
        self.style = style
        self.close = close


class WarningSpec:
    """Specification of a warning dialog.

    Reusable across different warning use-cases. Provide a unique ``kind``
    (used as the key in the registry and passed to the operator), a
    ``title``, the body ``lines``, and a list of :class:`WarningButton`.
    ``on_dismiss`` is invoked when the dialog is closed via ESC.
    """

    def __init__(
        self,
        kind: str,
        title: str,
        lines: List[str],
        buttons: List[WarningButton],
        on_dismiss: Optional[Callable[[], None]] = None,
        width: int = 760,
    ):
        self.kind = kind
        self.title = title
        self.lines = list(lines)
        self.buttons = list(buttons)
        self.on_dismiss = on_dismiss
        self.width = width


# Registry of warning specs keyed by ``kind``. Allows reusing the same
# draw-operator for multiple warning types without storing callables on
# Blender properties (which only support primitives).
_WARNING_REGISTRY: Dict[str, WarningSpec] = {}


def register_warning(spec: WarningSpec) -> None:
    """Register (or replace) a warning spec by its ``kind`` key."""
    _WARNING_REGISTRY[spec.kind] = spec


def get_warning(kind: str) -> Optional[WarningSpec]:
    return _WARNING_REGISTRY.get(kind)


# ---------------------------------------------------------------------------
# Generic warning draw operator
# ---------------------------------------------------------------------------


class BlenderKitWarningDialogOperator(BL_UI_OT_draw_operator):
    """Modal draw-operator that renders a registered warning spec."""

    bl_idname = "view3d.blenderkit_warning_dialog"
    bl_label = "BlenderKit warning"
    bl_description = "Show a BlenderKit warning dialog"
    bl_options = {"REGISTER"}
    instances: List["BlenderKitWarningDialogOperator"] = []

    kind: StringProperty(  # type: ignore[valid-type]
        name="kind",
        description="Warning kind, looked up in the warning registry",
        default="",
        options={"SKIP_SAVE"},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec: Optional[WarningSpec] = None
        self.panel: Optional[BL_UI_Drag_Panel] = None
        self.logo: Optional[BL_UI_Image] = None
        self.brand_lbl: Optional[BL_UI_Label] = None
        self.title_lbl: Optional[BL_UI_Label] = None
        self.body_lbls: List[BL_UI_Label] = []
        self.buttons: List[BL_UI_Button] = []

    # -- callback dispatch ---------------------------------------------------

    def _make_button_handler(self, btn: WarningButton):
        def _handler(_widget):
            if btn.close:
                self.finish()
            if btn.callback is not None:
                try:
                    btn.callback()
                except Exception:
                    bk_logger.exception(
                        "warning '%s' button '%s' callback failed",
                        self._spec.kind if self._spec else "?",
                        btn.label,
                    )

        return _handler

    # -- layout --------------------------------------------------------------

    def _build_widgets(self, context):
        spec = self._spec
        assert spec is not None
        # Use the system DPI scale (dpi / 96) on top of the user's view UI
        # scale so the dialog stays readable on high-DPI displays where
        # `view.ui_scale` alone often resolves to ~1.0.
        from . import ui_bgl

        view_scale = context.preferences.view.ui_scale
        dpi_scale = ui_bgl.get_ui_scale()
        ui_scale = max(view_scale, dpi_scale)

        margin = int(22 * ui_scale)
        title_size = int(24 * ui_scale)
        text_size = int(16 * ui_scale)
        line_h = int(text_size * 1.6)
        button_h = int(40 * ui_scale)
        button_gap = int(12 * ui_scale)
        button_pad_x = int(22 * ui_scale)
        char_w = int(10 * ui_scale)
        min_button_w = int(140 * ui_scale)

        # Per-button width based on the button's own label so buttons don't
        # all share the longest label's width (which previously pushed
        # short buttons like "Cancel" off the left edge of the panel).
        button_widths = [
            max(min_button_w, len(b.label) * char_w + 2 * button_pad_x)
            for b in spec.buttons
        ]
        buttons_row_w = sum(button_widths) + button_gap * max(0, len(button_widths) - 1)

        # Auto-grow panel width if the buttons row exceeds the requested width.
        width = max(int(spec.width * ui_scale), buttons_row_w + 2 * margin)

        # Header (logo + "BlenderKit" wordmark) sits above the title so it is
        # always clear which addon produced the dialog.
        logo_size = int(36 * ui_scale)
        brand_size = int(22 * ui_scale)
        brand_h = max(logo_size, int(brand_size * 1.4))
        header_gap = int(8 * ui_scale)
        title_h = int(title_size * 1.4)
        body_h = line_h * len(spec.lines)
        height = (
            margin
            + brand_h
            + header_gap
            + title_h
            + int(8 * ui_scale)
            + body_h
            + int(14 * ui_scale)
            + button_h
            + margin
        )

        area = context.area
        x = max(0, (area.width - width) // 2)
        y = max(0, (area.height - height) // 2)
        # Remember the current area size so we can recenter the panel when
        # the user resizes the Blender window.
        self._last_area_size = (area.width, area.height)
        self._panel_size = (width, height)

        # Background panel (acts as drag handle and as a click-through blocker
        # over the area underneath).
        panel = BL_UI_Drag_Panel(x, y, width, height)
        panel.bg_color = (0.06, 0.06, 0.06, 0.95)
        panel.background = True  # enables rounded background drawing
        panel.background_corner_radius = (12.0,)
        panel.background_border = True
        panel.background_border_color = (1.0, 0.55, 0.10, 1.0)
        panel.background_border_thickness = 2.0
        self.panel = panel

        # Header: BlenderKit logo + wordmark, so the user never wonders
        # which addon produced this dialog.
        from . import paths

        logo = BL_UI_Image(margin, margin, logo_size, logo_size)
        try:
            logo_fp = paths.get_addon_thumbnail_path("blenderkit_logo.png")
            logo.set_image(logo_fp)
            logo.set_image_size((logo_size, logo_size))
            logo.set_image_position((0, 0))
        except Exception:
            bk_logger.exception("Could not load BlenderKit logo for warning dialog")
        self.logo = logo

        brand_x = margin + logo_size + int(10 * ui_scale)
        brand_y = margin + (logo_size - brand_h) // 2
        brand_lbl = BL_UI_Label(brand_x, brand_y, width - brand_x - margin, brand_h)
        brand_lbl.text = "BlenderKit"
        brand_lbl.text_size = brand_size
        brand_lbl.text_color = (1.0, 0.72, 0.20, 1.0)
        self.brand_lbl = brand_lbl

        # Title (below header)
        title_y = margin + brand_h + header_gap
        title_lbl = BL_UI_Label(margin, title_y, width - 2 * margin, title_h)
        title_lbl.text = spec.title
        title_lbl.text_size = title_size
        title_lbl.text_color = (0.95, 0.95, 0.95, 1.0)
        self.title_lbl = title_lbl

        # Body
        body_y = title_y + title_h + int(8 * ui_scale)
        self.body_lbls = []
        for i, line in enumerate(spec.lines):
            lbl = BL_UI_Label(margin, body_y + i * line_h, width - 2 * margin, line_h)
            lbl.text = line
            lbl.text_size = text_size
            lbl.text_color = (0.92, 0.92, 0.92, 1.0)
            self.body_lbls.append(lbl)

        # Buttons - laid out from right to left in spec order so the first
        # spec button (typically the primary action) ends up on the right.
        self.buttons = []
        btn_y = height - margin - button_h
        cursor_x = width - margin
        for btn_spec, bw in zip(spec.buttons, button_widths):
            cursor_x -= bw
            button = BL_UI_Button(cursor_x, btn_y, bw, button_h)
            button.text = btn_spec.label
            button.text_size = text_size
            style = _BUTTON_STYLES.get(btn_spec.style, _BUTTON_STYLES[BUTTON_DEFAULT])
            button.bg_color = style["bg"]
            button.hover_bg_color = style["hover"]
            button.text_color = style["fg"]
            button.set_mouse_down(self._make_button_handler(btn_spec))
            self.buttons.append(button)
            cursor_x -= button_gap

    # -- operator hooks ------------------------------------------------------

    def on_invoke(self, context, event):
        spec = get_warning(self.kind)
        if spec is None:
            bk_logger.warning(
                "Warning dialog invoked with unknown kind '%s'", self.kind
            )
            return False
        if context.area is None or context.area.type != "VIEW_3D":
            bk_logger.warning("Warning dialog invoked without a VIEW_3D area; aborting")
            return False
        self._spec = spec
        self.context = context
        self.instances.append(self)

        self._build_widgets(context)

        widgets_panel = [
            self.logo,
            self.brand_lbl,
            self.title_lbl,
            *self.body_lbls,
            *self.buttons,
        ]
        widgets = [self.panel] + widgets_panel
        self.init_widgets(context, widgets)
        self.panel.add_widgets(widgets_panel)
        return True

    def invoke(self, context, event):
        # Mirror BL_UI_OT_draw_operator.invoke but honor on_invoke's return
        # value - returning False from on_invoke must cancel cleanly rather
        # than registering a dangling draw handler.
        result = self.on_invoke(context, event)
        if not result:
            return {"CANCELLED"}
        if not context.window or not context.area or not context.region:
            return {"CANCELLED"}

        from .bl_ui_widgets.bl_ui_widget import region_redraw

        context.window_manager.modal_handler_add(self)
        self.active_window_pointer = context.window.as_pointer()
        self.active_area_pointer = context.area.as_pointer()
        self.active_region_pointer = context.region.as_pointer()

        args = (self, context)
        self.register_handlers(args, context, timer_interval=self._timer_interval)

        region_redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}

        if not context.area:
            self.finish()
            return {"FINISHED"}

        # Recenter the panel when the area is resized (window resize, region
        # toggling, area splits). The widget panel keeps a fixed width/height,
        # so we just move it; child widgets follow via Drag_Panel layout.
        last = getattr(self, "_last_area_size", None)
        cur = (context.area.width, context.area.height)
        if last is not None and last != cur and self.panel is not None:
            pw, ph = self._panel_size
            new_x = max(0, (cur[0] - pw) // 2)
            new_y = max(0, (cur[1] - ph) // 2)
            self.panel.set_location(new_x, new_y)
            self._last_area_size = cur

        if self.handle_widget_events(event):
            return {"RUNNING_MODAL"}

        # Block clicks that fall on top of the panel so the user does not
        # accidentally interact with what is drawn underneath.
        if (
            event.type in {"LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"}
            and event.value == "PRESS"
            and self.panel is not None
            and self.panel.is_in_rect(event.mouse_region_x, event.mouse_region_y)
        ):
            return {"RUNNING_MODAL"}

        if event.type == "ESC" and event.value == "PRESS":
            self.finish()
            spec = self._spec
            if spec is not None and spec.on_dismiss is not None:
                try:
                    spec.on_dismiss()
                except Exception:
                    bk_logger.exception("warning '%s' on_dismiss failed", spec.kind)
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    @classmethod
    def unregister(cls):
        # Mirror the cleanup pattern used by disclaimer_op so leftover modal
        # instances are torn down on addon disable / Blender quit.
        instances_copy = cls.instances.copy()
        for instance in instances_copy:
            try:
                instance.unregister_handlers(instance.context)
            except Exception:
                pass
            try:
                instance.on_finish(instance.context)
            except Exception:
                pass
            if bpy.context.region is not None:
                bpy.context.region.tag_redraw()
            cls.instances.remove(instance)


def show_warning_dialog(kind: str) -> None:
    """Invoke the warning dialog operator for ``kind``.

    The warning must be registered via :func:`register_warning` first. Uses
    a fake context so it can be triggered from any context (timer, panel,
    other operators, ...).
    """
    from . import utils

    fake_context = utils.get_fake_context(bpy.context)
    try:
        if bpy.app.version < (4, 0, 0):
            bpy.ops.view3d.blenderkit_warning_dialog(  # type: ignore[attr-defined]
                fake_context, "INVOKE_DEFAULT", kind=kind
            )
        else:
            with bpy.context.temp_override(**fake_context):  # type: ignore[attr-defined]
                bpy.ops.view3d.blenderkit_warning_dialog(  # type: ignore[attr-defined]
                    "INVOKE_DEFAULT", kind=kind
                )
    except Exception:
        bk_logger.exception("Could not invoke warning dialog for kind '%s'", kind)


# ---------------------------------------------------------------------------
# Microsoft Store warning gating
# ---------------------------------------------------------------------------

MS_STORE_WARNING_KIND = "ms_store_blender"
BLENDER_DOWNLOAD_URL = "https://www.blender.org/download/"

# Guard so we do not stack multiple warning popups when the asset bar is
# repeatedly retriggered (search results, area changes, ...).
_ms_store_warning_pending = False


def _get_prefs():
    addon = bpy.context.preferences.addons.get(_ADDON_PACKAGE)
    if addon is None:
        return None
    return addon.preferences


def ms_store_warning_accepted() -> bool:
    """True if the user has already acknowledged the Microsoft Store warning."""
    prefs = _get_prefs()
    if prefs is None:
        return False
    return bool(getattr(prefs, "accepted_ms_store_warning", False))


def should_block_for_ms_store() -> bool:
    """True when we must show the warning instead of starting the asset bar."""
    if not is_microsoft_store_blender():
        return False
    return not ms_store_warning_accepted()


def _accept_ms_store_warning():
    global _ms_store_warning_pending
    _ms_store_warning_pending = False
    prefs = _get_prefs()
    if prefs is not None:
        prefs.accepted_ms_store_warning = True
    bk_logger.info(
        "User chose 'Proceed anyway' on Microsoft Store warning - re-enabling asset bar."
    )
    # Now that the user agreed, actually launch the asset bar.
    try:
        bpy.ops.view3d.run_assetbar_fix_context(  # type: ignore[attr-defined]
            keep_running=True, do_search=True
        )
    except Exception:
        bk_logger.exception(
            "Could not start asset bar after accepting Microsoft Store warning"
        )


def _open_blender_download():
    bk_logger.info("Opening blender.org download page from MS Store warning.")
    try:
        bpy.ops.wm.url_open(url=BLENDER_DOWNLOAD_URL)
    except Exception:
        bk_logger.exception("Could not open Blender download URL")


def _cancel_ms_store_warning():
    global _ms_store_warning_pending
    _ms_store_warning_pending = False
    bk_logger.info("User dismissed Microsoft Store warning - asset bar not started.")


def show_ms_store_warning() -> None:
    """Show the Microsoft Store warning, registering the spec on first use."""
    global _ms_store_warning_pending
    if _ms_store_warning_pending:
        return
    register_warning(
        WarningSpec(
            kind=MS_STORE_WARNING_KIND,
            title="Microsoft Store Blender detected",
            lines=[
                "You are running Blender installed from the Microsoft Store.",
                "This sandboxed install can break several BlenderKit features:",
                "  - launching the BlenderKit-Client binary",
                "  - background Blender processes (thumbnails, unpacking)",
                "  - writing into the user blenderkit_data folder",
                "",
                "If everything works for you, you can keep using BlenderKit.",
                "Otherwise we recommend installing Blender from blender.org.",
            ],
            buttons=[
                # Right-most button is listed first - this is the primary action.
                WarningButton(
                    "Proceed anyway",
                    _accept_ms_store_warning,
                    style=BUTTON_PRIMARY,
                ),
                WarningButton(
                    "Get Blender from blender.org",
                    _open_blender_download,
                    style=BUTTON_LINK,
                    close=False,
                ),
                WarningButton(
                    "Cancel",
                    _cancel_ms_store_warning,
                    style=BUTTON_DEFAULT,
                ),
            ],
            on_dismiss=_cancel_ms_store_warning,
            width=820,
        )
    )
    _ms_store_warning_pending = True
    show_warning_dialog(MS_STORE_WARNING_KIND)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (BlenderKitWarningDialogOperator,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
