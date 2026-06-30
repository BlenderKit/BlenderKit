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

        # Measure the add-on *package* as it is actually imported. Blender loads
        # the add-on from its install dir (e.g. .../scripts/addons/blenderkit),
        # NOT from this source checkout, so scoping coverage to the source tree
        # records every add-on module as never-executed (0%). Scoping to the
        # package name follows the imported files; codecov.yml `fixes` then maps
        # the install path back to repo paths.
        _cov = _coverage.Coverage(source=[sys.argv[-1]])
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

# Run the tests from the INSTALLED add-on, imported as ``<pkg>.tests.*`` submodules
# (top_level_dir = the add-on's parent) rather than the source checkout. This makes
# the test files the same ones ``coverage`` measures (source=[<pkg>]), so they
# report real coverage instead of 0% - and genuinely dead test code (an uncollected
# test, an unused helper) shows up as uncovered.
_addon_dir = os.path.dirname(sys.modules[sys.argv[-1]].__file__)
_tests_dir = os.path.join(_addon_dir, "tests")
_top_level = os.path.dirname(_addon_dir)

runner = unittest.TextTestRunner(buffer=False)
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()


def _discover(pattern):
    return testLoader.discover(_tests_dir, pattern, top_level_dir=_top_level)


suite.addTests(_discover("test_init.py"))
suite.addTests(_discover("test_upload.py"))
suite.addTests(_discover("test_timer.py"))
suite.addTests(_discover("test_paths.py"))
suite.addTests(_discover("test_utils.py"))
suite.addTests(_discover("test_version_compare.py"))
suite.addTests(_discover("test_client_lib.py"))
suite.addTests(_discover("test_search.py"))
suite.addTests(_discover("test_asset_bar_op.py"))
suite.addTests(_discover("test_global_vars.py"))
suite.addTests(_discover("test_manifest_toml.py"))
suite.addTests(_discover("test_ui_panels.py"))
suite.addTests(_discover("test_registration.py"))
suite.addTests(_discover("test_smoke.py"))
suite.addTests(_discover("test_upload_bg.py"))
suite.addTests(_discover("test_rating_nudge.py"))
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
