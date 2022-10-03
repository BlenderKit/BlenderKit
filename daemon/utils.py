"""Contains utility functions for daemon server. Mix of everything."""

import platform
import re
import sys

import globals


def get_headers(api_key: str = '') -> dict[str, str]:
  """Get headers with authorization."""

  headers = {
    'accept': 'application/json',
    'Platform-Version': platform.platform(),
    'system-id': globals.SYSTEM_ID,
    'addon-version': globals.VERSION,
  }
  if api_key != '':
    headers['Authorization'] = f'Bearer {api_key}'

  return headers


def slugify(slug: str) -> str:
  """Normalizes string, converts to lowercase, removes non-alpha characters, and converts spaces to hyphens."""

  slug = slug.lower()
  characters = '<>:"/\\|?\*., ()#'
  for ch in characters:
    slug = slug.replace(ch, '_')
  # import re
  # slug = unicodedata.normalize('NFKD', slug)
  # slug = slug.encode('ascii', 'ignore').lower()
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
