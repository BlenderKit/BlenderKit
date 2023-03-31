"""Main module (starting point) for daemon server. From here all other modules are imported.
Uses exit codes to signal different error types. Their meaning is defined and handled at daemon_lib.check_daemon_exit_code().
"""

import asyncio
from argparse import ArgumentParser
from logging import getLogger
from os import environ, getpid
from platform import system
from signal import SIGINT, raise_signal
from socket import AF_INET, SO_REUSEADDR, SOL_SOCKET, socket
from ssl import PROTOCOL_TLS_CLIENT, Purpose, SSLContext, create_default_context
from sys import stdout
from time import time
from uuid import uuid4


stdout.reconfigure(encoding='utf-8')
logger = getLogger('bk_daemon')

try:
  import aiohttp
  from aiohttp import web
except Exception as e:
  logger.error(f'{e}')
  exit(101)

try:
  import certifi
except Exception as e:
  logger.error(f'{e}')
  exit(102)

import assets
import comments
import configurator
import disclaimer
import globals
import oauth
import profiles
import tasks
import uploads

import ratings
import search
import utils


PORTS = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]


async def download_asset(request: web.Request):
  """Handle request for download of asset."""
  data = await request.json()
  task_id = str(uuid4())
  data['task_id'] = task_id #mozna k nicemu

  app_id = data['app_id']
  del data['app_id']
  
  task = tasks.Task(data, app_id, 'asset_download', task_id, message='Looking for asset')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(assets.do_asset_download(request, task))
  task.async_task.add_done_callback(tasks.handle_async_errors)
  
  return web.json_response({'task_id': task_id})


async def search_assets(request: web.Request):
  """Handle request for download of asset."""
  data = await request.json()
  task_id = str(uuid4())
  data['task_id'] = task_id #mozna k nicemu
  app_id = data['app_id']
  del data['app_id']

  task = tasks.Task(data, app_id, 'search', task_id, message='Searching assets')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(search.do_search(request, task))
  task.async_task.add_done_callback(tasks.handle_async_errors)

  return web.json_response({'task_id': task_id})


async def upload_asset(request: web.Request):
  """Handle request for upload of asset."""
  data = await request.json()  
  task_id = str(uuid4())
  app_id = data.pop('app_id')

  task = tasks.Task(data, app_id, 'asset_upload', task_id, message='Asset upload has started')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(uploads.do_upload(request, task))
  task.async_task.add_done_callback(tasks.handle_async_errors)

  return web.json_response({'task_id': task_id})


async def index(request: web.Request):
  """Report PID of server as Index page, can be used as is-alive endpoint."""
  pid = str(getpid())
  return web.Response(text=pid)


async def consumer_exchange(request: web.Request):
  auth_code = request.rel_url.query.get('code', None)
  redirect_url = f'{globals.SERVER}/oauth-landing/'
  if auth_code is None:
    return web.Response(text="Authorization Failed. Authorization code was not provided.")

  response_json, status, error = await oauth.get_tokens(request, auth_code=auth_code)
  if status == -1:
    text=f"Authorization Failed. Server is not reachable. Response: {error}"
    return web.Response(text=text)
  
  if status != 200:
    text = f"Authorization Failed. Retrieval of tokens failed (status code: {status}). Response: {error}"
    return web.Response(text=text)

  for app_id in globals.active_apps:
    task = tasks.Task(None, app_id, 'login', message='Getting authorization code')
    globals.tasks.append(task)
    task.result = response_json
    task.finished("Tokens obtained")

  return web.HTTPPermanentRedirect(redirect_url)


async def refresh_token(request: web.Request):
  atask = asyncio.ensure_future(oauth.refresh_tokens(request))
  atask.add_done_callback(tasks.handle_async_errors)
  return web.Response(text="ok")


async def subscribe_new_addon(request: web.Request, data: dict):
  """Subscribe new add-on into list of active applications.
  Also run all tasks which are needed on add-on startup - will be reported back to add-on once finished.
  """
  globals.active_apps.append(data['app_id'])
  disclaimer_task = asyncio.ensure_future(disclaimer.get_disclaimer(request))
  disclaimer_task.add_done_callback(tasks.handle_async_errors)

  categories_task = asyncio.ensure_future(search.fetch_categories(request))
  categories_task.add_done_callback(tasks.handle_async_errors)
  if data['api_key'] == '':
    return #everything done, if not logged in

  notifications_task = asyncio.ensure_future(disclaimer.get_notifications(request))
  notifications_task.add_done_callback(tasks.handle_async_errors)


