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

import addon_utils


addon_utils.enable("blenderkit", default_set=True)

runner = unittest.TextTestRunner()
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()

suite.addTests(testLoader.discover(".", "test_init.py"))
suite.addTests(testLoader.discover(".", "test_upload.py"))
suite.addTests(testLoader.discover(".", "test_timer.py"))
suite.addTests(testLoader.discover(".", "test_paths.py"))
suite.addTests(testLoader.discover(".", "test_utils.py"))
suite.addTests(testLoader.discover(".", "test_daemon_lib.py"))

result = runner.run(suite)
errors = len(result.errors)
failures = len(result.failures)
if errors + failures != 0:
    exit(1)
