
import logging
import platform
import shutil
import subprocess
import sys
import time
from os import environ, makedirs, path, pathsep


from . import global_vars
from .daemon_lib import get_daemon_directory_path


bk_logger = logging.getLogger(__name__)


def ensure_preinstalled_deps_copied():
  """Copy dependencies for current platform into global_dir/dependencies-3.x.y/installed"""

  deps_path = path.join(path.dirname(__file__), f"dependencies/{platform.system()}")
  deps_path = path.abspath(deps_path)

  shutil.copytree(deps_path, get_preinstalled_deps_path(), dirs_exist_ok=True)


def get_deps_directory_path() -> str:
  """Get path where dependencies (preinstalled and installed) should/are installed for this version of addon."""

  daemon_directory = get_daemon_directory_path()
  version = f'{global_vars.VERSION[0]}-{global_vars.VERSION[1]}-{global_vars.VERSION[2]}'
  install_path = path.join(daemon_directory, 'dependencies', version) #TODO: fetch version dynamically
  return path.abspath(install_path)


def get_installed_deps_path() -> str:
  """Get path to installed dependencies directory. Here addon will install external modules if needed."""

  installed_path = path.join(get_deps_directory_path(), 'installed')
  return path.abspath(installed_path)


def get_preinstalled_deps_path() -> str:
  """Get path to preinstalled modules for current platform: global-dir/dependencies_3-x-y/installed."""

  vendor_path = path.join(get_deps_directory_path(), 'preinstalled')
  return path.abspath(vendor_path)


def add_installed_deps():
  """Add installed dependencies directory into PATH."""

  dependencies_path = get_installed_deps_path()
  makedirs(dependencies_path, exist_ok=True)
  sys.path.insert(0, dependencies_path)

def add_preinstalled_deps():
  """Add preinstalled dependencies directory into PATH."""

  installed_path = get_preinstalled_deps_path()
  makedirs(installed_path, exist_ok=True)
  sys.path.insert(0, installed_path)


def ensure_deps():
  """Make sure that dependencies which need installation are available. Install dependencies if needed."""

  tried = 0
  while tried < 2:
    tried = tried + 1
    try:
      import aiohttp
      import certifi
      from aiohttp import web, web_request
      return
    except:
      install_dependencies()

def install_dependencies():
  """Install pip and install dependencies."""

  started = time.time()

  env  = environ.copy()
  if platform.system() == "Windows":
    env['PATH'] = env['PATH'] + pathsep + path.abspath(path.dirname(sys.executable) + "/../../../blender.crt")

  command = [sys.executable, '-m', 'ensurepip', '--user']
  result = subprocess.run(command, env=env, capture_output=True, text=True)
  bk_logger.warn(f"PIP INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")

  requirements = path.join(path.dirname(__file__), 'requirements.txt')
  command = [sys.executable, '-m', 'pip', 'install', '--upgrade', '-t', get_installed_deps_path(), '-r', requirements]
  result = subprocess.run(command, env=env, capture_output=True, text=True)
  bk_logger.warn(f"AIOHTTP INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")
  if result.returncode == 0:
    bk_logger.info(f"Install succesfully finished in {time.time()-started}")
    return

  bk_logger.warn(f"Install from requirements.txt failed, trying with unconstrained versions...")
  command = [sys.executable, '-m', 'pip', 'install', '--upgrade', '-t', get_installed_deps_path(), 'aiohttp', 'certifi']
  result = subprocess.run(command, env=env, capture_output=True, text=True)
  bk_logger.info(f"UNCONSTRAINED INSTALLATION:\ncommand {command} exited: {result.returncode},\nstdout: {result.stdout},\nstderr: {result.stderr}")
  if result.returncode == 0:
    bk_logger.info(f"Install succesfully finished in {time.time()-started}")
    return
  
  bk_logger.critical(f"Installation failed")
