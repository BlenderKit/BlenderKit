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
import math
import os
import re
import time
from functools import partial
from collections import Counter
from types import SimpleNamespace
from typing import Any, Dict, Optional, Union

import bpy
from bpy.props import BoolProperty, StringProperty

from . import (
    colors,
    comments_utils,
    global_vars,
    paths,
    ratings_utils,
    search,
    ui,
    ui_bgl,
    ui_panels,
    utils,
    viewport_utils,
)
from .bl_ui_widgets.bl_ui_button import BL_UI_Button
from .bl_ui_widgets.bl_ui_drag_panel import BL_UI_Drag_Panel
from .bl_ui_widgets.bl_ui_draw_op import BL_UI_OT_draw_operator
from .bl_ui_widgets.bl_ui_image import BL_UI_Image
from .bl_ui_widgets.bl_ui_label import BL_UI_Label, BL_UI_DuoLabel
from .bl_ui_widgets.bl_ui_widget import BL_UI_Widget


bk_logger = logging.getLogger(__name__)

# Maximum label length for manufacturer chips (e.g. "Ford motor company")
MAX_MANUFACTURER_LABEL_LEN = 17
# Maximum label length for generic active filter chips (term + value)
MAX_FILTER_LABEL_LEN = 24

THUMBNAIL_TYPES = [
    "THUMBNAIL",
    "PHOTO",
    "WIREFRAME",
]

active_area_pointer = 0

ROUNDING_RADIUS = 20

TOOLTIP_SIZE_PX = 512


def get_area_height(self):
    ctx = getattr(self, "context", None)

    if isinstance(ctx, dict):
        ctx_dict = ctx
    elif isinstance(ctx, SimpleNamespace):
        ctx_dict = {
            "window": getattr(ctx, "window", None),
            "area": getattr(ctx, "area", None),
            "region": getattr(ctx, "region", None),
        }
    else:
        if ctx is None:
            ctx = bpy.context
        ctx_dict = {
            "window": getattr(ctx, "window", None),
            "area": getattr(ctx, "area", None),
            "region": getattr(ctx, "region", None),
        }

    self.context = ctx_dict

    region = ctx_dict.get("region")
    if region is not None:
        return region.height

    area = ctx_dict.get("area")
    if area is not None:
        return area.height

    return 100


BL_UI_Widget.get_area_height = get_area_height  # type: ignore[method-assign]


