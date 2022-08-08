import unittest

import addon_utils


addon_utils.enable("blenderkit", default_set=True)

runner = unittest.TextTestRunner()
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()

suite = testLoader.discover('.', 'test_*.py')
result = runner.run(suite)
errors = len(result.errors)
failures = len(result.failures) 
if errors + failures != 0:
    exit(1)
