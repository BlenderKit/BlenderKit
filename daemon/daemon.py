"""Main module (starting point) for daemon server. From here all other modules are imported."""

import asyncio
import os
import sys
import uuid

from aiohttp import web

import assets, globals


PORT = 10753


async def download_asset(request):
  """Handle request for download of asset."""

  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id
  print('Starting asset download:', data['asset_data']['name'])
  asyncio.ensure_future(assets.do_asset_download(data))
  
  return web.json_response({'task_id': task_id})


async def index(request):
  """Report PID of server as Index page, can be used as is-alive endpoint."""

  pid = str(os.getpid())
  return web.Response(text=pid)


async def kill_download(request):
  """Handle request for kill of download with the task_id."""

  data = await request.json()
  globals.tasks[data['task_id']]['kill'] = True
  return web.Response(text="ok")


async def report(request):
  """Report progress of all tasks for a given app_id. Clears list of tasks."""
  
  data = await request.json()
  reports = {key: value for (key, value) in globals.tasks.items() if value['app_id'] == data['app_id']}
  globals.tasks = {key: value for (key, value) in globals.tasks.items() if value['app_id'] != data['app_id']}
  return web.json_response(reports)


class Shutdown(web.View):
  """Shedules shutdown of the server."""

  async def get(self):
    asyncio.ensure_future(self.shutdown_in_future())
    return web.Response(text='Going to kill him soon.')

  async def shutdown_in_future():
    await asyncio.sleep(1)
    sys.exit()


if __name__ == "__main__":
  server = web.Application()
  server.add_routes([
    web.get('/', index),
    web.get('/report', report),
    web.get('/kill_download', kill_download),
    web.post('/download_asset', download_asset),
    web.view('/shutdown', Shutdown),
  ])

  web.run_app(server, host='127.0.0.1', port=PORT)
