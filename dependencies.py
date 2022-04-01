
import subprocess
import sys
import time
from os import makedirs, path


def add_dependencies():
  """Add dependencies directory into path."""

  dependencies_path = get_dependencies_path()
  makedirs(dependencies_path, exist_ok=True)
  sys.path.insert(0, dependencies_path)

def get_dependencies_path():
  """Get path to dependencies directory. Here we will install and search for external modules."""

  fallback_path = path.join(path.dirname(__file__), "dependencies")

  return path.abspath(fallback_path)

def ensure_dependencies():
  """Make sure that dependencies which need installation are available. Install dependencies if needed."""

  tried = 0
  while tried < 2:
    tried = tried + 1
    try:
      import aiohttp
      del aiohttp
      return
    except:
      started = time.time()
      requirements = path.join(path.dirname(__file__), 'requirements.txt')
      ok = subprocess.call([sys.executable, '-m', 'ensurepip'])
      print(f"Ensure pip exited: {ok}")

      ok = subprocess.call([sys.executable, '-m', 'pip', 'install', '-t', get_dependencies_path(), '-r', requirements])
      print(f"Aiohttp install exited: {ok}")
      print(f"Install finished in {time.time()-started}")


