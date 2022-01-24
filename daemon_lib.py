from os import path, environ
import sys
import random
import subprocess
import requests
import bpy

PORT = 8080

def getAddress() -> str:
  return 'http://localhost:' + str(PORT)

def DownloadAsset():
  address = getAddress()
  with requests.Session() as session:
    ensureDaemonServerAlive(session)
    url = address + "/download-asset"
    data = {
      'assetID' : random.randint(0,10000),
    }

    session.post(url, json=data)
    print("POST MADE")
      

def ensureDaemonServerAlive(session):
  address = getAddress()
  try:
    with session.get(address) as resp:
      if resp.status_code != 200:
        startDaemonServer()
      print("Server alive, PID:", resp.text)
  except Exception as err:
    print("EXCEPTION OCCURED", err, type(err))
    startDaemonServer()

def startDaemonServer():
  daemonPath = path.join(path.dirname(__file__), 'daemon.py')
  pythonPath = sys.executable
  pythonHome = path.abspath(path.dirname(sys.executable) + "/..")
  env  = environ.copy()
  env['PYTHONPATH'] = pythonPath
  env['PYTHONHOME'] = pythonHome

  print("DAEMON PATH:", daemonPath)
  print("PYTHON PATH:", pythonPath)
  print("PYTHON HOME:", pythonHome)

  process = subprocess.Popen(
    executable = pythonPath,
    args       = daemonPath,
    env        = env,
    stdout     = subprocess.PIPE,
    stderr     = subprocess.PIPE,
    stdin      = subprocess.PIPE)
  print('DAEMON SERVER STARTED', process.returncode)


class AssetDownloadOperator(bpy.types.Operator):
    '''
    Testing button to trigger an asset download. TO BE REMOVED before merge!
    '''
    bl_idname = "view3d.download_asset"
    bl_label = "Starts asset download"
    bl_description = "Starts asset download"

    def execute(self, context):
      #DownloadAsset()
      startDaemonServer()
      return {'FINISHED'}


if __name__ == "__main__":
  pass
else:
  pass  
