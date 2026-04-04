import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
from . import asset_bar_op, paths


def _make_dummy_operator(**overrides):
    """Create a minimal mock of BlenderKitAssetBarOperator for icon tests."""
    return SimpleNamespace(
        hcount=overrides.get("hcount", 1),
        scroll_width=overrides.get("scroll_width", 30),
        bar_height=overrides.get("bar_height", 96),
        button_scroll_down=MagicMock(),
        button_scroll_up=MagicMock(),
    )


class TestUpdateScrollButtonIcons(unittest.TestCase):
    def test_single_row_uses_horizontal_arrows(self):
        dummy = _make_dummy_operator(hcount=1)
        asset_bar_op.BlenderKitAssetBarOperator.update_scroll_button_icons(dummy)

        dummy.button_scroll_down.set_image.assert_called_once_with(
            paths.get_addon_thumbnail_path("arrow_left.png")
        )
        dummy.button_scroll_up.set_image.assert_called_once_with(
            paths.get_addon_thumbnail_path("arrow_right.png")
        )

    def test_multi_row_uses_vertical_arrows(self):
        dummy = _make_dummy_operator(hcount=3, bar_height=288)
        asset_bar_op.BlenderKitAssetBarOperator.update_scroll_button_icons(dummy)

        dummy.button_scroll_down.set_image.assert_called_once_with(
            paths.get_addon_thumbnail_path("arrow_up.png")
        )
        dummy.button_scroll_up.set_image.assert_called_once_with(
            paths.get_addon_thumbnail_path("arrow_down.png")
        )

    def test_preserves_aspect_ratio(self):
        dummy = _make_dummy_operator(hcount=2, scroll_width=30, bar_height=180)
        asset_bar_op.BlenderKitAssetBarOperator.update_scroll_button_icons(dummy)

        # up/down source is 35x116, scale = min(30/35, 180/116) = min(0.857, 1.551) = 0.857
        # w = round(35 * 0.857) = 30, h = round(116 * 0.857) = 99
        expected_size = (30, 99)
        dummy.button_scroll_down.set_image_size.assert_called_once_with(expected_size)
        dummy.button_scroll_up.set_image_size.assert_called_once_with(expected_size)

        # x = (30 - 30) / 2 = 0, y = (180 - 99) / 2 = 40
        expected_pos = (0, 40)
        dummy.button_scroll_down.set_image_position.assert_called_once_with(
            expected_pos
        )
        dummy.button_scroll_up.set_image_position.assert_called_once_with(expected_pos)

    def test_clears_text_on_both_buttons(self):
        dummy = _make_dummy_operator(hcount=1)
        asset_bar_op.BlenderKitAssetBarOperator.update_scroll_button_icons(dummy)
        self.assertEqual(dummy.button_scroll_down.text, "")
        self.assertEqual(dummy.button_scroll_up.text, "")

        dummy2 = _make_dummy_operator(hcount=2, bar_height=180)
        asset_bar_op.BlenderKitAssetBarOperator.update_scroll_button_icons(dummy2)
        self.assertEqual(dummy2.button_scroll_down.text, "")
        self.assertEqual(dummy2.button_scroll_up.text, "")
