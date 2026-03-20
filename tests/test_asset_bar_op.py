# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
# #
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# #
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
# #
# ##### END GPL LICENSE BLOCK #####

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
from . import asset_bar_op, persistent_preferences


class TestAssetBarScrollUpdate(unittest.TestCase):
    def test_scroll_update_ignores_missing_search_results(self):
        dummy = SimpleNamespace(
            hide_tooltip=Mock(),
            button_scroll_down=SimpleNamespace(visible=True),
            button_scroll_up=SimpleNamespace(visible=True),
        )

        with patch.object(
            asset_bar_op.search,
            "get_active_history_step",
            return_value={"search_results": None, "search_results_orig": None},
        ):
            asset_bar_op.BlenderKitAssetBarOperator.scroll_update(dummy, always=True)

        dummy.hide_tooltip.assert_called_once_with()
        self.assertFalse(dummy.button_scroll_down.visible)
        self.assertFalse(dummy.button_scroll_up.visible)


class TestAssetBarPositioning(unittest.TestCase):
    def test_positioning_clears_stale_validation_icons(self):
        validation_icon = SimpleNamespace(visible=True, set_location=Mock())
        bookmark_button = SimpleNamespace(visible=True, set_location=Mock())
        progress_bar = SimpleNamespace(visible=True, set_location=Mock())
        author_button = SimpleNamespace(visible=True, set_location=Mock())
        asset_button = SimpleNamespace(
            visible=False,
            button_index=0,
            validation_icon=validation_icon,
            bookmark_button=bookmark_button,
            progress_bar=progress_bar,
            author_button=author_button,
            red_alert=SimpleNamespace(visible=True, set_location=Mock()),
            set_location=Mock(),
        )
        dummy = SimpleNamespace(
            assetbar_margin=0,
            button_size=100,
            wcount=1,
            hcount=1,
            scroll_offset=0,
            asset_buttons=[asset_button],
            icon_size=24,
            button_margin=0,
            validation_icon_margin=0,
            button_scroll_down=SimpleNamespace(height=0, set_image_position=Mock()),
            button_scroll_up=SimpleNamespace(height=0, set_image_position=Mock()),
            bar_height=100,
            position_active_filter_buttons=Mock(),
            clear_button_overlays=lambda button: asset_bar_op.BlenderKitAssetBarOperator.clear_button_overlays(
                dummy, button
            ),
        )

        with (
            patch.object(
                asset_bar_op.search,
                "get_search_results",
                return_value=[{"id": "mat-1"}],
            ),
            patch.object(
                asset_bar_op.utils, "profile_is_validator", return_value=False
            ),
        ):
            asset_bar_op.BlenderKitAssetBarOperator.position_and_hide_buttons(dummy)

        self.assertTrue(asset_button.visible)
        self.assertFalse(validation_icon.visible)
        self.assertFalse(bookmark_button.visible)
        self.assertFalse(progress_bar.visible)


class TestAssetBarInvoke(unittest.TestCase):
    def test_initial_search_is_marked_before_layout_init(self):
        history_step = {}
        ui_props = SimpleNamespace(assetbar_on=False, turn_off=False)
        context = SimpleNamespace(
            area=SimpleNamespace(),
            window_manager=SimpleNamespace(blenderkitUI=ui_props),
            window=SimpleNamespace(),
        )
        dummy = SimpleNamespace(
            instances=[],
            keep_running=True,
            bar_x=10,
            bar_y=20,
            panel=SimpleNamespace(set_location=Mock()),
            on_init=Mock(),
            check_new_search_results=Mock(),
            setup_widgets=Mock(),
            set_element_images=Mock(),
            position_and_hide_buttons=Mock(),
            hide_tooltip=Mock(),
            scroll_update=Mock(),
            _save_and_hide_overlays=Mock(),
        )

        with (
            patch.object(asset_bar_op.search, "get_search_results", return_value=None),
            patch.object(
                asset_bar_op.search,
                "get_active_history_step",
                return_value=history_step,
            ),
            patch.object(asset_bar_op.search, "search") as mocked_search,
        ):
            result = asset_bar_op.BlenderKitAssetBarOperator.on_invoke(
                dummy, context, object()
            )

        self.assertTrue(result)
        self.assertTrue(history_step["is_searching"])
        mocked_search.assert_called_once_with()
        dummy.on_init.assert_called_once_with(context)


