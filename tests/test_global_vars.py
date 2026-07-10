import unittest

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import global_vars


class TestVersions(unittest.TestCase):
    def test_client_version(self):
        """Client version in ./bk_client/client/VERSION and in global_vars.CLIENT_VERSION must be the same."""
        with open("bk_client/client/VERSION") as f:
            client_version = f.read().strip()
        self.assertEqual(
            global_vars.CLIENT_VERSION,
            f"v{client_version}",
            "global_vars.CLIENT_VERSION does not match the content of client/VERSION",
        )


class TestProductionIsSet(unittest.TestCase):
    def test_server_set_to_production(self):
        """Ensure the SERVER variable in global_vars is set to production."""
        expected_server = "https://www.blendkit.com"
        self.assertEqual(
            global_vars.SERVER,
            expected_server,
            f"SERVER is not set to production. Expected: {expected_server}, Found: {global_vars.SERVER}",
        )
