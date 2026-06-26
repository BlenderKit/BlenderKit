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
from . import persistent_preferences
from .asset_bar import asset_bar_op


class TestAssetBarScrollUpdate(unittest.TestCase):
    def test_scroll_update_ignores_missing_search_results(self):
        dummy = SimpleNamespace(
            hide_tooltip=Mock(),
            button_scroll_down=SimpleNamespace(visible=True),
            button_scroll_up=SimpleNamespace(visible=True),
            _scroll_animating=False,
            scroll_phase=0.0,
            _update_grid_draw_offset=Mock(),
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
    def create_drag_panel(self, *, drag_enabled=False, is_drag=False):
        panel = SimpleNamespace(
            drag_enabled=drag_enabled,
            is_drag=is_drag,
            resize_enabled=False,
            resize_edges=set(),
            resize_handle_size=0,
            resize_threshold_px=0,
            is_resize=False,
            resize_press_active=False,
            resize_hover_edge=None,
            active_resize_edge=None,
            resize_start_x=0,
            resize_start_y=0,
            x_screen=0,
            y_screen=0,
            width=100,
            height=50,
            widgets=[],
            child_widget_focused=Mock(return_value=False),
            get_area_height=Mock(return_value=100),
            is_in_rect=Mock(return_value=True),
            update=Mock(),
            layout_widgets=Mock(),
        )
        panel._call_resize_callback = lambda callback_name, *args: (
            asset_bar_op.BL_UI_Drag_Panel._call_resize_callback(
                panel, callback_name, *args
            )
        )
        panel._resize_threshold_reached = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel._resize_threshold_reached(panel, x, y)
        )
        panel._edge_hit_test = (
            lambda x, y: asset_bar_op.BL_UI_Drag_Panel._edge_hit_test(panel, x, y)
        )
        panel._update_resize_hover = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel._update_resize_hover(panel, x, y)
        )
        return panel

    def test_drag_panel_mouse_down_ignored_when_drag_disabled(self):
        panel = self.create_drag_panel(drag_enabled=False)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 10, 10)

        self.assertFalse(handled)
        self.assertFalse(panel.is_drag)

    def test_drag_panel_mouse_move_ignored_when_drag_disabled(self):
        panel = self.create_drag_panel(drag_enabled=False, is_drag=True)

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 10, 10)

        panel.update.assert_not_called()
        panel.layout_widgets.assert_not_called()


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
            _resize_drag_start_rows=7,
            _resize_drag_start_y=55,
        )

        asset_bar_op.BlenderKitAssetBarOperator._reset_resize_state(dummy)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertFalse(dummy._resize_dragging)
        self.assertFalse(dummy._resize_cursor_modal_active)
        self.assertEqual(dummy._resize_drag_start_rows, 1)
        self.assertEqual(dummy._resize_drag_start_y, 0)

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

    def test_update_expand_button_icon_uses_up_arrow_when_expanded(self):
        preferences = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(button_expand=SimpleNamespace(text=""))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.update_expand_button_icon(dummy)

        self.assertEqual(dummy.button_expand.text, "▲")

    def test_update_expand_button_icon_uses_down_arrow_when_collapsed(self):
        preferences = SimpleNamespace(assetbar_expanded=False)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(button_expand=SimpleNamespace(text=""))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.update_expand_button_icon(dummy)

        self.assertEqual(dummy.button_expand.text, "▼")

    def test_update_assetbar_layout_positions_toggle_button_and_enables_resize_edge(
        self,
    ):
        dummy = SimpleNamespace(
            scroll_update=Mock(),
            position_and_hide_buttons=Mock(),
            update_buttons=Mock(),
            button_close=SimpleNamespace(set_location=Mock()),
            other_button_size=40,
            bar_width=320,
            wcount=1,
            resize_edge_height=10,
            bar_height=180,
            button_expand=SimpleNamespace(set_location=Mock(), visible=False),
            button_scroll_up=SimpleNamespace(set_location=Mock()),
            panel=SimpleNamespace(
                width=0,
                height=0,
                resize_enabled=False,
                resize_handle_size=0,
                set_location=Mock(),
            ),
            tab_area_bg=SimpleNamespace(width=0),
            bar_x=12,
            bar_y=34,
            position_manufacturer_buttons=Mock(),
        )

        with patch.object(
            asset_bar_op.search,
            "get_active_history_step",
            return_value={"search_results": [{"id": 1}, {"id": 2}]},
        ):
            asset_bar_op.BlenderKitAssetBarOperator.update_assetbar_layout(
                dummy, context=object()
            )

        dummy.scroll_update.assert_called_once_with(
            always=True,
            update_visible_buttons=False,
        )
        dummy.button_expand.set_location.assert_called_once_with(280, 180)
        self.assertTrue(dummy.button_expand.visible)
        self.assertTrue(dummy.panel.resize_enabled)
        self.assertEqual(dummy.panel.resize_handle_size, 10)

    def test_toggle_expand_delegates_to_toggle_assetbar_rows(self):
        dummy = SimpleNamespace(toggle_assetbar_rows=Mock())

        asset_bar_op.BlenderKitAssetBarOperator.toggle_expand(dummy, widget=object())

        dummy.toggle_assetbar_rows.assert_called_once_with()

    def test_begin_resize_drag_hides_tooltip_and_marks_dragging(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            hide_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.begin_resize_drag(dummy)

        self.assertTrue(dummy._resize_dragging)
        dummy.hide_tooltip.assert_called_once_with()

    def test_end_resize_drag_restores_cursor(self):
        dummy = SimpleNamespace(
            _resize_dragging=True,
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.end_resize_drag(dummy, hovering=False)

        self.assertFalse(dummy._resize_dragging)
        dummy.restore_resize_cursor.assert_called_once_with(hovering=False)

    def test_on_panel_resize_begin_captures_row_state_and_starts_drag(self):
        dummy = SimpleNamespace(
            _resize_drag_start_rows=1,
            _resize_drag_start_y=0,
            get_requested_assetbar_rows=Mock(return_value=4),
            begin_resize_drag=Mock(),
            set_resize_drag_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_begin(
            dummy,
            panel=object(),
            edge="bottom",
            start_x=20,
            start_y=140,
        )

        self.assertEqual(dummy._resize_drag_start_rows, 4)
        self.assertEqual(dummy._resize_drag_start_y, 140)
        dummy.begin_resize_drag.assert_called_once_with()
        dummy.set_resize_drag_cursor.assert_called_once_with()

    def test_on_panel_resize_update_previews_rows_from_panel_drag(self):
        dummy = SimpleNamespace(
            _get_resize_rows_from_mouse_y=Mock(return_value=6),
            preview_assetbar_rows=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_update(
            dummy,
            panel=object(),
            edge="bottom",
            x=20,
            y=110,
        )

        dummy._get_resize_rows_from_mouse_y.assert_called_once_with(110)
        dummy.preview_assetbar_rows.assert_called_once_with(6)

    def test_on_panel_resize_end_applies_rows_and_restores_cursor_state(self):
        dummy = SimpleNamespace(
            _get_resize_rows_from_mouse_y=Mock(return_value=5),
            apply_assetbar_rows=Mock(),
            end_resize_drag=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_end(
            dummy,
            panel=object(),
            edge="bottom",
            x=20,
            y=100,
            hovering=True,
        )

        dummy._get_resize_rows_from_mouse_y.assert_called_once_with(100)
        dummy.apply_assetbar_rows.assert_called_once_with(5)
        dummy.end_resize_drag.assert_called_once_with(hovering=True)

    def test_on_panel_resize_click_toggles_rows(self):
        dummy = SimpleNamespace(
            toggle_assetbar_rows=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_click(
            dummy,
            panel=object(),
            edge="bottom",
            x=20,
            y=110,
        )

        dummy.toggle_assetbar_rows.assert_called_once_with()
        dummy.restore_resize_cursor.assert_called_once_with(hovering=True)

    def test_preview_assetbar_rows_refreshes_layout_for_changed_rows(self):
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=6),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 9)

        self.assertEqual(dummy._requested_rows_override, 6)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy._redraw_tracked_regions.assert_called_once_with()

    def test_preview_assetbar_rows_skips_refresh_for_same_rows(self):
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=4),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(),
            _refresh_layout=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 4)

        self.assertIsNone(dummy._requested_rows_override)
        dummy._refresh_layout.assert_not_called()
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
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 7)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertTrue(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_expand_button_icon.assert_called_once_with()
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
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 1)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertFalse(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_expand_button_icon.assert_called_once_with()

    def test_apply_assetbar_rows_raises_collapsed_floor_to_two(self):
        # Collapsing while the saved expanded size is below two must bump the
        # remembered size up to two, so a later re-expand restores a usable bar
        # instead of a single row.
        preferences = SimpleNamespace(
            maximized_assetbar_rows=1,
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
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=1),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 1)

        self.assertEqual(preferences.maximized_assetbar_rows, 2)
        self.assertFalse(preferences.assetbar_expanded)

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
        widget = SimpleNamespace(
            button_index=2,
            bookmark_button=SimpleNamespace(asset_index=None),
            author_button=SimpleNamespace(asset_index=None),
        )
        dummy = SimpleNamespace(
            _resize_dragging=True,
            scroll_offset=0,
            active_index=2,
            draw_tooltip=True,
            hide_tooltip=Mock(),
            update_bookmark_icon=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.exit_button(dummy, widget)

        self.assertTrue(dummy.draw_tooltip)
        self.assertEqual(dummy.active_index, 2)
        dummy.hide_tooltip.assert_not_called()

    def test_clamp_assetbar_rows_bounds_to_height_limit(self):
        dummy = SimpleNamespace(_get_height_limited_rows=Mock(return_value=6))
        clamp = asset_bar_op.BlenderKitAssetBarOperator.clamp_assetbar_rows

        self.assertEqual(clamp(dummy, 10), 6)  # capped to the height limit
        self.assertEqual(clamp(dummy, 0), 1)  # never below one row
        self.assertEqual(clamp(dummy, 4), 4)  # passed through

    def test_get_expanded_assetbar_rows_clamps_saved_row_count(self):
        prefs = SimpleNamespace(maximized_assetbar_rows=5)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=prefs)}
                )
            )
        )
        dummy = SimpleNamespace(clamp_assetbar_rows=Mock(side_effect=lambda r: r))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_expanded_assetbar_rows(
                dummy
            )

        dummy.clamp_assetbar_rows.assert_called_once_with(5)
        self.assertEqual(rows, 5)

    def test_get_assetbar_rows_from_drag_converts_distance_to_rows(self):
        dummy = SimpleNamespace(
            button_size=50, clamp_assetbar_rows=Mock(side_effect=lambda r: r)
        )
        from_drag = asset_bar_op.BlenderKitAssetBarOperator.get_assetbar_rows_from_drag

        # drag the bottom edge down 100px (200 -> 100) at 50px/row => +2 rows
        self.assertEqual(from_drag(dummy, 3, 200, 100), 5)

    def test_get_assetbar_rows_from_drag_falls_back_without_button_size(self):
        dummy = SimpleNamespace(
            button_size=0, clamp_assetbar_rows=Mock(side_effect=lambda r: r)
        )
        from_drag = asset_bar_op.BlenderKitAssetBarOperator.get_assetbar_rows_from_drag

        self.assertEqual(from_drag(dummy, 3, 200, 100), 3)

    def test_get_resize_rows_from_mouse_y_uses_drag_start_state(self):
        dummy = SimpleNamespace(
            _resize_drag_start_rows=3,
            _resize_drag_start_y=200,
            get_assetbar_rows_from_drag=Mock(return_value=5),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator._get_resize_rows_from_mouse_y(
            dummy, 100
        )

        dummy.get_assetbar_rows_from_drag.assert_called_once_with(3, 200, 100)
        self.assertEqual(rows, 5)

    def test_get_requested_assetbar_rows_uses_live_override(self):
        dummy = SimpleNamespace(
            _requested_rows_override=4, clamp_assetbar_rows=Mock(return_value=4)
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
            dummy
        )

        dummy.clamp_assetbar_rows.assert_called_once_with(4)
        self.assertEqual(rows, 4)

    def test_get_requested_assetbar_rows_expands_when_expanded(self):
        prefs = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=prefs)}
                )
            )
        )
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            get_expanded_assetbar_rows=Mock(return_value=6),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
                dummy
            )

        dummy.get_expanded_assetbar_rows.assert_called_once_with()
        self.assertEqual(rows, 6)

    def test_on_panel_resize_hover_sets_cursor_on_bottom(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_hover(
            dummy, None, "bottom", True
        )

        dummy.set_resize_hover_cursor.assert_called_once_with()
        dummy.restore_resize_cursor.assert_not_called()

    def test_on_panel_resize_hover_restores_cursor_when_leaving(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_hover(
            dummy, None, "bottom", False
        )

        dummy.restore_resize_cursor.assert_called_once_with()
        dummy.set_resize_hover_cursor.assert_not_called()

    def test_on_panel_resize_hover_ignores_non_bottom_edge(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_panel_resize_hover(
            dummy, None, "top", True
        )

        dummy.set_resize_hover_cursor.assert_not_called()
        dummy.restore_resize_cursor.assert_not_called()

    def test_on_panel_resize_callbacks_ignore_non_bottom_edge(self):
        dummy = SimpleNamespace(
            begin_resize_drag=Mock(),
            set_resize_drag_cursor=Mock(),
            preview_assetbar_rows=Mock(),
            apply_assetbar_rows=Mock(),
            end_resize_drag=Mock(),
            toggle_assetbar_rows=Mock(),
            restore_resize_cursor=Mock(),
            _get_resize_rows_from_mouse_y=Mock(),
            get_requested_assetbar_rows=Mock(),
        )
        op = asset_bar_op.BlenderKitAssetBarOperator

        op.on_panel_resize_begin(dummy, None, "left", 0, 0)
        op.on_panel_resize_update(dummy, None, "left", 0, 0)
        op.on_panel_resize_end(dummy, None, "left", 0, 0, False)
        op.on_panel_resize_click(dummy, None, "left", 0, 0)

        dummy.begin_resize_drag.assert_not_called()
        dummy.preview_assetbar_rows.assert_not_called()
        dummy.apply_assetbar_rows.assert_not_called()
        dummy.toggle_assetbar_rows.assert_not_called()

    def test_restore_resize_cursor_sets_default_when_not_hovering(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=False,
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.restore_resize_cursor(dummy)

        window.cursor_modal_restore.assert_not_called()
        window.cursor_set.assert_called_once_with("DEFAULT")

    def test_resize_cursor_helpers_noop_without_window(self):
        dummy = SimpleNamespace(
            _resize_dragging=False, _cursor_window=Mock(return_value=None)
        )
        op = asset_bar_op.BlenderKitAssetBarOperator

        # None window must short-circuit each cursor helper without raising.
        op.set_resize_hover_cursor(dummy)
        op.set_resize_drag_cursor(dummy)
        op.restore_resize_cursor(dummy)

        self.assertEqual(dummy._cursor_window.call_count, 3)

    def test_event_window_coords_returns_mouse_position(self):
        event = SimpleNamespace(mouse_x=12, mouse_y=34)

        coords = asset_bar_op.BlenderKitAssetBarOperator._event_window_coords(
            None, event
        )

        self.assertEqual(coords, (12, 34))

    def test_event_window_coords_none_without_mouse_attrs(self):
        coords = asset_bar_op.BlenderKitAssetBarOperator._event_window_coords(
            None, SimpleNamespace()
        )

        self.assertEqual(coords, (None, None))


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


class TestDragPanelResize(unittest.TestCase):
    def create_panel(self):
        panel = SimpleNamespace(
            drag_enabled=False,
            is_drag=False,
            resize_enabled=True,
            resize_edges={"bottom"},
            resize_handle_size=6,
            resize_threshold_px=5,
            is_resize=False,
            resize_press_active=False,
            resize_hover_edge=None,
            active_resize_edge=None,
            resize_start_x=0,
            resize_start_y=0,
            x_screen=10,
            y_screen=40,
            width=100,
            height=50,
            widgets=[],
            child_widget_focused=Mock(return_value=False),
            get_area_height=Mock(return_value=200),
            is_in_rect=Mock(return_value=False),
            update=Mock(),
            layout_widgets=Mock(),
            on_resize_begin=Mock(),
            on_resize_update=Mock(),
            on_resize_end=Mock(),
            on_resize_click=Mock(),
            on_resize_hover=Mock(),
        )
        panel._call_resize_callback = lambda callback_name, *args: (
            asset_bar_op.BL_UI_Drag_Panel._call_resize_callback(
                panel, callback_name, *args
            )
        )
        panel._resize_threshold_reached = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel._resize_threshold_reached(panel, x, y)
        )
        panel._edge_hit_test = (
            lambda x, y: asset_bar_op.BL_UI_Drag_Panel._edge_hit_test(panel, x, y)
        )
        panel._update_resize_hover = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel._update_resize_hover(panel, x, y)
        )
        return panel

    def test_edge_hit_test_detects_bottom_resize_strip(self):
        panel = self.create_panel()

        edge = panel._edge_hit_test(40, 108)

        self.assertEqual(edge, "bottom")

    def test_edge_hit_test_ignores_offscreen_buffer_grid_widget(self):
        # Smooth-scroll positions buffer asset thumbnails (grid widgets) just
        # below the visible bar for scroll animation. They are clipped, but
        # report is_in_rect True in the bottom resize strip. They must NOT count
        # as a focused child, otherwise the edge resize stops working once the
        # bar has buffer rows below it (regression: worked once, then dead).
        panel = self.create_panel()
        buffer_thumb = SimpleNamespace(
            _is_grid_widget=True, is_in_rect=lambda x, y: True
        )
        panel.widgets = [buffer_thumb]
        panel.child_widget_focused = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel.child_widget_focused(panel, x, y)
        )

        edge = panel._edge_hit_test(40, 108)

        self.assertEqual(edge, "bottom")

    def test_edge_hit_test_blocked_by_real_child_widget(self):
        # A genuine (non-grid) child under the cursor - e.g. the expand button -
        # must still suppress edge resize so its click is not hijacked.
        panel = self.create_panel()
        real_child = SimpleNamespace(is_in_rect=lambda x, y: True)
        panel.widgets = [real_child]
        panel.child_widget_focused = lambda x, y: (
            asset_bar_op.BL_UI_Drag_Panel.child_widget_focused(panel, x, y)
        )

        edge = panel._edge_hit_test(40, 108)

        self.assertIsNone(edge)

    def test_mouse_move_updates_resize_hover_state(self):
        panel = self.create_panel()

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 108)
        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 90)

        panel.on_resize_hover.assert_any_call(panel, "bottom", True)
        panel.on_resize_hover.assert_any_call(panel, "bottom", False)

    def test_mouse_down_starts_resize_press_on_bottom_edge(self):
        panel = self.create_panel()

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 40, 108)

        self.assertTrue(handled)
        self.assertTrue(panel.resize_press_active)
        self.assertEqual(panel.active_resize_edge, "bottom")
        self.assertEqual(panel.resize_start_y, 108)

    def test_mouse_move_starts_resize_after_threshold(self):
        panel = self.create_panel()
        asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 40, 108)

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 100)

        self.assertTrue(panel.is_resize)
        panel.on_resize_begin.assert_called_once_with(panel, "bottom", 40, 108)
        panel.on_resize_update.assert_called_once_with(panel, "bottom", 40, 100)

    def test_mouse_up_click_on_resize_edge_triggers_click_callback(self):
        panel = self.create_panel()
        asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 40, 108)

        asset_bar_op.BL_UI_Drag_Panel.mouse_up(panel, 40, 108)

        panel.on_resize_click.assert_called_once_with(panel, "bottom", 40, 108)
        panel.on_resize_end.assert_not_called()
        self.assertFalse(panel.resize_press_active)

    def test_mouse_up_after_resize_triggers_commit_callback(self):
        panel = self.create_panel()
        asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 40, 108)
        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 100)

        asset_bar_op.BL_UI_Drag_Panel.mouse_up(panel, 40, 108)

        panel.on_resize_end.assert_called_once_with(panel, "bottom", 40, 108, True)
        panel.on_resize_click.assert_not_called()
        self.assertFalse(panel.is_resize)

    def test_edge_hit_test_detects_top_resize_strip(self):
        panel = self.create_panel()
        panel.resize_edges = {"top"}

        self.assertEqual(panel._edge_hit_test(40, 162), "top")

    def test_edge_hit_test_detects_left_resize_strip(self):
        panel = self.create_panel()
        panel.resize_edges = {"left"}

        self.assertEqual(panel._edge_hit_test(7, 130), "left")

    def test_edge_hit_test_detects_right_resize_strip(self):
        panel = self.create_panel()
        panel.resize_edges = {"right"}

        self.assertEqual(panel._edge_hit_test(113, 130), "right")

    def test_mouse_move_continues_resize_after_it_started(self):
        panel = self.create_panel()
        asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 40, 108)
        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 100)  # crosses threshold

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 40, 95)  # keep resizing

        self.assertEqual(panel.on_resize_update.call_count, 2)
        panel.on_resize_update.assert_called_with(panel, "bottom", 40, 95)

    def test_child_widget_focused_ignores_widget_not_under_cursor(self):
        panel = self.create_panel()
        elsewhere = SimpleNamespace(is_in_rect=lambda x, y: False)
        panel.widgets = [elsewhere]

        focused = asset_bar_op.BL_UI_Drag_Panel.child_widget_focused(panel, 40, 40)

        self.assertFalse(focused)

    def test_mouse_down_starts_panel_drag_when_enabled(self):
        panel = self.create_panel()
        panel.drag_enabled = True
        panel.resize_enabled = False  # no resize edge in the way
        panel.is_in_rect = Mock(return_value=True)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 50, 130)

        self.assertTrue(handled)
        self.assertTrue(panel.is_drag)

    def test_mouse_down_ignored_outside_panel_when_drag_enabled(self):
        panel = self.create_panel()
        panel.drag_enabled = True
        panel.resize_enabled = False
        panel.is_in_rect = Mock(return_value=False)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 50, 130)

        self.assertFalse(handled)
        self.assertFalse(panel.is_drag)

    def test_mouse_move_drags_panel_when_dragging(self):
        panel = self.create_panel()
        panel.drag_enabled = True
        panel.is_drag = True

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 60, 70)

        panel.update.assert_called_once()
        panel.layout_widgets.assert_called_once()


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
