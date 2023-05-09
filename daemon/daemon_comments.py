"""Module which contains code for comments and notifications."""

import asyncio
from logging import getLogger

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
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_read
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
            return task.finished("comments downloaded")
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get comments failed"
        )
        return task.error(msg, message_detailed=detail)


async def create_comment(request: web.Request, task: daemon_tasks.Task) -> bool:
    """Create and upload the comment online."""
    asset_id = task.data["asset_id"]
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    url = f"{daemon_globals.SERVER}/api/v1/comments/asset-comment/{asset_id}/"
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_get
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            comment_data = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "GET in create_comment"
        )
        task.error(msg, message_detailed=detail)
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
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_comment_create
        resp_text, resp_status = None, -1
        async with session.post(url, headers=headers, data=post_data) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "POST in create_comment"
        )
        task.error(msg, message_detailed=detail)
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
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_feedback_create
        resp_text, resp_status = None, -1
        async with session.post(url, data=data, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "POST comment feedback"
        )
        return task.error(msg, message_detailed=detail)

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
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_feedback_create
        resp_text, resp_status = None, -1
        async with session.post(url, data=data, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Mark comment failed"
        )
        return task.error(msg, message_detailed=detail)

    task.finished("comment visibility updated")
    followup_task = daemon_tasks.Task(
        task.data, task.data["app_id"], "comments/get_comments"
    )
    daemon_globals.tasks.append(followup_task)
    get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
    get_comments_task.add_done_callback(daemon_tasks.handle_async_errors)
    return None


### NOTIFICATIONS
async def mark_notification_read_handler(request: web.Request) -> web.Response:
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
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/comments_feedback_create
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Mark notification as read failed"
        )
        return task.error(msg, message_detailed=detail)
    return task.finished("notification marked as read")
