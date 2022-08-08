import time
import unittest
from urllib.parse import urlparse

import requests

from blenderkit import daemon_lib


class TestDaemonUtilFunctions(unittest.TestCase):
  def test_get_port(self):
    ports = ["62485","65425", "55428", "49452", "35452","25152","5152", "1234"]
    self.assertIn(daemon_lib.get_port(), ports)

  def test_get_address(self):
    address = daemon_lib.get_address()
    parsed = urlparse(address)
    self.assertEqual(parsed.scheme, 'http')
    self.assertEqual(parsed.hostname, '127.0.0.1')
    self.assertEqual(parsed.port, int(daemon_lib.get_port()))


class TestDaemon(unittest.TestCase):
  def test_daemon_is_alive(self):
    with requests.Session() as session:
      for x in range(10):
        alive, pid = daemon_lib.daemon_is_alive(session)
        if alive == True:
          return
        time.sleep(1)
      self.fail('Daemon is offline')
