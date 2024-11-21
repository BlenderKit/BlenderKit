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

import os
import unittest

import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
from . import client_lib, global_vars


class Test01Registration(unittest.TestCase):
    def test01_global_vars_VERSION_set(self):
        assert global_vars.VERSION is not None
        assert global_vars.VERSION != [0, 0, 0, 0]
        if __package__ == "blenderkit":
            import blenderkit  # relative import .. would go outside the package, so we need to import oldschool here

            version = blenderkit.bl_info["version"]
        else:
            from .. import blenderkit

            version = blenderkit.VERSION
        assert global_vars.VERSION == version

    def test02_global_vars_PREFS_set(self):
        assert global_vars.PREFS != {}
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        prefs = {
            # SYSTEM STUFF
            "debug_value": bpy.app.debug_value,
            "binary_path": bpy.app.binary_path,
            "addon_dir": client_lib.get_addon_dir(),
            "addon_module_name": __package__,
            "app_id": os.getpid(),
            # STATISTICS
            "download_counter": user_preferences.download_counter,
            "asset_popup_counter": user_preferences.asset_popup_counter,
            "welcome_operator_counter": user_preferences.welcome_operator_counter,
            # MAIN PREFERENCES
            "api_key": user_preferences.api_key,
            "api_key_refresh": user_preferences.api_key_refresh,
            "api_key_timeout": user_preferences.api_key_timeout,
            "experimental_features": user_preferences.experimental_features,
            "keep_preferences": user_preferences.keep_preferences,
            # FILE PATHS
            "directory_behaviour": user_preferences.directory_behaviour,
            "global_dir": user_preferences.global_dir,
            "project_subdir": user_preferences.project_subdir,
            "unpack_files": user_preferences.unpack_files,
            # GUI
            "show_on_start": user_preferences.show_on_start,
            "thumb_size": user_preferences.thumb_size,
            "max_assetbar_rows": user_preferences.max_assetbar_rows,
            "search_field_width": user_preferences.search_field_width,
            "search_in_header": user_preferences.search_in_header,
            "tips_on_start": user_preferences.tips_on_start,
            "announcements_on_start": user_preferences.announcements_on_start,
            # NETWORK
            "client_port": user_preferences.client_port,
            "ip_version": user_preferences.ip_version,
            "ssl_context": user_preferences.ssl_context,
            "proxy_which": user_preferences.proxy_which,
            "proxy_address": user_preferences.proxy_address,
            "trusted_ca_certs": user_preferences.trusted_ca_certs,
            # UPDATES
            "auto_check_update": user_preferences.auto_check_update,
            "enable_prereleases": user_preferences.enable_prereleases,
            "updater_interval_months": user_preferences.updater_interval_months,
            "updater_interval_days": user_preferences.updater_interval_days,
            # IMPORT SETTINGS
            "resolution": user_preferences.resolution,
        }
        self.maxDiff = None
        self.assertDictEqual(global_vars.PREFS, prefs)
