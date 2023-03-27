import unittest

from blenderkit import dependencies


class Test01OnStartupTimer(unittest.TestCase):
    def test01_dependencies_installation(self):
        """Install dependencies."""
        dependencies.ensure_preinstalled_deps_copied()
        dependencies.add_installed_deps_path()
        dependencies.add_preinstalled_deps_path()
        dependencies.ensure_deps()
