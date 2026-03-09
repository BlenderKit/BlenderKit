import platform
import sys
import unittest
from urllib.parse import unquote

import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
from . import global_vars, ui_panels


class TestGetEnvironmentInfo(unittest.TestCase):
    def test_contains_addon_version_with_build_date(self):
        result = ui_panels.get_environment_info()
        ver = global_vars.VERSION
        expected = f"v{ver[0]}.{ver[1]}.{ver[2]}.{ver[3]}"
        self.assertIn(expected, result)

    def test_contains_blender_version(self):
        result = ui_panels.get_environment_info()
        self.assertIn(bpy.app.version_string, result)

    def test_contains_python_version(self):
        result = ui_panels.get_environment_info()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.assertIn(expected, result)

    def test_contains_os_info(self):
        result = ui_panels.get_environment_info()
        self.assertIn(platform.system(), result)
        self.assertIn(platform.machine(), result)

    def test_contains_proxy_setting(self):
        result = ui_panels.get_environment_info()
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        self.assertIn(user_preferences.proxy_which, result)

    def test_contains_all_template_fields(self):
        result = ui_panels.get_environment_info()
        self.assertIn("BlenderKit version:", result)
        self.assertIn("Blender version:", result)
        self.assertIn("Python version:", result)
        self.assertIn("Operating system & architecture:", result)
        self.assertIn("Proxy setting:", result)
        self.assertIn("VPN, proxy, or firewall", result)


class TestGetReportBugURL(unittest.TestCase):
    def test_points_to_github_issues(self):
        url = ui_panels.get_report_bug_url()
        self.assertTrue(url.startswith("https://github.com/BlenderKit/blenderkit/issues/new"))

    def test_uses_bug_report_template(self):
        url = ui_panels.get_report_bug_url()
        self.assertIn("template=bug-report.yaml", url)

    def test_prefills_title(self):
        url = ui_panels.get_report_bug_url()
        self.assertIn("title=", url)

    def test_prefills_description_with_env_info(self):
        url = ui_panels.get_report_bug_url()
        decoded = unquote(url)
        self.assertIn(bpy.app.version_string, decoded)
        self.assertIn(platform.system(), decoded)


class TestCopyEnvironmentInfo(unittest.TestCase):
    def test_copies_to_clipboard(self):
        result = bpy.ops.wm.blenderkit_copy_environment_info()
        self.assertEqual(result, {"FINISHED"})
        clipboard = bpy.context.window_manager.clipboard
        self.assertIn("BlenderKit version:", clipboard)
        self.assertIn("Blender version:", clipboard)
