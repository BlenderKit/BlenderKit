import asyncio
import concurrent.futures
import logging
import os
import queue
import sys
import threading
import time

import bpy
import requests

from . import colors, daemon_lib, download, reports, search
from .daemon import tasks


logger = logging.getLogger(__name__)

# pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.
pending_tasks = list()
reader_loop = None
ENABLE_ASYNC_LOOP =False

reports_queue = queue.Queue()


@bpy.app.handlers.persistent
def timer():
  """Recieve all responses from daemon and run according followup commands."""

  mt = time.time()
  global pending_tasks

  search.check_clipboard()

  app_id = os.getpid()
  results = list()

  if ENABLE_ASYNC_LOOP:
    global reports_queue
    # print('checking queue', daemon_lib.reports_queue.empty())
    while not reports_queue.empty():
      queue_result = reports_queue.get()
      print('from queue', queue_result)
      results.extend(queue_result)
    kick_async_loop()
    asyncio.ensure_future(daemon_lib.get_reports_async(app_id, reports_queue))
  else:
    results = daemon_lib.get_reports(app_id)

  results.extend(pending_tasks)
  logger.debug(f'timer before {mt-time.time()}')
  pending_tasks.clear()
  for task in results:
    task = tasks.Task(
      data = task['data'],
      task_id = task['task_id'],
      app_id = task['app_id'],
      task_type = task['task_type'],
      message = task['message'],
      progress = task['progress'],
      status = task['status'],
      result = task['result'],
      )
    handle_task(task)
    

  # print('timer',time.time()-mt)
  logger.debug(f'timer {mt-time.time()}')
  if len(download.download_tasks) > 0:
    return .2
  return .5

@bpy.app.handlers.persistent
def timer_image_cleanup():
  imgs = bpy.data.images[:]
  for i in imgs:
    if (i.name[:11] == '.thumbnail_' or i.filepath.find('bkit_g')>-1) and not i.has_data and i.users == 0:
      bpy.data.images.remove(i)
  return 60

def cancel_all_tasks(self, context):
  """Cancel all tasks."""

  global pending_tasks
  pending_tasks.clear()
  download.clear_downloads()
  search.clear_searches()

def handle_task(task: tasks.Task):
  """Handle incomming task information. Sort tasks by type and call apropriate functions."""
  
  #HANDLE ASSET DOWNLOAD
  if task.task_type == 'asset_download':
    download.handle_download_task(task)
    
  #HANDLE SEARCH (candidate to be a function)
  if task.task_type == 'search':
    if task.status == 'finished':
      search.handle_search_task(task)

    elif task.status == 'error':
      reports.add_report(task.message, 15, colors.RED)

  #HANDLE THUMBNAIL DOWNLOAD (candidate to be a function)
  if task.task_type == 'thumbnail_download':
    if task.status == 'finished':
      search.handle_preview_task(task)
    elif task.status == 'error':
      reports.add_report(task.message, 15, colors.RED)


def setup_asyncio_executor():
  """Set up AsyncIO to run properly on each platform."""

  if sys.platform == 'win32':
    asyncio.get_event_loop().close()
    # On Windows, the default event loop is SelectorEventLoop, which does
    # not support subprocesses. ProactorEventLoop should be used instead.
    # Source: https://docs.python.org/3/library/asyncio-subprocess.html
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
  else:
    loop = asyncio.get_event_loop()

  executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
  loop.set_default_executor(executor)
  # loop.set_debug(True)


def kick_async_loop(*args) -> bool:
  """Perform a single iteration of the asyncio event loop."""

  loop = asyncio.get_event_loop()
  loop.stop()
  loop.run_forever()

  return True#stop_after_this_kick

def start_server_thread():
  with requests.Session() as session:
    daemon_lib.ensure_daemon_alive(session)


def register_timer():
  if ENABLE_ASYNC_LOOP:
    setup_asyncio_executor()
  if not bpy.app.background:
    bpy.app.timers.register(timer, persistent=True, first_interval=3)
    bpy.app.timers.register(timer_image_cleanup, persistent=True, first_interval=60)

  thread = threading.Thread(target=start_server_thread, args=(), daemon=True)
  thread.start()

def unregister_timer():
  if bpy.app.timers.is_registered(timer):
    bpy.app.timers.unregister(timer)
    bpy.app.timers.unregister(timer_image_cleanup)
