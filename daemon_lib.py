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
    
    data = {
      'assetID' : random.randint(0,10000),
    }

    session.post(address+"/download-asset", json=data)
    print("POST MADE")
      

def ensureDaemonServerAlive(session):
  address = getAddress()
  try:
    with session.get(address) as resp:
      if resp.status_code != 200:
        startDaemonServer()
      print("Server alive, PID:", resp.text)
  except requests.ConnectionError as e:
    print("Connection error:", e)
    startDaemonServer()

def startDaemonServer():
  cmd = 'python daemon.py' #TODO: use full paths
  subprocess.Popen(
    cmd,
    stdout= subprocess.PIPE,
    stderr= subprocess.PIPE,
    stdin = subprocess.PIPE)
  print('DAEMON SERVER STARTED')


class AssetDownloadOperator(bpy.types.Operator):
    '''
    Testing button to trigger an asset download. TO BE REMOVED before merge!
    '''
    bl_idname = "view3d.download_asset"
    bl_label = "Starts asset download"
    bl_description = "Starts asset download"

    def execute(self, context):
      DownloadAsset()
      return {'FINISHED'}


if __name__ == "__main__":
  pass
else:
  pass  
