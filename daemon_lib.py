from os import path, environ
import sys
import subprocess
import requests

PORT = 10753


def get_address() -> str:
  """Get address of the daemon."""

  return 'http://127.0.0.1:' + str(PORT)


def get_reports(data):
  """Get report for all tasks at once."""

  # import time
  # mt = time.time()
  address = get_address()
  with requests.Session() as session:
    ensure_daemon_alive(session)
    url = address + "/report"
    # print(mt-time.time())

    resp = session.get(url, json=data)
    # print(resp)
    # print(mt-time.time())
    return resp.json()


def download_asset(data):
  """Download specified asset."""

  address = get_address()
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
    return resp.json()


def ensure_daemon_alive(session: requests.Session):
  """Make sure that daemon is running. If not start the daemon."""

  isAlive, _ = daemon_is_alive(session)
  if isAlive == True:
    return

  print("Starting daemon server")
  start_daemon_server()
  while True: #TODO: add a timeout break here
    isAlive, _ = daemon_is_alive(session)
    if isAlive == True:
      print("Daemon server started")
      return


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


def start_daemon_server(logPath = None):
  """Start daemon server in separate process."""

  daemonPath = path.join(path.dirname(__file__), 'daemon/daemon.py')
  pythonPath = sys.executable
  pythonHome = path.abspath(path.dirname(sys.executable) + "/..")
  env  = environ.copy()
  env['PYTHONPATH'] = pythonPath
  env['PYTHONHOME'] = pythonHome
  if logPath == None:
    logPath = path.abspath(path.expanduser('~') + "/blenderkit_data/daemon.log")
  with open(logPath, "wb") as log:
    process = subprocess.Popen(
      args       = [pythonPath, "-u", daemonPath],
      env        = env,
      stdout     = log,
      stderr     = log
      )


if __name__ == "__main__":
  pass
else:
  import bpy
