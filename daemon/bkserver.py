import json
import uuid
import asyncio

import aiohttp
from aiohttp import web

import assets
import tasks
import globals

async def websocket_handler(request):
  ws = web.WebSocketResponse(protocols=('v0.1.0'))
  await ws.prepare(request)

  async for msg in ws:
    if msg.type == aiohttp.WSMsgType.TEXT:
      if msg.data == 'close':
        await ws.close()
      else:
        data = json.loads(msg.data)
        print(data)
        data = {
          "asset_data": {
            "assetBaseId": data["asset_base_id"],
            "assetType" : data["asset_type"]
          },
          'PREFS': {
            'api_key': data
          }
        }


        task_id = str(uuid.uuid4())
        app_id = globals.active_apps[0]
        task = tasks.Task(data, app_id, 'asset_download', task_id, message='Looking for asset')
        globals.tasks.append(task)
        task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))
        print("DOWNLOAD TASK ADDED")

        await ws.send_str('got it')

    elif msg.type == aiohttp.WSMsgType.ERROR:
      print('ws connection closed with exception %s' %
      ws.exception())

    print('websocket connection closed')

    return ws