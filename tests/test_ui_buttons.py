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

import copy
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import bpy

from .boilerplate import __package__, module

asset_bar_op = module.asset_bar_op
global_vars = module.global_vars
search = module.search
utils = module.utils


class TestAssetBarButtons(unittest.TestCase):
    def setUp(self):
        self.ui_props = bpy.context.window_manager.blenderkitUI
        self.preferences = bpy.context.preferences.addons[__package__].preferences

        # snapshot mutable globals to keep tests isolated
        self._tabs_backup = copy.deepcopy(global_vars.TABS)
        self._data_backup = copy.deepcopy(global_vars.DATA)
        self._assetbar_on_backup = self.ui_props.assetbar_on
        self._turn_off_backup = self.ui_props.turn_off
        self._expanded_backup = self.preferences.assetbar_expanded

        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.finish()
        self.ui_props.assetbar_on = False
        self.ui_props.turn_off = False

    def tearDown(self):
        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.finish()

        global_vars.TABS.clear()
        global_vars.TABS.update(self._tabs_backup)
        global_vars.DATA.clear()
        global_vars.DATA.update(self._data_backup)
        self.ui_props.assetbar_on = self._assetbar_on_backup
        self.ui_props.turn_off = self._turn_off_backup
        self.preferences.assetbar_expanded = self._expanded_backup

    @contextmanager
    def _prevent_search(self):
        with patch.object(search, "search", return_value=None):
            yield

    def _ensure_context(self, ctx):
        if not ctx.get("window") or not ctx.get("area"):
            self.skipTest("No VIEW_3D area available to run asset bar operators.")

    def _invoke_asset_bar_widget(self, **kwargs):
        fake_ctx = utils.get_fake_context()
        self._ensure_context(fake_ctx)

        if bpy.app.version < (4, 0, 0):
            return bpy.ops.view3d.blenderkit_asset_bar_widget(
                fake_ctx, "INVOKE_DEFAULT", **kwargs
            )

        with bpy.context.temp_override(**fake_ctx):
            return bpy.ops.view3d.blenderkit_asset_bar_widget(
                "INVOKE_DEFAULT", **kwargs
            )

    def test_semicolon_shortcut_operator_toggles_asset_bar(self):
        with self._prevent_search():
            result_on = bpy.ops.view3d.run_assetbar_fix_context(
                keep_running=True, do_search=False
            )
        if "CANCELLED" in result_on:
            self.skipTest("Asset bar could not be started in this Blender session.")
        self.assertTrue(self.ui_props.assetbar_on)
        self.assertIsNotNone(asset_bar_op.asset_bar_operator)

        with self._prevent_search():
            result_off = bpy.ops.view3d.run_assetbar_fix_context(
                keep_running=False, do_search=False
            )
        self.assertIn("FINISHED", result_off)
        self.assertFalse(self.ui_props.assetbar_on)
        self.assertIsNone(asset_bar_op.asset_bar_operator)

    def test_asset_bar_widget_operator_invocation(self):
        with self._prevent_search():
            result = self._invoke_asset_bar_widget(keep_running=False, do_search=False)
        if "CANCELLED" in result:
            self.skipTest(
                "Asset bar widget operator was cancelled in this configuration."
            )

        self.assertTrue(self.ui_props.assetbar_on)
        self.assertIsNotNone(asset_bar_op.asset_bar_operator)
        asset_bar_op.asset_bar_operator.finish()
        self.assertFalse(self.ui_props.assetbar_on)
