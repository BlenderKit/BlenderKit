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

import unittest
from unittest.mock import Mock

import bpy

for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break

from . import search


def mocked_preferences() -> Mock:
    """Get Mock of the add-on preferences with default values."""
    preferences = Mock()
    preferences.nsfw_filter = True
    return preferences


def mocked_common_props() -> Mock:
    """Get Mock of the props shared across asset types."""
    props = Mock()
    props.search_keywords = ""
    props.search_verification_status = "ALL"
    props.unrated_quality_only = False
    props.unrated_wh_only = False
    props.search_file_size = False
    return props


def mocked_ui_props() -> Mock:
    ui_props = Mock()
    ui_props.quality_limit = 0
    ui_props.search_bookmarks = False
    ui_props.search_license = "ANY"
    ui_props.search_blender_version = False
    return ui_props


# TODO: Add test for build_common_query()


class TestBuildQueryModel(unittest.TestCase):
    def setUp(self):
        self.preferences = mocked_preferences()
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_style = "ANY"
        self.props.search_condition = "UNSPECIFIED"
        self.props.search_design_year = False
        self.props.search_polycount = False
        self.props.search_texture_resolution = False
        self.props.search_animated = False
        self.props.search_geometry_nodes = False

    def test_default_model_query(self):
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {"asset_type": "model", "sexualizedContent": False}
        self.assertEqual(query, expected)

    def test_style_other(self):
        self.props.search_style = "OTHER"
        self.props.search_style_other = "custom_style"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modelStyle": "custom_style",
        }
        self.assertEqual(query, expected)

    def test_style_specific(self):
        self.props.search_style = "REALISTIC"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modelStyle": "REALISTIC",
        }
        self.assertEqual(query, expected)

    def test_search_condition(self):
        self.props.search_condition = "NEW"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "condition": "NEW",
        }
        self.assertEqual(query, expected)

    def test_design_year_range(self):
        self.props.search_design_year = True
        self.props.search_design_year_min = 1900
        self.props.search_design_year_max = 2000
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "designYear_gte": 1900,
            "designYear_lte": 2000,
        }
        self.assertEqual(query, expected)

    def test_polycount_range(self):
        self.props.search_polycount = True
        self.props.search_polycount_min = 1000
        self.props.search_polycount_max = 10000
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "faceCount_gte": 1000,
            "faceCount_lte": 10000,
        }
        self.assertEqual(query, expected)

    def test_texture_resolution(self):
        self.props.search_texture_resolution = True
        self.props.search_texture_resolution_min = 512
        self.props.search_texture_resolution_max = 4096
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        self.assertEqual(query["textureResolutionMax_gte"], 512)
        self.assertEqual(query["textureResolutionMax_lte"], 4096)

    def test_animated_flag(self):
        self.props.search_animated = True
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {"asset_type": "model", "sexualizedContent": False, "animated": True}
        self.assertEqual(query, expected)

    def test_geometry_nodes(self):
        self.props.search_geometry_nodes = True
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modifiers": "nodes",
        }
        self.assertEqual(query, expected)

    def test_nsfw_filter_off(self):
        """Turned-off NSFW filter means all sexualizedContent is allowed, we expect empty string there."""
        self.preferences.nsfw_filter = False
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = expected = {"asset_type": "model", "sexualizedContent": ""}
        self.assertEqual(query, expected)


class TestBuildQueryScene(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()

    def test_default_scene_query(self):
        query = search.build_query_scene(self.props, self.ui_props)
        expected = {"asset_type": "scene"}
        self.assertEqual(query, expected)


class TestBuildQueryHDR(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_texture_resolution = False  # TODO: test alternations of this
        self.props.true_hdr = True  # TODO: test alternations of this

    def test_default_HDR_query(self):
        query = search.build_query_HDR(self.props, self.ui_props)
        expected = {"asset_type": "hdr", "trueHDR": True}
        self.assertEqual(query, expected)


# TODO: Add test for MATERIAL
class TestBuildQueryMaterial(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_style = "ANY"
        self.props.search_procedural = "BOTH"

    def test_query_default(self):
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material"}
        self.assertEqual(query, expected)

    def test_query_search_style(self):
        self.props.search_style = "REALISTIC"
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "style": "REALISTIC"}
        self.assertEqual(query, expected)

    def test_query_search_style_other(self):
        self.props.search_style = "OTHER"
        self.props.search_style_other = ""
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "style": ""}
        self.assertEqual(query, expected)

    def test_query_search_procedural_texture_based_default_resolution(self):
        self.props.search_procedural = "TEXTURE_BASED"
        self.props.search_texture_resolution = False
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "textureResolutionMax_gte": 0}
        self.assertEqual(query, expected)

    def test_query_search_procedural_texture_based_default(self):
        self.props.search_procedural = "TEXTURE_BASED"
        self.props.search_texture_resolution = True
        self.props.search_texture_resolution_min = 256
        self.props.search_texture_resolution_max = 4096
        query = search.build_query_material(self.props, self.ui_props)
        expected = {
            "asset_type": "material",
            "textureResolutionMax_gte": 256,
            "textureResolutionMax_lte": 4096,
        }
        self.assertEqual(query, expected)

    def test_query_search_procedural_procedural_based(self):
        self.props.search_procedural = "PROCEDURAL"
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "files_size_lte": 1024 * 1024}
        self.assertEqual(query, expected)


class TestBuildQueryBrush(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.image_paint_object = None  # TODO: test alternations of this

    def test_default_brush_query(self):
        query = search.build_query_brush(
            self.props, self.ui_props, self.image_paint_object
        )
        expected = {"asset_type": "brush", "mode": "sculpt"}
        self.assertEqual(query, expected)


class TestBuildQueryNodegroup(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()

    def test_default_nodegroup_query(self):
        query = search.build_query_nodegroup(self.props, self.ui_props)
        expected = {"asset_type": "nodegroup"}
        self.assertEqual(query, expected)
