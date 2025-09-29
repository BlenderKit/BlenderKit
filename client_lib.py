# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import dataclasses
import logging
import os
import platform
import shutil
import subprocess
from os import path
from typing import Optional
from http.client import responses as http_responses


import bpy
import requests

from . import datas, global_vars, reports, utils


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


def get_api_version() -> str:
    """Get version of API Client is expected to use. To keep stuff simple the API version is derrived from Client's version.
    From Client version vX.Y.Z we remove the .Z part to effectively get the vX.Y version of the API. For nonbreaking changes
    we increase the patch version of the Client. If the change breaks the API, then increase of minor/major version is expected.
    """
    splitted = global_vars.CLIENT_VERSION.split(".")
    return ".".join(splitted[:-1])


def get_base_url() -> str:
    """The base URL on which we will interact with the BlenderKit Client. Consists from address with port + version API path.
    All requests to Client goes to URLs starting with base URL in format: 127.0.0.1:{port}/vX.Y
    """
    address = get_address()
    vapi = get_api_version()
    return f"{address}/{vapi}"


def ensure_minimal_data(data: Optional[dict] = None) -> dict:
    """Ensure that the data send to the BlenderKit-Client contains:
    - app_id is the process ID of the Blender instance, so BlenderKit-client can return reports to the correct instance.
    - api_key is the authentication token for the BlenderKit server, so BlenderKit-Client can authenticate the user.
    - addon_version is the version of the BlenderKit add-on, so BlenderKit-client has understanding of the version of the add-on making the request.
    """
    if data is None:
        data = {}

    av = global_vars.VERSION
    addon_version = f"{av[0]}.{av[1]}.{av[2]}.{av[3]}"
    if "api_key" not in data:
        # for BG instances, where preferences are not available
        data.setdefault(
            "api_key", bpy.context.preferences.addons[__package__].preferences.api_key  # type: ignore
        )
    data.setdefault("app_id", os.getpid())
    data.setdefault("platform_version", platform.platform())
    data.setdefault("addon_version", addon_version)

    return data


def ensure_minimal_data_class(data_class):
    """Ensure that the data send to the BlenderKit-Client contains:
    - app_id is the process ID of the Blender instance, so BlenderKit-client can return reports to the correct instance.
    - api_key is the authentication token for the BlenderKit server, so BlenderKit-Client can authenticate the user.
    - addon_version is the version of the BlenderKit add-on, so BlenderKit-client has understanding of the version of the add-on making the request.
    """
    if data_class == None:
        data_class = dataclasses.dataclass()

    av = global_vars.VERSION
    if hasattr(data_class, "api_key"):
        # for BG instances, where preferences are not available
        api_key = bpy.context.preferences.addons[__package__].preferences.api_key
        setattr(data_class, "api_key", api_key)
    setattr(data_class, "app_id", os.getpid())
    setattr(data_class, "platform_version", platform.platform())
    setattr(data_class, "addon_version", f"{av[0]}.{av[1]}.{av[2]}.{av[3]}")
    return data_class


def reorder_ports(port: str = ""):
    """Reorder CLIENT_PORTS so the specified port is first.
    If no port is specified, the current first port is moved to back so second becomes the first.
    """
    if port == "":
        i = 1
    else:
        i = global_vars.CLIENT_PORTS.index(port)
    global_vars.CLIENT_PORTS = (
        global_vars.CLIENT_PORTS[i:] + global_vars.CLIENT_PORTS[:i]
    )
    bk_logger.info(
        f"Ports reordered so first port is now {global_vars.CLIENT_PORTS[0]} (previous index was {i})"
    )


def get_reports(app_id: str):
    """Get reports for all tasks of app_id Blender instance at once.
    If few last calls failed, then try to get reports also from other than default ports.
    """
    data = ensure_minimal_data({"app_id": app_id})
    data["project_name"] = utils.get_project_name()
    data["blender_version"] = utils.get_blender_version()

    # on 10, there is second BlenderKit-Client start
    if global_vars.CLIENT_FAILED_REPORTS < 10:
        url = f"{get_base_url()}/report"
        return request_report(url, data)

    last_exception = None
    for port in global_vars.CLIENT_PORTS:
        vapi = get_api_version()
        url = f"http://127.0.0.1:{port}/{vapi}/report"
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
    if last_exception is not None:
        raise last_exception


def request_report(url: str, data: dict) -> dict:
    """Make HTTP request to /report endpoint. If all goes well a JSON dict is returned.
    If something goes south, this function raises requests.HTTPError or requests.JSONDecodeError.
    """
    with requests.Session() as session:
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        if resp.status_code != 200:
            # not using resp.raise_for_status() for better message
            raise requests.HTTPError(
                f"{http_responses[resp.status_code]}: {resp.text}", response=resp
            )
        return resp.json()


