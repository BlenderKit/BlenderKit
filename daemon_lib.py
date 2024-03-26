import logging
import os
import platform
import re
import shutil
import subprocess
from os import path

import bpy
import requests

from . import global_vars, reports, utils


bk_logger = logging.getLogger(__name__)
NO_PROXIES = {"http": "", "https": ""}
TIMEOUT = (0.1, 1)


def get_address() -> str:
    """Get address of the BlenderKit-Client."""
    return f"http://127.0.0.1:{get_port()}"


def get_port() -> str:
    """Get the most probable port of currently running BlenderKit-Client.
    After add-on registration and if all goes well, the port is the same as
    """
    return global_vars.CLIENT_PORTS[0]


def ensure_minimal_data(data: dict = {}) -> dict:
    """Ensure that the data send to the BlenderKit-Client contains:
    - app_id is the process ID of the Blender instance, so BlenderKit-client can return reports to the correct instance.
    - api_key is the authentication token for the BlenderKit server, so BlenderKit-Client can authenticate the user.
    - addon_version is the version of the BlenderKit add-on, so BlenderKit-client has understanding of the version of the add-on making the request.
    """
    av = global_vars.VERSION
    if "api_key" not in data:  # for BG instances, where preferences are not available
        data.setdefault(
            "api_key", bpy.context.preferences.addons["blenderkit"].preferences.api_key
        )
    data.setdefault("app_id", os.getpid())
    data.setdefault("platform_version", platform.platform())
    data.setdefault(
        "addon_version",
        f"{av[0]}.{av[1]}.{av[2]}.{av[3]}",
    )
    return data


def reorder_ports(port: str):
    """Reorder CLIENT_PORTS so the specified port is first."""
    i = global_vars.CLIENT_PORTS.index(port)
    global_vars.CLIENT_PORTS = (
        global_vars.CLIENT_PORTS[i:] + global_vars.CLIENT_PORTS[:i]
    )


def get_reports(app_id: str):
    """Get reports for all tasks of app_id Blender instance at once.
    If few last calls failed, then try to get reports also from other than default ports.
    """
    data = ensure_minimal_data({"app_id": app_id})
    if (
        global_vars.CLIENT_FAILED_REPORTS < 10
    ):  # on 10, there is second BlenderKit-Client start
        url = f"{get_address()}/report"
        report = request_report(url, data)
        return report

    last_exception = None
    for port in global_vars.CLIENT_PORTS:
        url = f"http://127.0.0.1:{port}/report"
        try:
            report = request_report(url, data)
            bk_logger.warning(
                f"Got reports from BlenderKit-Client on port {port}, setting it as default for this instance"
            )
            reorder_ports(port)
            return report
        except Exception as e:
            bk_logger.info(f"Failed to get BlenderKit-Client reports: {e}")
            last_exception = e
    raise last_exception


def request_report(url: str, data: dict):
    with requests.Session() as session:
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


### ASSETS
# SEARCH
def asset_search(data):
    """Search for specified asset."""
    bk_logger.debug("Starting search request")
    address = get_address()
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = address + "/blender/asset_search"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        bk_logger.debug("Got search response")
        return resp.json()


# DOWNLOAD
def asset_download(data):
    """Download specified asset."""
    address = get_address()
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = address + "/blender/asset_download"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


def cancel_download(task_id):
    """Cancel the specified task with ID on the BlenderKit-Client."""
    address = get_address()
    data = ensure_minimal_data({"task_id": task_id})
    with requests.Session() as session:
        url = address + "/blender/cancel_download"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


