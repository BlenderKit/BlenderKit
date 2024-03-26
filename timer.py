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
    daemon_tasks,
    disclaimer_op,
    download,
    global_vars,
    persistent_preferences,
    ratings_utils,
    reports,
    search,
    tasks_queue,
    upload,
    utils,
)


bk_logger = logging.getLogger(__name__)
reports_queue = queue.Queue()
pending_tasks = (
    list()
)  # pending tasks are tasks that were not parsed correclty and should be tried to be parsed later.


def handle_failed_reports(exception: Exception) -> float:
    bk_logger.warning(
        f"Request for BlenderKit-Client reports failed: {type(exception)} {exception}"
    )
    global_vars.CLIENT_ACCESSIBLE = False
    if global_vars.CLIENT_FAILED_REPORTS in (0, 10):
        daemon_lib.start_blenderkit_client()

    global_vars.CLIENT_FAILED_REPORTS += 1
    if global_vars.CLIENT_FAILED_REPORTS < 15:
        return 0.1 * global_vars.CLIENT_FAILED_REPORTS

    bk_logger.warning(f"Could not get reports: {exception}")
    return_code, meaning = daemon_lib.check_blenderkit_client_exit_code()
    if return_code is None and global_vars.CLIENT_FAILED_REPORTS == 15:
        reports.add_report(
            "Client is not responding, add-on will not work.", 10, "ERROR"
        )
    if return_code is not None and global_vars.CLIENT_FAILED_REPORTS == 15:
        reports.add_report(
            f"Client is not running, add-on will not work. Error({return_code}): {meaning}",
            10,
            "ERROR",
        )

    wm = bpy.context.window_manager
    wm.blenderkitUI.logo_status = "logo_offline"
    global_vars.CLIENT_RUNNING = False
    daemon_lib.start_blenderkit_client()
    return 30.0


@bpy.app.handlers.persistent
def daemon_communication_timer():
    """Recieve all responses from daemon and run according followup commands.
    This function is the only one responsible for keeping the daemon up and running.
    """
    global pending_tasks
    bk_logger.debug("Getting tasks from daemon")
    search.check_clipboard()
    results = list()
    try:
        results = daemon_lib.get_reports(os.getpid())
        global_vars.CLIENT_FAILED_REPORTS = 0
    except Exception as e:
        return handle_failed_reports(e)

    if global_vars.CLIENT_ACCESSIBLE is False:
        bk_logger.info(
            f"BlenderKit-Client is running on port {global_vars.CLIENT_PORTS[0]}!"
        )
        global_vars.CLIENT_ACCESSIBLE = True
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"

    bk_logger.debug("Handling tasks")
    results_converted_tasks = []

    # convert to task type
    for task in results:
        task = daemon_tasks.Task(
            data=task["data"],
            task_id=task["task_id"],
            app_id=task["app_id"],
            task_type=task["task_type"],
            message=task["message"],
            progress=task["progress"],
            status=task["status"],
            result=task["result"],
        )
        results_converted_tasks.append(task)

    # add pending tasks which were already parsed but not handled
    results_converted_tasks.extend(pending_tasks)
    pending_tasks.clear()

    for task in results_converted_tasks:
        handle_task(task)

    bk_logger.debug("Task handling finished")
    if len(download.download_tasks) > 0:
        return 0.2
    return 0.5


@bpy.app.handlers.persistent
def timer_image_cleanup():
    imgs = bpy.data.images[:]
    for i in imgs:
        if (
            (i.name[:11] == ".thumbnail_" or i.filepath.find("bkit_g") > -1)
            and not i.has_data
            and i.users == 0
        ):
            bpy.data.images.remove(i)
    return 60


def save_prefs_cancel_all_tasks_and_restart_daemon(user_preferences, context):
    """Save preferences, cancel all blenderkit-client tasks and shutdown the blenderkit-client.
    The daemon_communication_timer will soon take care of starting the daemon again leading to a restart.
    """
    utils.save_prefs(user_preferences, context)
    if user_preferences.preferences_lock == True:
        return

    reports.add_report("Restarting client server", 5, "INFO")
    daemon_lib.reorder_ports(user_preferences.daemon_port)
    try:
        cancel_all_tasks(user_preferences, context)
        daemon_lib.shutdown_client()
    except Exception as e:
        bk_logger.warning(str(e))


def trusted_CA_certs_property_updated(user_preferences, context):
    """Update trusted CA certs environment variables and call save_prefs()."""
    update_trusted_CA_certs(user_preferences.trusted_ca_certs)
    return save_prefs_cancel_all_tasks_and_restart_daemon(user_preferences, context)


def update_trusted_CA_certs(certs: str):
    if certs == "":
        os.environ.pop("REQUESTS_CA_BUNDLE", None)
        os.environ.pop("CURL_CA_BUNDLE", None)
        return

    os.environ["REQUESTS_CA_BUNDLE"] = certs
    os.environ["CURL_CA_BUNDLE"] = certs
    return


def cancel_all_tasks(self, context):
    """Cancel all tasks."""
    global pending_tasks
    pending_tasks.clear()
    download.clear_downloads()
    search.clear_searches()
    # TODO: should add uploads


def task_error_overdrive(task: daemon_tasks.Task) -> None:
    """Handle error task - overdrive some error messages, trigger functions common for all errors."""
    if task.message.count("Invalid token.") > 0 and utils.user_logged_in():
        preferences = bpy.context.preferences.addons["blenderkit"].preferences

        # Invalid token and api_key_refresh present -> trying to refresh the token
        if preferences.api_key_refresh != "":
            daemon_lib.refresh_token(preferences.api_key_refresh, preferences.api_key)
            reports.add_report(
                "Invalid API key token. Refreshing the token now. If problem persist, please log-out and log-in.",
                5,
                "ERROR",
            )
            return

        # Invalid token and no api_key_refresh token -> nothing else we can try...
        bkit_oauth.logout()
        reports.add_report(
            "Invalid permanent API key token. Logged out. Please login again.",
            10,
            "ERROR",
        )


