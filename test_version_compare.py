import unittest
import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break

from . import version_compare


class VersionHelperFunctionsTestCase(unittest.TestCase):
    def test_equal_with_prefixes(self):
        self.assertTrue(version_compare.version_eq("v1.2", "1.2"))

    def test_prerelease_ranked_lower_for_same_parts(self):
        self.assertTrue(version_compare.version_lt("3.19rc", "3.19"))
        self.assertTrue(version_compare.version_gt("3.19", "3.19rc"))

    def test_compare_versions_tristate(self):
        self.assertEqual(version_compare.compare_versions("1.2.0", "1.2.0"), 0)
        self.assertEqual(version_compare.compare_versions("1.2.0", "1.2.1"), -1)
        self.assertEqual(version_compare.compare_versions("1.3", "1.2.9"), 1)


class VersionOrderingMatrixTestCase(unittest.TestCase):
    ORDERED_SAMPLES = [
        "v1.2",
        "1.2",
        "1.2.0",
        "1.2.0-rc1",
        "1.2.0-rc1-260127",
        "1.2.0-260126",
        "1.2.0-260127",
        "3.19_final",
        "3.19",
        "3.19.0-rc1",
        "3.19.0-rc1-260127",
        "3.19.0-260127",
        "3.19.0-260128",
        "build_41",
        "build_42",
    ]

    def test_pairwise_ordering(self):
        for left_index, left in enumerate(self.ORDERED_SAMPLES):
            for right_index, right in enumerate(self.ORDERED_SAMPLES):
                with self.subTest(left=left, right=right):
                    expected = (left_index > right_index) - (left_index < right_index)
                    self.assertEqual(
                        version_compare.compare_versions(left, right), expected
                    )