class TestAssetBarResizeHelpers(unittest.TestCase):
    def test_reset_resize_state_clears_resize_tracking(self):
        dummy = SimpleNamespace(
            _requested_rows_override=4,
            _resize_dragging=True,
            _resize_cursor_modal_active=True,
            _active_resize_handle=object(),
        )

        asset_bar_op.BlenderKitAssetBarOperator._reset_resize_state(dummy)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertFalse(dummy._resize_dragging)
        self.assertFalse(dummy._resize_cursor_modal_active)
        self.assertIsNone(dummy._active_resize_handle)

    def test_set_resize_hover_cursor_updates_cursor_when_not_dragging(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_hover_cursor(dummy)

        window.cursor_set.assert_called_once_with(asset_bar_op.ASSETBAR_RESIZE_CURSOR)

    def test_set_resize_hover_cursor_ignores_dragging(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_dragging=True,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_hover_cursor(dummy)

        window.cursor_set.assert_not_called()

    def test_set_resize_drag_cursor_enables_modal_cursor(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_drag_cursor(dummy)

        window.cursor_modal_set.assert_called_once_with(
            asset_bar_op.ASSETBAR_RESIZE_CURSOR
        )
        self.assertTrue(dummy._resize_cursor_modal_active)

    def test_restore_resize_cursor_restores_modal_cursor(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=True,
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.restore_resize_cursor(
            dummy, hovering=True
        )

        window.cursor_modal_restore.assert_called_once_with()
        window.cursor_set.assert_called_once_with(asset_bar_op.ASSETBAR_RESIZE_CURSOR)
        self.assertFalse(dummy._resize_cursor_modal_active)

    def test_update_assetbar_layout_positions_resize_edge_strip(self):
        dummy = SimpleNamespace(
            scroll_update=Mock(),
            position_and_hide_buttons=Mock(),
            update_buttons=Mock(),
            button_close=SimpleNamespace(set_location=Mock()),
            other_button_size=40,
            bar_width=320,
            button_resize_edge=SimpleNamespace(width=0, set_location=Mock()),
            bar_height=180,
            button_resize=SimpleNamespace(set_location=Mock()),
            resize_handle_width=40,
            button_scroll_up=SimpleNamespace(set_location=Mock()),
            panel=SimpleNamespace(width=0, height=0, set_location=Mock()),
            tab_area_bg=SimpleNamespace(width=0),
            bar_x=12,
            bar_y=34,
            position_manufacturer_buttons=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.update_assetbar_layout(
            dummy, context=object()
        )

        dummy.scroll_update.assert_called_once_with(
            always=True,
            update_visible_buttons=False,
        )
        self.assertEqual(dummy.button_resize_edge.width, 320)
        dummy.button_resize_edge.set_location.assert_called_once_with(0, 180)
        dummy.button_resize.set_location.assert_called_once_with(280, 180)

    def test_begin_resize_drag_tracks_active_handle_and_hides_tooltip(self):
        handle = object()
        dummy = SimpleNamespace(
            _active_resize_handle=None,
            _resize_dragging=False,
            hide_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.begin_resize_drag(
            dummy, active_handle=handle
        )

        self.assertIs(dummy._active_resize_handle, handle)
        self.assertTrue(dummy._resize_dragging)
        dummy.hide_tooltip.assert_called_once_with()

    def test_end_resize_drag_clears_active_handle_and_restores_cursor(self):
        dummy = SimpleNamespace(
            _active_resize_handle=object(),
            _resize_dragging=True,
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.end_resize_drag(dummy, hovering=False)

        self.assertIsNone(dummy._active_resize_handle)
        self.assertFalse(dummy._resize_dragging)
        dummy.restore_resize_cursor.assert_called_once_with(hovering=False)

    def test_preview_assetbar_rows_refreshes_layout_for_changed_rows(self):
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=6),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_resize_handle_labels=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 9)

        self.assertEqual(dummy._requested_rows_override, 6)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_resize_handle_labels.assert_called_once_with()
        dummy._redraw_tracked_regions.assert_called_once_with()

    def test_preview_assetbar_rows_skips_refresh_for_same_rows(self):
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=4),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(),
            _refresh_layout=Mock(),
            update_resize_handle_labels=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 4)

        self.assertIsNone(dummy._requested_rows_override)
        dummy._refresh_layout.assert_not_called()
        dummy.update_resize_handle_labels.assert_not_called()
        dummy._redraw_tracked_regions.assert_not_called()

    def test_apply_assetbar_rows_updates_preferences_and_refreshes_layout(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=2,
            assetbar_expanded=False,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=9,
            clamp_assetbar_rows=Mock(return_value=5),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_resize_handle_labels=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 7)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertTrue(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_resize_handle_labels.assert_called_once_with()
        dummy._redraw_tracked_regions.assert_called_once_with()

    def test_apply_assetbar_rows_keeps_expanded_rows_when_collapsing(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=5,
            assetbar_expanded=True,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=3,
            clamp_assetbar_rows=Mock(return_value=1),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_resize_handle_labels=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 1)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertFalse(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)

    def test_get_requested_assetbar_rows_returns_one_when_collapsed(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=6,
            assetbar_expanded=False,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(side_effect=lambda rows: rows),
            get_expanded_assetbar_rows=Mock(return_value=6),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
                dummy
            )

        self.assertEqual(rows, 1)
        dummy.get_expanded_assetbar_rows.assert_not_called()

    def test_toggle_assetbar_rows_collapses_when_expanded(self):
        preferences = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            apply_assetbar_rows=Mock(),
            get_expanded_assetbar_rows=Mock(return_value=4),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.toggle_assetbar_rows(dummy)

        dummy.apply_assetbar_rows.assert_called_once_with(1)

    def test_toggle_assetbar_rows_expands_to_saved_rows_when_collapsed(self):
        preferences = SimpleNamespace(assetbar_expanded=False)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            apply_assetbar_rows=Mock(),
            get_expanded_assetbar_rows=Mock(return_value=4),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.toggle_assetbar_rows(dummy)

        dummy.apply_assetbar_rows.assert_called_once_with(4)

    def test_enter_button_ignores_tooltip_updates_while_resizing(self):
        widget = SimpleNamespace(button_index=0)
        dummy = SimpleNamespace(
            _resize_dragging=True,
            scroll_offset=0,
            search_results_count=10,
            active_index=-1,
            show_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.enter_button(dummy, widget)

        self.assertEqual(dummy.active_index, -1)
        dummy.show_tooltip.assert_not_called()

    def test_exit_button_ignores_tooltip_cleanup_while_resizing(self):
        widget = SimpleNamespace(button_index=2)
        dummy = SimpleNamespace(
            _resize_dragging=True,
            scroll_offset=0,
            active_index=2,
            draw_tooltip=True,
            hide_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.exit_button(dummy, widget)

        self.assertTrue(dummy.draw_tooltip)
        self.assertEqual(dummy.active_index, 2)
        dummy.hide_tooltip.assert_not_called()


class TestPersistentPreferencesCompatibility(unittest.TestCase):
    def test_uses_json_assetbar_expanded_when_present(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=True,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=True),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"assetbar_expanded": False, "maximized_assetbar_rows": 4},
            user_preferences,
        )

        self.assertFalse(expanded)

    def test_uses_blender_property_when_json_key_is_missing(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=False,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=True),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"maximized_assetbar_rows": 4},
            user_preferences,
        )

        self.assertFalse(expanded)

    def test_falls_back_to_saved_row_count_when_property_was_not_persisted(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=True,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=False),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"maximized_assetbar_rows": 1},
            user_preferences,
        )

        self.assertFalse(expanded)