# UPLOAD
def asset_upload(upload_data, export_data, upload_set):
    """Upload specified asset."""
    data = {
        "PREFS": utils.get_preferences_as_dict(),
        "upload_data": upload_data,
        "export_data": export_data,
        "upload_set": upload_set,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_address() + "/blender/asset_upload"
        bk_logger.debug(f"making a request to: {url}")
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


### PROFILES
def download_gravatar_image(
    author_data,
):  # TODO: require avatar128 and gravatarHash and refuse directly
    """Fetch gravatar image for specified user. Find it on disk or download it from server."""
    data = {
        "id": author_data.get("id", ""),
        "avatar128": author_data.get("avatar128", ""),
        "gravatarHash": author_data.get("gravatarHash", ""),
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/profiles/download_gravatar_image",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def get_user_profile():
    """Fetch profile of currently logged-in user.
    This creates task on BlenderKit-Client to fetch data which are later handled once available.
    """
    data = ensure_minimal_data()
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
    data = ensure_minimal_data({"asset_id": asset_id})
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
        "reply_to_id": reply_to_id,
    }
    data = ensure_minimal_data(data)
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
        "flag": flag,
    }
    data = ensure_minimal_data(data)
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
        "is_private": is_private,
    }
    data = ensure_minimal_data(data)
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
    data = ensure_minimal_data({"notification_id": notification_id})
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/notifications/mark_notification_read",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### REPORTS
def report_usages(data: dict):
    """Report usages of assets in current scene via BlenderKit-Client to the server."""
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.post(
            f"{get_address()}/report_usages",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


# RATINGS
def get_rating(asset_id: str):
    data = ensure_minimal_data({"asset_id": asset_id})
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/ratings/get_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def send_rating(asset_id: str, rating_type: str, rating_value: str):
    data = {
        "asset_id": asset_id,
        "rating_type": rating_type,
        "rating_value": rating_value,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_address()}/ratings/send_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# BOOKMARKS
def get_bookmarks():
    data = ensure_minimal_data()
    with requests.Session() as session:
        return session.get(
            f"{get_address()}/ratings/get_bookmarks",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### BLOCKING WRAPPERS
def get_download_url(asset_data, scene_id, api_key):
    """Get download url from server. This is a blocking wrapper, will not return until results are available.
    Returns: (bool, str, str) - can_download, download_url, filename.
    """
    data = {
        "resolution": "blend",
        "asset_data": asset_data,
        "api_key": api_key,  # needs to be here, because prefs are not available in BG instances
        "PREFS": {
            "api_key": api_key,
            "scene_id": scene_id,
        },
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_address()}/wrappers/get_download_url",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        resp = resp.json()
        return (resp["can_download"], resp["download_url"], resp["filename"])


def blocking_file_upload(url: str, filepath: str) -> requests.Response:
    """Upload file to server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "url": url,
        "filepath": filepath,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_address()}/wrappers/blocking_file_upload",
            json=data,
            timeout=(1, 180),
            proxies=NO_PROXIES,
        )
        return resp


def blocking_file_download(url: str, filepath: str, api_key: str) -> requests.Response:
    """Upload file to server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "url": url,
        "filepath": filepath,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_address()}/wrappers/blocking_file_download",
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
    """Make blocking HTTP request through BlenderKit-Client.
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
    url: str, method: str, headers: dict = {}, json_data: dict = {}, messages: dict = {}
) -> requests.Response:
    """Make non-blocking HTTP request through BlenderKit-Client.
    This function will return ASAP, not returning any actual data.
    """
    data = {
        "url": url,
        "method": method,
        "headers": headers,
        "messages": messages,
    }
    data = ensure_minimal_data(data)
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
def send_oauth_verification_data(code_verifier, state: str):
    """Send OAUTH2 Code Verifier and State parameters to BlenderKit-Client.
    So it can later use them to authenticate the redirected response from the browser.
    """
    data = ensure_minimal_data(
        {
            "code_verifier": code_verifier,
            "state": state,
        }
    )
    with requests.Session() as session:
        resp = session.post(
            f"{get_address()}/oauth2/verification_data",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def refresh_token(refresh_token, old_api_key):
    """Refresh authentication token. BlenderKit-Client will use refresh token to get new API key token to replace the old_api_key.
    old_api_key is used later to replace token only in Blender instances with the same api_key. (User can be logged into multiple accounts.)
    """
    bk_logger.info("Calling API token refresh")
    data = ensure_minimal_data({"refresh_token": refresh_token})
    with requests.Session() as session:
        url = get_address() + "/refresh_token"
        resp = session.get(
            url,
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def oauth2_logout():
    """Logout from OAUTH2. BlenderKit-Client will revoke the token on the server."""
    data = ensure_minimal_data()
    data["refresh_token"] = global_vars.PREFS["api_key_refresh"]
    with requests.Session() as session:
        url = get_address() + "/oauth2/logout"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def unsubscribe_addon():
    """Unsubscribe the add-on from the BlenderKit-Client. Called when the add-on is disabled, uninstalled or when Blender is closed."""
    address = get_address()
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = address + "/blender/unsubscribe_addon"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def shutdown_client():
    """Request to shutdown the BlenderKit-Client."""
    address = get_address()
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = address + "/shutdown"
        resp = session.get(url, data=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def handle_client_status_task(task):
    if global_vars.CLIENT_RUNNING is False:
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"
    global_vars.CLIENT_RUNNING = True


def check_blenderkit_client_exit_code() -> tuple[int, str]:
    exit_code = global_vars.client_process.poll()
    if exit_code is None:
        return exit_code, "BlenderKit-Client process is running."

    message = f"BlenderKit-Client process exited with code {exit_code}. Please report a bug and paste content of log {get_client_log_path()}"
    return exit_code, message


def start_blenderkit_client():
    """Start BlenderKit-client in separate process.
    1. Check if binary is available at global_dir/client/vX.Y.Z.YYMMDD/blenderkit-client-<os>-<arch>(.exe)
    2. Copy the binary from add-on directory to global_dir/client/vX.Y.Z.YYMMDD/
    3. Start the BlenderKit-Client process which serves as bridge between BlenderKit add-on and BlenderKit server.
    """
    ensure_client_binary_installed()
    log_path = get_client_log_path()
    client_binary_path, client_version = get_client_binary_path()

    creation_flags = 0
    if platform.system() == "Windows":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        with open(log_path, "wb") as log:
            global_vars.client_process = subprocess.Popen(
                args=[
                    client_binary_path,
                    "--port",
                    get_port(),
                    "--server",
                    global_vars.SERVER,
                    "--proxy_which",
                    global_vars.PREFS.get("proxy_which", ""),
                    "--proxy_address",
                    global_vars.PREFS.get("proxy_address", ""),
                    "--trusted_ca_certs",
                    global_vars.PREFS.get("trusted_ca_certs", ""),
                    "--ssl_context",
                    global_vars.PREFS.get("ssl_context", ""),
                    "--version",
                    f"{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}",
                ],
                stdout=log,
                stderr=log,
                creationflags=creation_flags,
            )
    except Exception as e:
        reports.add_report(
            f"Error: BlenderKit-Client failed to start - {e}", 10, "ERROR"
        )
        raise (e)

    bk_logger.info(
        f"BlenderKit-Client {client_version} starting on {get_address()}, log file at: {log_path}"
    )


def decide_client_binary_name() -> str:
    """Decide the name of the BlenderKit-Client binary based on the current operating system and architecture.
    Possible return values:
    - blenderkit-client-windows-x86_64.exe
    - blenderkit-client-windows-arm64.exe
    - blenderkit-client-linux-x86_64
    - blenderkit-client-linux-arm64
    - blenderkit-client-macos-x86_64
    - blenderkit-client-macos-arm64
    """
    os_name = platform.system()
    architecture = platform.machine()
    if os_name == "Darwin":  # more user-friendly name for macOS
        os_name = "macos"
    if architecture == "AMD64":  # fix for windows
        architecture = "x86_64"

    if os_name == "Windows":
        return f"blenderkit-client-{os_name}-{architecture}.exe".lower()

    return f"blenderkit-client-{os_name}-{architecture}".lower()


def get_client_directory() -> str:
    """Get the path to the BlenderKit-Client directory located in global_dir."""
    global_dir = bpy.context.preferences.addons["blenderkit"].preferences.global_dir
    directory = path.join(global_dir, "client")
    return directory


def get_client_log_path() -> str:
    """Get path to BlenderKit-Client log file in global_dir/client.
    If the port is the default port 62485, the log file is named default.log,
    otherwise it is named client-<port>.log.
    """
    port = get_port()
    if port == "62485":
        log_path = os.path.join(get_client_directory(), f"default.log")
    else:
        log_path = os.path.join(get_client_directory(), f"client-{get_port()}.log")
    return path.abspath(log_path)


def get_client_version() -> str:
    """Get the version of the BlenderKit-Client binary bundled within the add-on.
    Binaries are located in blenderkit/client/vX.Y.Z.YYMMDD/ directory.
    From this directory name, we get the version of the client binary.
    """
    addon_dir = path.dirname(__file__)
    client_bundled_dir = path.join(addon_dir, "client")
    version_pattern = re.compile(r"^v\d+\.\d+\.\d+(?:\.\d+)?$")
    for entry in os.scandir(client_bundled_dir):
        if entry.is_dir() and version_pattern.match(entry.name):
            return entry.name

    raise AssertionError(
        "Directory with preinstalled blenderkit-client binaries not found."
    )


def get_preinstalled_client_path() -> str:
    """Get the path to the preinstalled BlenderKit-Client binary - located in add-on directory.
    This is the binary that is shipped with the add-on. It is copied to global_dir/client/vX.Y.Z.YYMMDD on first run.
    """
    addon_dir = path.dirname(__file__)
    client_version = get_client_version()
    binary_name = decide_client_binary_name()
    binary_path = path.join(addon_dir, "client", client_version, binary_name)
    return path.abspath(binary_path)


def get_client_binary_path():
    """Get the path to the BlenderKit-Client binary located in global_dir/client/bin/vX.Y.Z.YYMMDD.
    This is the binary that is used to start the client process.
    We do not start from the add-on because it might block update or delete of the add-on.
    Returns: (str, str) - path to the Client binary, version of the Client binary
    """
    client_dir = get_client_directory()
    binary_name = decide_client_binary_name()
    ver_string = get_client_version()
    binary_path = path.join(client_dir, "bin", ver_string, binary_name)
    return path.abspath(binary_path), ver_string


def ensure_client_binary_installed():
    """Ensure that the BlenderKit-Client binary is installed in global_dir/client/bin/vX.Y.Z.YYMMDD.
    If not, copy the binary from the add-on directory blenderkit/client.
    As side effect, this function also creates the global_dir/client/bin/vX.Y.Z.YYMMDD directory.
    """
    client_binary_path, _ = get_client_binary_path()
    if path.exists(client_binary_path):
        return

    preinstalled_client_path = get_preinstalled_client_path()
    bk_logger.info(f"Copying BlenderKit-Client binary {preinstalled_client_path}")
    os.makedirs(path.dirname(client_binary_path), exist_ok=True)
    shutil.copy(preinstalled_client_path, client_binary_path)
    os.chmod(client_binary_path, 0o711)
    bk_logger.info(f"BlenderKit-Client binary copied to {client_binary_path}")


def get_addon_dir():
    """Get the path to the add-on directory."""
    addon_dir = path.dirname(__file__)
    return addon_dir
