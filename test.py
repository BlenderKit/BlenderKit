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
import sys
import unittest


COLLECT_COVERAGE = os.getenv("COVERAGE") == "1"
if COLLECT_COVERAGE:
    try:
        import coverage as _coverage

        _cov = _coverage.Coverage(source=[os.path.dirname(os.path.abspath(__file__))])
        _cov.start()
    except ImportError:
        COLLECT_COVERAGE = False
        print("WARNING: coverage module not available, skipping coverage collection")

import addon_utils


print(f"----- Tests preparation ----- (mode:{os.getenv('TESTS_TYPE', 'all')})")
result = addon_utils.enable(sys.argv[-1], default_set=True)
if result is None:
    print(f"FATAL: addon '{sys.argv[-1]}' failed to load")
    sys.exit(1)
print(f"- addon enabled: {sys.argv[-1]}")

runner = unittest.TextTestRunner(buffer=False)
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()

suite.addTests(testLoader.discover("tests", "test_init.py"))
suite.addTests(testLoader.discover("tests", "test_upload.py"))
suite.addTests(testLoader.discover("tests", "test_timer.py"))
suite.addTests(testLoader.discover("tests", "test_paths.py"))
suite.addTests(testLoader.discover("tests", "test_utils.py"))
suite.addTests(testLoader.discover("tests", "test_version_compare.py"))
suite.addTests(testLoader.discover("tests", "test_client_lib.py"))
suite.addTests(testLoader.discover("tests", "test_search.py"))
suite.addTests(testLoader.discover("tests", "test_asset_bar_op.py"))
suite.addTests(testLoader.discover("tests", "test_global_vars.py"))
suite.addTests(testLoader.discover("tests", "test_manifest_toml.py"))
suite.addTests(testLoader.discover("tests", "test_ui_panels.py"))
suite.addTests(testLoader.discover("tests", "test_registration.py"))
suite.addTests(testLoader.discover("tests", "test_smoke.py"))
print(f"- {len(suite._tests)} tests discovered and loaded\n")

print(f"----- Running tests --------------------------------------------------")
result = runner.run(suite)
if COLLECT_COVERAGE:
    _cov.stop()
    _cov.xml_report(outfile="coverage-python.xml")
errors = len(result.errors)
failures = len(result.failures)
if errors + failures != 0:
    sys.exit(1)
