import logging
import os
import queue

import bpy

from . import (
    addon_updater_ops,
    bg_blender,
    bkit_oauth,
    categories,
    comments_utils,
    daemon_lib,
    disclaimer_op,
    download,
    global_vars,
    ratings_utils,
    reports,
    search,
    tasks_queue,
    upload,
    utils,
)
from .daemon import tasks


bk_logger = logging.getLogger(__name__)
reports_queue = queue.Queue()
pending_tasks = list() # pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.


def handle_failed_reports(exception: Exception) -> float:
    global_vars.DAEMON_ACCESSIBLE = False
    if global_vars.DAEMON_FAILED_REPORTS in (0,10):
        daemon_lib.start_daemon_server()

    global_vars.DAEMON_FAILED_REPORTS += 1
    if global_vars.DAEMON_FAILED_REPORTS < 15:
        return 0.1*global_vars.DAEMON_FAILED_REPORTS

    bk_logger.warning(f'Could not get reports: {exception}')
    return_code, meaning = daemon_lib.check_daemon_exit_code()
    if return_code is None and global_vars.DAEMON_FAILED_REPORTS==15:
        reports.add_report('Daemon is not responding, add-on will not work.', 10, 'ERROR')
    if return_code is not None and global_vars.DAEMON_FAILED_REPORTS==15:
        reports.add_report(f'Daemon is not running, add-on will not work. Error({return_code}): {meaning}', 10, 'ERROR')

    wm = bpy.context.window_manager
    wm.blenderkitUI.logo_status = "logo_offline"
    daemon_lib.start_daemon_server()
    return 30.0


@bpy.app.handlers.persistent
def daemon_communication_timer():
  """Recieve all responses from daemon and run according followup commands.
  This function is the only one responsible for keeping the daemon up and running.
  """
  global pending_tasks
  bk_logger.debug('Getting tasks from daemon')
  search.check_clipboard()
  app_id = os.getpid()
  results = list()

  try:
    api_key = bpy.context.preferences.addons['blenderkit'].preferences.api_key
    results = daemon_lib.get_reports(app_id, api_key)
    global_vars.DAEMON_FAILED_REPORTS = 0
  except Exception as e:
    return handle_failed_reports(e)

  if global_vars.DAEMON_ACCESSIBLE is False:
    reports.add_report("Daemon is running!")
    global_vars.DAEMON_ACCESSIBLE = True
    wm = bpy.context.window_manager
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
  daemon_lib.reorder_ports(bpy.context.preferences.addons['blenderkit'].preferences.daemon_port)
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
  #TODO: should add uploads


def handle_task(task: tasks.Task):
  """Handle incomming task information. Sort tasks by type and call apropriate functions."""
  #HANDLE ASSET DOWNLOAD
  if task.task_type == 'asset_download':
    return download.handle_download_task(task)

  #HANDLE ASSET UPLOAD
  if task.task_type == 'asset_upload':
    return upload.handle_asset_upload(task)

  if task.task_type == 'asset_metadata_upload':
    return upload.handle_asset_metadata_upload(task)

  #HANDLE SEARCH (candidate to be a function)
  if task.task_type == 'search':
    if task.status == 'finished':
      return search.handle_search_task(task)
    elif task.status == 'error':
      return reports.add_report(task.message, 15, 'ERROR')

  #HANDLE THUMBNAIL DOWNLOAD (candidate to be a function)
  if task.task_type == 'thumbnail_download':
    if task.status == 'finished':
      return search.handle_preview_task(task)
    elif task.status == 'error':
      return reports.add_report(task.message, 3, 'ERROR')

  #HANDLE LOGIN
  if task.task_type == "login":
    return bkit_oauth.handle_login_task(task)

  #HANDLE DAEMON STATUS REPORT
  if task.task_type == "daemon_status":
    return daemon_lib.handle_daemon_status_task(task)

  #HANDLE DISCLAIMER
  if task.task_type == "disclaimer":
    return disclaimer_op.handle_disclaimer_task(task)

  #HANDLE CATEGORIES FETCH
  if task.task_type == "categories_update":
    return categories.handle_categories_task(task)

  #HANDLE NOTIFICATIONS FETCH
  if task.task_type == "notifications":
    return comments_utils.handle_notifications_task(task)

  #HANDLE VARIOUS COMMENTS TASKS
  if task.task_type == "comments/get_comments":
    return comments_utils.handle_get_comments_task(task)
  if task.task_type == "comments/create_comment":
    return comments_utils.handle_create_comment_task(task)
  if task.task_type == "comments/feedback_comment":
    return comments_utils.handle_feedback_comment_task(task)
  if task.task_type == "comments/mark_comment_private":
    return comments_utils.handle_mark_comment_private_task(task)

  #HANDLE PROFILE
  if task.task_type == 'profiles/fetch_gravatar_image':
    return search.handle_fetch_gravatar_task(task) 
  if task.task_type == 'profiles/get_user_profile':
    return search.handle_get_user_profile(task)

  #HANDLE RATINGS
  if task.task_type == 'ratings/get_rating':
    return ratings_utils.handle_get_rating_task(task)
  if task.task_type == 'ratings/send_rating':
    return #TODO: at least on error we should show error message

  #HANDLE NONBLOCKING_REQUEST
  if task.task_type == 'wrappers/nonblocking_request':
    return utils.handle_nonblocking_request_task(task)

  #HANDLE MESSAGE FROM DAEMON
  if task.task_type == 'message_from_daemon':
    level = task.result.get('level', 'INFO').upper()
    duration = task.result.get('duration', 5)
    destination = task.result.get('destination', 'GUI')
    if destination == 'GUI':
        return reports.add_report(task.message, duration, level)
    if level == 'INFO':
        return bk_logger.info(task.message)
    if level == 'WARNING':
        return bk_logger.warning(task.message)
    if level == 'ERROR':
        return bk_logger.error(task.message)


@bpy.app.handlers.persistent
def check_timers_timer():
  """Checks if all timers are registered regularly. Prevents possible bugs from stopping the addon."""  
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


def on_startup_daemon_online_timer():
  """Run once when daemon is online after startup."""
  if not global_vars.DAEMON_ONLINE:
    return 1

  preferences = bpy.context.preferences.addons['blenderkit'].preferences
  if preferences.show_on_start:
    search.search()
  if preferences.api_key != '': #TODO: this could be started from daemon automatically?
    daemon_lib.get_user_profile(preferences.api_key)
  return


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
