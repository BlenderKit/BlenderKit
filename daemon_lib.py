import logging
import os
import platform
import subprocess
import sys
from os import environ, path
from urllib.parse import urlparse

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


def get_daemon_directory_path() -> str:
  """Get path to daemon directory in blenderkit_data directory."""
  global_dir = bpy.context.preferences.addons['blenderkit'].preferences.global_dir
  directory = path.join(global_dir, 'daemon')
  return path.abspath(directory)


def get_reports(app_id: str):
  """Get reports for all tasks of app_id Blender instance at once."""

  bk_logger.debug('Getting reports')
  address = get_address()
  with requests.Session() as session:
    url = address + "/report"
    data = {'app_id': app_id}
    try:
      resp = session.get(url, json=data)
      bk_logger.debug('Got reports')
      return resp.json()
    except Exception as e:
      raise(e)


def search_asset(data):
  """Search for specified asset."""

  bk_logger.debug('Starting search request')
  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    url = address + "/search_asset"
    resp = session.post(url, json=data)
    bk_logger.debug('Got search response')
    return resp.json()


def download_asset(data):
  """Download specified asset."""

  address = get_address()
  data['app_id'] = os.getpid()
  with requests.Session() as session:
    url = address + "/download_asset"
    resp = session.post(url, json=data)
    return resp.json()


def kill_download(task_id):
  """Kill the specified task with ID on the daemon."""

  address = get_address()
  with requests.Session() as session:
    url = address + "/kill_download"
    resp = session.get(url, json={'task_id':task_id})
    return resp


def get_disclaimer():
  """Get disclaimer from server."""

  address = get_address()
  with requests.Session() as session:
    url = address + "/get_disclaimer"
    data = {'app_id': os.getpid()}
    resp = session.get(url, json=data)
    return resp


def send_code_verifier(code_verifier: str):
  data = {'code_verifier': code_verifier}
  with requests.Session() as session:
    resp = session.post(f'{get_address()}/code_verifier', json=data)
    return resp


def refresh_token(refresh_token):
  """Refresh authentication token."""
  
  with requests.Session() as session:
    url = get_address() + "/refresh_token"
    resp = session.get(url, json={'refresh_token': refresh_token})
    return resp


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
  '''Request to restart the daemon server.'''
  address = get_address()
  with requests.Session() as session:
    url = address + "/shutdown"
    resp = session.get(url)
    return resp


def handle_daemon_status_task(task):
  bk_server_status = task.result[global_vars.SERVER]
  if bk_server_status == 200:
    if global_vars.DAEMON_ONLINE == False:
      reports.add_report(f'Connected to {urlparse(global_vars.SERVER).netloc}')
      wm = bpy.context.window_manager
      wm.blenderkitUI.logo_status = "logo"
      global_vars.DAEMON_ONLINE = True
    return

  if global_vars.DAEMON_ONLINE == True:
    reports.add_report(f'Disconnected from {urlparse(global_vars.SERVER).netloc}', timeout=10, type='ERROR')
    wm = bpy.context.window_manager
    wm.blenderkitUI.logo_status = "logo_offline"
    global_vars.DAEMON_ONLINE = False


def check_daemon_exit_code() -> tuple[int, str]:
  """Checks the exit code of daemon process. Returns exit_code and its message.
  Function polls the process which should not block, but better run only when daemon misbehaves and is expected that it already exited.
  """

  exit_code = global_vars.daemon_process.poll()
  if exit_code == None:
    return exit_code, "Daemon process is running."
  
  #exit_code = global_vars.daemon_process.returncode
  if exit_code == 101:
    message = f'Failed to import AIOHTTP. Try to delete {dependencies.get_dependencies_path()} and restart Blender.'
  elif exit_code == 102:
    message = f'Failed to import CERTIFI. Try to delete {dependencies.get_dependencies_path()} and restart Blender.'
  elif exit_code == 113:
    message = 'OSError: [Errno 10013] - cannot open port. Please check your antivirus or firewall and unblock blenderkit and/or daemon.py script.'
  else:
    log_dir = bpy.context.preferences.addons['blenderkit'].preferences.global_dir
    log_path = f'{log_dir}/blenderkit-daemon-{get_port()}.log'
    message = f'Unknown problem. Please report a bug and paste content of log {log_path}'

  return exit_code, message


def start_daemon_server():
  """Start daemon server in separate process."""

  daemon_dir = get_daemon_directory_path()
  log_path = f'{daemon_dir}/daemon-{get_port()}.log'
  blenderkit_path = path.dirname(__file__)
  daemon_path = path.join(blenderkit_path, 'daemon/daemon.py')
  preinstalled_deps = dependencies.get_preinstalled_deps_path()
  installed_deps = dependencies.get_installed_deps_path()

  env  = environ.copy()
  env['PYTHONPATH'] = installed_deps + os.pathsep + preinstalled_deps

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
      global_vars.daemon_process = subprocess.Popen(
        args = [
          sys.executable,
          '-u', daemon_path,
          '--port', get_port(),
          '--server', global_vars.SERVER,
          '--proxy_which', global_vars.PREFS.get('proxy_which'),
          '--proxy_address', global_vars.PREFS.get('proxy_address'),
          '--proxy_ca_certs', global_vars.PREFS.get('proxy_ca_certs'),
          '--ip_version', global_vars.PREFS.get('ip_version'),
          '--system_id', bpy.context.preferences.addons['blenderkit'].preferences.system_id,
          '--version', f'{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}',
        ],
        env           = env,
        stdout        = log,
        stderr        = log,
        creationflags = creation_flags,
      )
  except PermissionError as e:
    reports.add_report(f"FATAL ERROR: Write access denied to {daemon_dir}. Check you have write permissions to the directory.", 10, 'ERROR')
    raise(e)
  except OSError as e:
    if platform.system() != "Windows":
      reports.add_report(str(e), 10, 'ERROR')
      raise(e)
    if e.winerror == 87: # parameter is incorrect, issue #100
      error_message = f"FATAL ERROR: Daemon server blocked from starting. Please check your antivirus or firewall. Error: {e}"
      reports.add_report(error_message, 10, 'ERROR')
      raise(e)
    else:
      reports.add_report(str(e), 10, 'ERROR')
      raise(e)
  except Exception as e:
    reports.add_report(f"Error: Daemon server failed to start - {e}", 10, 'ERROR')
    raise(e)

  if python_check.returncode == 0:
    bk_logger.info(f'Daemon server starting on address {get_address()}, log file for errors located at: {log_path}')
  else:
    bk_logger.warning(f'Tried to start daemon server on address {get_address()}, PID: {global_vars.daemon_process.pid},\nlog file located at: {log_path}')
    reports.add_report(f'Due to unsuccessful Python check the daemon server will probably fail to run. Please report a bug at BlenderKit.', 5, 'ERROR')

