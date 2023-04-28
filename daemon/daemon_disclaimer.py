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
        data, app_id, "disclaimer", str(uuid.uuid4()), message="Getting disclaimer"
    )
    daemon_globals.tasks.append(task)
    headers = daemon_utils.get_headers(data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        async with session.get(
            f"{daemon_globals.SERVER}/api/v1/disclaimer/active/", headers=headers
        ) as resp:
            response = await resp.json()
    except ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"Get disclaimer failed: {e.message} ({e.status})")
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"Get disclaimer {type(e)}: {e}")

    if len(response["results"]) > 0:
        task.result = response
        return task.finished("Disclaimer retrieved")
    return task.finished("Disclaimer not retrieved, serve a tip to user")


async def get_notifications(request: web.Request):
    """Retrieve unread notifications from the server."""
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "notifications",
        str(uuid.uuid4()),
        message="Getting notifications",
    )
    daemon_globals.tasks.append(task)
    headers = daemon_utils.get_headers(data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        async with session.get(
            f"{daemon_globals.SERVER}/api/v1/notifications/unread/", headers=headers
        ) as resp:
            task.result = await resp.json()
    except ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"Get notifications failed: {e.message} ({e.status})")
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"Get notifications {type(e)}: {e}")

    return task.finished("Notifications retrieved")