class TestAssetBarResizeHandle(unittest.TestCase):
    @staticmethod
    def _fake_button_init(widget, x, y, width, height):
        widget.x = x
        widget.y = y
        widget.x_screen = x
        widget.y_screen = y
        widget.width = width
        widget.height = height
        widget.context = None
        widget._text = ""
        widget._BL_UI_Button__state = 0

    def create_handle(self, **kwargs):
        operator = SimpleNamespace(
            get_requested_assetbar_rows=Mock(return_value=4),
            begin_resize_drag=Mock(),
            set_resize_drag_cursor=Mock(),
            preview_assetbar_rows=Mock(),
            apply_assetbar_rows=Mock(),
            toggle_assetbar_rows=Mock(),
            end_resize_drag=Mock(),
            get_assetbar_rows_from_drag=Mock(return_value=7),
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )
        with patch.object(
            asset_bar_op.BL_UI_Button,
            "__init__",
            new=self._fake_button_init,
        ):
            handle = asset_bar_op.AssetBarResizeHandle(
                10,
                20,
                30,
                40,
                operator,
                **kwargs,
            )
        handle.context = SimpleNamespace(
            area=SimpleNamespace(height=200),
            region=SimpleNamespace(x=0, y=0, height=200),
        )
        return handle, operator

    def test_default_text_is_hidden_for_edge_handle(self):
        handle, _operator = self.create_handle(show_label=False)

        self.assertEqual(handle._default_text(), "")

    def test_draw_text_skips_hidden_edge_handle_label(self):
        handle, _operator = self.create_handle(show_label=False)

        with patch.object(asset_bar_op.BL_UI_Button, "draw_text") as draw_text:
            handle.draw_text(area_height=200)

        draw_text.assert_not_called()

    def test_draw_text_uses_button_label_when_visible(self):
        handle, _operator = self.create_handle()

        with patch.object(asset_bar_op.BL_UI_Button, "draw_text") as draw_text:
            handle.draw_text(area_height=200)

        draw_text.assert_called_once_with(200)

    def test_mouse_down_starts_press_and_sets_initial_state(self):
        handle, operator = self.create_handle()

        result = handle.mouse_down(20, 160)

        self.assertTrue(result)
        self.assertTrue(handle._press_active)
        self.assertFalse(handle._drag_active)
        self.assertEqual(handle._drag_start_y, 160)
        self.assertEqual(handle._drag_start_rows, 4)
        operator.begin_resize_drag.assert_not_called()
        operator.set_resize_drag_cursor.assert_not_called()

    def test_handle_event_starts_drag_after_move_threshold(self):
        handle, operator = self.create_handle()
        handle.mouse_down(20, 160)
        handle._to_widget_region_coords = Mock(return_value=(20, 150))
        operator.get_assetbar_rows_from_drag.return_value = 6
        event = SimpleNamespace(type="MOUSEMOVE")

        result = handle.handle_event(event)

        self.assertTrue(result)
        self.assertTrue(handle._drag_active)
        operator.begin_resize_drag.assert_called_once_with(active_handle=handle)
        operator.set_resize_drag_cursor.assert_called_once_with()
        operator.preview_assetbar_rows.assert_called_once_with(6)

    def test_mouse_move_previews_rows_while_dragging(self):
        handle, operator = self.create_handle()
        handle._press_active = True
        handle._drag_active = True
        handle._drag_start_y = 160
        handle._drag_start_rows = 4
        operator.get_assetbar_rows_from_drag.return_value = 6

        handle.mouse_move(20, 120)

        operator.get_assetbar_rows_from_drag.assert_called_once_with(4, 160, 120)
        operator.preview_assetbar_rows.assert_called_once_with(6)

    def test_mouse_up_click_inside_toggles_rows_without_dragging(self):
        handle, operator = self.create_handle()
        handle.mouse_down(20, 160)

        handle.mouse_up(20, 160)

        self.assertFalse(handle._press_active)
        self.assertFalse(handle._drag_active)
        operator.toggle_assetbar_rows.assert_called_once_with()
        operator.restore_resize_cursor.assert_called_once_with(hovering=True)
        operator.apply_assetbar_rows.assert_not_called()

    def test_mouse_up_click_inside_on_edge_handle_does_not_toggle_rows(self):
        handle, operator = self.create_handle(
            show_label=False,
            click_to_toggle=False,
        )
        handle.mouse_down(20, 160)

        handle.mouse_up(20, 160)

        operator.toggle_assetbar_rows.assert_not_called()
        operator.restore_resize_cursor.assert_called_once_with(hovering=True)
        operator.apply_assetbar_rows.assert_not_called()

    def test_mouse_up_inside_applies_rows_and_keeps_hover_cursor(self):
        handle, operator = self.create_handle()
        handle._press_active = True
        handle._drag_active = True
        handle._drag_start_y = 160
        handle._drag_start_rows = 4
        operator.get_assetbar_rows_from_drag.return_value = 5

        handle.mouse_up(20, 160)

        self.assertFalse(handle._drag_active)
        operator.apply_assetbar_rows.assert_called_once_with(5)
        operator.end_resize_drag.assert_called_once_with(hovering=True)

    def test_mouse_up_outside_applies_rows_and_restores_default_cursor(self):
        handle, operator = self.create_handle()
        handle._press_active = True
        handle._drag_active = True
        handle._drag_start_y = 160
        handle._drag_start_rows = 4
        operator.get_assetbar_rows_from_drag.return_value = 3

        handle.mouse_up(0, 0)

        self.assertFalse(handle._drag_active)
        operator.apply_assetbar_rows.assert_called_once_with(3)
        operator.end_resize_drag.assert_called_once_with(hovering=False)

    def test_handle_event_routes_drag_mousemove(self):
        handle, _operator = self.create_handle()
        handle._press_active = True
        handle._drag_active = True
        handle._to_widget_region_coords = Mock(return_value=(20, 120))
        handle.mouse_move = Mock()
        event = SimpleNamespace(type="MOUSEMOVE")

        result = handle.handle_event(event)

        self.assertTrue(result)
        handle.mouse_move.assert_called_once_with(20, 120)

    def test_handle_event_routes_drag_release(self):
        handle, _operator = self.create_handle()
        handle._press_active = True
        handle._drag_active = True
        handle._to_widget_region_coords = Mock(return_value=(20, 120))
        handle.mouse_up = Mock()
        event = SimpleNamespace(type="LEFTMOUSE", value="RELEASE")

        result = handle.handle_event(event)

        self.assertTrue(result)
        handle.mouse_up.assert_called_once_with(20, 120)


