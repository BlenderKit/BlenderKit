"""Contains utility functions for daemon server. Mix of everything."""

import platform
import re
import sys
from pathlib import Path

import aiohttp
import globals


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
  if api_key == None:
    return headers

  headers['Authorization'] = f'Bearer {api_key}'
  return headers


def dict_to_params(inputs, parameters=None):
  if parameters == None:
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


async def download_file(url: str, destination: str, session: aiohttp.ClientSession, api_key: str=''):
  """Download a file from url into destination on the disk, creates directory structure if needed.
  With api_key the request will be authorized for BlenderKit server.
  """
  parent_dir = Path(destination).parent.mkdir(parents=True, exist_ok=True)
  headers = get_headers(api_key)
  async with session.get(url, headers=headers) as resp:
    if resp.status != 200:
      raise Exception(f"File download error: {resp.status}")
    with open(destination, 'wb') as file:
      async for chunk in resp.content.iter_chunked(4096 * 32):
        file.write(chunk)
