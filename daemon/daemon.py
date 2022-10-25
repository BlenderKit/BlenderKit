"""Main module (starting point) for daemon server. From here all other modules are imported.
Uses exit codes to signal different error types. Their meaning is defined and handled at daemon_lib.check_daemon_exit_code().
"""

import argparse
import asyncio
import logging
import os
import socket
import ssl
import time
import uuid
from ssl import Purpose


logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s [%(filename)s:%(lineno)d]', datefmt='%H:%M:%S')

try:
  import aiohttp
  from aiohttp import web, web_request
except Exception as e:
  logging.ERROR(f'{e}')
  exit(101)

try:
  import certifi
except Exception as e:
  logging.ERROR(f'{e}')
  exit(102)

import assets
import disclaimer
import globals
import oauth
import tasks

import search


async def download_asset(request: web_request.Request):
  """Handle request for download of asset."""
  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu

  app_id = data['app_id']
  del data['app_id']
  
  task = tasks.Task(data, app_id, 'asset_download', task_id, message='Looking for asset')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))
  task.async_task.add_done_callback(tasks.handle_async_errors)
  
  return web.json_response({'task_id': task_id})


async def search_assets(request: web_request.Request):
  """Handle request for download of asset."""
  data = await request.json()
  task_id = str(uuid.uuid4())
  data['task_id'] = task_id #mozna k nicemu
  app_id = data['app_id']
  del data['app_id']

  task = tasks.Task(data, app_id, 'search', task_id, message='Searching assets')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(search.do_search(request, task))
  task.async_task.add_done_callback(tasks.handle_async_errors)

  return web.json_response({'task_id': task_id})


async def index(request: web_request.Request):
  """Report PID of server as Index page, can be used as is-alive endpoint."""
  pid = str(os.getpid())
  return web.Response(text=pid)


async def consumer_exchange(request: web_request.Request):
  auth_code = request.rel_url.query.get('code', None)
  redirect_url = f'{globals.SERVER}/oauth-landing/'
  if auth_code == None:
    return web.Response(text="Authorization Failed. Authorization code was not provided.")

  response_json, status, error = await oauth.get_tokens(request, auth_code=auth_code)
  if status == -1:
    return web.Response(text=f"Authorization Failed. Server is not reachable. Response: {error}")
  
  if status != 200:
    return web.Response(text=f"Authorization Failed. Retrieval of tokens failed (status code: {status}). Response: {error}")

  for app_id in globals.active_apps:
    task = tasks.Task(None, app_id, 'login', message='Getting authorization code')
    globals.tasks.append(task)
    task.result = response_json
    task.finished("Tokens obtained")

  return web.HTTPPermanentRedirect(redirect_url)


async def refresh_token(request: web_request.Request):
  atask = asyncio.ensure_future(oauth.refresh_tokens(request)) #TODO: Await errors here
  atask.add_done_callback(tasks.handle_async_errors)
  return web.Response(text="ok")


async def get_disclaimer(request: web_request.Request):
  atask = asyncio.ensure_future(disclaimer.get_disclaimer(request))
  atask.add_done_callback(tasks.handle_async_errors)
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


async def code_verifier(request: web_request.Request):
  """Gets code_verifier for OAuth login."""
  data = await request.json()
  globals.code_verifier = data['code_verifier']
  return web.Response(text="ok")


async def report(request: web_request.Request):
  """Report progress of all tasks for a given app_id. Clears list of tasks."""
  globals.last_report_time = time.time()
  data = await request.json()
  #check if the app was already active
  if data['app_id'] not in globals.active_apps:
    globals.active_apps.append(data['app_id'])

  reports = list()
  for task in reversed(globals.tasks): #reversed so removal doesn't skip items
    if task.app_id != data['app_id']:
      continue

    reports.append(task.to_seriazable_object())
    if task.status == "finished":
      globals.tasks.remove(task)
    if task.status == "error":
      print(f"{task.task_type.upper()} task error, taskID: {task.task_id}, appID: {task.app_id}, message: {task.message}, result: {task.result}, data: {task.data}")
      globals.tasks.remove(task)

  status_report = tasks.Task({}, data['app_id'], 'daemon_status', result= globals.servers_statuses)
  reports.append(status_report.to_seriazable_object())
  reports.reverse()

  return web.json_response(reports)


async def shutdown(request: web_request.Request):
  """Shedules shutdown of the server."""
  logging.warning('Shutdown requested, exiting Daemon')
  asyncio.ensure_future(shutdown_daemon(request.app))
  return web.Response(text='Going to shutdown.')


async def report_blender_quit(request: web_request.Request):
  data = await request.json()
  logging.warning(f"Blender quit (ID {data['app_id']}) was reported")
  if data['app_id'] in globals.active_apps:
    globals.active_apps.remove(data['app_id'])
  if len(globals.active_apps)==0:
    logging.warning('No more apps to serve, exiting Daemon')
    asyncio.ensure_future(shutdown_daemon(request.app))

  return web.Response(text="ok") 