### ASSETS
# SEARCH
def asset_search(search_data: datas.SearchData):
    """Search for specified asset."""
    bk_logger.info(f"Starting search request: {search_data.urlquery}")

    search_data = ensure_minimal_data_class(search_data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_search"
        resp = session.post(
            url, json=datas.asdict(search_data), timeout=TIMEOUT, proxies=NO_PROXIES
        )
        bk_logger.debug("Got search response")
        return resp.json()


# DOWNLOAD
def asset_download(data):
    """Download specified asset."""
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_download"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


def cancel_download(task_id: str):
    """Cancel the specified task with ID on the BlenderKit-Client."""
    data = ensure_minimal_data({"task_id": task_id})
    with requests.Session() as session:
        url = get_base_url() + "/blender/cancel_download"
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
        url = get_base_url() + "/blender/asset_upload"
        bk_logger.debug(f"making a request to: {url}")
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


### PROFILES
def download_gravatar_image(author_data: datas.UserProfile) -> requests.Response:
    """Fetch gravatar image for specified user. Find it on disk or download it from server."""
    data = {
        "id": author_data.id,
        "avatar128": author_data.avatar128,
        "gravatarHash": author_data.gravatarHash,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/profiles/download_gravatar_image"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def get_user_profile() -> requests.Response:
    """Fetch profile of currently logged-in user.
    This creates task on BlenderKit-Client to fetch data which are later handled once available.
    """
    data = ensure_minimal_data()
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/profiles/get_user_profile",
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
            f"{get_base_url()}/comments/get_comments",
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
            f"{get_base_url()}/comments/create_comment",
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
            f"{get_base_url()}/comments/feedback_comment",
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
            f"{get_base_url()}/comments/mark_comment_private",
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
            f"{get_base_url()}/notifications/mark_notification_read",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### REPORTS
def report_usages(data: dict):
    """Report usages of assets in current scene via BlenderKit-Client to the server."""
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/report_usages",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# RATINGS
def get_rating(asset_id: str):
    data = ensure_minimal_data({"asset_id": asset_id})
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/ratings/get_rating",
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
            f"{get_base_url()}/ratings/send_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# BOOKMARKS
def get_bookmarks():
    data = ensure_minimal_data()
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/ratings/get_bookmarks",
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
            f"{get_base_url()}/wrappers/get_download_url",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        resp = resp.json()
        return (resp["can_download"], resp["download_url"], resp["filename"])


def complete_upload_file_blocking(
    api_key, asset_id, filepath, filetype: str, fileindex: int
) -> bool:
    """Complete file upload in just one step, blocks until upload is finished. Useful for background scripts."""
    data = {
        "api_key": api_key,
        "assetId": asset_id,
        "fileType": filetype,
        "fileIndex": fileindex,
        "filePath": filepath,
        "originalFilename": os.path.basename(filepath),  # teoreticky asi nemusi byt
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_base_url()}/wrappers/complete_upload_file_blocking",
            json=data,
            timeout=(1, 600),
            proxies=NO_PROXIES,
        )

        print("complete_upload_file_blocking resp:", resp)
        return resp.ok


def blocking_file_download(url: str, filepath: str, api_key: str) -> requests.Response:
    """Upload file to server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "url": url,
        "filepath": filepath,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/blocking_file_download",
            json=data,
            timeout=(1, 600),
            proxies=NO_PROXIES,
        )


def blocking_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    json_data: Optional[dict] = None,
    timeout: tuple = TIMEOUT,
) -> requests.Response:
    """Make blocking HTTP request through BlenderKit-Client.
    Will not return until results are available."""
    if headers is None:
        headers = {}
    data = {
        "url": url,
        "method": method,
        "headers": headers,
    }
    if json_data is not None:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/blocking_request",
            json=data,
            timeout=timeout,
            proxies=NO_PROXIES,
        )


### REQUEST WRAPPERS
def nonblocking_request(
    url: str,
    method: str,
    headers: Optional[dict] = None,
    json_data: Optional[dict] = None,
    messages: Optional[dict] = None,
) -> requests.Response:
    """Make non-blocking HTTP request through BlenderKit-Client.
    This function will return ASAP, not returning any actual data.
    """
    if headers is None:
        headers = {}
    if messages is None:
        messages = {}
    data = {
        "url": url,
        "method": method,
        "headers": headers,
        "messages": messages,
    }
    data = ensure_minimal_data(data)
    if json_data is not None:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/nonblocking_request",
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
            f"{get_base_url()}/oauth2/verification_data",
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
        url = get_base_url() + "/refresh_token"
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
        url = get_base_url() + "/oauth2/logout"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def unsubscribe_addon():
    """Unsubscribe the add-on from the BlenderKit-Client. Called when the add-on is disabled, uninstalled or when Blender is closed."""
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = get_base_url() + "/blender/unsubscribe_addon"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def shutdown_client():
    """Request to shutdown the BlenderKit-Client."""
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = get_base_url() + "/shutdown"
        resp = session.get(url, data=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def handle_client_status_task(task):
    if global_vars.CLIENT_RUNNING is False:
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"
    global_vars.CLIENT_RUNNING = True


def check_blenderkit_client_return_code() -> tuple[int, str]:
    """Check the return code for the started BlenderKit-Client. If the return code returned from process.poll() is None - returned by this func as -1, it means Client still runs - we consider this a success!
    However if the return code from poll() is present, it failed to start and we check the return code value. If the return code is known,
    we print information to user about the reason. So they do not need to dig in the Client log.
    """
    # Return codes - as defined in main.go
    rcServerStartOtherError = 40
    rcServerStartOtherNetworkingError = 41
    rcServerStartOtherSyscallError = 42
    rcServerStartSyscallEADDRINUSE = 43
    rcServerStartSyscallEACCES = 44
    if global_vars.client_process is None:
        return -2, "Unexpectedly global_vars.client_process is None"

    exit_code = global_vars.client_process.poll()
    if exit_code is None:
        return -1, "BlenderKit-Client process is running."

    # need to initialize msg, was throwing an error
    msg = f"Unknown error."
    if exit_code == rcServerStartOtherError:
        msg = f"Other starting problem."
    if exit_code == rcServerStartOtherNetworkingError:
        msg = f"Other networking problem."
    if exit_code == rcServerStartOtherSyscallError:
        msg = f"Other syscall error."

    if exit_code == rcServerStartSyscallEADDRINUSE:  # This is known solution
        return (
            exit_code,
            "Address already in use: please change the port in add-on preferences.",
        )
    if exit_code == rcServerStartSyscallEACCES:  # This needs verification
        return (
            exit_code,
            "Access denied: change port in preferences, check permissions and antivirus rights.",
        )

    message = (
        f"{msg} Please report a bug and paste content of log {get_client_log_path()}"
    )
    return exit_code, message


def start_blenderkit_client():
    """Start BlenderKit-client in separate process.
    1. Check if binary is available at global_dir/client/vX.Y.Z/blenderkit-client-<os>-<arch>(.exe)
    2. Copy the binary from add-on directory to global_dir/client/vX.Y.Z/
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
                    "--software",
                    "Blender",
                    "--pid",
                    str(os.getpid()),
                ],
                stdout=log,
                stderr=log,
                creationflags=creation_flags,
            )
    except Exception as e:
        msg = f"Error: BlenderKit-Client {client_version} failed to start on {get_address()}:{e}"
        reports.add_report(msg, type="ERROR")
        raise (e)

    bk_logger.info(f"BlenderKit-Client {client_version} starting on {get_address()}")


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
    global_dir = bpy.context.preferences.addons[__package__].preferences.global_dir  # type: ignore
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


