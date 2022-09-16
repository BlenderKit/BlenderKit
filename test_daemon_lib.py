import os
import time
import unittest
from urllib.parse import urlparse

import bpy
import requests

from blenderkit import daemon_lib, global_vars, paths, utils


### DAEMON IS NOT RUNNING ###

class Test01DaemonNotRunning(unittest.TestCase):
  def test01_daemon_not_running(self):
    """Tests run in background (bpy.app.background == True), so daemon is not started during registration.
    Also the daemon_communication_timer() and all other timers are not registered.
    So we expect daemon to be not running.
    """
    with requests.Session() as session:
      alive, pid = daemon_lib.daemon_is_alive(session)
      self.assertFalse(alive)
      self.assertIsInstance(alive, bool)
      self.assertIsInstance(pid, str)

  def test02_get_reports_not_running(self):
    app_id = os.getpid()
    try:
      daemon_lib.get_reports(app_id)
      self.fail('got report but daemon should be offline')
    except requests.exceptions.ConnectionError as err:
      type(err)
      return
    except Exception as err:
      self.fail(f'expected requests.exceptions.ConnectionError, got {err}')


### DAEMON IS RUNNING ###
  
class Test02DaemonRunning(unittest.TestCase):
  def test01_start_daemon_server(self):
    daemon_lib.start_daemon_server()
    with requests.Session() as session:
      for i in range(10):
        time.sleep(i*0.5)
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive == True:
          break
      self.assertTrue(alive)


class Test03DaemonUtilFunctions(unittest.TestCase):
  def test_get_port(self):
    ports = ["62485","65425", "55428", "49452", "35452","25152","5152", "1234"]
    self.assertIn(daemon_lib.get_port(), ports)

  def test_get_address(self):
    address = daemon_lib.get_address()
    parsed = urlparse(address)
    self.assertEqual(parsed.scheme, 'http')
    self.assertEqual(parsed.hostname, '127.0.0.1')
    self.assertEqual(parsed.port, int(daemon_lib.get_port()))

  def test_daemon_directory_path(self):
    dir_path = daemon_lib.get_daemon_directory_path()
    self.assertTrue(os.path.exists(dir_path))


class Test04GetReportsDaemonRunning(unittest.TestCase):
  def test_get_reports_running(self):
    """Get reports for current Blender PID (app_id)."""
    app_id = os.getpid()
    reports = daemon_lib.get_reports(app_id)
    self.assertEqual(1, len(reports))
    self.assertEqual(reports[0]['app_id'], app_id)
    self.assertEqual(reports[0]['task_type'], 'daemon_status')

  def test_get_reports_another_app_id(self):
    """Get reports for non-existing Blender PID (app_id)."""
    app_id = os.getpid() + 10
    reports = daemon_lib.get_reports(app_id)
    self.assertEqual(1, len(reports))
    self.assertEqual(reports[0]['app_id'], app_id)
    self.assertEqual(reports[0]['task_type'], 'daemon_status')

class Test05SearchAssets(unittest.TestCase):
  def _search_asset(self, search_word, asset_type):
    addon_version = f'{global_vars.VERSION[0]}-{global_vars.VERSION[1]}-{global_vars.VERSION[2]}-{global_vars.VERSION[3]}'
    blender_version = bpy.app.version
    urlquery = f'https://www.blenderkit.com/api/v1/search/?query={search_word}+asset_type:{asset_type}+order:_score&dict_parameters=1&page_size=15&addon_version={addon_version}&blender_version={blender_version}'
    tempdir = paths.get_temp_dir(f'{asset_type}_search')
    data = {
      'PREFS': utils.get_prefs_dir(),
      'tempdir': tempdir,
      'urlquery': urlquery,
      'asset_type': asset_type,
    }
    response = daemon_lib.search_asset(data)
    search_task_id = response['task_id']

    for i in range(10):
      reports = daemon_lib.get_reports(os.getpid())
      for task in reports:
        if search_task_id == task['task_id'] and task['status'] == 'finished' and task['result'] != {}:
          return
      time.sleep(i*0.1)
    self.fail('Error waiting for search task to be reported as finished')

  def test01(self): self._search_asset('cat', 'model')
  def test02(self): self._search_asset('car', 'model')
  def test03(self): self._search_asset('steel', 'material')
  def test04(self): self._search_asset('paint', 'material')
  def test05(self): self._search_asset('room', 'scene')
  def test06(self): self._search_asset('water', 'scene')
  def test07(self): self._search_asset('forest', 'hdr')
  def test08(self): self._search_asset('city', 'hdr')
  def test09(self): self._search_asset('fur', 'brush')
  def test10(self): self._search_asset('hair', 'brush')


### DAEMON IS NOT RUNNING ###

class Test99DaemonStopped(unittest.TestCase):
  def test_kill_daemon_server(self):
    daemon_lib.kill_daemon_server()
    with requests.Session() as session:
      for _ in range(5):
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive == False:
          break
        time.sleep(1)
      self.assertFalse(alive)
