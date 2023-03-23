"""Contains utility functions for daemon server. Mix of everything."""

import asyncio
import platform
import re
import sys
from logging import Formatter, StreamHandler, basicConfig, getLogger
from pathlib import Path
from socket import AF_INET

import aiohttp
import globals
import tasks
from aiohttp import web


logger = getLogger(__name__)

def get_headers(api_key: str = '') -> dict[str, str]:
  """Get headers with or without authorization."""
  headers = {
    'accept': 'application/json',
    'Platform-Version': platform.platform(),
    'system-id': globals.SYSTEM_ID,
    'addon-version': globals.VERSION,
  }
  if api_key == '':
    return headers
  if api_key is None:
    return headers

  headers['Authorization'] = f'Bearer {api_key}'
  return headers


def dict_to_params(inputs, parameters=None):
  if parameters is None:
    parameters = []
  for k in inputs.keys():
    if type(inputs[k]) == list:
      strlist = ""
      for idx, s in enumerate(inputs[k]):
        strlist += s
        if idx < len(inputs[k]) - 1:
          strlist += ','

      value = "%s" % strlist
    elif type(inputs[k]) != bool:
      value = inputs[k]
    else:
      value = str(inputs[k])
    parameters.append(
      {
        "parameterType": k,
        "value": value
      })
  return parameters


def slugify(slug: str) -> str:
  """Normalizes string, converts to lowercase, removes non-alpha characters, and converts spaces to hyphens."""
  slug = slug.lower()
  characters = '<>:"/\\|?\*., ()#'
  for ch in characters:
    slug = slug.replace(ch, '_')
  slug = re.sub(r'[^a-z0-9]+.- ', '-', slug).strip('-')
  slug = re.sub(r'[-]+', '-', slug)
  slug = re.sub(r'/', '_', slug)
  slug = re.sub(r'\\\'\"', '_', slug)
  if len(slug) > 50:
    slug = slug[:50]

  return slug


def get_process_flags():
  """Get proper priority flags so background processess can run with lower priority."""
  ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
  BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
  HIGH_PRIORITY_CLASS = 0x00000080
  IDLE_PRIORITY_CLASS = 0x00000040
  NORMAL_PRIORITY_CLASS = 0x00000020
  REALTIME_PRIORITY_CLASS = 0x00000100
  flags = BELOW_NORMAL_PRIORITY_CLASS
  if sys.platform != 'win32':  # TODO test this on windows
    flags = 0
  return flags


async def message_to_addon(app_id:str, message:str, destination:str='GUI', level:str='INFO', duration:int=5):
  """Send message to addon's GUI or to its console.
  level can be INFO, WARNING, ERROR.
  destination can be GUI or CONSOLE.
  duration is in seconds, only for GUI messages.
  """
  print(f'Sending {level} message to add-on {destination}: {message} (PID{app_id})')
  result = {
    'destination': destination,
    'level': level,
    'duration': duration,
  }
  message_task = tasks.Task(
    app_id=app_id,
    message = message,
    task_type='message_from_daemon',
    result=result,
    status='finished',
    progress=100,
    data={},
    )
  globals.tasks.append(message_task)


async def download_file(url: str, destination: str, session: aiohttp.ClientSession, api_key: str=''):
  """Download a file from url into destination on the disk, creates directory structure if needed.
  With api_key the request will be authorized for BlenderKit server.
  """
  Path(destination).parent.mkdir(parents=True, exist_ok=True)
  headers = get_headers(api_key)
  async with session.get(url, headers=headers) as resp:
    if resp.status != 200:
      raise Exception(f"File download error: {resp.status}")
    with open(destination, 'wb') as file:
      async for chunk in resp.content.iter_chunked(4096 * 32):
        file.write(chunk)


async def blocking_request_handler(request: web.Request):
  """Handle request for blocking HTTP request.
  Function do not return until results are available. No task is created.
  """
  data = await request.json()
  session = request.app['SESSION_API_REQUESTS']
  try:
    async with session.request(data['method'], data['url'], headers=data['headers'], json=data.get('json')) as resp:
        data = await resp.json()
        return web.json_response(data)
  except Exception as e:
    logger.error(f'{e}')
    return web.Response(status=resp.status, text=str(e))


async def nonblocking_request_handler(request: web.Request):
    """Handle request for nonblocking HTTP request."""
    data = await request.json()
    task = tasks.Task(data, data['app_id'], 'wrappers/nonblocking_request')
    globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(make_request(request, task))
    task.async_task.add_done_callback(tasks.handle_async_errors)
    return web.json_response({'task_id': task.task_id})


async def make_request(request: web.Request, task: tasks.Task):
    session = request.app['SESSION_API_REQUESTS']
    url = task.data.get('url')
    method = task.data.get('method')
    headers = task.data.get('headers')
    json_data = task.data.get('json')
    messages = task.data.get('messages', {})
    error_message = messages.get("error", "Request failed")
    success_message = messages.get("success", "Request succeeded")
    try:
        async with session.request(method, url, headers=headers, json=json_data, raise_for_status=True) as resp:
            if resp.content_type == 'application/json':
                task.result = await resp.json()
            else:
                task.result = await resp.text()
            return task.finished(success_message)
    except aiohttp.ClientResponseError as e:
        return task.error(f'{error_message}: {e.message} ({e.code})')
    except Exception as e:
        return task.error(f'{error_message}: {e}')


def get_formatter():
  """Get default formatter for daemon loggers."""
  return Formatter(fmt='%(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]', datefmt='%H:%M:%S')


def configure_logger():
  """Configure 'bk_daemon' logger to which all other logs defined as `logger = logging.getLogger(__name__)` writes.
  Sets it logging level to `globals.LOGGING_LEVEL_DAEMON`.
  """
  basicConfig(level=globals.LOGGING_LEVEL_DAEMON)
  logger = getLogger("bk_daemon")
  logger.propagate = False
  logger.handlers = []
  handler = StreamHandler()
  handler.stream = sys.stdout #517
  handler.setFormatter(get_formatter())
  logger.addHandler(handler)


def configure_imported_loggers():
  """Configure loggers for imported modules so they can have different logging level `globals.LOGGING_LEVEL_IMPORTED`
  than main bk_daemon logger."""
  aiohttp_logger = getLogger("aiohttp")
  aiohttp_logger.propagate = False
  aiohttp_logger.handlers = []
  aiohttp_handler = StreamHandler()
  aiohttp_handler.stream = sys.stdout #517
  aiohttp_handler.setLevel(globals.LOGGING_LEVEL_IMPORTED)
  aiohttp_handler.setFormatter(get_formatter())
  aiohttp_logger.addHandler(aiohttp_handler)


def configure_loggers():
  """Configure all loggers for BlenderKit addon. See called functions for details."""
  configure_logger()
  configure_imported_loggers()


async def any_DNS_available():
    """Check if any DNS server is available."""
    PORT = 53
    TIMEOUT = 1
    for i, HOST in enumerate(globals.DNS_HOSTS):
        try:         
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(HOST, PORT, family=AF_INET),
                timeout=TIMEOUT)
            writer.close()
            await writer.wait_closed()
            if i > 0:
               globals.DNS_HOSTS = [globals.DNS_HOSTS[i],] + globals.DNS_HOSTS[:i] + globals.DNS_HOSTS[i+1:]  
            return 200
        except Exception as e:
            if i >= 2:
                globals.DNS_HOSTS = globals.DNS_HOSTS[i:] + globals.DNS_HOSTS[:i]
                logger.warning(f"DNS check failed: {e}")
                return str(e)
