import pathlib
import unittest

from blenderkit import paths


class TestDownloadDirs(unittest.TestCase):
  def _test_get_download_dirs(self, asset):
    result = paths.get_download_dirs(asset)
    path = pathlib.Path(result[0])
    self.assertTrue(path.is_dir(), msg=path)

  def test001(self): self._test_get_download_dirs("brush")
  def test002(self): self._test_get_download_dirs("texture")
  def test003(self): self._test_get_download_dirs("model")
  def test004(self): self._test_get_download_dirs("scene")
  def test005(self): self._test_get_download_dirs("material")
  def test006(self): self._test_get_download_dirs("hdr")

class TestGlobalDict(unittest.TestCase):
  def test_default_global_dict(self):
    result = paths.default_global_dict()
    path = pathlib.Path(result)
    self.assertTrue(path.is_dir(), msg=path)
