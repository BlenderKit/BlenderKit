import os
import time
import unittest
from urllib.parse import urlparse

import bpy
import requests

from blenderkit import daemon_lib, download, global_vars, paths, utils


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
class DaemonRunningTestCase(unittest.TestCase):
  def _start_daemon_server(self):
    daemon_lib.start_daemon_server()
    with requests.Session() as session:
      for i in range(10):
        time.sleep(i*0.5)
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive is True:
          break
      self.assertTrue(alive)

class Test02DaemonRunning(DaemonRunningTestCase):
  def test01_start_daemon_server(self): self._start_daemon_server()
    

class Test03DaemonUtilFunctions(unittest.TestCase):
  def test_get_port(self):
    ports = ["62485","65425","55428","49452","35452","25152","5152","1234"]
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


class SearchAndDownloadAssetTestCase(unittest.TestCase):
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
      'blender_version': f'{blender_version[0]}.{blender_version[1]}.{blender_version[2]}',
    }
    response = daemon_lib.search_asset(data)
    search_task_id = response['task_id']

    to_download = None
    for i in range(10):
      reports = daemon_lib.get_reports(os.getpid())
      for task in reports:
        if search_task_id != task['task_id']:
          continue
        if task['status'] == 'error':
          self.fail(f'Search task failed {task["message"]}')
        if task['status'] != 'finished':
          continue
        if task['result'] != {}:
          for result in task['result']['results']:
            if result['canDownload'] is True:
              if to_download is None:
                to_download = result
                continue
              result_size = result.get('filesSize', 9999999)
              if result_size is None:
                result_size = 9999999
              to_download_size = to_download.get('filesSize', 9999999)
              if to_download_size is None:
                to_download_size = 9999999
              if result_size < to_download_size:
                to_download = result
          return to_download

      time.sleep(i*0.1)
    self.fail('Error waiting for search task to be reported as finished')

  def _download_asset(self, asset_data):
    if asset_data is None:
      self.fail('Asset data from search are None')

    download.start_download(asset_data, resolution=512, model_location=(0.0, 0.0, 0.0), model_rotation=(0.0, 0.0, 0.0))
    for _ in range(100):
      reports = daemon_lib.get_reports(os.getpid())
      for task in reports:
        if task['task_type'] != 'asset_download':
          continue
        if task['status'] != 'finished':
          continue
        return
      time.sleep(1)


class Test05SearchAndDownloadAsset(SearchAndDownloadAssetTestCase):
  assets_to_download = []
  #small assets are chosen here
  def test00Search(self): self.assets_to_download.append(self._search_asset('Toy train-02', 'model'))
  def test01Search(self): self.assets_to_download.append(self._search_asset('Wooden toy car', 'model'))
  def test02Search(self): self.assets_to_download.append(self._search_asset('flowers1 wallpaper', 'material'))
  def test03Search(self): self.assets_to_download.append(self._search_asset('hexa wallpaper', 'material'))
  def test04Search(self): self.assets_to_download.append(self._search_asset('Desk for product visualization', 'scene'))
  def test05Search(self): self.assets_to_download.append(self._search_asset('Butterfly Mural Room', 'scene'))
  def test06Search(self): self.assets_to_download.append(self._search_asset('Garden Nook', 'hdr'))
  def test07Search(self): self.assets_to_download.append(self._search_asset('Dark Autumn Forest', 'hdr'))
  def test08Search(self): self.assets_to_download.append(self._search_asset('bricks', 'brush'))
  def test09Search(self): self.assets_to_download.append(self._search_asset('Human eye iris', 'brush'))

  def test10Download(self): self._download_asset(self.assets_to_download[0])
  def test12Download(self): self._download_asset(self.assets_to_download[2])
  def test14Download(self): self._download_asset(self.assets_to_download[4])
  def test16Download(self): self._download_asset(self.assets_to_download[6])
  def test18Download(self): self._download_asset(self.assets_to_download[8])

### DAEMON IS NOT RUNNING ###

class DaemonStoppedTestCase(unittest.TestCase):
  def _kill_daemon_server(self):
    daemon_lib.kill_daemon_server()
    with requests.Session() as session:
      for _ in range(5):
        alive, _ = daemon_lib.daemon_is_alive(session)
        if alive is False:
          break
        time.sleep(1)
      self.assertFalse(alive)

class Test99DaemonStopped(DaemonStoppedTestCase):
  def test_kill_daemon_server(self): self._kill_daemon_server()
