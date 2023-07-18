import unittest

import addon_utils


addon_utils.enable("blenderkit", default_set=True)

runner = unittest.TextTestRunner()
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()

suite.addTests(testLoader.discover(".", "test_init.py"))
suite.addTests(testLoader.discover(".", "test_timer.py"))
suite.addTests(testLoader.discover(".", "test_paths.py"))
suite.addTests(testLoader.discover(".", "test_daemon_lib.py"))

result = runner.run(suite)
errors = len(result.errors)
failures = len(result.failures)
if errors + failures != 0:
    exit(1)
