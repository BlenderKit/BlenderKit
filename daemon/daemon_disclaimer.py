"""Holds functionality for getting disclaimers and notifications."""


import uuid
from logging import getLogger

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import ClientResponseError, web


logger = getLogger(__name__)


async def get_disclaimer(request: web.Request) -> None:
    """Get disclaimer from the server."""
    data = await request.json()
    app_id = data["app_id"]
    task = daemon_tasks.Task(
        data,
        app_id,
        "disclaimer",
        task_id=str(uuid.uuid4()),
        message="Getting disclaimer",
    )
    daemon_globals.tasks.append(task)
    headers = daemon_utils.get_headers(data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        resp_text, resp_json = None, None
        async with session.get(
            f"{daemon_globals.SERVER}/api/v1/disclaimer/active/", headers=headers
        ) as resp:
            resp_text = await resp.text()
            resp_json = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_json, "Get disclaimer failed"
        )
        return task.error(msg, message_detailed=detail)

    if len(resp_json["results"]) > 0:
        task.result = resp_json
        return task.finished("Disclaimer retrieved")
    return task.finished("Disclaimer not retrieved, serve a tip to user")


async def get_notifications(request: web.Request):
    """Retrieve unread notifications from the server."""
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "notifications",
        task_id=str(uuid.uuid4()),
        message="Getting notifications",
    )
    daemon_globals.tasks.append(task)
    headers = daemon_utils.get_headers(data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        resp_text, resp_json = None, None
        async with session.get(
            f"{daemon_globals.SERVER}/api/v1/notifications/unread/", headers=headers
        ) as resp:
            resp_text = await resp.text()
            task.result = resp_json= await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_json, "Get notifications failed"
        )
        return task.error(msg, message_detailed=detail)
        
    return task.finished("Notifications retrieved")
