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
from . import asset_bar_op


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
        asset_button = SimpleNamespace(
            visible=False,
            button_index=0,
            validation_icon=validation_icon,
            bookmark_button=bookmark_button,
            progress_bar=progress_bar,
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

        window.cursor_set.assert_called_once_with("SCROLL_Y")

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

        window.cursor_modal_set.assert_called_once_with("SCROLL_Y")
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
        window.cursor_set.assert_called_once_with("SCROLL_Y")
        self.assertFalse(dummy._resize_cursor_modal_active)


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
