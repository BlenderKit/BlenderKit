
import time
import subprocess
from os import path, makedirs
import sys
import platform

def add_vendored():
  """Add vendored modules directory and fallback directory into path."""

  vendor_path = get_vendor_path()
  fallback_path = get_vendor_fallback_path()
  makedirs(vendor_path, exist_ok=True)
  makedirs(fallback_path, exist_ok=True)
  sys.path.insert(0, vendor_path)
  sys.path.insert(0, fallback_path)

def get_vendor_path() -> str:
  """Get path to pre-installed modules for current platform: vendor/Windows, vendor/Darwin or vendor/Linux."""

  directory = f"vendor/{platform.system()}"
  vendor_path = path.join(path.dirname(__file__), directory)

  return path.abspath(vendor_path)

def get_vendor_fallback_path():
  """Get path to fallback directory in vendor. Here we will install and search for modules if needed if vendored modules did not succeeded."""

  directory = "vendor/Fallback"
  fallback_path = path.join(path.dirname(__file__), directory)
  
  return path.abspath(fallback_path)

def ensure_dependencies():
  """Make sure that dependencies which need installation are available. Install dependencies if needed."""

  tried = 0
  while tried < 2:
    tried = tried + 1
    try:
      import aiohttp
      break
    except:
      started = time.time()
      requirements = path.join(path.dirname(__file__), 'requirements.txt')
      ok = subprocess.call([sys.executable, '-m', 'ensurepip'])
      print(f"Ensure pip exited: {ok}")

      fallback_dir = get_vendor_fallback_path()
      ok = subprocess.call([sys.executable, '-m', 'pip', 'install', '-t', fallback_dir, '-r', requirements])
      print(f"Aiohttp install exited: {ok}")
      print(f"Install finished in {time.time()-started}")

  del aiohttp