class TestAssetBarRowLimit(unittest.TestCase):
    def test_row_limit_is_based_on_visible_asset_cap(self):
        dummy = SimpleNamespace(wcount=10)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, 20)

    def test_row_limit_scales_with_narrow_layout(self):
        dummy = SimpleNamespace(wcount=4)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, 50)

    def test_row_limit_falls_back_when_wcount_is_zero(self):
        dummy = SimpleNamespace(wcount=0)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, asset_bar_op.ASSETBAR_MAX_VISIBLE_ASSETS)


class TestAssetBarRowCount(unittest.TestCase):
    def test_keeps_saved_rows_with_no_results_while_search_is_running(self):
        dummy = SimpleNamespace(
            wcount=8,
            get_requested_assetbar_rows=Mock(return_value=4),
            _get_height_limited_rows=Mock(return_value=6),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator.get_target_row_count(
            dummy,
            search_results=None,
            is_searching=True,
            context=object(),
        )

        self.assertEqual(rows, 4)

    def test_keeps_saved_rows_while_search_is_running(self):
        dummy = SimpleNamespace(
            wcount=8,
            get_requested_assetbar_rows=Mock(return_value=4),
            _get_height_limited_rows=Mock(return_value=6),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator.get_target_row_count(
            dummy,
            search_results=[{"id": 1}],
            is_searching=True,
            context=object(),
        )

        self.assertEqual(rows, 4)

    def test_uses_total_result_count_after_first_page_arrives(self):
        dummy = SimpleNamespace(
            wcount=8,
            get_requested_assetbar_rows=Mock(return_value=4),
            _get_height_limited_rows=Mock(return_value=6),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator.get_target_row_count(
            dummy,
            search_results=[{"id": idx} for idx in range(10)],
            total_result_count=1000,
            is_searching=False,
            context=object(),
        )

        self.assertEqual(rows, 4)
