"""Main module (starting point) for daemon server. From here all other modules are imported."""

import asyncio
import os
import sys
import uuid
import ssl
import certifi
import json

import aiohttp
from aiohttp import web

import assets, search, globals


PORT = 10753


async def download_asset(request):
  """Handle request for download of asset."""

  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu
  print('Starting asset download:', data['asset_data']['name'])

  asyncio.ensure_future(assets.do_asset_download(request.app['PERSISTENT_SESSION'], data, task_id))
  
  return web.json_response({'task_id': task_id})


async def search_assets(request):
  """Handle request for download of asset."""

  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu
  print('Starting search:', data['urlquery'])

  asyncio.ensure_future(search.do_search(request.app['PERSISTENT_SESSION'], data, task_id))

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
  if len(globals.tasks) > 0:
    print("TOTAL TASKS:", len(globals.tasks))
  #reports = {key: value for (key, value) in globals.tasks.items() if value['app_id'] == data['app_id']}
  
  #globals.tasks = {key: value for (key, value) in globals.tasks.items() if value['app_id'] != data['app_id']}
  #tohle melo cistit? moc to tam nevidim :/
  reports = list()
  for task in globals.tasks:
    print("TASK=", task)
    if task.app_id != data['app_id']:
      continue

    reports.append(task.to_seriazable_object())
    if task.status == "finished":
      task.delete()

  return web.json_response(reports)


class Shutdown(web.View):
  """Shedules shutdown of the server."""

  async def get(self):
    asyncio.ensure_future(self.shutdown_in_future())
    return web.Response(text='Going to kill him soon.')

  async def shutdown_in_future(self):
    await asyncio.sleep(1)
    sys.exit()


async def persistent_session(app):
  sslcontext = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
  sslcontext.load_verify_locations(certifi.where())
  conn = aiohttp.TCPConnector(ssl=sslcontext)
  app['PERSISTENT_SESSION'] = session = aiohttp.ClientSession(connector=conn)
  yield
  await asyncio.gather(
    session.close(),
    conn.close()
  )


if __name__ == "__main__":
  server = web.Application()
  server.cleanup_ctx.append(persistent_session)
  server.add_routes([
    web.get('/', index),
    web.get('/report', report),
    web.get('/kill_download', kill_download),
    web.post('/download_asset', download_asset),
    web.post('/search_asset', search_assets),
    web.view('/shutdown', Shutdown),
  ])

  web.run_app(server, host='127.0.0.1', port=PORT)
