"""Contains functions for work with profiles - profile of current user and also profiles of authors.
TODO: We should find a better vocabulary for this.
"""

import asyncio
import getpass
import os
import tempfile
from logging import getLogger
from urllib.parse import urljoin

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


logger = getLogger(f"daemon.{__name__}")


async def fetch_gravatar_image_handler(request: web.Request):
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "profiles/fetch_gravatar_image",
        message="Fetching gravatar image",
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(fetch_gravatar_image(task, request))
    task.async_task.set_name(f"{task.task_type}-{task.task_id}")
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def get_user_profile_handler(request: web.Request):
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "profiles/get_user_profile",
        message="Getting user profile",
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(get_user_profile(task, request))
    task.async_task.set_name(f"{task.task_type}-{task.task_id}")
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def fetch_gravatar_image(task: daemon_tasks.Task, request: web.Request):
    """Get gravatar image from blenderkit server.
    - task.data - author data from elastic search result + task.data['app_id']
    """
    if "avatar128" not in task.data:
        return fetch_gravatar_image_old(task, request)

    username = getpass.getuser()
    safe_username = "".join(c for c in username if c.isalnum())
    gravatar_path = os.path.join(
        tempfile.gettempdir(),
        f"bktemp_{safe_username}",
        "bkit_g",
        f'{task.data["id"]}.jpg',
    )
    if os.path.exists(gravatar_path):
        task.result = {"gravatar_path": gravatar_path}
        return task.finished("Found on disk")

    url = urljoin(daemon_globals.SERVER, task.data["avatar128"])
    session = request.app["SESSION_SMALL_THUMBS"]
    error = await daemon_utils.download_file(url, gravatar_path, session)
    if error != "":
        return task.error(f"Gravatar download failed - {error}")

    task.result = {"gravatar_path": gravatar_path}
    return task.finished("Downloaded")


async def fetch_gravatar_image_old(task: daemon_tasks.Task, request: web.Request):
    """Older way of getting gravatar image. May be needed for some users with old gravatars."""  # TODO: is this still in use?
    if task.data.get("gravatarHash") is None:
        return
    username = getpass.getuser()
    safe_username = "".join(c for c in username if c.isalnum())
    gravatar_path = os.path.join(
        tempfile.gettempdir(),
        f"bktemp_{safe_username}",
        "bkit_g",
        f'{task.data["gravatarHash"]}.jpg',
    )
    if os.path.exists(gravatar_path):
        task.result = {"gravatar_path": gravatar_path}
        return task.finished("Found on disk")

    url = urljoin(
        "https://www.gravatar.com/avatar", f'{task.data["gravatarHash"]}?d=404'
    )
    session = request.app["SESSION_SMALL_THUMBS"]
    error = await daemon_utils.download_file(url, gravatar_path, session)
    if error != "":
        return task.error(f"Gravatar download failed - {error}")

    task.result = {"gravatar_path": gravatar_path}
    return task.finished("Downloaded")


async def get_user_profile(task: daemon_tasks.Task, request: web.Request) -> None:
    """Get profile data for currently logged-in user. Data are cleaned a little bit and then reported to the add-on."""
    api_key = task.data["api_key"]
    headers = daemon_utils.get_headers(api_key)
    session = request.app["SESSION_API_REQUESTS"]
    url = f"{daemon_globals.SERVER}/api/v1/me/"
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/me_list
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            resp_json = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get profile"
        )
        return task.error(msg, message_detailed=detail)

    if resp_json.get("user") is None:
        return task.error("profile is None")

    task.result = convert_user_data(resp_json)
    return task.finished("data suceessfully fetched")


def convert_user_data(data: dict):
    """Convert user data quotas to MiB, otherwise numbers would be too big for Python int type"""
    user = data["user"]
    if user.get("sumAssetFilesSize") is not None:
        user["sumAssetFilesSize"] /= 1024 * 1024
    if user.get("sumPrivateAssetFilesSize") is not None:
        user["sumPrivateAssetFilesSize"] /= 1024 * 1024
    if user.get("remainingPrivateQuota") is not None:
        user["remainingPrivateQuota"] /= 1024 * 1024
    data["user"] = user
    return data
