import json
import uuid
import asyncio
import os

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
          api_key = globals.active_apps[app_id]['PREFS']['api_key']
          prefs = globals.active_apps[app_id]['PREFS']
          break

        data = json.loads(msg.data)
        response = await search.search_asset_by_asset_base_id(request, data['asset_base_id'], api_key)
        prefs['scene_id'] = scene_uuid
        data = {
          'PREFS': prefs,
          'resolution': 'resolution_1K', # TODO: we can get this from prefs also
          'model_location': (0,0,0),
          'model_rotation': (0,0,0),
          'downloaders': [{
            "location": (0,0,0),
            "rotation": (0,0,0)
            }],
          }
        download_dirs = {'brush': 'brushes', 'texture': 'textures', 'model': 'models', 'scene': 'scenes', 'material': 'materials', 'hdr': 'hdrs'}
        data['asset_data'] = response['results'][0]
        asset_type = data["asset_data"]["assetType"]
        download_dirs = os.path.join(prefs["global_dir"], download_dirs[asset_type])
        data['download_dirs'] = [download_dirs,]

        task_id = str(uuid.uuid4())
        task = tasks.Task(data, app_id, 'ws_asset_download', task_id, message='Downloading asset')
        globals.tasks.append(task)
        task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))

        await ws.send_str('got it')

    elif msg.type == aiohttp.WSMsgType.ERROR:
      print(f'ws connection closed with exception {ws.exception()}')

    print('websocket connection closed')

    return ws