def get_preinstalled_client_path() -> str:
    """Get the path to the preinstalled BlenderKit-Client binary - located in add-on directory.
    This is the binary that is shipped with the add-on. It is copied to global_dir/client/vX.Y.Z on first run.
    """
    addon_dir = path.dirname(__file__)
    binary_name = decide_client_binary_name()
    binary_path = path.join(
        addon_dir, "client", global_vars.CLIENT_VERSION, binary_name
    )
    return path.abspath(binary_path)


def get_client_binary_path():
    """Get the path to the BlenderKit-Client binary located in global_dir/client/bin/vX.Y.Z.
    This is the binary that is used to start the client process.
    We do not start from the add-on because it might block update or delete of the add-on.
    Returns: (str, str) - path to the Client binary, version of the Client binary
    """
    client_dir = get_client_directory()
    binary_name = decide_client_binary_name()
    ver_string = global_vars.CLIENT_VERSION
    binary_path = path.join(client_dir, "bin", ver_string, binary_name)
    return path.abspath(binary_path), ver_string


def ensure_client_binary_installed():
    """Ensure that the BlenderKit-Client binary is installed in global_dir/client/bin/vX.Y.Z.
    If not, copy the binary from the add-on directory blenderkit/client.
    As side effect, this function also creates the global_dir/client/bin/vX.Y.Z directory.
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
