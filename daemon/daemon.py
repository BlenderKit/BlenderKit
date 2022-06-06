"""Main module (starting point) for daemon server. From here all other modules are imported."""

import argparse
import asyncio
import os
import ssl
import sys
import time
import uuid
from ssl import Purpose

import aiohttp
import certifi

from aiohttp import web, web_request

import globals
import tasks
import search
import oauth
import assets

async def download_asset(request: web_request.Request):
  """Handle request for download of asset."""

  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu

  app_id = data['app_id']
  del data['app_id']
  
  task = tasks.Task(data, task_id, app_id, 'asset_download', message='Looking for asset')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))
  
  return web.json_response({'task_id': task_id})


async def search_assets(request: web_request.Request):
  """Handle request for download of asset."""

  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu
  asyncio.ensure_future(search.do_search(request, data, task_id))

  return web.json_response({'task_id': task_id})


async def index(request: web_request.Request):
  """Report PID of server as Index page, can be used as is-alive endpoint."""

  pid = str(os.getpid())
  return web.Response(text=pid)


async def consumer_exchange(request: web_request.Request):
  auth_code = request.rel_url.query.get('code', None)
  redirect_url = "https://www.blenderkit.com/oauth-landing/" #this needs to switch between devel/stage/production

  if auth_code == None:
    return web.Response(text="Authorization Failed. Authorization code was not provided.")

  status, response_json = await oauth.get_tokens(request, auth_code=auth_code)
  if status != 200:
    return web.Response(text=f"Authorization Failed. Retrieval of tokens failed (status code: {status.code}). Response: {response_json}")

  for app_id in globals.active_apps:
    task = tasks.Task(None, str(uuid.uuid4()), app_id, 'login', message='Getting authorization code')
    globals.tasks.append(task)
    task.result = response_json
    task.finished("Tokens obtained")

  return web.HTTPPermanentRedirect(redirect_url)


async def refresh_token(request: web_request.Request):
  asyncio.ensure_future(oauth.refresh_tokens(request))
  return web.Response(text="ok")

async def kill_download(request: web_request.Request):
  """Handle request for kill of task with the task_id."""

  data = await request.json()

  for i, task in enumerate(globals.tasks):
    if data['task_id'] == task.task_id:
      #globals.tasks[i].cancel() #needs to handle cleaning when download is cancelled
      del globals.tasks[i]
      break

  return web.Response(text="ok")


async def report(request: web_request.Request):
  """Report progress of all tasks for a given app_id. Clears list of tasks."""

  globals.last_report_time = time.time()

  data = await request.json()
  #check if the app was already active
  if data['app_id'] not in globals.active_apps:
    globals.active_apps.append(data['app_id'])

  reports = list()
  for task in globals.tasks:
    if task.app_id != data['app_id']:
      continue

    reports.append(task.to_seriazable_object())
    if task.status == "finished":
      globals.tasks.remove(task)

  return web.json_response(reports)


class Shutdown(web.View):
  """Shedules shutdown of the server."""

  async def get(self):
    asyncio.ensure_future(self.shutdown_in_future())
    return web.Response(text='Going to shutdown soon.')

  async def shutdown_in_future(self):
    await asyncio.sleep(1)
    sys.exit()


async def persistent_sessions(app):
  sslcontext = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
  
  if app['PROXY_CA_CERTS'] != '':
    sslcontext.load_verify_locations(app['PROXY_CA_CERTS'])
  sslcontext.load_verify_locations(certifi.where())
  sslcontext.load_default_certs(purpose=Purpose.CLIENT_AUTH)

  if app['PROXY_WHICH'] == 'SYSTEM':
    trust_env = True
  elif app['PROXY_WHICH'] == 'CUSTOM':
    trust_env = True
    os.environ["HTTPS_PROXY"] = app['PROXY_ADDRESS']
  else:
    trust_env = False

  conn_api_requests = aiohttp.TCPConnector(ssl=sslcontext, limit=64)
  app['SESSION_API_REQUESTS'] = session_api_requests = aiohttp.ClientSession(connector=conn_api_requests, trust_env=trust_env)

  conn_small_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=16)
  app['SESSION_SMALL_THUMBS'] = session_small_thumbs = aiohttp.ClientSession(connector=conn_small_thumbs, trust_env=trust_env)
  
  conn_big_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=4)
  app['SESSION_BIG_THUMBS'] = session_big_thumbs = aiohttp.ClientSession(connector=conn_big_thumbs, trust_env=trust_env)

  conn_assets = aiohttp.TCPConnector(ssl=sslcontext, limit=2)
  app['SESSION_ASSETS'] = session_assets = aiohttp.ClientSession(connector=conn_assets, trust_env=trust_env)

  yield
  await asyncio.gather(
    conn_api_requests.close(),
    session_api_requests.close(),

    conn_small_thumbs.close(),
    session_small_thumbs.close(),

    conn_big_thumbs.close(),
    session_big_thumbs.close(),

    conn_assets.close(),
    session_assets.close(),
  )

async def should_i_live(app: web.Application):
  while True:
    since_report = time.time() - globals.last_report_time
    if since_report > globals.TIMEOUT:
      sys.exit() #we should handle this more nicely
    await asyncio.sleep(10)

async def report_blender_quit(request: web_request.Request):

  data = await request.json()
  if data['app_id'] in globals.active_apps:
    globals.active_apps.remove(data['app_id'])
  if len(globals.active_apps)==0:
    print('no more apps to serve, exiting Daemon')
    sys.exit() #we should handle this more nicely

async def start_background_tasks(app: web.Application):
  app['should_i_live'] = asyncio.create_task(should_i_live(app))


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument('--port', type=str, default="10753")
  parser.add_argument('--proxy-which', type=str, default="SYSTEM")
  parser.add_argument('--proxy-address', type=str, default="")
  parser.add_argument('--proxy-ca-certs', type=str, default="")
  args = parser.parse_args()
  globals.PORT = args.port

  server = web.Application()
  server['PROXY_WHICH'] = args.proxy_which
  server['PROXY_ADDRESS'] = args.proxy_address
  server['PROXY_CA_CERTS'] = args.proxy_ca_certs

  server.cleanup_ctx.append(persistent_sessions)
  server.add_routes([
    web.get('/', index),
    web.get('/report', report),
    web.get('/kill_download', kill_download),
    web.post('/download_asset', download_asset),
    web.post('/search_asset', search_assets),
    web.view('/shutdown', Shutdown),
    web.view('/report_blender_quit', report_blender_quit),
    web.get('/consumer/exchange/', consumer_exchange),
    web.get('/refresh_token', refresh_token),
  ])

  server.on_startup.append(start_background_tasks)
  web.run_app(server, host='127.0.0.1', port=args.port)
