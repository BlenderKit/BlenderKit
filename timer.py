import bpy
from . import daemon_lib, tasks_queue, reports, download, search
import os
import time
import threading
import requests
import asyncio
import concurrent.futures
import queue
# pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.
pending_tasks = dict()
reader_loop = None
ENABLE_ASYNC_LOOP =False

reports_queue = queue.Queue()



@bpy.app.handlers.persistent
def timer():
  '''
  Recieves all responses from daemon and runs according followup commands
  '''
  mt = time.time()
  global pending_tasks

  search.check_clipboard()

  data = {
    'app_id': os.getpid(),
  }
  results = dict()

  if ENABLE_ASYNC_LOOP:
    global reports_queue
    # print('checking queue', daemon_lib.reports_queue.empty())
    while not reports_queue.empty():
      queue_result = reports_queue.get()
      print('from queue', queue_result)
      results.update(queue_result)
    kick_async_loop()
    asyncio.ensure_future(daemon_lib.get_reports_async(data, reports_queue))
  else:
    results = daemon_lib.get_reports(data)

  results.update(pending_tasks)
  print('timer before', mt-time.time())
  pending_tasks = dict()
  for key, value in results.items():
    # print(key,value)
    if value['type'] == 'error-report':
      reports.add_report(value['text'], timeout=value['timeout'])
    if value['type'] == 'download-progress':
      download.download_write_progress(key, value)
    if value['type'] == 'download-finished':
      appended = download.download_post(value)
      if not appended:
        pending_tasks[key] = value
    if value['type'] == 'search-finished':
      parsed = search.search_post(key,value)
      if not parsed:
        pending_tasks[key] = value
    if value['type'] == 'thumbnail-available':
      pass

  # print('timer',time.time()-mt)
  print('timer',mt-time.time())
  if len(download.download_tasks) > 0:
    return .2
  return .5



def setup_asyncio_executor():
    """Sets up AsyncIO to run properly on each platform."""

    import sys

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
    """Performs a single iteration of the asyncio event loop.
    """

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

  thread = threading.Thread(target=start_server_thread, args=(), daemon=True)
  thread.start()

def unregister_timer():
  if bpy.app.timers.is_registered(timer):
    bpy.app.timers.unregister(timer)
