"""Module which contains code for comments and notifications."""

import asyncio
from logging import getLogger

import aiohttp
import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


logger = getLogger(__name__)


### COMMENTS
async def comments_handler(request: web.Request):
    data = await request.json()
    func = request.match_info["func"]
    task = daemon_tasks.Task(data, data["app_id"], f"comments/{func}")
    daemon_globals.tasks.append(task)
    if func == "get_comments":
        task.async_task = asyncio.ensure_future(get_comments(request, task))
    elif func == "create_comment":
        task.async_task = asyncio.ensure_future(create_comment(request, task))
    elif func == "feedback_comment":
        task.async_task = asyncio.ensure_future(feedback_comment(request, task))
    elif func == "mark_comment_private":
        task.async_task = asyncio.ensure_future(mark_comment_private(request, task))

    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.json_response({"task_id": task.task_id})


async def get_comments(request: web.Request, task: daemon_tasks.Task):
    """Retrieve comments from server."""
    asset_id = task.data["asset_id"]
    headers = daemon_utils.get_headers(task.data.get("api_key", ""))
    session = request.app["SESSION_API_REQUESTS"]
    url = f"{daemon_globals.SERVER}/api/v1/comments/assets-uuidasset/{asset_id}/"
    try:
        async with session.get(url, headers=headers) as resp:
            task.result = await resp.json()
            task.finished("comments downloaded")
    except aiohttp.ClientResponseError as e:
        logger.error(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"Get comments failed: {e.message} ({e.status})")
    except Exception as e:
        logger.error(f"{type(e)}: {e}")
        return task.error(f"Get comments {type(e)}: {e}")


async def create_comment(request: web.Request, task: daemon_tasks.Task) -> bool:
    """Create and upload the comment online."""
    asset_id = task.data["asset_id"]
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    url = f"{daemon_globals.SERVER}/api/v1/comments/asset-comment/{asset_id}/"
    try:
        async with session.get(url, headers=headers) as resp:
            comment_data = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.error(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        task.error(f"GET in create_comment failed: {e.message} ({e.status})")
        return False
    except Exception as e:
        logger.error(f"{type(e)}: {e}")
        task.error(f"GET in create_comment {type(e)}: {e}")
        return False

    post_data = {
        "name": "",
        "email": "",
        "url": "",
        "followup": task.data["reply_to_id"] > 0,
        "reply_to": task.data["reply_to_id"],
        "honeypot": "",
        "content_type": "assets.uuidasset",
        "object_pk": asset_id,
        "timestamp": comment_data["form"]["timestamp"],
        "security_hash": comment_data["form"]["securityHash"],
        "comment": task.data["comment_text"],
    }
    url = f"{daemon_globals.SERVER}/api/v1/comments/comment/"
    try:
        async with session.post(url, headers=headers, data=post_data) as resp:
            task.result = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.error(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        task.error(f"POST in create_comment failed: {e.message} ({e.status})")
        return False
    except Exception as e:
        logger.error(f"{type(e)}: {e}")
        task.error(f"POST in create_comment {type(e)}: {e}")
        return False

    task.finished("Comment created")
    followup_task = daemon_tasks.Task(
        task.data, task.data["app_id"], "comments/get_comments"
    )
    daemon_globals.tasks.append(followup_task)
    get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
    get_comments_task.add_done_callback(daemon_tasks.handle_async_errors)


async def feedback_comment(request: web.Request, task: daemon_tasks.Task):
    """Upload feedback flag on the comment to the server. Flag is like/dislike but can be also a different flag."""
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    data = {
        "comment": task.data["comment_id"],
        "flag": task.data["flag"],
    }
    url = f"{daemon_globals.SERVER}/api/v1/comments/feedback/"
    try:
        async with session.post(url, data=data, headers=headers) as resp:
            task.result = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        task.error(f"Feedback POST failed: {e.message} ({e.status})")
        return False
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"Feedback POST {type(e)}: {e}")

    task.finished("flag uploaded")
    followup_task = daemon_tasks.Task(
        task.data, task.data["app_id"], "comments/get_comments"
    )
    daemon_globals.tasks.append(followup_task)
    get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
    get_comments_task.add_done_callback(daemon_tasks.handle_async_errors)


async def mark_comment_private(request: web.Request, task: daemon_tasks.Task) -> None:
    """Update visibility of the comment."""
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    data = {"is_private": task.data["is_private"]}
    url = (
        f'{daemon_globals.SERVER}/api/v1/comments/is_private/{task.data["comment_id"]}/'
    )
    try:
        async with session.post(url, data=data, headers=headers) as resp:
            task.result = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"Mark comment failed: {e.message} ({e.status})")
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"Mark comment {type(e)}: {e}")

    task.finished("comment visibility updated")
    followup_task = daemon_tasks.Task(
        task.data, task.data["app_id"], "comments/get_comments"
    )
    daemon_globals.tasks.append(followup_task)
    get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
    get_comments_task.add_done_callback(daemon_tasks.handle_async_errors)
    return None


### NOTIFICATIONS
async def mark_notification_read_handler(request: web.Request):
    data = await request.json()
    task = daemon_tasks.Task(
        data, data["app_id"], "notifications/mark_notification_read"
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(mark_notification_read(request, task))
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.json_response({"task_id": task.task_id})


async def mark_notification_read(request: web.Request, task: daemon_tasks.Task) -> None:
    """Mark notification as read."""
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    url = f'{daemon_globals.SERVER}/api/v1/notifications/mark-as-read/{task.data["notification_id"]}/'
    try:
        async with session.get(url, headers=headers) as resp:
            task.result = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"Mark notification failed: {e.message} ({e.status})")
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"Mark notification {type(e)}: {e}")

    return task.finished("notification marked as read")
