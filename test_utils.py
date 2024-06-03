import unittest

from blenderkit import utils


class FileSizeToTextTestCase(unittest.TestCase):
    kib = 1024
    mib = kib * 1024
    gib = mib * 1024
    tib = gib * 1024

    def test_negative_size(self):
        self.assertEqual(utils.files_size_to_text(-1), "0")
        self.assertEqual(utils.files_size_to_text(-10), "0")
        self.assertEqual(utils.files_size_to_text(-100), "0")

    def test_zero_size(self):
        self.assertEqual(utils.files_size_to_text(0), "0 bytes")

    def test_bytes(self):
        self.assertEqual(utils.files_size_to_text(1), "1 byte")
        self.assertEqual(utils.files_size_to_text(512), "512 bytes")
        self.assertEqual(utils.files_size_to_text(1023), "1023 bytes")

    def test_kibibytes(self):
        self.assertEqual(utils.files_size_to_text(1024), "1 KiB")
        self.assertEqual(utils.files_size_to_text(1536), "1.5 KiB")
        self.assertEqual(utils.files_size_to_text(2048), "2 KiB")
        self.assertEqual(utils.files_size_to_text(1048473), "1023.9 KiB")

    def test_mebibytes(self):
        self.assertEqual(utils.files_size_to_text(1048576), "1 MiB")
        self.assertEqual(utils.files_size_to_text(1572864), "1.5 MiB")
        self.assertEqual(utils.files_size_to_text(2097152), "2 MiB")
        self.assertEqual(utils.files_size_to_text(1073636966), "1023.9 MiB")

    def test_gibibytes(self):
        self.assertEqual(utils.files_size_to_text(1073741824), "1 GiB")
        self.assertEqual(utils.files_size_to_text(1610612736), "1.5 GiB")
        self.assertEqual(utils.files_size_to_text(2147483648), "2 GiB")
        self.assertEqual(utils.files_size_to_text(1099404253593), "1023.9 GiB")

    def test_tebibytes(self):
        self.assertEqual(utils.files_size_to_text(1099511627776), "1 TiB")
        self.assertEqual(utils.files_size_to_text(1649267441664), "1.5 TiB")
        self.assertEqual(utils.files_size_to_text(2199023255552), "2 TiB")