## BACKGROUND TASKS

async def life_check(app: web.Application):
  while True:
    since_report = time.time() - globals.last_report_time
    if since_report > globals.TIMEOUT:
      asyncio.ensure_future(shutdown_daemon(app))
    await asyncio.sleep(10)


async def online_status_check(app: web.Application, server: str):
  while True:
    try:
      resp = await app['SESSION_API_REQUESTS'].head("https://www.blenderkit.com/static/img/blenderkit-logo-hexa-256x296.png", timeout=3) #QUICK FIX, NEEDS TO BE RESOLVED
      globals.servers_statuses[server] = resp.status
      if resp.status != 200:
        logging.warning(f'{server}: status code {resp.status}')
    except Exception as e:
        logging.warning(f'{server}: request failed')
        globals.servers_statuses[server] = f'{e}'
    finally:
      resp.close()

    await asyncio.sleep(60)


async def start_background_tasks(app: web.Application):
  app['life_check'] = asyncio.create_task(life_check(app))
  for i, server in enumerate(globals.servers_statuses):
    app[f'online-status-check-{i}'] = asyncio.create_task(online_status_check(app, server))


async def cleanup_background_tasks(app: web.Application):
  app['life_check'].cancel()
  for i, _ in enumerate(globals.servers_statuses):
    app[f'online-status-check-{i}'].cancel()
  exit(0)


async def shutdown_daemon(app: web.Application):
  await app.shutdown()
  await app.cleanup()


## CONFIGURATION

async def persistent_sessions(app):
  sslcontext = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
  
  if app['PROXY_CA_CERTS'] != '':
    sslcontext.load_verify_locations(app['PROXY_CA_CERTS'])
  sslcontext.load_verify_locations(certifi.where())
  try:
    sslcontext.load_default_certs(purpose=Purpose.CLIENT_AUTH)
  except Exception as e:
    logging.warning('failed to load default certs:', e)

  if app['PROXY_WHICH'] == 'SYSTEM':
    trust_env = True
  elif app['PROXY_WHICH'] == 'CUSTOM':
    trust_env = True
    os.environ["HTTPS_PROXY"] = app['PROXY_ADDRESS']
  else:
    trust_env = False

  if globals.IP_VERSION == 'IPv4':
    family = socket.AF_INET
  else: # default value
    family = 0

  conn_api_requests = aiohttp.TCPConnector(ssl=sslcontext, limit=64, family=family)
  app['SESSION_API_REQUESTS'] = session_api_requests = aiohttp.ClientSession(connector=conn_api_requests, trust_env=trust_env)

  conn_small_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=16, family=family)
  app['SESSION_SMALL_THUMBS'] = session_small_thumbs = aiohttp.ClientSession(connector=conn_small_thumbs, trust_env=trust_env)
  
  conn_big_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=8, family=family)
  app['SESSION_BIG_THUMBS'] = session_big_thumbs = aiohttp.ClientSession(connector=conn_big_thumbs, trust_env=trust_env)

  conn_assets = aiohttp.TCPConnector(ssl=sslcontext, limit=4, family=family)
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


## MAIN 

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--port', type=str, default='10753')
  parser.add_argument('--server', type=str, default='https://www.blenderkit.com')
  parser.add_argument('--proxy_which', type=str, default='SYSTEM')
  parser.add_argument('--proxy_address', type=str, default='')
  parser.add_argument('--proxy_ca_certs', type=str, default='')
  parser.add_argument('--ip_version', type=str, default='BOTH')
  parser.add_argument('--system_id', type=str, default='')
  parser.add_argument('--version', type=str, default='')
  args = parser.parse_args()

  globals.PORT = args.port
  globals.SERVER = args.server
  globals.IP_VERSION = args.ip_version
  globals.servers_statuses[args.server] = None
  globals.SYSTEM_ID = args.system_id
  globals.VERSION = args.version
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
    web.view('/shutdown', shutdown),
    web.view('/report_blender_quit', report_blender_quit),
    web.get('/consumer/exchange/', consumer_exchange),
    web.get('/refresh_token', refresh_token),
    web.get('/get_disclaimer', get_disclaimer),
    web.post('/code_verifier', code_verifier),
  ])

  server.on_startup.append(start_background_tasks)
  server.on_cleanup.append(cleanup_background_tasks)
  
  try:
    print(f'Starting with {args}')
    web.run_app(server, host='127.0.0.1', port=args.port)
  except OSError as e:
    # [Errno 10013] error while attempting to bind on address ('[host IP]', [port?]): An attempt was made to access a socket in a way forbidden by its access permissions
    if e.errno == 10013:
      logging.ERROR(f'Antivirus blocked Daemon: {e}')
      exit(113)
    else:
      logging.ERROR(f'Daemon start blocked by error: {e}')
      exit(100)
  except Exception as e:
    logging.ERROR(f'Daemon start blocked by error: {e}')
    exit(100)