async def kill_download(request: web.Request):
  """Handle request for kill of task with the task_id."""
  data = await request.json()
  for i, task in enumerate(globals.tasks):
    if data['task_id'] == task.task_id:
      #globals.tasks[i].cancel() #needs to handle cleaning when download is cancelled
      del globals.tasks[i]
      break

  return web.Response(text="ok")


async def code_verifier(request: web.Request):
  """Gets code_verifier for OAuth login."""
  data = await request.json()
  globals.code_verifier = data['code_verifier']
  return web.Response(text="ok")


async def report(request: web.Request):
  """Report progress of all tasks for a given app_id. Clears list of tasks."""
  globals.last_report_time = time()
  data = await request.json()
  #check if the app was already active
  if data['app_id'] not in globals.active_apps:
    await subscribe_new_addon(request, data)

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

  status_report = tasks.Task({}, data['app_id'], 'daemon_status', result={'online_status': globals.online_status})
  reports.append(status_report.to_seriazable_object())
  reports.reverse()
  resp = web.json_response(reports)
  return resp


async def shutdown(request: web.Request):
  """Shedules shutdown of the server."""
  logger.info('Shutdown requested, exiting Daemon')
  raise_signal(SIGINT)
  return web.Response(text='Going to shutdown.')


async def report_blender_quit(request: web.Request):
  data = await request.json()
  logger.info(f"Blender quit (ID {data['app_id']}) was reported")
  if data['app_id'] in globals.active_apps:
    globals.active_apps.remove(data['app_id'])
  if len(globals.active_apps)==0:
    logger.info('No more apps to serve, exiting Daemon')
    raise_signal(SIGINT)

  return web.Response(text="ok") 


## BACKGROUND TASKS

async def life_check(app: web.Application):
  while True:
    since_report = time() - globals.last_report_time
    if since_report > globals.TIMEOUT:
      raise_signal(SIGINT)
    await asyncio.sleep(10)


async def online_status_check(app: web.Application):
  while True:
    globals.online_status = await utils.any_DNS_available()
    if globals.online_status == 200:
      await asyncio.sleep(3)
    else:
      await asyncio.sleep(1)


async def start_background_tasks(app: web.Application):
  app['life_check'] = asyncio.create_task(life_check(app))
  app['online_status_check'] = asyncio.create_task(online_status_check(app))


async def cleanup_background_tasks(app: web.Application):
  try:
    app['life_check'].cancel()
    app['online_status_check'].cancel()
  except Exception as e:
    logger.warning(f'BG tasks canceling failed: {e}')


## CONFIGURATION
def find_and_bind_socket(port: str) -> socket:
    """Try to bind a socket on defined port. If that fails, repeat on different
    ports until a bindable socket is found, binded and returned.
    If all possibilities fail, then exit the program.
    """
    i = PORTS.index(port)
    ports = PORTS[i:] + PORTS[:i]
    addrs = ['127.0.0.1', 'localhost', '0.0.0.0']
    for addr in addrs:
        for port in ports:
            try:
                sock = socket()
                sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                sock.bind((addr, int(port)))
                globals.PORT = int(port)
                return sock
            except Exception as e:
                logger.warning(f'error binding socket {addr}:{port} - {e}')
    logger.error('Unable to bind any socket')
    exit(111)

