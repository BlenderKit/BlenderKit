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

import pathlib
import unittest

from blenderkit import paths


class TestDownloadDirs(unittest.TestCase):
    def _test_get_download_dirs(self, asset):
        result = paths.get_download_dirs(asset)
        path = pathlib.Path(result[0])
        self.assertTrue(path.is_dir(), msg=path)

    def test001(self):
        self._test_get_download_dirs("brush")

    def test002(self):
        self._test_get_download_dirs("texture")

    def test003(self):
        self._test_get_download_dirs("model")

    def test004(self):
        self._test_get_download_dirs("scene")

    def test005(self):
        self._test_get_download_dirs("material")

    def test006(self):
        self._test_get_download_dirs("hdr")


class TestGlobalDict(unittest.TestCase):
    def test_default_global_dict(self):
        result = paths.default_global_dict()
        path = pathlib.Path(result)
        self.assertTrue(path.is_dir(), msg=path)
