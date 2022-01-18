import asyncio
from os import getpid
from aiohttp import web

PORT = 8080

async def IsAlive(request):
  pid = str(getpid())
  return web.Response(text=pid)


class DownloadAsset(web.View):
  async def post(self):
    data = await self.request.json()
    print('download started for:', data)
    asyncio.ensure_future(self.doDownload(data))
    return web.Response(text="ok")

  async def doDownload(self, data):
    tasks[data["assetID"]] = 0
    await asyncio.sleep(5)
    tasks[data["assetID"]] = 1
    print("ASSET DOWNLOADED")


class Report(web.View):
  async def get(self):
    return web.json_response(tasks)


if __name__ == "__main__":
  server = web.Application()
  server.add_routes([
    web.get('/', IsAlive),
    web.view('/report', Report),
    web.view('/download-asset', DownloadAsset),
    ])

  tasks = dict()
  web.run_app(server, port=PORT)
