import logging
import os
import platform
import subprocess
import sys
from os import environ, path

import bpy
import requests

from . import dependencies, global_vars, reports


bk_logger = logging.getLogger(__name__)
NO_PROXIES = {"http": "", "https": ""}
TIMEOUT = (0.1, 1)


def get_address() -> str:
    """Get address of the daemon."""
    return f"http://127.0.0.1:{get_port()}"


def get_port() -> str:
    """Get the most probable port of currently running daemon.
    After add-on registration and if all goes well, the port is the same as
    """
    return global_vars.DAEMON_PORTS[0]


def reorder_ports(port: str):
    """Reorder DAEMON_PORTS so the specified port is first."""
    i = global_vars.DAEMON_PORTS.index(port)
    global_vars.DAEMON_PORTS = (
        global_vars.DAEMON_PORTS[i:] + global_vars.DAEMON_PORTS[:i]
    )


def get_daemon_directory_path() -> str:
    """Get path to daemon directory in blenderkit_data directory."""
    global_dir = bpy.context.preferences.addons["blenderkit"].preferences.global_dir
    directory = path.join(global_dir, "daemon")
    return path.abspath(directory)


def get_reports(app_id: str, api_key=""):
    """Get reports for all tasks of app_id Blender instance at once.
    If few last calls failed, then try to get reports also from other than default ports.
    """
    data = {"app_id": app_id, "api_key": api_key}
    if global_vars.DAEMON_FAILED_REPORTS < 10:  # on 10, there is second daemon start
        url = f"{get_address()}/report"
        report = request_report(url, data)
        return report

    last_exception = None
    for port in global_vars.DAEMON_PORTS:
        url = f"http://127.0.0.1:{port}/report"
        try:
            report = request_report(url, data)
            bk_logger.warning(
                f"Got reports port {port}, setting it as default for this instance"
            )
            reorder_ports(port)
            return report
        except Exception as e:
            bk_logger.info(f"Failed to get daemon reports: {e}")
            last_exception = e
    raise last_exception


def request_report(url: str, data: dict):
    with requests.Session() as session:
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


### ASSETS
# SEARCH
def search_asset(data):
    """Search for specified asset."""
    bk_logger.debug("Starting search request")
    address = get_address()
    data["app_id"] = os.getpid()
    with requests.Session() as session:
        url = address + "/search_asset"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        bk_logger.debug("Got search response")
        return resp.json()


# DOWNLOAD
def download_asset(data):
    """Download specified asset."""
    address = get_address()
    data["app_id"] = os.getpid()
    with requests.Session() as session:
        url = address + "/download_asset"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


def kill_download(task_id):
    """Kill the specified task with ID on the daemon."""
    address = get_address()
    with requests.Session() as session:
        url = address + "/kill_download"
        resp = session.get(
            url, json={"task_id": task_id}, timeout=TIMEOUT, proxies=NO_PROXIES
        )
        return resp


# UPLOAD
def upload_asset(upload_data, export_data, upload_set):
    """Upload specified asset."""
    data = {
        "app_id": os.getpid(),
        "upload_data": upload_data,
        "export_data": export_data,
        "upload_set": upload_set,
    }
    with requests.Session() as session:
        url = get_address() + "/upload_asset"
        bk_logger.debug(f"making a request to: {url}")
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


