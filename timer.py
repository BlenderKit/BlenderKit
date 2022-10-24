import asyncio
import concurrent.futures
import logging
import os
import queue
import sys

import bpy

from . import (
    addon_updater_ops,
    bg_blender,
    bkit_oauth,
    categories,
    colors,
    daemon_lib,
    disclaimer_op,
    download,
    global_vars,
    reports,
    search,
    tasks_queue,
    utils,
)
from .daemon import tasks


bk_logger = logging.getLogger(__name__)
reports_queue = queue.Queue()
pending_tasks = list() # pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.
ENABLE_ASYNC_LOOP = False
start_count = 0

@bpy.app.handlers.persistent
def daemon_communication_timer():
  """Recieve all responses from daemon and run according followup commands.
  This function is the only one responsible for keeping the daemon up and running.
  """

  global start_count
  global pending_tasks
  bk_logger.debug('Getting tasks from daemon')
  search.check_clipboard()

  app_id = os.getpid()
  results = list()

  if ENABLE_ASYNC_LOOP:
    global reports_queue
    # print('checking queue', daemon_lib.reports_queue.empty())
    while not reports_queue.empty():
      queue_result = reports_queue.get()
      # print('from queue', queue_result)
      results.extend(queue_result)
    kick_async_loop()
    asyncio.ensure_future(daemon_lib.get_reports_async(app_id, reports_queue))
  else:
    wm = bpy.context.window_manager
    try:
      results = daemon_lib.get_reports(app_id)
      start_count = 0
    except Exception as e:
      global_vars.DAEMON_ACCESSIBLE = False
      
      if start_count < 3:
        start_count = start_count + 1
        daemon_lib.start_daemon_server()
        return start_count

      return_code, meaning = daemon_lib.check_daemon_exit_code()
      if return_code == None:
        reports.add_report(f'Daemon is not responding, add-on will not work.', 10, 'ERROR')
      else:
        reports.add_report(f'Daemon is not running, add-on will not work. Error({return_code}): {meaning}', 10, 'ERROR')

      bk_logger.warning(f'Could not get reports: {e}')
      wm.blenderkitUI.logo_status = "logo_offline"
      daemon_lib.start_daemon_server()
      return 30

    if global_vars.DAEMON_ACCESSIBLE != True:
      reports.add_report("Daemon is running!")
      global_vars.DAEMON_ACCESSIBLE = True
      wm.blenderkitUI.logo_status = "logo"

  results.extend(pending_tasks)
  bk_logger.debug('Handling tasks')
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

  bk_logger.debug('Task handling finished')
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

def save_prefs_cancel_all_tasks_and_restart_daemon(self, context):
  """Save preferences, cancel all daemon tasks and shutdown the daemon.
  The daemon_communication_timer will soon take care of starting the daemon again leading to a restart.
  """
  utils.save_prefs(self, context)
  reports.add_report("Restarting daemon server", 5, "INFO")
  try:
    cancel_all_tasks(self, context)
    daemon_lib.kill_daemon_server()
  except Exception as e:
    bk_logger.warning(str(e))

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
      reports.add_report(task.message, 15, 'ERROR')

  #HANDLE THUMBNAIL DOWNLOAD (candidate to be a function)
  if task.task_type == 'thumbnail_download':
    if task.status == 'finished':
      search.handle_preview_task(task)
    elif task.status == 'error':
      reports.add_report(task.message, 3, 'ERROR')

  #HANDLE LOGIN
  if task.task_type == "login":
    bkit_oauth.handle_login_task(task)

  #HANDLE DAEMON STATUS REPORT
  if task.task_type == "daemon_status":
    daemon_lib.handle_daemon_status_task(task)

  #HANDLE DISCLAIMER
  if task.task_type == "disclaimer":
    disclaimer_op.handle_disclaimer_task(task)

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


@bpy.app.handlers.persistent
def check_timers_timer():
  """Checks if all timers are registered regularly. Prevents possible bugs from stopping the addon."""

  if ENABLE_ASYNC_LOOP:
    setup_asyncio_executor()
  
  if not bpy.app.timers.is_registered(download.download_timer):
    bpy.app.timers.register(download.download_timer)
  if not bpy.app.timers.is_registered(tasks_queue.queue_worker):
    bpy.app.timers.register(tasks_queue.queue_worker)
  if not bpy.app.timers.is_registered(bg_blender.bg_update):
    bpy.app.timers.register(bg_blender.bg_update)
  if not bpy.app.timers.is_registered(daemon_communication_timer):
    bpy.app.timers.register(daemon_communication_timer, persistent=True)
  if not bpy.app.timers.is_registered(timer_image_cleanup):
    bpy.app.timers.register(timer_image_cleanup, persistent=True, first_interval=60)
  return 5.0

def on_startup_timer():
  """Run once on the startup of add-on."""
  addon_updater_ops.check_for_update_background()
  utils.ensure_system_ID()

  api_key = bpy.context.preferences.addons['blenderkit'].preferences.api_key
  categories.fetch_categories_thread(api_key)
  search.get_profile()


def on_startup_daemon_online_timer():
  """Run once when daemon is online after startup."""

  if global_vars.DAEMON_ONLINE:
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    if preferences.show_on_start:
      search.search()
    return

  return 1

def register_timers():
  """Registers all timers. 
  It registers check_timers_timer which registers all other periodic non-ending timers.
  And individually it register all timers which are expected to end.
  """

  if bpy.app.background:
    return

  #PERIODIC TIMERS
  bpy.app.timers.register(check_timers_timer, persistent=True) # registers all other non-ending timers
  
  #ONETIMERS
  bpy.app.timers.register(on_startup_timer)
  bpy.app.timers.register(on_startup_daemon_online_timer, first_interval=1)
  bpy.app.timers.register(disclaimer_op.show_disclaimer_timer, first_interval=1)


def unregister_timers():
  """Unregister all timers at the very start of unregistration.
  This prevents the timers being called before the unregistration finishes.
  Also reports unregistration to daemon.
  """

  if bpy.app.background:
    return

  if bpy.app.timers.is_registered(check_timers_timer):
    bpy.app.timers.unregister(check_timers_timer)
  if bpy.app.timers.is_registered(download.download_timer):
    bpy.app.timers.unregister(download.download_timer)
  if bpy.app.timers.is_registered(tasks_queue.queue_worker):
    bpy.app.timers.unregister(tasks_queue.queue_worker)
  if bpy.app.timers.is_registered(bg_blender.bg_update):
    bpy.app.timers.unregister(bg_blender.bg_update)
  if bpy.app.timers.is_registered(daemon_communication_timer):
    bpy.app.timers.unregister(daemon_communication_timer)
  if bpy.app.timers.is_registered(timer_image_cleanup):
    bpy.app.timers.unregister(timer_image_cleanup)

  if bpy.app.timers.is_registered(on_startup_timer):
    bpy.app.timers.unregister(on_startup_timer)
  if bpy.app.timers.is_registered(on_startup_daemon_online_timer):
    bpy.app.timers.unregister(on_startup_daemon_online_timer)
  if bpy.app.timers.is_registered(disclaimer_op.show_disclaimer_timer):
    bpy.app.timers.unregister(disclaimer_op.show_disclaimer_timer)
