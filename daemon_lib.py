from os import path, environ
import os
import sys
import subprocess
import requests
import aiohttp
import time

from . import vendor

def get_address() -> str:
  """Get address of the daemon."""

  return 'http://127.0.0.1:' + get_port()

def get_port() -> str:
  """Get port of the daemon."""
  
  if __name__ == "__main__":
    port = 10753
  else:
    port = bpy.context.preferences.addons['blenderkit'].preferences.daemon_port

  return str(port)

async def get_reports_async(app_id: str, queue):
  """Get report for all task at once with asyncio and aiohttp."""
  global reports_queue
  address = get_address()
  url = address + "/report"
  t = time.time()
  async with aiohttp.ClientSession() as session:
    # ensure_daemon_alive(session)
    data = {'app_id': app_id}
    async with session.get(url, json=data) as resp:
      # text = await resp.text()
      json_data = await resp.json()
      if len(json_data)>0:
        # print('from daemon', json_data)
        queue.put(json_data)
        print(t-time.time())

def get_reports(app_id: str):
  """Get report for all tasks at once."""

  # import time
  # mt = time.time()
  address = get_address()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/report"
    # print(mt-time.time())
    data = {'app_id': app_id}
    resp = session.get(url, json=data)
    # print(resp)
    # print(mt-time.time())
    return resp.json()

def search_asset(data):
  """Search for specified asset."""

  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/search_asset"
    resp = session.post(url, json=data)
    print(f"Asked for search, {data['urlquery']}, {resp.status_code}")
    return resp.json()

def download_asset(data):
  """Download specified asset."""

  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/download_asset"
    resp = session.post(url, json=data)
    print(f"Asked for asset download, {data['asset_data']['name']}, {resp.status_code}")
    return resp.json()


def kill_download(task_id):
  """Kill the specified task with ID on the daemon."""

  address = get_address()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/kill_download"
    resp = session.get(url, json={'task_id':task_id})
    print(f"Asked for end of download, {task_id}, {resp.status_code}")
    return resp


def ensure_daemon_alive(session: requests.Session):
  """Make sure that daemon is running. If not start the daemon."""

  isAlive, _ = daemon_is_alive(session)
  if isAlive == True:
    return

  print(f'Starting daemon server on port {get_port()}')
  start_daemon_server()

def daemon_is_alive(session: requests.Session) -> tuple[bool, str]:
  """Check whether daemon is responding."""

  address = get_address()
  try:
    with session.get(address) as resp:
      if resp.status_code != 200:
        return False, f'Server response not 200: {resp.status_code}'
      return True, f'Server alive, PID: {resp.text}'

  except requests.exceptions.ConnectionError as err:
    return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


def start_daemon_server(log_dir: str = None):
  """Start daemon server in separate process."""

  env  = environ.copy()
  vendor_dir = vendor.get_vendor_path()
  fallback_dir = vendor.get_vendor_fallback_path()
  env['PYTHONPATH'] = vendor_dir + os.pathsep + fallback_dir

  python_home = path.abspath(path.dirname(sys.executable) + "/..")
  env['PYTHONHOME'] = python_home



  if log_dir == None:
    log_dir = path.abspath(path.expanduser('~') + "/blenderkit_data")
  log_path = f'{log_dir}/blenderkit-daemon-{get_port()}.log'

  blenderkit_path = path.dirname(__file__)
  daemon_path = path.join(blenderkit_path, 'daemon/daemon.py')
  with open(log_path, "wb") as log:
    process = subprocess.Popen(
      args       = [sys.executable, "-u", daemon_path, "--port", get_port()],
      env        = env,
      stdout     = log,
      stderr     = log
      )

  print(f'Daemon server started on address {get_address()}')


if __name__ == "__main__":
  pass
else:
  import bpy
