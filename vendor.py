
import time
import subprocess
from os import path
import sys
import platform

def add_vendored():
  """Add directory with vendored packages to path."""

  sys.path.insert(0, get_vendor_path())

def get_vendor_path() -> str:

  system = platform.system()
  
  directory = f"vendor/{system}"
  vendor_path = path.join(path.dirname(__file__), directory)

  return path.abspath(vendor_path)

def ensure_dependencies():
  """Make sure that dependencies which need installation are available. Install dependencies if needed."""

  try:
    import aiohttp
  except:
    started = time.time()
    requirements = path.join(path.dirname(__file__), 'requirements.txt')
    ok = subprocess.call([sys.executable, '-m', 'ensurepip'])
    print(f"Ensure pip: {ok}")
    ok = subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', requirements])

    print(f"Aiohttp install: {ok}")

    import aiohttp
    ended = time.time()
    print(f"install finished in {ended-started}")
  
  del aiohttp
