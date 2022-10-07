import json
import uuid
import asyncio

import aiohttp
from aiohttp import web

import assets
import tasks
import globals
import search

async def websocket_handler(request):
  ws = web.WebSocketResponse(protocols=('v0.1.0'))
  await ws.prepare(request)

  async for msg in ws:
    if msg.type == aiohttp.WSMsgType.TEXT:
      if msg.data == 'close':
        await ws.close()
      else:
        for app_id in globals.active_apps:
          app_id = app_id
          scene_uuid = globals.active_apps[app_id]['scene_uuid']
          api_key = globals.active_apps[app_id]['api_key']
          download_dirs = ["/Users/ag/blenderkit_data/models"]
          break

        data = json.loads(msg.data)

        response = await search.search_asset_by_asset_base_id(request, data['asset_base_id'], api_key)
        

        data = {
          'PREFS': {
            'api_key': api_key,
            'scene_id': scene_uuid,
          },
          'resolution': 'resolution_1K', # we can get this from prefs also
          'download_dirs': download_dirs,
        }
        data['asset_data'] = response['results'][0]

        task_id = str(uuid.uuid4())
        task = tasks.Task(data, app_id, 'asset_download', task_id, message='Looking for asset')
        globals.tasks.append(task)
        task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))
        print("DOWNLOAD FROM WEBSITE ADDED", data)

        await ws.send_str('got it')

    elif msg.type == aiohttp.WSMsgType.ERROR:
      print('ws connection closed with exception %s' %
      ws.exception())

    print('websocket connection closed')

    return ws