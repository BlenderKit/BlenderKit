
import platform
import subprocess
import sys
import time
from os import makedirs, path


def add_fallback():
  """Add dependencies directory into PATH."""

  dependencies_path = get_fallback_path()
  makedirs(dependencies_path, exist_ok=True)
  sys.path.insert(0, dependencies_path)

def get_fallback_path():
  """Get path to fallback dependencies directory. Here addon will install external modules if needed. Located at dependencies/Fallback."""

  directory = "dependencies/Fallback"
  fallback_path = path.join(path.dirname(__file__), directory)
  return path.abspath(fallback_path)

def add_vendored():
  """Add vendored modules directory into PATH. It contains pre-installed dependency modules. Located at dependencies/Windows, dependencies/Darwin or dependencies/Linux."""

  vendored_path = get_vendored_path()
  makedirs(vendored_path, exist_ok=True)
  sys.path.insert(0, vendored_path)

def get_vendored_path() -> str:
  """Get path to pre-installed modules for current platform: dependencies/Windows, dependencies/Darwin or dependencies/Linux."""

  directory = f"dependencies/{platform.system()}"
  vendor_path = path.join(path.dirname(__file__), directory)
  return path.abspath(vendor_path)

def ensure_deps():
  """Make sure that dependencies which need installation are available. Install dependencies if needed."""

  tried = 0
  while tried < 2:
    tried = tried + 1
    try:
      import aiohttp
      import certifi
      return
    except:
      install_dependencies()

def install_dependencies():
  """Install pip and install dependencies."""

  started = time.time()

  command = [sys.executable, '-m', 'ensurepip', '--user']
  result = subprocess.run(command, capture_output=True, text=True)
  print(f"PIP INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")

  requirements = path.join(path.dirname(__file__), 'requirements.txt')
  command = [sys.executable, '-m', 'pip', 'install', '--upgrade', '-t', get_fallback_path(), '-r', requirements]
  result = subprocess.run(command, capture_output=True, text=True)
  print(f"AIOHTTP INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")
  if result.returncode == 0:
    print(f"Install succesfully finished in {time.time()-started}")
    return

  print(f"Install from requirements.txt failed, trying with unconstrained versions...")
  command = [sys.executable, '-m', 'pip', 'install', '--upgrade', '-t', get_fallback_path(), 'aiohttp', 'certifi']
  result = subprocess.run(command, capture_output=True, text=True)
  print(f"UNCONSTRAINED INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")
  if result.returncode == 0:
    print(f"Install succesfully finished in {time.time()-started}")
    return
  
  print(f"Installation failed")
