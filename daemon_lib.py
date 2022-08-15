import logging
import os
import platform
import subprocess
import sys
import time
from os import environ, path

import aiohttp
import bpy
import requests

from . import colors, dependencies, global_vars, reports


bk_logger = logging.getLogger(__name__)

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
        queue.put(json_data)

def get_reports(app_id: str):
  """Get report for all tasks at once."""

  address = get_address()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/report"
    data = {'app_id': app_id}
    resp = session.get(url, json=data)

    return resp.json()

def search_asset(data):
  """Search for specified asset."""

  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/search_asset"
    resp = session.post(url, json=data)
    return resp.json()

def download_asset(data):
  """Download specified asset."""

  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/download_asset"
    resp = session.post(url, json=data)
    return resp.json()


def kill_download(task_id):
  """Kill the specified task with ID on the daemon."""

  address = get_address()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/kill_download"
    resp = session.get(url, json={'task_id':task_id})
    return resp

def refresh_token(refresh_token):
  """Refresh authentication token."""
  
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = get_address() + "/refresh_token"
    resp = session.get(url, json={'refresh_token': refresh_token})
    return resp

def ensure_daemon_alive(session: requests.Session):
  """Make sure that daemon is running. If not start the daemon."""

  isAlive, _ = daemon_is_alive(session)
  if isAlive == True:
    return

  bk_logger.info(f'Starting daemon server on port {get_port()}')
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

def report_blender_quit():
  address = get_address()
  with requests.Session() as session:
    url = address + "/report_blender_quit"
    resp = session.get(url, json={'app_id':os.getpid()})
    return resp

def kill_daemon_server():
  ''' Request to restart the daemon server.'''
  address = get_address()
  with requests.Session() as session:
    url = address + "/shutdown"
    resp = session.get(url)
    return resp

def start_daemon_server():
  """Start daemon server in separate process."""

  log_dir = bpy.context.preferences.addons['blenderkit'].preferences.global_dir
  log_path = f'{log_dir}/blenderkit-daemon-{get_port()}.log'
  blenderkit_path = path.dirname(__file__)
  daemon_path = path.join(blenderkit_path, 'daemon/daemon.py')
  vendor_dir = dependencies.get_vendored_path()
  fallback_dir = dependencies.get_fallback_path()

  env  = environ.copy()
  env['PYTHONPATH'] = vendor_dir + os.pathsep + fallback_dir

  python_home = path.abspath(path.dirname(sys.executable) + "/..")
  env['PYTHONHOME'] = python_home
  
  creation_flags = 0
  if platform.system() == "Windows":
    env['PATH'] = env['PATH'] + os.pathsep + path.abspath(path.dirname(sys.executable) + "/../../../blender.crt")
    creation_flags = subprocess.CREATE_NO_WINDOW

  python_check = subprocess.run(args=[sys.executable, "--version"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  if python_check.returncode != 0:
    bk_logger.warning(
      f"Error checking Python interpreter, exit code: {python_check.returncode}," +
      f"Stdout: {python_check.stdout}, " +
      f"Stderr: {python_check.stderr}, " +
      f"Where Python: {sys.executable}, " +
      f"Environment: {env}"
    )

  try:
    with open(log_path, "wb") as log:
      daemon_process = subprocess.Popen(
        args = [
          sys.executable,
          "-u", daemon_path,
          "--port", get_port(),
          "--proxy-which", global_vars.PREFS.get('proxy_which'),
          "--proxy-address", global_vars.PREFS.get('proxy_address'),
          "--proxy-ca-certs", global_vars.PREFS.get('proxy_ca_certs'),
        ],
        env           = env,
        stdout        = log,
        stderr        = log,
        creationflags = creation_flags,
      )
  except PermissionError as e:
    reports.add_report(f"FATAL ERROR: Write access denied to {log_dir}. Check you have write permissions to the directory.", 10, colors.RED)
    raise(e)
  except OSError as e:
    if platform.system() != "Windows":
      reports.add_report(str(e), 10, colors.RED)
      raise(e)
    if e.winerror == 87: # parameter is incorrect, issue #100
      error_message = f"FATAL ERROR: Daemon server blocked from starting. Please check your antivirus or firewall. Error: {e}"
      reports.add_report(error_message, 10, colors.RED)
      raise(e)
    else:
      reports.add_report(str(e), 10, colors.RED)
      raise(e)
  except Exception as e:
    reports.add_report(f"Error: Daemon server failed to start - {e}", 10, colors.RED)
    raise(e)

  if python_check.returncode == 0:
    reports.add_report(f'Daemon server started on address {get_address()}, PID: {daemon_process.pid}, log file located at: {log_path}', 5, colors.GREEN)
  else:
    reports.add_report(f'Tried to start daemon server on address {get_address()}, PID: {daemon_process.pid},\nlog file located at: {log_path}', 5, colors.RED)
    reports.add_report(f"Due to unsuccessful Python check the daemon server will probably fail to run. Please report a bug at BlenderKit.", 5, colors.RED)