### PROFILES
def fetch_gravatar_image(author_data):
    """Fetch gravatar image for specified user. Find it on disk or download it from server."""
    author_data["app_id"] = os.getpid()
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/profiles/fetch_gravatar_image",
            json=author_data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def get_user_profile(api_key):
    """Get profile of currently logged-in user.
    This creates task to daemon to fetch data which are later handled once available.
    """
    data = {"api_key": api_key, "app_id": os.getpid()}
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/profiles/get_user_profile",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### COMMENTS
def get_comments(asset_id, api_key=""):
    """Get all comments on the asset."""
    data = {
        "asset_id": asset_id,
        "api_key": api_key,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/comments/get_comments",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def create_comment(asset_id, comment_text, api_key, reply_to_id=0):
    """Create a new comment."""
    data = {
        "asset_id": asset_id,
        "comment_text": comment_text,
        "api_key": api_key,
        "reply_to_id": reply_to_id,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/comments/create_comment",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def feedback_comment(asset_id, comment_id, api_key, flag="like"):
    """Feedback the comment - by default with like. Other flags can be used also."""
    data = {
        "asset_id": asset_id,
        "comment_id": comment_id,
        "api_key": api_key,
        "flag": flag,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/comments/feedback_comment",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def mark_comment_private(asset_id, comment_id, api_key, is_private=False):
    """Mark the comment as private or public."""
    data = {
        "asset_id": asset_id,
        "comment_id": comment_id,
        "api_key": api_key,
        "is_private": is_private,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/comments/mark_comment_private",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### NOTIFICATIONS
def mark_notification_read(notification_id):
    """Mark the notification as read on the server."""
    data = {
        "notification_id": notification_id,
        "api_key": bpy.context.preferences.addons["blenderkit"].preferences.api_key,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/notifications/mark_notification_read",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### REPORTS
def report_usages(report: dict):
    """Report usages of assets in current scene via daemon to the server."""
    report["api_key"] = bpy.context.preferences.addons["blenderkit"].preferences.api_key
    report["app_id"] = os.getpid()
    with requests.Session() as session:
        resp = session.post(
            f"{get_address()}/report_usages",
            json=report,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


# RATINGS
def get_rating(asset_id: str):
    data = {
        "api_key": bpy.context.preferences.addons["blenderkit"].preferences.api_key,
        "app_id": os.getpid(),
        "asset_id": asset_id,
    }
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/ratings/get_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def send_rating(asset_id: str, rating_type: str, rating_value: str):
    data = {
        "api_key": bpy.context.preferences.addons["blenderkit"].preferences.api_key,
        "app_id": os.getpid(),
        "asset_id": asset_id,
        "rating_type": rating_type,
        "rating_value": rating_value,
    }
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/ratings/send_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# BOOKMARKS
def get_bookmarks():
    data = {
        "api_key": bpy.context.preferences.addons["blenderkit"].preferences.api_key,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/ratings/get_bookmarks",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### BLOCKING WRAPPERS
def get_download_url(asset_data, scene_id, api_key):
    """Get download url from server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "app_id": os.getpid(),
        "resolution": "blend",
        "asset_data": asset_data,
        "PREFS": {
            "api_key": api_key,
            "scene_id": scene_id,
        },
    }
    with requests.Session() as session:
        resp = session.get(
            f"{get_address()}/wrappers/get_download_url",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        resp = resp.json()
        return (resp["has_url"], resp["asset_data"])


def blocking_file_upload(url: str, filepath: str) -> requests.Response:
    """Upload file to server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "url": url,
        "filepath": filepath,
        "app_id": os.getpid(),
    }
    with requests.Session() as session:
        resp = session.get(
            f"{get_address()}/wrappers/blocking_file_upload",
            json=data,
            timeout=(1, 180),
            proxies=NO_PROXIES,
        )
        return resp


def blocking_request(
    url: str,
    method: str = "GET",
    headers: dict = {},
    json_data: dict = {},
    timeout: tuple = TIMEOUT,
) -> requests.Response:
    """Make blocking HTTP request through daemon's AIOHTTP library.
    Will not return until results are available."""
    data = {
        "url": url,
        "method": method,
        "headers": headers,
    }
    if json_data != {}:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/wrappers/blocking_request",
            json=data,
            timeout=timeout,
            proxies=NO_PROXIES,
        )


### REQUEST WRAPPERS
def nonblocking_request(
    url: str, method: str, headers: dict, json_data: dict = {}, messages: dict = {}
) -> requests.Response:
    """Make non-blocking HTTP request through daemon's AIOHTTP library.
    This function will return ASAP, not returning any actual data.
    """
    data = {
        "url": url,
        "method": method,
        "headers": headers,
        "messages": messages,
        "app_id": os.getpid(),
    }
    if json_data != {}:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/wrappers/nonblocking_request",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### AUTHORIZATION
def send_code_verifier(code_verifier: str):
    data = {"code_verifier": code_verifier}
    with requests.Session() as session:
        resp = session.post(
            f"{get_address()}/code_verifier",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def refresh_token(refresh_token):
    """Refresh authentication token."""
    with requests.Session() as session:
        url = get_address() + "/refresh_token"
        resp = session.get(
            url,
            json={"refresh_token": refresh_token},
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def daemon_is_alive(session: requests.Session) -> tuple[bool, str]:
    """Check whether daemon is responding."""
    address = get_address()
    try:
        with session.get(address, timeout=TIMEOUT, proxies=NO_PROXIES) as resp:
            if resp.status_code != 200:
                return False, f"Server response not 200: {resp.status_code}"
            return True, f"Server alive, PID: {resp.text}"

    except requests.exceptions.ConnectionError as err:
        return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


def report_blender_quit():
    address = get_address()
    with requests.Session() as session:
        url = address + "/report_blender_quit"
        resp = session.get(
            url, json={"app_id": os.getpid()}, timeout=TIMEOUT, proxies=NO_PROXIES
        )
        return resp


def kill_daemon_server():
    """Request to restart the daemon server."""
    address = get_address()
    with requests.Session() as session:
        url = address + "/shutdown"
        resp = session.get(url, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def handle_daemon_status_task(task):
    if global_vars.DAEMON_RUNNING is False:
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"
    global_vars.DAEMON_RUNNING = True


def check_daemon_exit_code() -> tuple[int, str]:
    """Checks the exit code of daemon process. Returns exit_code and its message.
    Function polls the process which should not block.
    But better run only when daemon misbehaves and is expected that it already exited.
    """
    exit_code = global_vars.daemon_process.poll()
    if exit_code is None:
        return exit_code, "Daemon process is running."

    # exit_code = global_vars.daemon_process.returncode
    log_path = f"{get_daemon_directory_path()}/daemon-{get_port()}.log"
    if exit_code == 101:
        message = f"failed to import AIOHTTP. Try to delete {dependencies.get_dependencies_path()} and restart Blender."
    elif exit_code == 102:
        message = f"failed to import CERTIFI. Try to delete {dependencies.get_dependencies_path()} and restart Blender."
    elif exit_code == 100:
        message = f"unexpected OSError. Please report a bug and paste content of log {log_path}"
    elif exit_code == 111:
        message = "unable to bind any socket. Check your antivirus/firewall and unblock BlenderKit."
    elif exit_code == 113:
        message = (
            "cannot open port. Check your antivirus/firewall and unblock BlenderKit."
        )
    elif exit_code == 114:
        message = f"invalid pointer address. Please report a bug and paste content of log {log_path}"
    elif exit_code == 121:
        message = 'semaphore timeout exceeded. In preferences set IP version to "Use only IPv4".'
    elif exit_code == 148:
        message = "address already in use. Select different daemon port in preferences."
    elif exit_code == 149:
        message = "address already in use. Select different daemon port in preferences."
    else:
        message = f"unexpected Exception. Please report a bug and paste content of log {log_path}"

    return exit_code, message


def start_daemon_server():
    """Start daemon server in separate process."""
    daemon_dir = get_daemon_directory_path()
    log_path = f"{daemon_dir}/daemon-{get_port()}.log"
    blenderkit_path = path.dirname(__file__)
    daemon_path = path.join(blenderkit_path, "daemon/daemon.py")
    preinstalled_deps = dependencies.get_preinstalled_deps_path()
    installed_deps = dependencies.get_installed_deps_path()

    env = environ.copy()
    env["PYTHONPATH"] = installed_deps + os.pathsep + preinstalled_deps

    python_home = path.abspath(path.dirname(sys.executable) + "/..")
    env["PYTHONHOME"] = python_home

    creation_flags = 0
    if platform.system() == "Windows":
        env["PATH"] = (
            env["PATH"]
            + os.pathsep
            + path.abspath(path.dirname(sys.executable) + "/../../../blender.crt")
        )
        creation_flags = subprocess.CREATE_NO_WINDOW

    python_check = subprocess.run(
        args=[sys.executable, "--version"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if python_check.returncode != 0:
        bk_logger.warning(
            f"Error checking Python interpreter, exit code: {python_check.returncode},"
            + f"Stdout: {python_check.stdout}, "
            + f"Stderr: {python_check.stderr}, "
            + f"Where Python: {sys.executable}, "
            + f"Environment: {env}"
        )

    try:
        with open(log_path, "wb") as log:
            global_vars.daemon_process = subprocess.Popen(
                args=[
                    sys.executable,
                    "-u",
                    daemon_path,
                    "--port",
                    get_port(),
                    "--server",
                    global_vars.SERVER,
                    "--proxy_which",
                    global_vars.PREFS.get("proxy_which", ""),
                    "--proxy_address",
                    global_vars.PREFS.get("proxy_address", ""),
                    "--proxy_ca_certs",
                    global_vars.PREFS.get("proxy_ca_certs", ""),
                    "--ip_version",
                    global_vars.PREFS.get("ip_version", ""),
                    "--ssl_context",
                    global_vars.PREFS.get("ssl_context", ""),
                    "--system_id",
                    bpy.context.preferences.addons["blenderkit"].preferences.system_id,
                    "--version",
                    f"{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}",
                ],
                env=env,
                stdout=log,
                stderr=log,
                creationflags=creation_flags,
            )
    except PermissionError as e:
        reports.add_report(
            f"FATAL ERROR: Write access denied to {daemon_dir}. Check you have write permissions to the directory.",
            10,
            "ERROR",
        )
        raise (e)
    except OSError as e:
        if platform.system() != "Windows":
            reports.add_report(str(e), 10, "ERROR")
            raise (e)
        if e.winerror == 87:  # parameter is incorrect, issue #100
            error_message = f"FATAL ERROR: Daemon server blocked from starting. Check your antivirus or firewall. Error: {e}"
            reports.add_report(error_message, 10, "ERROR")
            raise (e)
        else:
            reports.add_report(str(e), 10, "ERROR")
            raise (e)
    except Exception as e:
        reports.add_report(f"Error: Daemon server failed to start - {e}", 10, "ERROR")
        raise (e)

    if python_check.returncode == 0:
        bk_logger.info(
            f"Daemon server starting on address {get_address()}, log file for errors located at: {log_path}"
        )
    else:
        pid = global_vars.daemon_process.pid
        bk_logger.warning(
            f"Tried to start daemon server on address {get_address()}, PID: {pid},\nlog file: {log_path}"
        )
        reports.add_report(
            "Unsuccessful Python check. Daemon will probably fail to run.", 5, "ERROR"
        )
