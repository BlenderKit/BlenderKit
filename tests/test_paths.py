
import unittest
from blenderkit import paths


class TestPathsMethods(unittest.TestCase):

    def test_upper(self):
        self.assertEqual(paths.get_oauth_landing_url(), 'FOO')