def handle_task(task: daemon_tasks.Task):
    """Handle incomming task information. Sort tasks by type and call apropriate functions."""
    if task.status == "error":
        task_error_overdrive(task)

    # HANDLE ASSET DOWNLOAD
    if task.task_type == "asset_download":
        return download.handle_download_task(task)

    # HANDLE ASSET UPLOAD
    if task.task_type == "asset_upload":
        return upload.handle_asset_upload(task)

    if task.task_type == "asset_metadata_upload":
        return upload.handle_asset_metadata_upload(task)

    # HANDLE SEARCH (candidate to be a function)
    if task.task_type == "search":
        if task.status == "finished":
            return search.handle_search_task(task)
        elif task.status == "error":
            return search.handle_search_task_error(task)

    # HANDLE THUMBNAIL DOWNLOAD (candidate to be a function)
    if task.task_type == "thumbnail_download":
        return search.handle_thumbnail_download_task(task)

    # HANDLE LOGIN
    if task.task_type == "login":
        return bkit_oauth.handle_login_task(task)

    # HANDLE TOKEN REFRESH
    if task.task_type == "token_refresh":
        return bkit_oauth.handle_token_refresh_task(task)

    # HANDLE OAUTH LOGOUT
    if task.task_type == "oauth2/logout":
        return bkit_oauth.handle_logout_task(task)

    # HANDLE CLIENT STATUS REPORT
    if task.task_type == "client_status":
        return daemon_lib.handle_client_status_task(task)

    # HANDLE DISCLAIMER
    if task.task_type == "disclaimer":
        return disclaimer_op.handle_disclaimer_task(task)

    # HANDLE CATEGORIES FETCH
    if task.task_type == "categories_update":
        return categories.handle_categories_task(task)

    # HANDLE NOTIFICATIONS FETCH
    if task.task_type == "notifications":
        return comments_utils.handle_notifications_task(task)

    # HANDLE VARIOUS COMMENTS TASKS
    if task.task_type == "comments/get_comments":
        return comments_utils.handle_get_comments_task(task)
    if task.task_type == "comments/create_comment":
        return comments_utils.handle_create_comment_task(task)
    if task.task_type == "comments/feedback_comment":
        return comments_utils.handle_feedback_comment_task(task)
    if task.task_type == "comments/mark_comment_private":
        return comments_utils.handle_mark_comment_private_task(task)

    # HANDLE PROFILE
    if task.task_type == "profiles/fetch_gravatar_image":
        return search.handle_fetch_gravatar_task(task)
    if task.task_type == "profiles/get_user_profile":
        return search.handle_get_user_profile(task)

    # HANDLE RATINGS
    if task.task_type == "ratings/get_rating":
        return ratings_utils.handle_get_rating_task(task)
    if task.task_type == "ratings/send_rating":
        return ratings_utils.handle_send_rating_task(task)

    # HANDLE BOOKMARKS
    if task.task_type == "ratings/get_bookmarks":
        return ratings_utils.handle_get_bookmarks_task(task)

    # HANDLE NONBLOCKING_REQUEST
    if task.task_type == "wrappers/nonblocking_request":
        return utils.handle_nonblocking_request_task(task)

    # HANDLE MESSAGE FROM DAEMON
    if task.task_type == "message_from_daemon":
        level = task.result.get("level", "INFO").upper()
        duration = task.result.get("duration", 5)
        destination = task.result.get("destination", "GUI")
        if destination == "GUI":
            return reports.add_report(task.message, duration, level)
        if level == "INFO":
            return bk_logger.info(task.message)
        if level == "WARNING":
            return bk_logger.warning(task.message)
        if level == "ERROR":
            return bk_logger.error(task.message)


@bpy.app.handlers.persistent
def check_timers_timer():
    """Checks if all timers are registered regularly. Prevents possible bugs from stopping the addon."""
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
    """Run once on the startup of add-on (Blender start with enabled add-on, add-on enabled)."""
    persistent_preferences.load_preferences_from_JSON()
    addon_updater_ops.check_for_update_background()
    utils.check_globaldir_permissions()

    return None


def on_startup_daemon_online_timer():
    """Run once when daemon is online after startup."""
    if not global_vars.CLIENT_RUNNING:
        return 1

    preferences = bpy.context.preferences.addons["blenderkit"].preferences
    refresh_needed = bkit_oauth.ensure_token_refresh()
    if refresh_needed:  # called for new API token, lets wait for a while
        return 1

    if preferences.show_on_start:
        search.search()

    return


def register_timers():
    """Register all timers if add-on is not running in background (thumbnail rendering, upload, unpacking and also tests).
    It registers check_timers_timer which registers all other periodic non-ending timers.
    And individually it register all timers which are expected to end.
    """
    if bpy.app.background:
        return

    # PERIODIC TIMERS
    bpy.app.timers.register(
        check_timers_timer, persistent=True
    )  # registers all other non-ending timers

    # ONETIMERS
    bpy.app.timers.register(on_startup_timer)
    bpy.app.timers.register(on_startup_daemon_online_timer, first_interval=1)
    bpy.app.timers.register(disclaimer_op.show_disclaimer_timer, first_interval=1)


def unregister_timers():
    """Unregister all timers at the very start of unregistration.
    This prevents the timers being called before the unregistration finishes.
    """
    if bpy.app.background:
        return

    if bpy.app.timers.is_registered(check_timers_timer):
        bpy.app.timers.unregister(check_timers_timer)
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
