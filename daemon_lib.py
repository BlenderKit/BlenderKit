from os import path, environ
import sys
import random
import subprocess
import requests

PORT = 8080

def getAddress() -> str:
  return 'http://localhost:' + str(PORT)


def getReports(data):
  address = getAddress()
  with requests.Session() as session:
    ensureDaemonServerAlive(session)
    url = address + "/report"
    # data = {
    #   'assetID' : random.randint(0,10000),
    # }
    resp = session.post(url, json=data)
    print(f"Asked for asset download, {data['asset_data']['name']}, {resp.status_code}")

def DownloadAsset(data):
  address = getAddress()
  with requests.Session() as session:
    ensureDaemonServerAlive(session)
    url = address + "/download-asset"
    resp = session.post(url, json=data)
    print(f"Asked for asset download, {data['asset_data']['name']}, {resp.status_code}")


def ensureDaemonServerAlive(session: requests.Session):
  isAlive, _ = daemonServerIsAlive(session)
  if isAlive == True:
    return

  print("Starting daemon server")
  startDaemonServer()
  while True: #TODO: add a timeout break here
    isAlive, _ = daemonServerIsAlive(session)
    if isAlive == True:
      print("Daemon server started")
      return


def daemonServerIsAlive(session: requests.Session) -> tuple[bool, str]:
  address = getAddress()
  try:
    with session.get(address) as resp:
      if resp.status_code != 200:
        return False, f'Server response not 200: {resp.status_code}'
      return True, f'Server alive, PID: {resp.text}'

  except requests.exceptions.ConnectionError as err:
    return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


def startDaemonServer(logPath = None):
  daemonPath = path.join(path.dirname(__file__), 'daemon.py')
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
  DownloadAsset()
  DownloadAsset()
  DownloadAsset()
  
else:
  import bpy

  class AssetDownloadOperator(bpy.types.Operator):
    '''
    Testing button to trigger an asset download. TO BE REMOVED before merge!
    '''
    bl_idname = "view3d.download_asset"
    bl_label = "Starts asset download"
    bl_description = "Starts asset download"

    def execute(self, context):
      DownloadAsset({})
      return {'FINISHED'}
