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
  def test_daemon_not_running(self):
    """Tests run in background (bpy.app.background == True), so daemon is not started during registration.
    Also the daemon_communication_timer() and all other timers are not registered.
    So we expect daemon to be not running.
    """
    with requests.Session() as session:
      alive, pid = daemon_lib.daemon_is_alive(session)
      self.assertFalse(alive)
      self.assertIsInstance(alive, bool)
      self.assertIsInstance(pid, str)
  
  def test_daemon_up_and_down(self):
    daemon_lib.start_daemon_server()
    with requests.Session() as session:
      for _ in range(10):
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive == True:
          break
        time.sleep(1)
      self.assertTrue(alive)

      daemon_lib.kill_daemon_server()
      for _ in range(5):
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive == False:
          break
        time.sleep(1)
      self.assertFalse(alive)
