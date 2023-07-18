import os
import unittest

import bpy

import blenderkit
from blenderkit import global_vars


class Test01Registration(unittest.TestCase):
    def test01_global_vars_VERSION_set(self):
        assert global_vars.VERSION is not None
        assert global_vars.VERSION == blenderkit.bl_info["version"]

    def test02_global_vars_PREFS_set(self):
        assert global_vars.PREFS != {}
        user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
        prefs = {
            "debug_value": bpy.app.debug_value,
            "binary_path": bpy.app.binary_path,
            "api_key": user_preferences.api_key,
            "api_key_refresh": user_preferences.api_key_refresh,
            "system_id": user_preferences.system_id,
            "global_dir": user_preferences.global_dir,
            "project_subdir": user_preferences.project_subdir,
            "directory_behaviour": user_preferences.directory_behaviour,
            "is_saved": user_preferences.directory_behaviour,
            "app_id": os.getpid(),
            "ip_version": user_preferences.ip_version,
            "ssl_context": user_preferences.ssl_context,
            "proxy_which": user_preferences.proxy_which,
            "proxy_address": user_preferences.proxy_address,
            "proxy_ca_certs": user_preferences.proxy_ca_certs,
            "unpack_files": user_preferences.unpack_files,
            "models_resolution": user_preferences.models_resolution,
            "mat_resolution": user_preferences.mat_resolution,
            "hdr_resolution": user_preferences.hdr_resolution,
        }
        assert global_vars.PREFS == prefs