def modal_inside(self, context, event):
    ui_props = bpy.context.window_manager.blenderkitUI

    # Initialize mouse coordinates early so shortcut handling in the first modal
    # events does not fail on fresh operators (Blender 3.0 lacks these attrs).
    if not hasattr(self, "mouse_x") or not hasattr(self, "mouse_y"):
        self.mouse_x, self.mouse_y = self._event_coords_in_active_region(event)

    if ui_props.turn_off:
        ui_props.turn_off = False
        self.finish()

    if self._finished:
        return {"FINISHED"}

    user_preferences = bpy.context.preferences.addons[__package__].preferences
    if self.context:
        context = self.context

    # HANDLE PHOTO THUMBNAIL SWITCH
    if hasattr(self, "needs_tooltip_update") and self.needs_tooltip_update:
        self.needs_tooltip_update = False
        sr = search.get_search_results()
        if sr and self.active_index < len(sr):
            asset_data = sr[self.active_index]
            if asset_data["assetType"].lower() in {"printable", "model", "scene"}:
                if self.show_thumbnail_variant == "PHOTO":
                    photo_img = ui.get_full_photo_thumbnail(asset_data)
                    if photo_img:
                        self.tooltip_image.set_image(photo_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                elif self.show_thumbnail_variant == "THUMBNAIL":
                    wire_img = ui.get_full_wire_thumbnail(asset_data)
                    if wire_img:
                        self.tooltip_image.set_image(wire_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                else:
                    set_thumb_check(
                        self.tooltip_image, asset_data, thumb_type="thumbnail"
                    )

    if not context.area:
        self.finish()
        w, a, r = utils.get_largest_area(area_type="VIEW_3D")
        if a is not None:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
        return {"FINISHED"}

    is_quad_view = self._is_quad_view(context)
    if getattr(self, "_quad_view_state", None) != is_quad_view:
        self._quad_view_state = is_quad_view
        self.active_area_pointer = None  # force refresh of area/region pointers
        self.active_region_pointer = None
        self.finish()
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
        return {"FINISHED"}

    # Update active viewport based on cursor location so the asset bar follows the
    # region the user is interacting with.
    self.update_active_view_from_cursor(context, event)

    sr = search.get_search_results()
    if sr is not None:
        # this check runs more search, useful especially for first search. Could be moved to a better place where the check
        # doesn't run that often.
        # Calculate current max rows based on expanded state
        if user_preferences.assetbar_expanded:
            current_max_rows = user_preferences.maximized_assetbar_rows
        else:
            current_max_rows = 1

        if len(sr) - ui_props.scroll_offset < (ui_props.wcount * current_max_rows) + 15:
            self.search_more()

    time_diff = time.time() - self.update_timer_start
    if time_diff > self.update_timer_limit:
        self.update_timer_start = time.time()
        self.update_buttons()

        # progress bar
        # change - let's try to optimize and redraw only when needed
        change = False
        for asset_button in self.asset_buttons:
            if not asset_button.visible:
                continue
            if sr is not None and len(sr) > asset_button.asset_index:
                asset_data = sr[asset_button.asset_index]
                self.update_progress_bar(asset_button, asset_data)
        if change:
            context.region.tag_redraw()

    # Check for tab shortcut keys directly in the modal function
    if (
        event.ctrl
        and event.value == "PRESS"
        and self.panel.is_in_rect(self.mouse_x, self.mouse_y)
    ):
        if event.type == "T" and not event.shift:
            bk_logger.info("Ctrl+T pressed - add new tab")
            if hasattr(self, "new_tab_button"):  # Only if we can add more tabs
                self.add_new_tab(None)
            return {"RUNNING_MODAL"}
        elif event.type == "W" and not event.shift:
            bk_logger.info("Ctrl+W pressed - close tab")
            if len(global_vars.TABS["tabs"]) > 1:  # Don't close last tab
                self.remove_tab(self.close_tab_buttons[global_vars.TABS["active_tab"]])
            return {"RUNNING_MODAL"}
        elif event.type == "TAB":
            bk_logger.info("Ctrl+Tab pressed - switch tab")
            tabs = global_vars.TABS["tabs"]
            current = global_vars.TABS["active_tab"]
            if event.shift:
                # Go to previous tab
                new_index = (current - 1) % len(tabs)
            else:
                # Go to next tab
                new_index = (current + 1) % len(tabs)
            self.switch_to_history_step(new_index, tabs[new_index]["history_index"])
            return {"RUNNING_MODAL"}
        elif event.type in {
            "ONE",
            "TWO",
            "THREE",
            "FOUR",
            "FIVE",
            "SIX",
            "SEVEN",
            "EIGHT",
            "NINE",
        }:
            # Convert numkey to index (0-based)
            tab_idx = {
                "ONE": 0,
                "TWO": 1,
                "THREE": 2,
                "FOUR": 3,
                "FIVE": 4,
                "SIX": 5,
                "SEVEN": 6,
                "EIGHT": 7,
                "NINE": 8,
            }[event.type]

            if tab_idx < len(global_vars.TABS["tabs"]):
                bk_logger.info(
                    "Ctrl+%d pressed - go to tab %d", tab_idx + 1, tab_idx + 1
                )
                self.switch_to_history_step(
                    tab_idx, global_vars.TABS["tabs"][tab_idx]["history_index"]
                )
            return {"RUNNING_MODAL"}

    # Handle Alt+Left/Right for history navigation
    elif (
        event.alt
        and event.value == "PRESS"
        and self.panel.is_in_rect(self.mouse_x, self.mouse_y)
    ):
        if event.type == "LEFT_ARROW":
            bk_logger.info("Alt+Left pressed - history back")
            active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
            if active_tab["history_index"] > 0:
                self.history_back(None)  # None instead of widget
            return {"RUNNING_MODAL"}
        elif event.type == "RIGHT_ARROW":
            bk_logger.info("Alt+Right pressed - history forward")
            active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
            if active_tab["history_index"] < len(active_tab["history"]) - 1:
                self.history_forward(None)  # None instead of widget
            return {"RUNNING_MODAL"}

    # ANY EVENT ACTIVATED = DON'T LET EVENTS THROUGH
    if self.handle_widget_events(event):
        return {"RUNNING_MODAL"}

    if event.type in {"ESC"} and event.value == "PRESS":
        # just escape dragging when dragging, not appending.
        if not ui_props.dragging:
            self.finish()

            # return {"FINISHED"} # we can jump out immediately

    self.mouse_x, self.mouse_y = self._event_coords_in_active_region(event)

    # TRACKPAD SCROLL
    if event.type == "TRACKPADPAN" and self.panel.is_in_rect(
        self.mouse_x, self.mouse_y
    ):
        # accumulate trackpad inputs
        self.trackpad_x_accum -= event.mouse_x - event.mouse_prev_x
        self.trackpad_y_accum += event.mouse_y - event.mouse_prev_y

        step = 0
        multiplier = 30
        if abs(self.trackpad_x_accum) > abs(self.trackpad_y_accum) or self.hcount < 2:
            step = math.floor(self.trackpad_x_accum / multiplier)
            self.trackpad_x_accum -= step * multiplier
            # reset the other axis not to accidentally scroll it
            if step != 0:
                self.trackpad_y_accum = 0
        if abs(self.trackpad_y_accum) > 0 and self.hcount > 1:
            step = self.wcount * math.floor(self.trackpad_x_accum / multiplier)
            self.trackpad_y_accum -= step * multiplier
            # reset the other axis not to accidentally scroll it
            if step != 0:
                self.trackpad_x_accum = 0
        if step != 0:
            self.scroll_offset += step
            self.scroll_update()
        return {"RUNNING_MODAL"}

    # MOUSEWHEEL SCROLL
    if event.type == "WHEELUPMOUSE" and self.panel.is_in_rect(
        self.mouse_x, self.mouse_y
    ):
        if self.hcount > 1:
            self.scroll_offset -= self.wcount
        else:
            self.scroll_offset -= 2
        self.scroll_update()
        return {"RUNNING_MODAL"}

    elif event.type == "WHEELDOWNMOUSE" and self.panel.is_in_rect(
        self.mouse_x, self.mouse_y
    ):
        if self.hcount > 1:
            self.scroll_offset += self.wcount
        else:
            self.scroll_offset += 2

        self.scroll_update()
        return {"RUNNING_MODAL"}

    if self.check_ui_resized(context):
        # Force a clean rebuild when the viewport size changes.
        if not getattr(self, "_restart_pending", False):
            self._restart_pending = True
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.assetbar_on = False
            ui_props.turn_off = True
            self.restart_asset_bar()
        return {"FINISHED"}

    if self.check_new_search_results(context) or self.check_region_changed(context):
        self._refresh_layout(context)
        # also update tooltip visibility
        # if there's less results and active button is not visible, hide tooltip
        # happened only when e.g. running new search from web browser (copying assetbaseid to clipboard)
        # fixes issue #1766
        if self.active_index >= len(search.get_search_results()):
            self.hide_tooltip()
        self.scroll_update(
            always=True
        )  # one extra update for scroll for correct redraw, updates all buttons

    # this was here to check if sculpt stroke is running, but obviously that didn't help,
    #  since the RELEASE event is caught by operator and thus there is no way to detect a stroke has ended...
    if bpy.context.mode in ("SCULPT", "PAINT_TEXTURE"):
        if (
            event.type == "MOUSEMOVE"
        ):  # ASSUME THAT SCULPT OPERATOR ACTUALLY STEALS THESE EVENTS,
            # SO WHEN THERE ARE SOME WE CAN APPEND BRUSH...
            bpy.context.window_manager["appendable"] = True
        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                bpy.context.window_manager["appendable"] = False
    return {"PASS_THROUGH"}


def asset_bar_modal(self, context, event):
    return modal_inside(self, context, event)


def asset_bar_invoke(self, context, event):
    # sprinkling of black magic
    result = self.on_invoke(context, event)
    if not result:
        return {"CANCELLED"}
    if not context.window:
        return {"CANCELLED"}
    if not context.area:
        return {"CANCELLED"}

    args = (self, context)

    self.register_handlers(args, context)

    self.update_timer_limit = 0.5
    self.update_timer_start = time.time()
    self._timer = context.window_manager.event_timer_add(0.5, window=context.window)

    context.window_manager.modal_handler_add(self)
    global active_area_pointer
    self.active_window_pointer = context.window.as_pointer()
    self.active_area_pointer = context.area.as_pointer()
    active_area_pointer = self.active_area_pointer
    self.active_region_pointer = context.region.as_pointer()
    self.operator_area_pointer = self.active_area_pointer
    self.operator_region_pointer = self.active_region_pointer
    self._active_area_ref = context.area
    self._active_region_ref = context.region

    return {"RUNNING_MODAL"}


asset_bar_operator = None


def get_tooltip_data(asset_data):
    tooltip_data = asset_data.get("tooltip_data")
    if tooltip_data is not None:
        return

    author_text = ""
    if global_vars.BKIT_AUTHORS:
        author_id = int(asset_data["author"]["id"])
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author:
            if len(author.firstName) > 0 or len(author.lastName) > 0:
                author_text = f"by {author.firstName} {author.lastName}"
        else:
            bk_logger.warning("get_tooltip_data() AUTHOR NOT FOUND: %s", author_id)

    aname = asset_data["displayName"]
    if len(aname) == 0:
        # this shouldn't happen, but obviously did on server in addons section.
        aname = ""
    else:
        aname = aname[0].upper() + aname[1:]
    if len(aname) > 36:
        aname = f"{aname[:33]}..."

    rc = asset_data.get("ratingsCount")
    show_rating_threshold = 0
    rcount = 0
    quality = "-"
    if rc:
        rcount = min(rc.get("quality", 0), rc.get("workingHours", 0))
    if rcount > show_rating_threshold:
        quality = str(round(asset_data["ratingsAverage"].get("quality")))

    # Add pricing information
    base_price_text = ""
    user_price_text = ""

    user_price_color = colors.WHITE
    base_price_color = colors.WHITE

    user_price_bg_color = colors.GRAY
    base_price_bg_color = colors.GRAY

    # Check if asset is free or paid (works for all asset types)
    is_free = asset_data.get("isFree", True)
    can_download = asset_data.get("canDownload", True)

    if asset_data.get("assetType") == "addon":
        # Get pricing info from extensions cache.
        # Pricing info is shown only for add-ons.
        base_price_text = asset_data.get("basePrice")
        user_price_text = asset_data.get("userPrice")
        is_for_sale = asset_data.get("isForSale")

        # for debug show both prices always
        if utils.profile_is_validator():
            if user_price_text:
                user_price_text = f" ${user_price_text} "
            else:
                user_price_text = ""
            user_price_color = colors.WHITE
            user_price_bg_color = colors.GREEN_PRICE

            if base_price_text:
                base_price_text = f" ${base_price_text} "
            else:
                base_price_text = ""
            base_price_color = colors.TEXT_DIM
            base_price_bg_color = colors.PURPLE_PRICE
        else:
            if is_for_sale and not can_download and user_price_text and base_price_text:
                user_price_text = f" ${user_price_text} "
                user_price_bg_color = colors.GREEN_PRICE
                user_price_color = colors.WHITE

                base_price_text = f" (${base_price_text}) "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.TEXT_DIM

            elif is_for_sale and not can_download and base_price_text:
                base_price_text = f" ${base_price_text} "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.WHITE

                user_price_text = ""

            elif not is_free and not is_for_sale:
                base_price_text = " Full Plan "
                base_price_bg_color = colors.ORANGE_FULL
                base_price_color = colors.WHITE

                user_price_text = ""

            elif is_for_sale and can_download:
                # purchased, so we dont show price anymore
                base_price_text = f" Purchased "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.WHITE

                user_price_text = ""

    tooltip_data = {
        "aname": aname,
        "author_text": author_text,
        "quality": quality,
        # --- colors for price texts and backgrounds
        "user_price_text": user_price_text,
        "base_price_text": base_price_text,
        "user_price_color": user_price_color,
        "base_price_color": base_price_color,
        "user_price_bg_color": user_price_bg_color,
        "base_price_bg_color": base_price_bg_color,
    }
    asset_data["tooltip_data"] = tooltip_data


def set_thumb_check(
    element: Union[BL_UI_Button, BL_UI_Image],
    asset: Dict[str, Any],
    thumb_type: str = "thumbnail_small",
) -> None:
    """Set image in case it is loaded in search results. Checks global_vars.DATA["images available"].
    - if image download failed, it will be set to 'thumbnail_not_available.jpg'
    - if image doesn't exist, it will be set to 'thumbnail_notready.jpg'
    """
    directory = paths.get_temp_dir("%s_search" % asset["assetType"])
    tpath = os.path.join(directory, asset[thumb_type])

    if element.get_image_path() == tpath:
        return  # no need to update

    image_ready = global_vars.DATA["images available"].get(tpath)
    if image_ready is None:
        tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
    if image_ready is False or asset[thumb_type] == "":
        tpath = paths.get_addon_thumbnail_path("thumbnail_not_available.jpg")

    if element.get_image_path() == tpath:
        return
    element.set_image(tpath)
    element.set_image_colorspace("")


class BlenderKitAssetBarOperator(BL_UI_OT_draw_operator):
    """BlenderKit Asset Bar Operator."""

    bl_idname = "view3d.blenderkit_asset_bar_widget"
    bl_label = "BlenderKit asset bar refresh"
    bl_description = "BlenderKit asset bar refresh"
    bl_options = {"REGISTER"}
    instances = []

    do_search: BoolProperty(  # type: ignore[valid-type]
        name="Run Search", description="", default=True, options={"SKIP_SAVE"}
    )
    keep_running: BoolProperty(  # type: ignore[valid-type]
        name="Keep Running", description="", default=True, options={"SKIP_SAVE"}
    )

    category: StringProperty(  # type: ignore[valid-type]
        name="Category",
        description="search only subtree of this category",
        default="",
        options={"SKIP_SAVE"},
    )

    tooltip: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    show_thumbnail_variant: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Show Thumbnail Variant",
        description="Toggle between normal, photo and wireframe thumbnail - use [ or ] to cycle through thumbnails. Currently used only for printables, models, and scenes.",
        default="THUMBNAIL",
        items=[
            ("THUMBNAIL", "Thumbnail", "Normal thumbnail"),
            ("PHOTO", "Photo", "Photo thumbnail"),
            ("WIREFRAME", "Wireframe", "Wireframe thumbnail"),
        ],
        options={"SKIP_SAVE"},
    )

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _resolve_window(self, context):
        return getattr(context, "window", None) or bpy.context.window

    def _validated_area(self, area):
        if area is None:
            return None
        try:
            area.as_pointer()
        except ReferenceError:
            return None
        return area

    def _validated_region(self, region):
        if region is None:
            return None
        try:
            region.as_pointer()
        except ReferenceError:
            return None
        return region

    def _safe_space_data(self, area):
        if area is None:
            return None
        try:
            return area.spaces.active
        except ReferenceError:
            return None

    def _build_context_snapshot(self, context, area=None, region=None):
        area = self._validated_area(area) or self._validated_area(
            getattr(context, "area", None)
        )
        region = self._validated_region(region) or self._validated_region(
            getattr(context, "region", None)
        )
        return SimpleNamespace(
            window=self._resolve_window(context),
            area=area,
            region=region,
            space_data=self._safe_space_data(area),
        )

    def _unwrap_area_region(self, ctx):
        if isinstance(ctx, dict):
            return ctx.get("area"), ctx.get("region")
        return getattr(ctx, "area", None), getattr(ctx, "region", None)

    def _current_area_region(self):
        """Return the currently active area and region with sensible fallbacks."""
        area = self._validated_area(getattr(self, "_active_area_ref", None))
        region = self._validated_region(getattr(self, "_active_region_ref", None))

        ctx_area, ctx_region = self._unwrap_area_region(getattr(self, "context", None))
        if area is None:
            area = self._validated_area(ctx_area)
        if region is None:
            region = self._validated_region(ctx_region)

        if area is None:
            area = self._validated_area(getattr(bpy.context, "area", None))
        if region is None:
            region = self._validated_region(getattr(bpy.context, "region", None))

        return area, region

    def _event_window_coords(self, event):
        if not hasattr(event, "mouse_x") or not hasattr(event, "mouse_y"):
            return None, None
        return getattr(event, "mouse_x", None), getattr(event, "mouse_y", None)

    def _apply_widget_context(self, override_ctx):
        """Apply the given override context to all widgets in the asset bar.

        All widgets get the new context,
        except for the main panel and tooltip panel (and their children).
        """
        self._override_context = override_ctx
        if not hasattr(self, "widgets"):
            return
        panel = getattr(self, "panel", None)
        panel_children = (
            set(panel.widgets) if isinstance(panel, BL_UI_Drag_Panel) else set()
        )
        tooltip_panel = getattr(self, "tooltip_panel", None)
        tooltip_children = (
            set(self.tooltip_widgets) if hasattr(self, "tooltip_widgets") else set()
        )

        for widget in self.widgets:
            widget.context = override_ctx
            if (
                widget is panel
                or widget in panel_children
                or widget is tooltip_panel
                or widget in tooltip_children
            ):
                continue
            widget.update(widget.x, widget.y)

        if isinstance(panel, BL_UI_Drag_Panel):
            panel.update(panel.x, panel.y)
            panel.layout_widgets()

        if isinstance(tooltip_panel, BL_UI_Drag_Panel):
            tooltip_panel.update(tooltip_panel.x, tooltip_panel.y)
            tooltip_panel.layout_widgets()

    def _find_area_region_from_event(self, context, event):
        x, y = self._event_window_coords(event)
        if x is None or y is None:
            return None, None

        screen = getattr(self._resolve_window(context), "screen", None)
        if screen is None:
            return None, None

        for area in screen.areas:
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            if not (
                area.x <= x < area.x + area.width and area.y <= y < area.y + area.height
            ):
                continue

            target_region = None
            fallback_region = None
            for region in viewport_utils.iter_view3d_window_regions(area):
                if fallback_region is None:
                    fallback_region = region
                if (
                    region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height
                ):
                    target_region = region
                    break

            return area, target_region or fallback_region

        return None, None

    def _cursor_inside_active_area(self, event):
        # return False
        area = self._validated_area(getattr(self, "_active_area_ref", None))
        if area is None:
            return False

        x, y = self._event_window_coords(event)
        if x is None or y is None:
            return False

        if not (
            area.x <= x < area.x + area.width and area.y <= y < area.y + area.height
        ):
            return False

        region = self._validated_region(getattr(self, "_active_region_ref", None))
        if region is None:
            return True

        return (
            region.x <= x < region.x + region.width
            and region.y <= y < region.y + region.height
        )

    def _view_changed(
        self,
        area_pointer,
        region_pointer,
        previous_area_pointer,
        previous_region_pointer,
    ):
        return (
            previous_area_pointer != area_pointer
            or previous_region_pointer != region_pointer
        )

    def _store_active_view(self, context, area, region, area_pointer, region_pointer):
        self.active_area_pointer = area_pointer
        self.active_region_pointer = region_pointer
        global active_area_pointer
        active_area_pointer = area_pointer
        self._active_area_ref = area
        self._active_region_ref = region
        self.context = context

    def _refresh_layout(self, override_ctx):
        self.update_assetbar_sizes(override_ctx)
        self.update_tooltip_size(override_ctx)
        try:
            self.update_assetbar_layout(override_ctx)
            self.update_tooltip_layout(override_ctx)
            if hasattr(self, "tooltip_panel"):
                self.tooltip_panel.layout_widgets()
        except Exception as e:
            bk_logger.log(
                1, "Error updating asset bar layout, some objects may be missing. %s", e
            )

    def _safe_tag_redraw(self, region):
        if region is None:
            return
        try:
            region.tag_redraw()
        except ReferenceError:
            pass

    def _tag_regions_for_redraw(self, current_region, previous_region_ref):
        self._safe_tag_redraw(current_region)
        if previous_region_ref and previous_region_ref is not current_region:
            self._safe_tag_redraw(previous_region_ref)

    def _switch_active_view(self, context, area, region, *, force=True):
        """Switch the active area/region the asset bar is attached to.

        If `force` is True, the switch is applied even if the area/region
        pointers match the previously stored ones.
        """
        area = self._validated_area(area)
        region = self._validated_region(region)
        if area is None or region is None:
            return

        self.area = area
        self.region = region

        area_pointer = area.as_pointer()
        region_pointer = region.as_pointer()
        previous_area_pointer = getattr(self, "active_area_pointer", None)
        previous_region_pointer = getattr(self, "active_region_pointer", None)
        previous_region_ref = getattr(self, "_active_region_ref", None)

        self._store_active_view(context, area, region, area_pointer, region_pointer)

        override_ctx = self._build_context_snapshot(context, area, region)
        self._apply_widget_context(override_ctx)

        if force or self._view_changed(
            area_pointer,
            region_pointer,
            previous_area_pointer,
            previous_region_pointer,
        ):
            # Rebuild sizes/layout whenever we truly jump to a different area (or
            # the caller explicitly requests it) so the bar respects the new
            # region dimensions/UI scale. Plain cursor moves within the same view
            # keep the old layout for performance.
            self._refresh_layout(override_ctx)

        # Explicitly request redraws so the handler updates in the new region and
        # the previous one releases its stale widgets.
        self._tag_regions_for_redraw(region, previous_region_ref)

    def _redraw_tracked_regions(self):
        """Request redraw on any region the operator stored explicitly."""
        _, stored_region = self._unwrap_area_region(getattr(self, "context", None))
        regions = {
            self._validated_region(getattr(self, "_active_region_ref", None)),
            self._validated_region(
                getattr(getattr(self, "_override_context", None), "region", None)
            ),
            self._validated_region(stored_region),
        }

        for region in regions:
            self._safe_tag_redraw(region)

    def update_active_view_from_cursor(self, context, event):
        """Update the active area/region based on the current cursor location.

        This makes the asset bar follow the user's cursor as they move between
        different 3D viewports.
        """
        if event.type not in {"TIMER", "MOUSEMOVE"}:
            return

        user_prefs = bpy.context.preferences.addons[__package__].preferences
        follow_cursor = getattr(user_prefs, "assetbar_follows_cursor", True)

        if not follow_cursor and not self._is_quad_view(context):
            return

        area, region = self._find_area_region_from_event(context, event)
        if area is None or region is None:
            return

        # In quad view, only the perspective pane should host the asset bar. Keep the
        # legacy "follow any quad" behavior here for potential reuse:
        # if self._is_quad_view(context) and self._cursor_inside_active_area(event):
        #     return
        if self._is_quad_view(context) and not self._is_perspective_region(region):
            return

        # When follow is disabled, allow switching only within the same area; in quad
        # view this lets the bar appear in the hovered quad without jumping across
        # different 3D view areas.
        if not follow_cursor:
            active_area = self._validated_area(getattr(self, "_active_area_ref", None))
            if (
                active_area is not None
                and area.as_pointer() != active_area.as_pointer()
            ):
                return

        if self._cursor_inside_active_area(event):
            return

        self._switch_active_view(context, area, region)

    def _event_coords_in_active_region(self, event):
        region = self._validated_region(getattr(self, "_active_region_ref", None))
        if region is not None:
            x, y = self._event_window_coords(event)
            if x is not None and y is not None:
                return x - region.x, y - region.y

        return getattr(event, "mouse_region_x", 0), getattr(event, "mouse_region_y", 0)

    @classmethod
    def description(cls, context, properties):
        """Get the description for the asset bar operator."""
        return properties.tooltip

    def new_text(self, text, x, y, width=100, height=15, text_size=None, halign="LEFT"):
        """Create a new text label widget."""
        label = BL_UI_Label(x, y, width, height)
        label.text = text
        if text_size is None:
            text_size = 14
        label.text_size = text_size
        label.text_color = self.text_color
        label._halign = halign
        return label

    def new_duo_text(
        self,
        text_a,
        x,
        y,
        text_b="",
        width=100,
        height=15,
        text_size=None,
        halign="LEFT",
    ):
        """Create a new text label widget."""
        label = BL_UI_DuoLabel(x, y, width, height)
        label.use_rounded_background = True
        label.background_corner_radius = "50%"
        label.background_padding = (4, 4)
        label.text_a = text_a
        label.text_b = text_b
        if text_size is None:
            text_size = 14
        label.text_size = text_size
        label.text_a_color = self.text_color
        label.text_b_color = self.text_color

        label._halign = halign
        return label

    # region tooltip
    def init_tooltip(self):
        """Initialize the tooltip panel and its widgets."""
        self.tooltip_widgets = []
        self._tooltip_available_height = None
        if not hasattr(self, "tooltip_size"):
            self.tooltip_size = int(self.tooltip_base_size_pixels)
        self.tooltip_scale = getattr(self, "tooltip_scale", 1.0)

        # Fallbacks in case update_tooltip_size was not called yet
        self.tooltip_width = getattr(self, "tooltip_width", self.tooltip_size)
        image_height = getattr(self, "tooltip_image_height", self.tooltip_size)
        info_height = getattr(
            self,
            "tooltip_info_height",
            max(
                int(image_height * self.bottom_panel_fraction),
                self.asset_name_text_size * 3,
            ),
        )
        self.tooltip_image_height = image_height
        self.tooltip_info_height = info_height
        self.tooltip_height = self.tooltip_image_height + self.tooltip_info_height
        self.labels_start = self.tooltip_image_height

        # total_size = tooltip# + 2 * self.margin
        self.tooltip_panel = BL_UI_Drag_Panel(
            0, 0, self.tooltip_width, self.tooltip_height
        )
        self.tooltip_panel.bg_color = (0.0, 0.0, 0.0, 0.5)
        self.tooltip_panel.use_rounded_background = True
        self.tooltip_panel.background_corner_radius = ROUNDING_RADIUS
        self.tooltip_panel.visible = False

        tooltip_image = BL_UI_Image(0, 0, 1, 1)
        img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        tooltip_image.set_image(img_path)
        tooltip_image.set_image_size((self.tooltip_width, self.tooltip_image_height))
        tooltip_image.set_image_position((0, 0))
        tooltip_image.set_image_colorspace("")
        tooltip_image.background = False
        tooltip_image.bg_color = (0.0, 0.0, 0.0, 0.0)
        tooltip_image.use_rounded_background = True
        tooltip_image.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.tooltip_image = tooltip_image
        self.tooltip_widgets.append(tooltip_image)

        tooltip_image_help = self.new_text(
            "Left click to append. Right click for menu.",
            self.tooltip_margin,
            self.tooltip_image_height - self.tooltip_margin - self.author_text_size,
            height=self.author_text_size,
            text_size=self.author_text_size,
        )
        tooltip_image_help.text_color = (1.0, 0.6, 0.6, 0.9)
        tooltip_image_help.visible = False
        self.tooltip_image_help = tooltip_image_help
        self.tooltip_widgets.append(self.tooltip_image_help)

        dark_panel = BL_UI_Widget(
            0,
            self.labels_start,
            self.tooltip_width,
            self.tooltip_info_height,
        )
        dark_panel.bg_color = (0.0, 0.0, 0.0, 0.7)
        dark_panel.use_rounded_background = True
        dark_panel.background_corner_radius = (0, 0, ROUNDING_RADIUS, ROUNDING_RADIUS)
        self.tooltip_dark_panel = dark_panel
        self.tooltip_widgets.append(dark_panel)

        name_label = self.new_text(
            "",
            self.tooltip_margin,
            self.labels_start + self.tooltip_margin,
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        self.asset_name = name_label
        self.tooltip_widgets.append(name_label)

        self.gravatar_size = max(
            int(self.tooltip_info_height - 2 * self.tooltip_margin),
            self.asset_name_text_size,
        )

        authors_name = self.new_text(
            "author",
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.author_text_size - self.tooltip_margin,
            self.labels_start,
            height=self.author_text_size,
            text_size=self.author_text_size,
            halign="RIGHT",
        )
        self.authors_name = authors_name
        self.tooltip_widgets.append(authors_name)

        gravatar_image = BL_UI_Image(
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.gravatar_size - self.tooltip_margin,
            1,
            1,
        )
        img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        gravatar_image.set_image(img_path)
        gravatar_image.set_image_size(
            (
                self.gravatar_size,
                self.gravatar_size,
            )
        )
        gravatar_image.set_image_position((0, 0))
        gravatar_image.set_image_colorspace("")
        gravatar_image.background_corner_radius = (
            0,
            0,
            ROUNDING_RADIUS / 2,
            0,
        )
        self.gravatar_image = gravatar_image
        self.tooltip_widgets.append(gravatar_image)

        quality_star = BL_UI_Image(
            self.tooltip_margin,
            self.tooltip_height - self.tooltip_margin - self.asset_name_text_size,
            1,
            1,
        )
        img_path = paths.get_addon_thumbnail_path("star_grey.png")
        quality_star.set_image(img_path)
        quality_star.set_image_size(
            (self.asset_name_text_size, self.asset_name_text_size)
        )
        quality_star.set_image_position((0, 0))
        self.quality_star = quality_star
        self.tooltip_widgets.append(quality_star)

        quality_label = self.new_text(
            "",
            2 * self.tooltip_margin + self.asset_name_text_size,
            self.tooltip_height - int(self.asset_name_text_size + self.tooltip_margin),
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        self.tooltip_widgets.append(quality_label)
        self.quality_label = quality_label

        # Add user/base price label for addons
        multi_price_label = self.new_duo_text(
            "",
            self.tooltip_margin,
            self.tooltip_height
            - int(self.asset_name_text_size + 2 * self.tooltip_margin),
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        multi_price_label.use_rounded_background = True
        multi_price_label.background_corner_radius = "50%"
        multi_price_label.text_a_color = (
            1.0,
            0.8,
            0.2,
            1.0,
        )  # Golden color for current price
        multi_price_label.text_b_color = (
            0.8,
            0.4,
            0.4,
            1.0,
        )  # Reddish color for base price
        self.multi_price_label = multi_price_label
        self.tooltip_widgets.append(self.multi_price_label)

        user_preferences = bpy.context.preferences.addons[__package__].preferences
        offset = 0
        if (
            user_preferences.asset_popup_counter
            < user_preferences.asset_popup_counter_max
        ) or utils.profile_is_validator():
            # this is shown only to users who don't know yet about the popup card.
            label = self.new_text(
                "Right click for menu.",
                self.tooltip_margin,
                self.tooltip_height + self.tooltip_margin,
                height=self.author_text_size,
                text_size=self.author_text_size,
            )
            self.tooltip_widgets.append(label)
            self.comments = label
            offset += 1
            if utils.profile_is_validator():
                label.multiline = True
                label.text = "No comments yet."
        # version warning
        version_warning = self.new_text(
            "",
            self.tooltip_margin,
            self.tooltip_height
            + self.tooltip_margin
            + int(self.author_text_size * offset),
            height=self.author_text_size,
            text_size=self.author_text_size,
        )
        version_warning.text_color = self.warning_color
        self.tooltip_widgets.append(version_warning)
        self.version_warning = version_warning

    def hide_tooltip(self):
        """Hide the tooltip panel and its widgets."""
        self.tooltip_panel.visible = False
        for w in self.tooltip_widgets:
            w.visible = False
        self._redraw_tracked_regions()

    def show_tooltip(self):
        """Show the tooltip panel and its widgets."""
        self.tooltip_panel.visible = True
        self.tooltip_panel.active = False
        for w in self.tooltip_widgets:
            w.visible = True
        self._redraw_tracked_regions()

    def _reset_tooltip_dimensions(self):
        """Restore tooltip scale and panel size before recomputing layout.

        Prevents a previously downscaled tooltip from keeping a shrunken size
        on subsequent openings (e.g. after tight vertical space).
        """

        ui_scale = ui_bgl.get_ui_scale()
        self.tooltip_scale = ui_scale
        self._tooltip_available_height = None

        base_size = int(self.tooltip_base_size_pixels * ui_scale)
        base_height = int(base_size * (1 + self.bottom_panel_fraction))

        self.tooltip_size = base_size
        self.tooltip_height = base_height

        if hasattr(self, "tooltip_panel"):
            self.tooltip_panel.width = base_size
            self.tooltip_panel.height = base_height

    def update_tooltip_size(self, context):
        """Calculate all important sizes for the tooltip"""
        region = context.region
        ui_props = bpy.context.window_manager.blenderkitUI

        ui_scale = ui_bgl.get_ui_scale()
        desired_size = int(self.tooltip_base_size_pixels * ui_scale)
        desired_full_height = int(desired_size * (1 + self.bottom_panel_fraction))

        available_height = getattr(self, "_tooltip_available_height", None)
        if available_height is None:
            tooltip_panel = getattr(self, "tooltip_panel", None)
            anchor_y = None
            if tooltip_panel is not None:
                anchor_y = getattr(tooltip_panel, "y_screen", None)
            if anchor_y is None:
                anchor_y = self.bar_y + self.bar_height
            anchor_y = max(-region.height, min(region.height, anchor_y))
            if anchor_y < 0:
                available_height = anchor_y + region.height
            else:
                available_height = region.height - anchor_y

        available_height = max(64, int(available_height))
        if desired_full_height > available_height:
            scale_factor = available_height / max(desired_full_height, 1)
        else:
            scale_factor = 1.0

        final_size = max(32, int(desired_size * scale_factor))
        self.tooltip_scale = final_size / self.tooltip_base_size_pixels
        self.tooltip_size = final_size
        self.asset_name_text_size = int(
            0.039 * self.tooltip_base_size_pixels * self.tooltip_scale
        )
        self.author_text_size = int(self.asset_name_text_size * 0.8)
        self.tooltip_margin = int(
            0.017 * self.tooltip_base_size_pixels * self.tooltip_scale
        )

        if ui_props.asset_type == "HDR":
            self.tooltip_width = self.tooltip_size * 2
            self.tooltip_image_height = self.tooltip_size
        else:
            self.tooltip_width = self.tooltip_size
            self.tooltip_image_height = self.tooltip_size

        self.tooltip_info_height = max(
            int(self.tooltip_image_height * self.bottom_panel_fraction),
            self.asset_name_text_size * 3,
        )
        self.labels_start = self.tooltip_image_height
        self.comments_text_size = max(
            15,
            int(0.034 * self.tooltip_base_size_pixels * self.tooltip_scale),
            int(self.author_text_size),
        )

        self.tooltip_height = self.tooltip_image_height + self.tooltip_info_height
        self.gravatar_size = max(
            int(self.tooltip_info_height - 2 * self.tooltip_margin),
            self.asset_name_text_size,
        )

        self._tooltip_available_height = None

    def update_tooltip_layout(self, context):
        """Update the layout of the tooltip"""
        # update Tooltip size /scale for HDR or if area too small

        self.tooltip_panel.width = self.tooltip_width
        self.tooltip_panel.height = self.tooltip_height

        self.tooltip_image_help.set_location(
            self.tooltip_margin,
            self.tooltip_image_height - self.tooltip_margin - self.author_text_size,
        )
        self.tooltip_image_help.text_size = self.author_text_size
        self.tooltip_image.width = self.tooltip_width
        self.tooltip_image.height = self.tooltip_image_height

        self.labels_start = self.tooltip_image_height

        self.tooltip_image.set_image_size(
            (self.tooltip_width, self.tooltip_image_height)
        )
        self.tooltip_image.set_location(0, 0)

        self.gravatar_image.set_location(
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.gravatar_size - self.tooltip_margin,
        )
        self.gravatar_image.set_image_size(
            (
                self.gravatar_size,
                self.gravatar_size,
            )
        )

        self.authors_name.set_location(
            self.tooltip_width - self.gravatar_size - (self.tooltip_margin * 2),
            self.tooltip_height - self.author_text_size - self.tooltip_margin,
        )
        self.authors_name.text_size = self.author_text_size
        self.authors_name.height = self.author_text_size

        self.asset_name.set_location(
            self.tooltip_margin,
            self.labels_start + self.tooltip_margin,
        )
        self.asset_name.text_size = self.asset_name_text_size
        self.asset_name.height = self.asset_name_text_size

        self.tooltip_dark_panel.set_location(
            0,
            self.labels_start,
        )
        self.tooltip_dark_panel.height = self.tooltip_info_height
        self.tooltip_dark_panel.width = self.tooltip_width

        self.quality_label.set_location(
            2 * self.tooltip_margin + self.asset_name_text_size,
            self.tooltip_height - int(self.asset_name_text_size + self.tooltip_margin),
        )
        self.quality_label.text_size = self.asset_name_text_size
        self.quality_label.height = self.asset_name_text_size

        self.quality_star.set_location(
            self.tooltip_margin,
            self.tooltip_height - self.tooltip_margin - self.asset_name_text_size,
        )
        self.quality_star.set_image_size(
            (self.asset_name_text_size, self.asset_name_text_size)
        )

        # right after the asset name
        self.multi_price_label.set_location(
            self.tooltip_margin,
            self.labels_start + (self.tooltip_margin * 3) + self.asset_name.height,
        )
        self.multi_price_label.width = self.tooltip_width - 2 * self.tooltip_margin
        self.multi_price_label.height = self.asset_name_text_size
        self.multi_price_label.text_size = self.asset_name_text_size

        if hasattr(self, "comments"):
            self.comments.set_location(
                self.tooltip_margin,
                self.tooltip_height + self.tooltip_margin,
            )
            self.comments.text_size = self.comments_text_size

    def update_tooltip_image(self, asset_id):
        """Update tooltip image when it finishes downloading and the downloaded image matches the active one."""
        search_results = search.get_search_results()
        if search_results is None:
            return

        if self.active_index == -1:  # prev search got no results
            return

        if self.active_index >= len(search_results):
            return

        asset_data = search_results[self.active_index]
        if asset_data["assetBaseId"] == asset_id:
            set_thumb_check(self.tooltip_image, asset_data, thumb_type="thumbnail")

    def update_comments_for_validators(self, asset_data):
        """Update the comments section in the tooltip for validator profiles."""
        if not utils.profile_is_validator():
            return

        comments = global_vars.DATA.get("asset comments", {})
        comments = comments.get(asset_data["assetBaseId"], [])
        comment_text = "No comments yet."
        if comments is not None:
            comment_text = ""
            # iterate comments from last to first
            for comment in reversed(comments):
                comment_text += f"{comment['userName']}:\n"
                # strip urls and stuff
                comment_lines = comment["comment"].split("\n")
                for line in comment_lines:
                    urls, text = utils.has_url(line)
                    if urls:
                        comment_text += f"{text}{urls[0][0]}\n"
                    else:
                        comment_text += f"{text}\n"
                comment_text += "\n"

        self.comments.text = comment_text

    # endregion tooltip

    # region panel

    def asset_button_init(self, asset_x, asset_y, button_idx):
        """Initialize an asset button at the given position with the given index."""
        button_bg_color = (0.2, 0.2, 0.2, 0.1)
        button_hover_color = (0.8, 0.8, 0.8, 0.2)
        fully_transparent_color = (0.2, 0.2, 0.2, 0.0)
        new_button = BL_UI_Button(asset_x, asset_y, self.button_size, self.button_size)

        new_button.bg_color = button_bg_color
        new_button.hover_bg_color = button_hover_color
        new_button.text = ""  # asset_data['name']

        new_button.set_image_size((self.thumb_size, self.thumb_size))
        new_button.set_image_position((self.button_margin, self.button_margin))
        new_button.button_index = button_idx
        new_button.search_index = button_idx
        new_button.set_mouse_down(self.drag_drop_asset)
        new_button.set_mouse_down_right(self.asset_menu)
        new_button.set_mouse_enter(self.enter_button)
        new_button.set_mouse_exit(self.exit_button)
        new_button.text_input = self.handle_key_input

        # add validation icon to button
        validation_icon = BL_UI_Image(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            0,
            0,
        )

        validation_icon.set_image_size((self.icon_size, self.icon_size))
        validation_icon.set_image_position((0, 0))
        self.validation_icons.append(validation_icon)
        new_button.validation_icon = validation_icon

        bookmark_button = BL_UI_Button(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y + self.button_margin + self.validation_icon_margin,
            self.icon_size,
            self.icon_size,
        )
        bookmark_button.set_image_size((self.icon_size, self.icon_size))
        bookmark_button.set_image_position((0, 0))
        bookmark_button.button_index = button_idx
        bookmark_button.search_index = button_idx
        bookmark_button.text = ""
        bookmark_button.set_mouse_down(self.bookmark_asset)

        img_fp = paths.get_addon_thumbnail_path("bookmark_empty.png")
        bookmark_button.set_image(img_fp)
        bookmark_button.bg_color = fully_transparent_color
        bookmark_button.hover_bg_color = self.button_bg_color
        bookmark_button.select_bg_color = fully_transparent_color
        bookmark_button.visible = False
        new_button.bookmark_button = bookmark_button
        self.bookmark_buttons.append(bookmark_button)
        progress_bar = BL_UI_Widget(
            asset_x, asset_y + self.button_size - 6, self.button_size, 6
        )
        progress_bar.bg_color = (0.0, 1.0, 0.0, 0.3)
        new_button.progress_bar = progress_bar
        self.progress_bars.append(progress_bar)

        if utils.profile_is_validator():
            red_alert = BL_UI_Widget(
                asset_x - self.validation_icon_margin,
                asset_y - self.validation_icon_margin,
                self.button_size + 2 * self.validation_icon_margin,
                self.button_size + 2 * self.validation_icon_margin,
            )
            red_alert.bg_color = (1.0, 0.0, 0.0, 0.0)
            red_alert.visible = False
            red_alert.active = False
            new_button.red_alert = red_alert
            self.red_alerts.append(red_alert)

        return new_button

    def init_ui(self):
        """Initialize the asset bar UI and its widgets."""
        self.button_bg_color = (0.2, 0.2, 0.2, 1.0)
        self.button_hover_color = (0.8, 0.8, 0.8, 1.0)
        self.button_selected_color = (0.5, 0.5, 0.5, 1.0)
        self.button_selected_color_dim = (0.3, 0.3, 0.3, 1.0)

        self.buttons = []
        self.asset_buttons = []
        self.validation_icons = []
        self.bookmark_buttons = []
        self.progress_bars = []
        self.red_alerts = []
        self.widgets_panel = []
        self.tab_buttons = []
        self.close_tab_buttons = []
        self.active_filter_buttons = []
        self.manufacturer_buttons = []

        # Create panel with extended height
        self.panel = BL_UI_Drag_Panel(
            0,
            0,
            self.bar_width,
            self.bar_height,  # Use total height including tabs
        )
        self.panel.bg_color = (0.0, 0.0, 0.0, 0.9)

        # Create tab area background
        self.tab_area_bg = BL_UI_Widget(
            0,  # x position will be set in update_assetbar_layout
            -self.other_button_size,  # Position at top where tabs are
            self.bar_width,  # Same width as asset bar
            self.other_button_size,  # Same height as tab buttons
        )
        # dark blue
        self.tab_area_bg.bg_color = colors.TOP_BAR_BLUE
        self.tab_area_bg.use_rounded_background = True
        self.tab_area_bg.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )

        # Add widgets to panel - add tab background first so it's behind everything
        self.widgets_panel.append(self.tab_area_bg)

        # we init max possible buttons.
        button_idx = 0
        for x in range(0, self.max_wcount):
            for y in range(0, self.max_hcount):
                # asset_x = self.assetbar_margin + a * (self.button_size)
                # asset_y = self.assetbar_margin + b * (self.button_size)
                # button_idx = x + y * self.max_wcount
                asset_idx = button_idx + self.scroll_offset
                # if asset_idx < len(sr):
                new_button = self.asset_button_init(0, 0, button_idx)
                new_button.asset_index = asset_idx
                self.asset_buttons.append(new_button)
                button_idx += 1

        self.button_close = BL_UI_Button(
            self.bar_width - self.other_button_size,
            -self.other_button_size,
            self.other_button_size,
            self.other_button_size,
        )
        self.button_close.bg_color = self.button_bg_color
        self.button_close.hover_bg_color = self.button_hover_color
        self.button_close.use_rounded_background = True
        self.button_close.background_corner_radius = (
            0,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.button_close.text = "×"
        self.button_close.text_size = self.other_button_size * 0.8
        self.button_close.set_image_position((0, 0))
        self.button_close.set_image_size(
            (self.other_button_size, self.other_button_size)
        )
        self.button_close.set_mouse_down(self.cancel_press)

        self.widgets_panel.append(self.button_close)

        # Expand/collapse button (positioned at bottom of assetbar)
        self.button_expand = BL_UI_Button(
            self.bar_width - self.other_button_size,
            self.bar_height,
            self.other_button_size,
            self.other_button_size,
        )
        self.button_expand.bg_color = self.button_bg_color
        self.button_expand.hover_bg_color = self.button_hover_color
        self.button_expand.text = ""
        self.button_expand.text_size = self.other_button_size * 0.8
        self.button_expand.use_rounded_background = True
        self.button_expand.background_corner_radius = (
            0,
            0,
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
        )
        self.button_expand.set_image_position((0, 0))
        self.button_expand.set_image_size(
            (self.other_button_size, self.other_button_size)
        )
        self.button_expand.set_mouse_down(self.toggle_expand)

        self.widgets_panel.append(self.button_expand)

        self.scroll_width = 30
        self.button_scroll_down = BL_UI_Button(
            -self.scroll_width, 0, self.scroll_width, self.bar_height
        )
        self.button_scroll_down.bg_color = self.button_bg_color
        self.button_scroll_down.hover_bg_color = self.button_hover_color
        self.button_scroll_down.use_rounded_background = True
        self.button_scroll_down.background_corner_radius = (
            ROUNDING_RADIUS,
            0,
            0,
            ROUNDING_RADIUS,
        )
        self.button_scroll_down.text = ""
        self.button_scroll_down.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_down.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

        self.button_scroll_down.set_mouse_down(self.scroll_down)

        self.widgets_panel.append(self.button_scroll_down)

        self.button_scroll_up = BL_UI_Button(
            self.bar_width, 0, self.scroll_width, self.bar_height
        )
        self.button_scroll_up.bg_color = self.button_bg_color
        self.button_scroll_up.hover_bg_color = self.button_hover_color
        self.button_scroll_up.use_rounded_background = True
        self.button_scroll_up.background_corner_radius = (
            0,
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
        )
        self.button_scroll_up.text = ""
        self.button_scroll_up.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_up.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

        self.button_scroll_up.set_mouse_down(self.scroll_up)

        self.widgets_panel.append(self.button_scroll_up)

        # Add tab navigation elements
        button_size = self.other_button_size
        margin = int(button_size * 0.05)
        space = int(button_size * 0.4)
        tab_icon_size = int(button_size * 0.7)  # Size for the asset type icon
        tab_width = (
            button_size * 4 + tab_icon_size
        )  # Widen the tabs to accommodate type icon

        # Back/Forward history buttons
        self.history_back_button = BL_UI_Button(
            margin, -button_size, button_size, button_size
        )
        self.history_back_button.bg_color = self.button_bg_color
        self.history_back_button.hover_bg_color = self.button_hover_color
        self.history_back_button.use_rounded_background = True
        self.history_back_button.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.history_back_button.text = ""
        icon_size = int(button_size * 0.6)
        margin_lr = int((button_size - icon_size) / 2)
        self.history_back_button.set_image(
            paths.get_addon_thumbnail_path("history_back.png")
        )
        self.history_back_button.set_image_size((icon_size, icon_size))
        self.history_back_button.set_image_position((margin_lr, margin_lr))

        self.history_forward_button = BL_UI_Button(
            margin * 2 + button_size,
            -button_size,
            button_size,
            button_size,
        )
        self.history_forward_button.bg_color = self.button_bg_color
        self.history_forward_button.hover_bg_color = self.button_hover_color
        self.history_forward_button.use_rounded_background = True
        self.history_forward_button.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.history_forward_button.text = ""
        self.history_forward_button.set_image(
            paths.get_addon_thumbnail_path("history_forward.png")
        )
        self.history_forward_button.set_image_size((icon_size, icon_size))
        self.history_forward_button.set_image_position((margin_lr, margin_lr))

        # Tab buttons
        tabs = global_vars.TABS["tabs"]
        tab_x_start = margin * 4 + button_size * 3  # Starting x position of first tab

        tabs_end_x = 0

        for i, tab in enumerate(tabs):
            is_active = i == global_vars.TABS["active_tab"]

            # Calculate positions
            tab_x = tab_x_start + i * (
                tab_width + button_size + margin + space
            )  # Space for tab and close button

            # Tab button
            tab_button = BL_UI_Button(
                tab_x,  # Position with spacing for close buttons
                -button_size,
                tab_width,  # Width of tab
                button_size,
            )

            tab_button.hover_bg_color = self.button_hover_color
            tab_button.text = tab["name"]
            tab_button.text_size = button_size * 0.5
            tab_button.text_color = self.text_color
            tab_button.bg_color = self.button_bg_color
            tab_button.use_rounded_background = True
            tab_button.background_padding = (margin, 0)  # extra margin
            tab_button.background_corner_radius = (
                ROUNDING_RADIUS,
                0,
                0,
                0,
            )
            if is_active:
                tab_button.bg_color = self.button_selected_color

            tab_button.tab_index = i  # Store tab index
            tab_button.set_mouse_down(self.switch_tab)  # Add click handler
            self.tab_buttons.append(tab_button)

            # Set asset type icon as tab button image
            tab_button.set_image_size((tab_icon_size, tab_icon_size))
            tab_button.set_image_position(
                (margin * 2, (button_size - tab_icon_size) / 2)
            )  # Center vertically

            # Only create close button if there's more than one tab
            close_x = tab_x + tab_width + margin  # Position right after tab
            close_tab = BL_UI_Button(
                close_x,
                -button_size,
                button_size,
                button_size,
            )
            close_tab.bg_color = self.button_bg_color
            # slightly red
            close_tab.hover_bg_color = (0.8, 0.0, 0.0, 0.2)
            close_tab.text = "×"  # Set text after creation
            close_tab.text_size = button_size * 0.8
            close_tab.text_color = self.text_color
            close_tab.use_rounded_background = True
            close_tab.background_corner_radius = (0, ROUNDING_RADIUS, 0, 0)
            if is_active:
                close_tab.bg_color = self.button_selected_color_dim

            close_tab.tab_index = i  # Store tab index
            # if there's only one tab, the button closes asset bar instead of closing tab
            if len(tabs) > 1:
                close_tab.set_mouse_down(self.remove_tab)  # Add click handler
            else:
                close_tab.set_mouse_down(self.cancel_press)

            self.close_tab_buttons.append(close_tab)

            tabs_end_x = close_x + button_size

        # New tab button - position after all tabs and close buttons
        if len(tabs) > 0:
            new_tab_x = (
                space + tabs_end_x + margin * 2
            )  # After last tab and its close button
        else:
            new_tab_x = tab_x_start  # If no tabs, start at the beginning

        # if too close to the right side, let's not create this button
        if new_tab_x + button_size < self.bar_width:
            self.new_tab_button = BL_UI_Button(
                new_tab_x,
                -button_size,
                button_size,
                button_size,
            )
            # Change from default button color to slightly green
            self.new_tab_button.bg_color = (0.2, 0.5, 0.2, 1.0)  # Green tint
            # Slightly lighter green on hover
            self.new_tab_button.hover_bg_color = (0.3, 0.7, 0.3, 0.5)
            self.new_tab_button.text = "+"
            self.new_tab_button.text_size = button_size * 0.8
            self.new_tab_button.text_color = self.text_color
            self.new_tab_button.use_rounded_background = True
            self.new_tab_button.background_corner_radius = ROUNDING_RADIUS
            self.new_tab_button.set_mouse_down(self.add_new_tab)
            self.widgets_panel.append(self.new_tab_button)

        # Then add all other widgets
        self.widgets_panel.extend(
            [
                self.history_back_button,
                self.history_forward_button,
            ]
        )
        self.widgets_panel.extend(self.tab_buttons)
        self.widgets_panel.extend(self.close_tab_buttons)

        # Back/Forward history buttons
        self.history_back_button.set_mouse_down(self.history_back)
        self.history_forward_button.set_mouse_down(self.history_forward)

        # Set initial visibility based on history
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        self.history_back_button.visible = active_tab["history_index"] > 0
        self.history_forward_button.visible = (
            active_tab["history_index"] < len(active_tab["history"]) - 1
        )

        # Manufacturer filter buttons (stay hidden until populated)
        # Active filter chips (generic, per tab)
        for _ in range(self.max_active_filter_chips):
            chip_button = BL_UI_Button(0, 0, 100, self.filter_button_height)
            chip_button.bg_color = (0.18, 0.18, 0.18, 0.9)
            chip_button.hover_bg_color = (0.22, 0.22, 0.22, 1.0)
            chip_button.text = ""
            chip_button.text_size = self.filter_button_text_size
            chip_button.text_color = self.text_color
            chip_button.visible = False
            chip_button.use_rounded_background = True
            chip_button.background_corner_radius = "50%"
            chip_button.background_border = True
            chip_button.background_border_color = colors.ACTIVE_BLUE
            chip_button.background_border_thickness = 1.5
            chip_button.set_mouse_down(self.remove_active_filter_chip)
            chip_button.active_filter = None
            self.active_filter_buttons.append(chip_button)

        self.widgets_panel.extend(self.active_filter_buttons)

        # Manufacturer filter buttons (stay hidden until populated)
        for _ in range(self.max_manufacturer_filters):
            filter_button = BL_UI_Button(0, 0, 80, self.filter_button_height)
            # start with a neutral gray; exact shade is updated when buttons are positioned
            base_gray = 50 / 255
            filter_button.bg_color = (base_gray, base_gray, base_gray, 0.85)
            filter_button.hover_bg_color = (
                base_gray + 0.1,
                base_gray + 0.1,
                base_gray + 0.1,
                1.0,
            )
            filter_button.text = ""
            filter_button.text_size = self.filter_button_text_size
            filter_button.text_color = self.text_color
            filter_button.visible = False
            filter_button.use_rounded_background = True
            filter_button.background_corner_radius = "50%"
            filter_button.set_mouse_down(
                partial(self.apply_term_filter, term="manufacturer")
            )
            filter_button.manufacturer_name = ""
            self.manufacturer_buttons.append(filter_button)

        # Clear manufacturer filter bubble (red cross)
        self.widgets_panel.extend(self.manufacturer_buttons)

    # endregion panel

    def show_notifications(self, widget):
        """Show notifications on the asset bar."""
        bpy.ops.wm.show_notifications()
        if comments_utils.check_notifications_read():
            widget.visible = False

    # region checks

    def check_new_search_results(self, context):
        """checks if results were replaced.
        this can happen from search, but also by switching results.
        We should rather trigger that update from search. maybe let's add a uuid to the results?
        """
        # Get search results from history
        sr = search.get_search_results()
        current_id = id(sr) if sr is not None else None

        if not hasattr(self, "search_results_count"):
            self.search_results_count = len(sr) if sr else 0
            self.last_asset_type = sr[0]["assetType"] if sr else ""
            self._last_search_results_id = current_id
            return True

        if current_id != getattr(self, "_last_search_results_id", None):
            self._last_search_results_id = current_id
            self.search_results_count = len(sr) if sr else 0
            if sr:
                self.last_asset_type = sr[0]["assetType"]
            return True

        if sr is not None and len(sr) != self.search_results_count:
            self.search_results_count = len(sr)
            return True
        return False

    def get_region_size(self, context):
        """Get the size of the region."""
        # just check the size of region..

        region = context.region
        area = context.area
        ui_width = 0
        tools_width = 0
        for r in area.regions:
            if r.type == "UI":
                ui_width = r.width
            if r.type == "TOOLS":
                tools_width = r.width
        total_width = region.width - tools_width - ui_width
        return total_width, region.height

    def check_region_changed(self, context):
        """Check if the region has changed."""
        region_width, region_height = self.get_region_size(context)

        if not hasattr(self, "total_width"):
            self.total_width = region_width
            self.region_height = region_height

        changed = (
            region_height != self.region_height or region_width != self.total_width
        )

        if changed:
            self.region_height = region_height
            self.total_width = region_width
            return True
        return False

    def check_ui_resized(self, context):
        """Check if the UI has been resized."""
        scaling = ui_bgl.get_ui_scale()

        if not hasattr(self, "_ui_scale_state"):
            self._ui_scale_state = scaling

        scale_changed = scaling != self._ui_scale_state

        if scale_changed:
            self._ui_scale_state = scaling
            return True
        return False

    # endregion checks

    # region updates

    def update_assetbar_sizes(self, context):
        """Calculate all important sizes for the asset bar"""
        region = context.region
        area = context.area

        ui_props = bpy.context.window_manager.blenderkitUI
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        scale = ui_bgl.get_ui_scale()
        self._ui_scale_factor = scale
        # assetbar sizing (fixed, not scaled)

        self.button_margin = int(round(0 * scale))
        self.assetbar_margin = int(round(2 * scale))
        # user preference thumb size is in logical pixels; scale to match Blender UI scaling
        self.thumb_size = int(round(user_preferences.thumb_size * scale))
        self.button_size = int(2 * self.button_margin + self.thumb_size)
        self.free_button_margin = int(self.button_size * 0.05)

        self.other_button_size = int(round(30 * scale))
        self.filter_button_height = int(round(25 * scale))
        self.filter_button_text_size = int(round(20 * scale))
        self.icon_size = int(round(24 * scale))
        self.validation_icon_margin = int(round(3 * scale))
        reg_multiplier = 1
        if not bpy.context.preferences.system.use_region_overlap:
            reg_multiplier = 0

        ui_width = 0
        tools_width = 0
        reg_multiplier = 1
        if not bpy.context.preferences.system.use_region_overlap:
            reg_multiplier = 0
        for r in area.regions:
            if r.type == "UI":
                ui_width = r.width * reg_multiplier
            if r.type == "TOOLS":
                tools_width = r.width * reg_multiplier
        self.bar_x = int(
            tools_width + self.button_margin + ui_props.bar_x_offset * scale
        )
        base_bar_y = int(self.button_margin + ui_props.bar_y_offset * scale)
        self.bar_y = base_bar_y

        self.bar_end = int(ui_width + 180 + self.other_button_size)
        self.bar_width = int(region.width - self.bar_x - self.bar_end)
        # Quad view and very small regions can shrink the available width below a single
        # thumbnail. Keep the bar wide enough to host at least one column and keep the
        # math stable so the buttons do not disappear entirely.
        self.bar_width = max(1, self.bar_width)

        effective_bar_width = max(self.bar_width, self.button_size)
        self.wcount = max(1, math.floor(effective_bar_width / self.button_size))

        self.max_hcount = math.floor(
            max(region.width, context.window.width) / self.button_size
        )
        self.max_wcount = user_preferences.maximized_assetbar_rows

        history_step = search.get_active_history_step()
        search_results = history_step.get("search_results")

        self.manufacturer_button_min_width = int(round(70 * scale))
        self.manufacturer_button_max_width = int(round(200 * scale))

        self.active_filter_button_min_width = int(round(80 * scale))
        self.active_filter_button_max_width = int(round(360 * scale))

        self._refresh_active_filter_layout()

        bubble_offset = 0
        has_filter_bubbles = getattr(self, "_active_filter_rows", 0) > 0
        if self._filter_bubbles_enabled() and has_filter_bubbles:
            bubble_offset = self.filter_button_height + self.free_button_margin

        self.bar_y = base_bar_y + bubble_offset

        # we need to init all possible thumb previews in advance/
        # Calculate hcount based on expanded state
        if search_results is not None and self.wcount > 0:
            if user_preferences.assetbar_expanded:
                max_rows = user_preferences.maximized_assetbar_rows
                available_height = (
                    region.height
                    - self.bar_y
                    - 2 * self.assetbar_margin
                    - self.other_button_size
                )
                max_rows_by_height = math.floor(available_height / self.button_size)
                max_rows = (
                    min(max_rows, max_rows_by_height) if max_rows_by_height > 0 else 1
                )
            else:
                max_rows = 1
            self.hcount = min(
                max_rows,
                math.ceil(len(search_results) / self.wcount),
            )
            self.hcount = max(self.hcount, 1)
        else:
            self.hcount = 1

        self._base_bar_height = (
            self.button_size * self.hcount + 2 * self.assetbar_margin
        )
        self._update_manufacturer_data(search_results)
        self.bar_height = self._base_bar_height + self.manufacturer_section_height

        if ui_props.down_up == "UPLOAD":
            self.reports_y = region.height - self.bar_y - 600
            ui_props.reports_y = region.height - self.bar_y - 600
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x

        else:  # ui.bar_y - ui.bar_height - 100
            self.reports_y = region.height - self.bar_y - self.bar_height - 50
            ui_props.reports_y = int(region.height - self.bar_y - self.bar_height - 50)
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x

    def update_ui_size(self, context):
        """Calculate all important sizes for the asset bar and tooltip"""
        self._refresh_layout(context)

    def update_assetbar_layout(self, context):
        """Update the layout of the asset bar"""
        self.scroll_update(always=True)

        self.position_and_hide_buttons()

        self.button_close.set_location(
            self.bar_width - self.other_button_size, -self.other_button_size
        )
        self.button_expand.set_location(
            self.bar_width - self.other_button_size, self.bar_height
        )

        self.button_scroll_up.set_location(self.bar_width, 0)
        self.panel.width = self.bar_width
        self.panel.height = self.bar_height

        # Update tab area background position
        self.tab_area_bg.width = self.bar_width

        self.panel.set_location(self.bar_x, self.bar_y)

        self.position_manufacturer_buttons()

    def update_layout(self, context, event):
        """update UI sizes after their recalculation"""
        self.update_assetbar_layout(context)
        self.update_tooltip_layout(context)

    def _is_quad_view(self, context):
        """Return True when the current 3D view runs in quad-view layout."""
        space_data = getattr(context, "space_data", None)
        if not space_data or getattr(space_data, "type", "") != "VIEW_3D":
            return False
        quadviews = getattr(space_data, "region_quadviews", None)
        if quadviews is None:
            return False
        try:
            return len(quadviews) > 0
        except TypeError:
            return bool(quadviews)

    def _is_perspective_region(self, region):
        """Return True if the given region is a perspective (or camera) view."""
        r3d = getattr(region, "data", None) or getattr(region, "regiondata", None)
        if r3d is None:
            return False
        return getattr(r3d, "view_perspective", "") in {"PERSP", "CAMERA"}

    def _filter_bubbles_enabled(self) -> bool:
        """Return True when experimental filter bubbles are allowed to render."""
        addon = bpy.context.preferences.addons.get(__package__)
        prefs = getattr(addon, "preferences", None)
        return (
            bool(getattr(prefs, "display_filter_bubbles", False))
            and utils.experimental_enabled()
        )

    def set_element_images(self):
        """set ui elements images, has to be done after init of UI."""
        # img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
        # self.button_close.set_image(img_fp)
        self.button_scroll_down.set_image(
            paths.get_addon_thumbnail_path("arrow_left.png")
        )
        self.button_scroll_up.set_image(
            paths.get_addon_thumbnail_path("arrow_right.png")
        )
        # if not comments_utils.check_notifications_read():
        #     img_fp = paths.get_addon_thumbnail_path('bell.png')
        #     self.button_notifications.set_image(img_fp)

        # Update tab icons
        self.update_tab_icons()

        # Update expand button icon
        self.update_expand_button_icon()

    def update_tab_icons(self):
        """Update tab icons based on the active history step's asset type"""
        tabs = global_vars.TABS["tabs"]
        for i, tab_button in enumerate(self.tab_buttons):
            if i >= len(tabs):
                continue

            tab = tabs[i]
            history_index = tab["history_index"]

            if history_index >= 0 and history_index < len(tab["history"]):
                history_step = tab["history"][history_index]
                ui_state = history_step.get("ui_state", {})
                ui_props = ui_state.get("ui_props", {})
                asset_type = ui_props.get("asset_type", "").lower()

                # Set the icon based on asset type
                if asset_type:
                    icon_path = paths.get_addon_thumbnail_path(
                        f"asset_type_{asset_type}.png"
                    )
                    if not paths.icon_path_exists(icon_path):
                        icon_path = paths.get_addon_thumbnail_path(
                            "asset_type_model.png"
                        )

                    tab_button.set_image(icon_path)
                    tab_button.set_image_colorspace("")

    def update_expand_button_icon(self):
        """Update expand button icon based on current expanded state."""
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        if user_preferences.assetbar_expanded:
            # Show up arrow when expanded (to collapse)
            self.button_expand.text = "▲"
        else:
            # Show down arrow when collapsed (to expand)
            self.button_expand.text = "▼"

    def _extract_manufacturer_name(self, asset_data):
        manufacturer = asset_data.get("dictParameters", {}).get("manufacturer")
        if not manufacturer:
            return ""
        return self._sanitize_manufacturer_name(str(manufacturer)) or ""

    def _sanitize_manufacturer_name(self, name: str) -> Optional[str]:
        cleaned = name.strip()
        if not cleaned:
            return None

        lowered = cleaned.lower()
        is_url = lowered.startswith(("http://", "https://", "www.")) or "://" in lowered
        if is_url:
            return None

        tokens = re.split(r"[\s,\\/|_-]+", lowered)
        invalid_tokens = {"me", "unknown", "self", "none", "n/a", "na", "null", "nil"}
        if any(t in invalid_tokens for t in tokens if t):
            return None

        # also use regex to disqualify names without any letters, or with only special characters
        if not re.search(r"[a-zA-Z]", cleaned):
            return None

        return cleaned

    def _format_manufacturer_label(self, name: str) -> str:
        if len(name) <= MAX_MANUFACTURER_LABEL_LEN:
            return name
        return name[: MAX_MANUFACTURER_LABEL_LEN - 3].rstrip() + "..."

    def _refresh_manufacturer_names(self, search_results):
        if not search_results:
            self._manufacturer_names = []
            self._manufacturer_counts = Counter()
            return

        counts = Counter()
        for asset_data in search_results:
            name = self._extract_manufacturer_name(asset_data)
            if name:
                counts[name] += 1

        most_common = counts.most_common(self.max_manufacturer_filters)
        self._manufacturer_names = [name for name, _ in most_common]
        self._manufacturer_counts = counts

    def _estimate_manufacturer_button_width(self, label):
        char_width = max(6, int(self.other_button_size * 0.4))
        base_width = 2 * self.button_margin
        width = base_width + char_width * len(label)
        width = max(self.manufacturer_button_min_width, width)
        width = min(self.manufacturer_button_max_width, width)
        return int(width)

    def _estimate_active_filter_button_width(self, label: str) -> int:
        char_width = max(6, int(self.other_button_size * 0.4))
        base_width = 2 * self.button_margin
        width = base_width + char_width * len(label)
        width = max(self.active_filter_button_min_width, width)
        width = min(self.active_filter_button_max_width, width)
        return int(width)

    def _format_filter_label(self, term: str, label: str) -> str:
        display_body = f"{term.capitalize()}: {label}" if term else label
        # Active filter chips should show the full label without shortening
        return f"{display_body} ×"

    def _refresh_active_filter_layout(self):
        if not self._filter_bubbles_enabled():
            self._active_filter_button_layout = []
            self._active_filter_rows = 0
            return

        filters = search.get_active_filters()
        layout = []

        clear_slot = 0  # reserved for potential future clear-all button
        raw_available = self.bar_width - 2 * self.assetbar_margin - clear_slot
        min_width = self.active_filter_button_min_width
        # Prevent the offset from eating all available width; keep at least one chip visible
        capped_offset = max(0, raw_available - min_width)
        content_width = max(min_width, raw_available - capped_offset)

        if not filters or raw_available <= 0:
            self._active_filter_button_layout = []
            self._active_filter_rows = 0
            return

        max_x = self.assetbar_margin + clear_slot + capped_offset + content_width
        current_x = self.assetbar_margin + clear_slot + capped_offset
        current_row = 0

        for f in filters[: self.max_active_filter_chips]:
            term = f.get("term", "")
            value = f.get("value", "")
            label_source = f.get("label") or value
            label = self._format_filter_label(term, label_source)
            width = self._estimate_active_filter_button_width(label)
            width = min(width, content_width)
            if current_x + width > max_x and current_x > self.assetbar_margin:
                current_row += 1
                current_x = self.assetbar_margin + clear_slot

            layout.append(
                {
                    "term": term,
                    "value": value,
                    "label": label,
                    "width": int(width),
                    "row": current_row,
                    "x": int(current_x),
                }
            )
            current_x += width + self.free_button_margin

        self._active_filter_button_layout = layout
        self._active_filter_rows = current_row + 1 if layout else 0

    def _recalculate_manufacturer_layout(self):
        names = self._manufacturer_names[: self.max_manufacturer_filters]
        content_width = max(0, self.bar_width - 2 * self.assetbar_margin)

        if not names or content_width <= 0:
            self._manufacturer_button_layout = []
            self._manufacturer_rows = 0
            self.manufacturer_section_height = 0
            return

        max_x = self.bar_width - self.assetbar_margin
        current_x = self.assetbar_margin
        current_row = 0
        layout = []

        for name in names:
            label = self._format_manufacturer_label(name)
            width = self._estimate_manufacturer_button_width(label)
            width = min(width, content_width)
            if current_x + width > max_x and current_x > self.assetbar_margin:
                current_row += 1
                current_x = self.assetbar_margin

            layout.append(
                {
                    "name": name,
                    "label": label,
                    "width": int(width),
                    "row": current_row,
                    "x": int(current_x),
                }
            )
            current_x += width + self.free_button_margin

        self._manufacturer_button_layout = layout
        self._manufacturer_rows = current_row + 1 if layout else 0
        if self._manufacturer_rows > 0:
            self.manufacturer_section_height = self._manufacturer_rows * (
                self.filter_button_height + (self.free_button_margin * 2)
            )
        else:
            self.manufacturer_section_height = 0

    def _update_manufacturer_data(self, search_results: Optional[list[dict]] = None):
        if not self._filter_bubbles_enabled():
            self._manufacturer_names = []
            self._manufacturer_counts = Counter()
            self._manufacturer_button_layout = []
            self._manufacturer_rows = 0
            self.manufacturer_section_height = 0
            for btn in getattr(self, "manufacturer_buttons", []):
                btn.visible = False
            return

        self._refresh_manufacturer_names(search_results)
        self._recalculate_manufacturer_layout()
        self.position_manufacturer_buttons()

    def _calculate_manufacturer_gray(self, count, min_count, max_count):
        """Map manufacturer usage count to a gray value between 50 and 120."""
        min_gray = 50 / 255
        max_gray = 120 / 255

        if max_count <= min_count:
            return min_gray

        factor = (count - min_count) / (max_count - min_count)
        gray = min_gray + factor * (max_gray - min_gray)
        return min(max_gray, max(min_gray, gray))

    def position_active_filter_buttons(self):
        if not self.active_filter_buttons:
            return

        if not self._filter_bubbles_enabled():
            for button in self.active_filter_buttons:
                button.visible = False
                button.active_filter = None
            return

        # Ensure layout is up to date with current width/filters
        self._refresh_active_filter_layout()
        layout = getattr(self, "_active_filter_button_layout", [])

        # Keep chips below the toolbar but above the asset bar when space is tight
        base_y = -(
            self.other_button_size
            + self.filter_button_height
            + self.free_button_margin * 2
        )

        start_y = base_y + self.free_button_margin
        start_y = max(start_y, -self.bar_y + self.free_button_margin)

        for idx, button in enumerate(self.active_filter_buttons):
            if idx < len(layout):
                data = layout[idx]
                row_y = start_y + data["row"] * (
                    self.filter_button_height + self.free_button_margin * 2
                )
                button.set_location(data["x"], int(row_y))
                button.width = data["width"]
                button.height = self.filter_button_height
                button.text = data["label"].upper()
                button.text_size = self.other_button_size * 0.4
                button.visible = True
                button.active_filter = {"term": data["term"], "value": data["value"]}
            else:
                button.visible = False

    def position_manufacturer_buttons(self):
        if not self.manufacturer_buttons:
            return

        if not self._filter_bubbles_enabled():
            for button in self.manufacturer_buttons:
                button.visible = False
            return

        layout = getattr(self, "_manufacturer_button_layout", [])
        experimental_enabled = utils.experimental_enabled()
        if not experimental_enabled:
            layout = []
        counts = getattr(self, "_manufacturer_counts", {}) or {}

        base_y = (
            self.assetbar_margin
            + self.button_size * self.hcount
            + self.free_button_margin
        )
        displayed_counts = [counts.get(data["name"], 0) for data in layout]

        min_count = min(displayed_counts) if displayed_counts else 1
        max_count = max(displayed_counts) if displayed_counts else 1

        manufacturer_width = 0
        for idx, button in enumerate(self.manufacturer_buttons):
            if idx < len(layout):
                data = layout[idx]
                button.set_location(
                    self.panel.x + data["x"],
                    self.panel.y + base_y,
                )
                # shift to the right so we leave space for the clear bubble
                # button.x += clear_slot
                button.width = data["width"]
                button.height = self.filter_button_height
                button.text = data.get("label", data["name"]).upper()
                button.text_size = self.other_button_size * 0.4
                button.visible = True
                button.manufacturer_name = data["name"]
                count = counts.get(data["name"], min_count)
                gray = self._calculate_manufacturer_gray(count, min_count, max_count)
                hover_gray = min(gray + 0.1, 1.0)
                button.bg_color = (gray, gray, gray, 0.85)
                button.hover_bg_color = (hover_gray, hover_gray, hover_gray, 1.0)

                manufacturer_width += (
                    data["width"]
                    + self.free_button_margin
                    + int(self.button_size * 0.05)
                )
            else:
                button.visible = False

    def position_and_hide_buttons(self):
        """Position asset buttons in the asset bar and hide unused buttons."""
        # position and layout buttons
        sr = search.get_search_results()
        if sr is None:
            sr = []

        i = 0
        for y in range(0, self.hcount):
            for x in range(0, self.wcount):
                asset_x = self.assetbar_margin + x * (self.button_size)
                asset_y = self.assetbar_margin + y * (self.button_size)
                button_idx = x + y * self.wcount
                asset_idx = button_idx + self.scroll_offset
                if len(self.asset_buttons) <= button_idx:
                    break
                button = self.asset_buttons[button_idx]
                button.set_location(asset_x, asset_y)
                button.validation_icon.set_location(
                    asset_x
                    + self.button_size
                    - self.icon_size
                    - self.button_margin
                    - self.validation_icon_margin,
                    asset_y
                    + self.button_size
                    - self.icon_size
                    - self.button_margin
                    - self.validation_icon_margin,
                )
                button.bookmark_button.set_location(
                    asset_x
                    + self.button_size
                    - self.icon_size
                    - self.button_margin
                    - self.validation_icon_margin,
                    asset_y + self.button_margin + self.validation_icon_margin,
                )
                button.progress_bar.set_location(
                    asset_x, asset_y + self.button_size - 6
                )
                if asset_idx < len(sr):
                    button.visible = True
                    button.validation_icon.visible = True
                    button.bookmark_button.visible = False
                    # button.progress_bar.visible = True
                else:
                    button.visible = False
                    button.validation_icon.visible = False
                    button.bookmark_button.visible = False
                    button.progress_bar.visible = False
                if utils.profile_is_validator():
                    button.red_alert.set_location(
                        asset_x - self.validation_icon_margin,
                        asset_y - self.validation_icon_margin,
                    )
                i += 1

        for a in range(i, len(self.asset_buttons)):
            button = self.asset_buttons[a]
            button.visible = False
            button.validation_icon.visible = False
            button.bookmark_button.visible = False
            button.progress_bar.visible = False

        self.position_active_filter_buttons()

        self.button_scroll_down.height = self.bar_height
        self.button_scroll_down.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )
        self.button_scroll_up.height = self.bar_height
        self.button_scroll_up.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

    # endregion updates

    # region setup

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._quad_view_state = None
        self._restart_pending = False
        self.scroll_offset = 0
        self._tooltip_available_height = None
        self.max_manufacturer_filters = 10
        self.manufacturer_buttons = []
        self._manufacturer_names = []
        self._manufacturer_counts = Counter()
        self._manufacturer_button_layout = []
        self._manufacturer_rows = 0
        self.manufacturer_section_height = 0
        self._last_search_results_id = None
        self._base_bar_height = 0
        self.max_active_filter_chips = 8
        self.active_filter_buttons = []
        self._active_filter_button_layout = []
        self._active_filter_rows = 0
        self.manufacturer_button_min_width = 70
        self.manufacturer_button_max_width = 200

    def on_init(self, context):
        """Initialize the asset bar operator."""
        self.tooltip_base_size_pixels = TOOLTIP_SIZE_PX
        self.tooltip_scale = 1.0
        self.bottom_panel_fraction = 0.18
        self.needs_tooltip_update = False
        self.update_ui_size(context)
        self._quad_view_state = self._is_quad_view(context)

        # todo move all this to update UI size
        ui_props = context.window_manager.blenderkitUI

        self.draw_tooltip = False
        # let's take saved scroll offset and use it to keep scroll between operator runs

        self.last_scroll_offset = -10  # set to -10 so it updates on first run
        self.scroll_offset = ui_props.scroll_offset

        self.text_color = (0.9, 0.9, 0.9, 1.0)
        self.warning_color = (0.9, 0.5, 0.5, 1.0)

        self.init_ui()
        self.init_tooltip()
        self.hide_tooltip()

        self.trackpad_x_accum = 0
        self.trackpad_y_accum = 0

    def setup_widgets(self, context, event):
        """Set up all widgets for the asset bar and tooltip."""
        widgets_panel = []
        widgets_panel.extend(self.widgets_panel)
        widgets_panel.extend(self.buttons)

        widgets_panel.extend(self.asset_buttons)
        widgets_panel.extend(self.red_alerts)
        # we try to put bookmark_buttons before others, because they're on top
        widgets_panel.extend(self.bookmark_buttons)
        widgets_panel.extend(self.validation_icons)
        widgets_panel.extend(self.progress_bars)

        widgets = [self.panel]

        widgets += widgets_panel
        widgets.append(self.tooltip_panel)
        widgets += self.tooltip_widgets

        self.init_widgets(context, widgets)

        self.panel.add_widgets(widgets_panel)
        self.tooltip_panel.add_widgets(self.tooltip_widgets)

        stored_area, stored_region = self._unwrap_area_region(
            getattr(self, "context", None)
        )
        override_ctx = self._build_context_snapshot(
            context,
            stored_area or context.area,
            stored_region or context.region,
        )
        self._apply_widget_context(override_ctx)

    # endregion setup

    # region events

    def on_invoke(self, context, event):
        """Invoke the asset bar operator."""
        self.instances.append(self)
        if not context.area:
            return False

        ui_props = context.window_manager.blenderkitUI

        self.on_init(context)
        self.context = context

        # start search if there isn't a search result yet
        if not search.get_search_results():
            search.search()

        if ui_props.assetbar_on:
            # keep_running=True means "reuse" the existing instance instead of toggling it off
            if not self.keep_running:
                ui_props.turn_off = True
                # if there was an error, reset the flag so next invocation can start cleanly
                ui_props.assetbar_on = False
            return False

        # Clear stale shutdown flag from previous sessions (e.g. undo or addon reload)
        ui_props.turn_off = False
        ui_props.assetbar_on = True
        global asset_bar_operator

        asset_bar_operator = self

        self.active_index = -1

        self.check_new_search_results(context)
        self.setup_widgets(context, event)
        self.set_element_images()
        self.position_and_hide_buttons()
        self.hide_tooltip()

        self.panel.set_location(self.bar_x, self.bar_y)

        self.scroll_update(always=True)

        self.window = context.window
        self.area = context.area
        self.scene = bpy.context.scene
        return True

    def on_finish(self, context):
        # redraw all areas, since otherwise it stays to hang for some more time.
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d_tooltip, 'WINDOW')
        # to pass the operator to validation icons
        global asset_bar_operator
        asset_bar_operator = None

        context.window_manager.event_timer_remove(self._timer)

        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.assetbar_on = False
        ui_props.scroll_offset = self.scroll_offset

        self._finished = True
        # to ensure the asset buttons are removed from screen
        self._redraw_tracked_regions()

    # handlers
    def enter_button(self, widget):
        """Handle mouse enter on an asset button."""
        if not hasattr(widget, "button_index") or widget.button_index < 0:
            return  # click on left/right arrow button gave no attr button_index
            # we should detect on which button_index scroll/left/right happened to refresh shown thumbnail

        bpy.context.window.cursor_set("HAND")
        search_index = widget.button_index + self.scroll_offset
        if search_index < self.search_results_count:
            self.show_tooltip()
        if self.active_index != search_index:
            self.active_index = search_index
            sr = search.get_search_results()
            if search_index >= len(sr):
                return  # issue #1481 - index can be sometimes over the length of search results
            asset_data = sr[search_index]

            self.draw_tooltip = True
            # self.tooltip = asset_data['tooltip']
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = search_index  # + self.scroll_offset

            # Update tooltip size based on asset type
            thumbnail_found = False
            self.tooltip_image_help.visible = False
            if asset_data["assetType"].lower() in {
                "printable",
                "model",
                "scene",
            } and self.show_thumbnail_variant in {"PHOTO", "WIREFRAME"}:
                t_type = self.show_thumbnail_variant.lower()
                if t_type == "photo":
                    photo_img = ui.get_full_photo_thumbnail(asset_data)
                    if photo_img:
                        self.tooltip_image.set_image(photo_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                        thumbnail_found = True
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                        self.tooltip_image_help.text = "Photo thumbnail not ready yet."
                        self.tooltip_image_help.visible = True

                elif t_type == "wireframe":
                    wire_img = ui.get_full_wire_thumbnail(asset_data)
                    if wire_img:
                        self.tooltip_image.set_image(wire_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                        thumbnail_found = True
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                        self.tooltip_image_help.text = (
                            "Wireframe thumbnail not ready yet."
                        )
                        self.tooltip_image_help.visible = True

            if not thumbnail_found:
                set_thumb_check(self.tooltip_image, asset_data, thumb_type="thumbnail")

            get_tooltip_data(asset_data)
            an = asset_data["displayName"]
            max_name_length = 30
            if len(an) > max_name_length + 3:
                an = an[:30] + "..."

            search_props = utils.get_search_props()

            # if in top nodegroup category, show which type the nodegroup is
            if (
                asset_data["assetType"] == "nodegroup"
                and search_props.search_category == "nodegroup"
            ):
                an = f"{an} - {asset_data['dictParameters']['nodeType']} nodes"

            self.asset_name.text = an
            self.authors_name.text = asset_data["tooltip_data"]["author_text"]

            # Hide ratings for addons
            is_addon = asset_data.get("assetType") == "addon"
            if not is_addon:
                quality_text = asset_data["tooltip_data"]["quality"]
                if utils.profile_is_validator():
                    quality_text += f" / {int(asset_data['score'])}"
                self.quality_label.text = quality_text
                self.quality_label.visible = True
                self.quality_star.visible = True
            else:
                self.quality_label.visible = False
                self.quality_star.visible = False

            # Update price labels for addons
            user_price_text = asset_data["tooltip_data"].get("user_price_text", "")
            base_price_text = asset_data["tooltip_data"].get("base_price_text", "")

            user_price_text_color = asset_data["tooltip_data"].get(
                "user_price_color", ""
            )
            base_price_text_color = asset_data["tooltip_data"].get(
                "base_price_color", ""
            )

            user_price_background_color = asset_data["tooltip_data"].get(
                "user_price_bg_color", ""
            )
            base_price_background_color = asset_data["tooltip_data"].get(
                "base_price_bg_color", ""
            )

            self.multi_price_label.text_a = user_price_text
            self.multi_price_label.text_a_color = user_price_text_color
            self.multi_price_label.segment_background_color_a = (
                user_price_background_color
            )

            self.multi_price_label.text_b = base_price_text
            self.multi_price_label.text_b_color = base_price_text_color
            self.multi_price_label.segment_background_color_b = (
                base_price_background_color
            )

            self.multi_price_label.multiline = True

            if user_price_text and base_price_text:
                self.multi_price_label.strikethrough_b = True
                self.multi_price_label.visible = True
                self.multi_price_label.segment_backgrounds = True
            elif user_price_text or base_price_text:
                self.multi_price_label.visible = True
                self.multi_price_label.strikethrough_b = False
                self.multi_price_label.segment_backgrounds = True
            else:
                self.multi_price_label.visible = False
                self.multi_price_label.strikethrough_b = False
                self.multi_price_label.segment_backgrounds = False

            # preview comments for validators
            self.update_comments_for_validators(asset_data)

            from_newer, difference = utils.asset_from_newer_blender_version(asset_data)
            if from_newer:
                if difference == "major":
                    self.version_warning.text = f"Made in Blender {asset_data['sourceAppVersion']}! Use at your own risk."
                elif difference == "minor":
                    self.version_warning.text = f"Made in Blender {asset_data['sourceAppVersion']}! Caution advised."
                else:
                    self.version_warning.text = f"Made in Blender {asset_data['sourceAppVersion']}! Some features may not work."
            else:
                self.version_warning.text = ""

            author_id = int(asset_data["author"]["id"])
            author = global_vars.BKIT_AUTHORS.get(author_id)
            if author is None:
                bk_logger.info("\n\n\nget_tooltip_data() AUTHOR NOT FOUND", author_id)

            if author is not None and author.gravatarImg:
                self.gravatar_image.set_image(author.gravatarImg)
            else:
                img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                self.gravatar_image.set_image(img_path)
            self.gravatar_image.set_image_colorspace("")

            area, region = self._current_area_region()

            properties_width = 0
            if area is not None:
                for r in getattr(area, "regions", []):
                    if r.type == "UI":
                        properties_width = r.width
                        break

            # reset tooltip sizing so each spawn starts from base values
            self._reset_tooltip_dimensions()

            fallback_region = getattr(bpy.context, "region", None)
            active_region = region or fallback_region
            region_width = getattr(active_region, "width", None)
            if region_width is None:
                region_width = self.tooltip_panel.width + properties_width
            region_height = getattr(active_region, "height", None)
            if region_height is None:
                region_height = self.tooltip_panel.height + widget.height

            tooltip_x = min(
                int(widget.x_screen),
                int(region_width - self.tooltip_panel.width - properties_width),
            )
            tooltip_x = max(0, tooltip_x)

            # Calculate space above and below the button to decide tooltip placement
            full_tooltip_height = self.tooltip_panel.height
            space_above = widget.y_screen
            space_below = region_height - (widget.y_screen + widget.height)
            place_above = (
                space_below < full_tooltip_height
                and space_below < full_tooltip_height * 0.7
                and space_below < space_above
            )

            if place_above:
                available_height = space_above
            else:
                available_height = space_below

            self._tooltip_available_height = max(64, int(available_height))

            # need to set image here because of context issues.
            img_path = paths.get_addon_thumbnail_path("star_grey.png")
            self.quality_star.set_image(img_path)

            tooltip_context = self._build_context_snapshot(
                bpy.context, area, active_region
            )
            self.update_tooltip_size(tooltip_context)
            self.update_tooltip_layout(tooltip_context)
            tooltip_width = self.tooltip_width
            max_x = max(0, int(region_width - tooltip_width - properties_width))
            tooltip_x = min(max(0, int(widget.x_screen)), max_x)

            if place_above:
                tooltip_y = int(widget.y_screen - self.tooltip_height)
            else:
                tooltip_y = int(widget.y_screen + widget.height)

            max_y = max(0, int(region_height - self.tooltip_height))
            tooltip_y = min(max(0, tooltip_y), max_y)

            self.tooltip_panel.set_location(tooltip_x, tooltip_y)
            self.tooltip_panel.layout_widgets()
            # show bookmark button - always on mouse enter
            if widget.bookmark_button:
                widget.bookmark_button.visible = True

            # bpy.ops.wm.blenderkit_asset_popup('INVOKE_DEFAULT')

    def exit_button(self, widget):
        """Handle mouse exit from an asset button."""
        # this condition checks if there wasn't another button already entered, which can happen with small button gaps
        if self.active_index == widget.button_index + self.scroll_offset:
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.draw_tooltip = False
            self.draw_tooltip = False
            self.hide_tooltip()
            self.active_index = -1
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = self.active_index
            bpy.context.window.cursor_set("DEFAULT")
        # hide bookmark button - only when Not bookmarked
        # make sure to transfer some data, to prevent missing attribute
        widget.bookmark_button.asset_index = widget.button_index
        self.update_bookmark_icon(widget.bookmark_button)

    def bookmark_asset(self, widget):
        """Bookmark the asset linked to this button."""
        # bookmark the asset linked to this button
        if not utils.user_logged_in():
            bpy.ops.wm.blenderkit_login_dialog(
                "INVOKE_DEFAULT",
                message="Please login to bookmark your favorite assets.",
            )
            return

        sr = search.get_search_results()
        asset_data = sr[widget.asset_index]  # + self.scroll_offset]

        bpy.ops.wm.blenderkit_bookmark_asset(asset_id=asset_data["id"])
        self.update_bookmark_icon(widget)

    def drag_drop_asset(self, widget):
        """Start drag and drop operation for the asset linked to this button."""
        now = time.time()
        # avoid double click to download assets under panels, mainly category panel
        if now - ui_panels.last_time_overlay_panel_active < 0.5:
            return
        # start drag drop
        bpy.ops.view3d.asset_drag_drop(
            "INVOKE_DEFAULT",
            asset_search_index=widget.search_index + self.scroll_offset,
        )

    def cancel_press(self, widget):
        """Handle cancel/close button press."""
        self.finish()

    def toggle_expand(self, widget):
        """Toggle the expanded state of the assetbar."""
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        user_preferences.assetbar_expanded = not user_preferences.assetbar_expanded

        # Update the button icon
        self.update_expand_button_icon()

        # Restart the asset bar to apply the new layout
        self.restart_asset_bar()

    def handle_key_input(self, event):
        """Handle keyboard shortcuts for asset bar operations."""
        # Check if enough time has passed since last popup/text input activity
        # to prevent shortcuts from triggering while typing in text fields
        now = time.time()
        if now - ui_panels.last_time_overlay_panel_active < 0.5:
            return False

        # Shortcut: Toggle between normal, photo and wireframe thumbnail
        if event.type in {"ONE"}:
            if self.show_thumbnail_variant != "THUMBNAIL":
                self.show_thumbnail_variant = "THUMBNAIL"
                self.needs_tooltip_update = True
        if event.type in {"TWO"}:
            if self.show_thumbnail_variant != "PHOTO":
                self.show_thumbnail_variant = "PHOTO"
                self.needs_tooltip_update = True
        if event.type in {"THREE"}:
            if self.show_thumbnail_variant != "WIREFRAME":
                self.show_thumbnail_variant = "WIREFRAME"
                self.needs_tooltip_update = True
        if (
            event.type in {"LEFT_BRACKET", "RIGHT_BRACKET"}
            and not event.shift
            and self.active_index > -1
        ):
            # iterate index and update tooltip
            c_idx = 0
            was_thumbnail_variant = self.show_thumbnail_variant
            if self.show_thumbnail_variant in THUMBNAIL_TYPES:
                c_idx = THUMBNAIL_TYPES.index(self.show_thumbnail_variant)

            if event.type == "LEFT_BRACKET":
                c_idx -= 1
            elif event.type == "RIGHT_BRACKET":
                c_idx += 1
            # clamp index - no rollover
            c_idx = min(max(c_idx, 0), len(THUMBNAIL_TYPES) - 1)

            if was_thumbnail_variant == THUMBNAIL_TYPES[c_idx]:
                return True
            # else update
            self.show_thumbnail_variant = THUMBNAIL_TYPES[c_idx]
            self.needs_tooltip_update = True
            return True

        # Shortcut: Search by author
        if event.type == "A":
            self.search_by_author(self.active_index)
            return True

        # Shortcut: Delete asset from hard-drive
        if event.type == "X" and self.active_index > -1:
            # delete downloaded files for this asset
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bk_logger.info("deleting asset from local drive: %s", asset_data["name"])
            paths.delete_asset_debug(asset_data)
            asset_data["downloaded"] = 0
            return True

        # Shortcut: Open Author's personal Webpage
        if event.type == "W" and self.active_index > -1:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            author_id = int(asset_data["author"]["id"])
            author = global_vars.BKIT_AUTHORS.get(author_id)
            if author is None:
                bk_logger.warning("author is none")
                return True
            utils.p("author:", author)
            url = author.get("aboutMeUrl")
            if url is None:
                bk_logger.warning("url is none")
                return True
            bpy.ops.wm.url_open(url=url)
            return True

        # Shortcut: Search Similar
        if event.type == "S" and self.active_index > -1:
            self.search_similar(self.active_index)
            return True

        if event.type == "C" and self.active_index > -1:
            self.search_in_category(self.active_index)
            return True

        if event.type == "B" and self.active_index > -1:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.wm.blenderkit_bookmark_asset(asset_id=asset_data["id"])
            return True

        # Shortcut: Open Author's profile on BlenderKit
        if event.type == "P" and self.active_index > -1:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            author_id = int(asset_data["author"]["id"])
            author = global_vars.BKIT_AUTHORS.get(author_id)
            if author is None:
                return True
            utils.p("author:", author)
            url = paths.get_author_gallery_url(author.id)
            bpy.ops.wm.url_open(url=url)
            return True

        # FastRateMenu
        if event.type == "R" and self.active_index > -1 and not event.shift:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            if not utils.user_is_owner(asset_data=asset_data):
                bpy.ops.wm.blenderkit_menu_rating_upload(
                    asset_name=asset_data["name"],
                    asset_id=asset_data["id"],
                    asset_type=asset_data["assetType"],
                )
            return True

        if (
            event.type == "V"
            and event.shift
            and self.active_index > -1
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="validated"
            )
            return True

        if (
            event.type == "H"
            and event.shift
            and self.active_index > -1
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="on_hold"
            )
            return True

        if (
            event.type == "U"
            and event.shift
            and self.active_index > -1
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="uploaded"
            )
            return True

        if (
            event.type == "R"
            and event.shift
            and self.active_index > -1
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="rejected"
            )
            return True

        return False  # Let other shortcuts be handled

    def scroll_up(self, widget):
        """Scroll up in the asset bar."""
        self.scroll_offset += self.wcount * self.hcount
        self.scroll_update()
        self.enter_button(widget)

    def scroll_down(self, widget):
        """Scroll down in the asset bar."""
        self.scroll_offset -= self.wcount * self.hcount
        self.scroll_update()
        self.enter_button(widget)

    # endregion events

    # region actions

    def apply_term_filter(self, widget: BL_UI_Button, *, term: str):
        """Apply term filter based on the clicked bubble."""
        value = getattr(widget, f"{term}_name", "")
        if not value:
            self.clear_term_filter(widget, term=term)
            return

        label = getattr(widget, "text", value)
        # Mark data-driven filters so we can drop them when the asset type changes
        search.set_active_filter(term=term, value=value, label=label, origin="data")
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def clear_term_filter(self, widget: BL_UI_Button, *, term: str):
        """Remove term filter from the search keywords."""
        search.remove_active_filter(term=term)
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def _filter_out_term(self, term: str, keywords: str):
        """Remove term:* tokens using regex; return clean token list without extra +/spaces."""
        # strip term segments that may contain spaces until the next '+' or string end
        without_term = re.sub(
            rf"(?:^|\+)\s*{term}:[^+]+", "", keywords, flags=re.IGNORECASE
        )
        # normalize plus separators and drop empty pieces
        tokens = [part for part in without_term.replace(" ", "").split("+") if part]
        return tokens

    def remove_active_filter_chip(self, widget: BL_UI_Button):
        active_filter = getattr(widget, "active_filter", None)
        if not active_filter:
            return
        search.remove_active_filter(
            term=active_filter.get("term", ""), value=active_filter.get("value")
        )
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def asset_menu(self, widget):
        """Open the asset menu for the asset linked to this button."""
        self.hide_tooltip()
        bpy.ops.wm.blenderkit_asset_popup("INVOKE_DEFAULT")
        # bpy.ops.wm.call_menu(name='OBJECT_MT_blenderkit_asset_menu')

    def search_more(self):
        """Search for more assets."""
        history_step = search.get_active_history_step()
        sro = history_step.get("search_results_orig")
        if sro is None:
            return
        if sro.get("next") is None:
            return
        search_props = utils.get_search_props()
        active_history_step = search.get_active_history_step()
        if active_history_step.get("is_searching"):
            return

        search.search(get_next=True)

    def update_bookmark_icon(self, bookmark_button: BL_UI_Button):
        """Update the bookmark icon for a given bookmark button."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_index = bookmark_button.asset_index  # type: ignore
        # sometimes happened here that the asset_index was out of range
        if asset_index >= len(sr):
            return
        asset_data = sr[asset_index]
        rating = ratings_utils.get_rating_local(asset_data["id"])
        if rating is not None and rating.bookmarks == 1:
            icon = "bookmark_full.png"
            visible = True
        else:
            icon = "bookmark_empty.png"
            if self.active_index == bookmark_button.asset_index:  # type: ignore
                visible = True
            else:
                visible = False
        bookmark_button.visible = visible
        img_fp = paths.get_addon_thumbnail_path(icon)
        bookmark_button.set_image(img_fp)

    def update_progress_bar(self, asset_button, asset_data):
        """Update the progress bar for  each button in asset bar.
        Enabled addons are shown in green, disabled but installed in blue."""

        pb = asset_button.progress_bar
        if pb is None:
            return

        if asset_data["downloaded"] > 0:
            pb.bg_color = colors.GREEN
            # For addons, always show full bar when installed, with color based on enabled status
            if asset_data.get("assetType") == "addon":
                w = self.button_size  # Full width for installed addons
                is_enabled = asset_data.get("enabled", False)
                if not is_enabled:
                    # Pale blue for installed but disabled addons
                    pb.bg_color = colors.BLUE
            w = int(self.button_size * asset_data["downloaded"] / 100.0)
            pb.width = w
            pb.update(pb.x_screen, pb.y_screen)
            pb.visible = True
        else:
            pb.visible = False
            return

        self._safe_tag_redraw(bpy.context.region)

    def update_validation_icon(self, asset_button, asset_data: dict):
        """Update the validation icon for each button in asset bar."""
        if utils.profile_is_validator():
            rating = global_vars.RATINGS.get(asset_data["id"])
            v_icon = ui.verification_icons[
                asset_data.get("verificationStatus", "validated")
            ]
            if v_icon is not None:
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            elif rating is None or rating.quality is None:
                v_icon = "star_grey.png"
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            else:
                asset_button.validation_icon.visible = False
        else:
            if asset_data.get("canDownload", True) == 0:
                img_fp = paths.get_addon_thumbnail_path("locked.png")
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            else:
                asset_button.validation_icon.visible = False

    def update_image(self, asset_id):
        """should be run after thumbs are retrieved so they can be updated"""
        sr = search.get_search_results()
        if not sr:
            return
        for asset_button in self.asset_buttons:
            if asset_button.asset_index < len(sr):
                asset_data = sr[asset_button.asset_index]
                if asset_data["assetBaseId"] == asset_id:
                    set_thumb_check(
                        asset_button, asset_data, thumb_type="thumbnail_small"
                    )

    def update_buttons(self):
        """Update asset buttons in the asset bar based on current search results and scroll offset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results")
        if not sr:
            return
        visible_results = []

        # remember also position for manufacturer buttons

        for asset_button in self.asset_buttons:
            if asset_button.visible:
                asset_button.asset_index = (
                    asset_button.button_index + self.scroll_offset
                )
                if asset_button.asset_index < len(sr):
                    asset_button.visible = True

                    asset_data = sr[asset_button.asset_index]
                    if asset_data is None:
                        continue
                    # update bookmark buttons
                    asset_button.bookmark_button.asset_index = asset_button.asset_index

                    set_thumb_check(
                        asset_button, asset_data, thumb_type="thumbnail_small"
                    )
                    # asset_button.set_image(img_filepath)
                    self.update_validation_icon(asset_button, asset_data)

                    self.update_bookmark_icon(asset_button.bookmark_button)

                    self.update_progress_bar(asset_button, asset_data)

                    if (
                        utils.profile_is_validator()
                        and asset_data["verificationStatus"] == "uploaded"
                    ):
                        over_limit = utils.is_upload_old(
                            asset_data.get("lastBlendUpload")
                        )
                        if over_limit:
                            redness = min(over_limit * 0.05, 0.7)
                            asset_button.red_alert.bg_color = (1, 0, 0, redness)
                            asset_button.red_alert.visible = True
                        else:
                            asset_button.red_alert.visible = False
                    elif utils.profile_is_validator():
                        asset_button.red_alert.visible = False
                    visible_results.append(asset_data)

            else:
                asset_button.visible = False
                asset_button.validation_icon.visible = False
                asset_button.bookmark_button.visible = False
                asset_button.progress_bar.visible = False
                if utils.profile_is_validator():
                    asset_button.red_alert.visible = False

        # Refresh manufacturer chips to match currently visible assets
        self._update_manufacturer_data(visible_results)

    def scroll_update(self, always=False):
        """Update scroll position and visibility of scroll buttons."""
        self.hide_tooltip()
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results")
        sro = history_step.get("search_results_orig")
        # orig_offset = self.scroll_offset
        # empty results
        if sr is None:
            self.button_scroll_down.visible = False
            self.button_scroll_up.visible = False
            return

        self.scroll_offset = min(
            self.scroll_offset, len(sr) - (self.wcount * self.hcount)
        )
        self.scroll_offset = max(self.scroll_offset, 0)
        # only update if scroll offset actually changed, otherwise this is unnecessary

        if (
            sro["count"] > len(sr)
            and len(sr) - self.scroll_offset < (self.wcount * self.hcount) + 15
        ):
            self.search_more()

        if self.scroll_offset == 0:
            self.button_scroll_down.visible = False
        else:
            self.button_scroll_down.visible = True

        if self.scroll_offset >= sro["count"] - (self.wcount * self.hcount):
            self.button_scroll_up.visible = False
        else:
            self.button_scroll_up.visible = True

        # here we save some time by only updating the images if the scroll offset actually changed
        if self.last_scroll_offset == self.scroll_offset and not always:
            return
        self.last_scroll_offset = self.scroll_offset

        self.update_buttons()

    def search_by_author(self, asset_index):
        """Search for assets by the author of the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        a = asset_data["author"]["id"]
        if a is not None:
            sprops = utils.get_search_props()
            ui_props = bpy.context.window_manager.blenderkitUI
            # if there is already an author id in the search keywords, remove it first, the author_id can be any so
            # use regex to find it
            # for validators, set verification status to ALL
            if utils.profile_is_validator():
                sprops.search_verification_status = "ALL"
            ui_props.search_keywords = re.sub(
                r"\+author_id:\d+", "", ui_props.search_keywords
            )
            ui_props.search_keywords += f"+author_id:{a}"

            search.search()
        return True

    def search_similar(self, asset_index):
        """Search for similar assets to the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        keywords = search.get_search_similar_keywords(asset_data)
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_keywords = keywords
        search.search()

    def search_in_category(self, asset_index):
        """Search for assets in the same category as the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        category = asset_data.get("category")
        if category is None:
            return True
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_category = category
        search.search()

    # endregion actions

    # region main operations

    @classmethod
    def unregister(cls):
        """Unregister the asset bar operator and clean up instances."""
        bk_logger.debug("unregistering class %s", cls)
        instances_copy = cls.instances.copy()
        for instance in instances_copy:
            try:
                bk_logger.debug("- instance %s", instance)
            except ReferenceError:
                bk_logger.debug("- instance <deleted>")
            try:
                instance.unregister_handlers(instance.context)
            except Exception as e:
                bk_logger.debug("-- error unregister_handlers(): %s", e)
            try:
                instance.on_finish(instance.context)
            except Exception as e:
                bk_logger.debug("-- error calling on_finish(): %s", e)
            cls.instances.remove(instance)

    def restart_asset_bar(self):
        """Restart the asset bar UI."""
        ui_props = bpy.context.window_manager.blenderkitUI
        self.finish()
        w, a, r = utils.get_largest_area(area_type="VIEW_3D")
        if a is not None:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)

    # endregion main operations

    # region tab management

    def add_new_tab(self, widget):
        """Add a new tab when the + button is clicked."""
        tabs = global_vars.TABS["tabs"]
        new_tab = {
            "name": f"Tab {len(tabs) + 1}",  # Default name with incremented number
            "history": [],  # Empty history list
            "history_index": -1,  # No history yet
            "active_filters": [],
        }
        tabs.append(new_tab)

        # Get current history step to copy its state and results
        current_history_step = search.get_active_history_step()

        # Create history step for the new tab, copying the current UI state
        new_history_step = search.create_history_step(new_tab)

        # Copy search results from current history step if they exist
        if current_history_step.get("search_results"):
            new_history_step["search_results"] = current_history_step["search_results"]
            new_history_step["search_results_orig"] = current_history_step[
                "search_results_orig"
            ]
            new_history_step["is_searching"] = False

            # Update search results count to trigger UI refresh
            self.search_results_count = len(new_history_step["search_results"])
            # Force scroll update to show results
            self.scroll_update(always=True)

        new_active_tab = len(tabs) - 1
        self.switch_to_history_step(new_active_tab, 0)

        # Write history step to tab
        # Restart asset bar to show new tab
        self.restart_asset_bar()

    def remove_tab(self, widget):
        """Remove a tab when its close button is clicked."""
        tabs = global_vars.TABS["tabs"]

        # Don't remove the last tab
        if len(tabs) <= 1:
            return

        tab_index = widget.tab_index

        # If removing active tab, switch to previous tab
        if global_vars.TABS["active_tab"] == tab_index:
            global_vars.TABS["active_tab"] = max(0, tab_index - 1)
        # If removing tab before active tab, adjust active tab index
        elif global_vars.TABS["active_tab"] > tab_index:
            global_vars.TABS["active_tab"] -= 1

        # Remove the tab
        tabs.pop(tab_index)

        # Restart asset bar to update UI
        self.restart_asset_bar()

    def update_history_buttons_rounding(self):
        """Update the rounding of history navigation buttons based on their visibility."""
        if self.history_back_button.visible and self.history_forward_button.visible:
            self.history_back_button.background_corner_radius = (
                ROUNDING_RADIUS,
                0,
                0,
                0,
            )
            self.history_forward_button.background_corner_radius = (
                0,
                ROUNDING_RADIUS,
                0,
                0,
            )
        else:
            self.history_back_button.background_corner_radius = (
                ROUNDING_RADIUS,
                ROUNDING_RADIUS,
                0,
                0,
            )
            self.history_forward_button.background_corner_radius = (
                ROUNDING_RADIUS,
                ROUNDING_RADIUS,
                0,
                0,
            )

    def switch_to_history_step(self, tab_index, history_index):
        """Switch to a specific tab and history step."""
        # Update UI properties without triggering update callbacks
        ui_props = bpy.context.window_manager.blenderkitUI
        # lock the search
        ui_props.search_lock = True

        if (
            tab_index == global_vars.TABS["active_tab"]
            and history_index == global_vars.TABS["tabs"][tab_index]["history_index"]
        ):
            return  # Already on this tab and history step
        # make original tab original background color
        self.tab_buttons[global_vars.TABS["active_tab"]].bg_color = self.button_bg_color
        # make also tab close button original background color
        self.close_tab_buttons[global_vars.TABS["active_tab"]].bg_color = (
            self.button_bg_color
        )

        global_vars.TABS["active_tab"] = tab_index
        global_vars.TABS["tabs"][tab_index]["history_index"] = history_index

        # Get active history step of the selected tab
        history_step = search.get_active_history_step()
        ui_state = history_step["ui_state"]

        # Update UI properties
        for prop_name, value in ui_state["ui_props"].items():
            if hasattr(ui_props, prop_name):
                # strings need to be quoted
                if isinstance(value, str):
                    exec(f"ui_props.{prop_name} = '{value}'")
                else:
                    exec(f"ui_props.{prop_name} = {value}")

        # Update search type specific properties
        search_props = utils.get_search_props()
        for prop_name, value in ui_state["search_props"].items():
            if hasattr(search_props, prop_name):
                # strings need to be quoted
                if isinstance(value, str):
                    exec(f"search_props.{prop_name} = '{value}'")
                else:
                    exec(f"search_props.{prop_name} = {value}")

        # Restore active filter chips for this tab
        active_tab = global_vars.TABS["tabs"][tab_index]
        search.set_active_filters_for_tab(
            active_tab, ui_state.get("active_filters", [])
        )

        # update tab label
        # only if the button exists
        if len(self.tab_buttons) > tab_index:
            search.update_tab_name(global_vars.TABS["tabs"][tab_index])
        # Restore scroll position
        self.scroll_offset = history_step.get("scroll_offset", 0)

        # Update history button visibility
        self.history_back_button.visible = active_tab["history_index"] > 0
        self.history_forward_button.visible = (
            active_tab["history_index"] < len(active_tab["history"]) - 1
        )
        self.update_history_buttons_rounding()

        # Recalculate layout to reflect active filter chip changes on this history step
        self.update_ui_size(bpy.context)

        # set colors and rounding for tabs
        for tab_button in self.tab_buttons:
            c_tab_index = tab_button.tab_index
            if c_tab_index == tab_index:
                tab_button.bg_color = self.button_selected_color
                self.close_tab_buttons[tab_index].bg_color = (
                    self.button_selected_color_dim
                )

            else:
                tab_button.bg_color = self.button_bg_color
                self.close_tab_buttons[c_tab_index].bg_color = self.button_bg_color

        # update filters
        search.update_filters()
        # Update UI to show current tab's search results
        self.scroll_update(always=True)
        # Update tab icons to reflect the current asset type
        self.update_tab_icons()
        # unlock the search
        ui_props.search_lock = False

    def history_back(self, widget):
        """Navigate to previous history step."""
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        if active_tab["history_index"] > 0:
            self.switch_to_history_step(
                global_vars.TABS["active_tab"], active_tab["history_index"] - 1
            )

    def history_forward(self, widget):
        """Navigate to next history step."""
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        if active_tab["history_index"] < len(active_tab["history"]) - 1:
            self.switch_to_history_step(
                global_vars.TABS["active_tab"], active_tab["history_index"] + 1
            )

    def switch_tab(self, widget):
        """Switch to the clicked tab and restore its UI state."""
        self.switch_to_history_step(
            widget.tab_index,
            global_vars.TABS["tabs"][widget.tab_index]["history_index"],
        )

    # endregion tab management


def handle_bkclientjs_get_asset(task: search.client_tasks.Task):
    """Handle incoming bkclientjs/get_asset task after the user asked for download in online gallery. How it goes:
    1. set search in the history
    2. set the results in the history step
    3. open the asset bar
    We handle the task in asset_bar_op because we need access to the asset_bar_operator without circular import from search.
    """
    bk_logger.info("handle_bkclientjs_get_asset: %s", task.result["asset_data"]["name"])

    # Get asset data from task result
    asset_data = task.result.get("asset_data")
    if not asset_data:
        bk_logger.error("No asset data found in task")
        return

    # Parse the asset data
    parsed_asset_data = search.parse_result(asset_data)
    if not parsed_asset_data:
        bk_logger.error("Failed to parse asset data")
        return

    search.append_history_step(
        search_keywords=f"asset_base_id:{asset_data['assetBaseId']}",
        search_results=[parsed_asset_data],
        asset_type=asset_data.get("assetType", "").upper(),
        search_results_orig={"results": [asset_data], "count": 1},
    )

    # If asset bar is not open, try to open it
    if asset_bar_operator is None:
        try:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]
        except Exception as e:
            bk_logger.error("Failed to open asset bar: %s", e)
            return

    # Force redraw of the region if asset bar exists
    if asset_bar_operator and asset_bar_operator.area:
        search.load_preview(parsed_asset_data)
        asset_bar_operator.update_image(parsed_asset_data["assetBaseId"])
        asset_bar_operator.area.tag_redraw()


BlenderKitAssetBarOperator.modal = asset_bar_modal  # type: ignore[method-assign]
BlenderKitAssetBarOperator.invoke = asset_bar_invoke  # type: ignore[method-assign]


def register():
    bpy.utils.register_class(BlenderKitAssetBarOperator)


def unregister():
    bpy.utils.unregister_class(BlenderKitAssetBarOperator)