async def persistent_sessions(app):
  if globals.SSL_CONTEXT == "PRECONFIGURED":
    sslcontext = create_default_context()
  else:
    sslcontext = SSLContext(protocol=PROTOCOL_TLS_CLIENT)

  if app['PROXY_CA_CERTS'] != '':
    sslcontext.load_verify_locations(app['PROXY_CA_CERTS'])
  sslcontext.load_verify_locations(certifi.where())
  try:
    sslcontext.load_default_certs(purpose=Purpose.CLIENT_AUTH)
  except Exception as e:
    logger.warning('failed to load default certs:', e)

  if app['PROXY_WHICH'] == 'SYSTEM':
    trust_env = True
  elif app['PROXY_WHICH'] == 'CUSTOM':
    trust_env = True
    environ["HTTPS_PROXY"] = app['PROXY_ADDRESS']
  else:
    trust_env = False

  if globals.IP_VERSION == 'IPv4':
    family = AF_INET
  else: # default value
    family = 0

  conn_api_requests = aiohttp.TCPConnector(ssl=sslcontext, limit=64, family=family)
  app['SESSION_API_REQUESTS'] = session_api_requests = aiohttp.ClientSession(connector=conn_api_requests, trust_env=trust_env)

  conn_small_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=16, family=family)
  app['SESSION_SMALL_THUMBS'] = session_small_thumbs = aiohttp.ClientSession(connector=conn_small_thumbs, trust_env=trust_env)
  
  conn_big_thumbs = aiohttp.TCPConnector(ssl=sslcontext, limit=8, family=family)
  app['SESSION_BIG_THUMBS'] = session_big_thumbs = aiohttp.ClientSession(connector=conn_big_thumbs, trust_env=trust_env)

  timeout = aiohttp.ClientTimeout(total=24*60*60) # 1 day
  conn_assets = aiohttp.TCPConnector(ssl=sslcontext, limit=4, family=family)
  app['SESSION_ASSETS'] = session_assets = aiohttp.ClientSession(connector=conn_assets, trust_env=trust_env, timeout=timeout)

  conn_uploads = aiohttp.TCPConnector(ssl=sslcontext, limit=4, family=family)
  app['SESSION_UPLOADS'] = session_uploads = aiohttp.ClientSession(connector=conn_uploads, trust_env=trust_env, timeout=timeout)

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

    conn_uploads.close(),
    session_uploads.close(),
  )


## MAIN

if __name__ == '__main__':
  utils.configure_loggers()
  parser = ArgumentParser()
  parser.add_argument('--port', type=str, default=PORTS[0])
  parser.add_argument('--server', type=str, default='https://www.blenderkit.com')
  parser.add_argument('--proxy_which', type=str, default='SYSTEM')
  parser.add_argument('--proxy_address', type=str, default='')
  parser.add_argument('--proxy_ca_certs', type=str, default='')
  parser.add_argument('--ip_version', type=str, default='BOTH')
  parser.add_argument('--ssl_context', type=str, default='DEFAULT')
  parser.add_argument('--system_id', type=str, default='')
  parser.add_argument('--version', type=str, default='')
  args = parser.parse_args()
  logger.info(f'Daemon (PID {getpid()}) initiated with {args}')

  globals.PORT = args.port
  globals.SERVER = args.server
  globals.IP_VERSION = args.ip_version
  globals.SSL_CONTEXT = args.ssl_context
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
    web.post('/upload_asset', upload_asset),
    web.view('/shutdown', shutdown),
    web.view('/report_blender_quit', report_blender_quit),
    web.get('/consumer/exchange/', consumer_exchange),
    web.get('/refresh_token', refresh_token),
    web.post('/code_verifier', code_verifier),
    web.post('/report_usages', assets.report_usages_handler),
    web.post('/comments/{func}', comments.comments_handler),
    web.post('/notifications/mark_notification_read', comments.mark_notification_read_handler),
    web.get('/wrappers/get_download_url', assets.get_download_url_wrapper),
    web.get('/wrappers/blocking_file_upload', assets.blocking_file_upload_handler),
    web.get('/wrappers/blocking_request', utils.blocking_request_handler),
    web.get('/wrappers/nonblocking_request', utils.nonblocking_request_handler),
    web.get('/profiles/fetch_gravatar_image', profiles.fetch_gravatar_image_handler),
    web.get('/profiles/get_user_profile', profiles.get_user_profile_handler),
    web.get('/ratings/get_rating', ratings.get_rating_handler),
    web.post('/ratings/send_rating', ratings.send_rating_handler),
    web.get('/ratings/get_bookmarks', ratings.get_bookmarks_handler),
    web.get('/debug', configurator.debug_handler),
  ])

  server.on_startup.append(start_background_tasks)
  server.on_cleanup.append(cleanup_background_tasks)

  sock = find_and_bind_socket(args.port)
  try:
    web.run_app(server, sock=sock)
  except OSError as e:
    if system() == "Windows":
      if e.winerror == 121: exit(121)
    if e.errno == 10013: exit(113)
    if e.errno == 10014: exit(114)
    if e.errno == 48: exit(148)
    if e.errno == 10048: exit(149)
    exit(110)
  except Exception: exit(100)

  sock.close()
  logger.info('Daemon script has ended.')
