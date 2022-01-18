import random
import asyncio
import aiohttp

PORT = 8080

def getAddress() -> str:
  return 'http://localhost:' + str(PORT)

async def DownloadAsset():
  address = getAddress()
  async with aiohttp.ClientSession() as session:
    await ensureDaemonServerAlive(session)
    
    data = {
      'assetID' : random.randint(0,10000),
    }

    await session.post(address+"/download-asset", json=data)
    print("POST MADE")
      
  
async def ensureDaemonServerAlive(session):
  address = getAddress()
  try:
    async with session.get(address) as resp:
      if resp.status != 200:
        await startDaemonServer()
      text = await resp.text()
      print("Server alive, PID:", text)
  except aiohttp.ClientConnectorError as e:
    print("Connection error:", e)
    await startDaemonServer()

async def startDaemonServer():
  cmd = 'python daemon.py' #TODO: use full paths
  await asyncio.create_subprocess_shell(
    cmd,
    stdout= asyncio.subprocess.PIPE,
    stderr= asyncio.subprocess.PIPE,
    stdin = asyncio.subprocess.PIPE)
  print('DAEMON SERVER STARTED')


if __name__ == "__main__":
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  asyncio.run(DownloadAsset())
  

