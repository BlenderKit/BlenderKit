import asyncio
from logging import getLogger

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


logger = getLogger(__name__)


async def get_rating_handler(request: web.Request):
    data = await request.json()
    task = daemon_tasks.Task(
        data, data["app_id"], "ratings/get_rating", message="Getting rating data"
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(get_rating(task, request))
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def get_rating(task: daemon_tasks.Task, request: web.Request) -> None:
    session = request.app["SESSION_API_REQUESTS"]
    headers = daemon_utils.get_headers(task.data.get("api_key", ""))
    url = f'{daemon_globals.SERVER}/api/v1/assets/{task.data["asset_id"]}/rating/'
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/assets_rating_list
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get rating failed"
        )
        return task.error(msg, message_detailed=detail)
    return task.finished("Rating data obtained")


async def send_rating_handler(request: web.Request):
    """Handle incomming rating request (quality, work hours, bookmark, etc).
    If the rating value is 0, delete the rating from the server.
    """
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "ratings/send_rating",
        message=f'Sending {data["rating_type"]} rating',
    )
    daemon_globals.tasks.append(task)
    if float(data["rating_value"]) == 0:
        task.async_task = asyncio.ensure_future(delete_rating(task, request))
    else:
        task.async_task = asyncio.ensure_future(send_rating(task, request))
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def send_rating(task: daemon_tasks.Task, request: web.Request) -> None:
    session = request.app["SESSION_API_REQUESTS"]
    headers = daemon_utils.get_headers(task.data.get("api_key", ""))
    data = {"score": task.data["rating_value"]}
    logger.info(
        f'Sending rating {task.data["rating_type"]}={task.data["rating_value"]} for asset {task.data["asset_id"]}'
    )
    url = f'{daemon_globals.SERVER}/api/v1/assets/{task.data["asset_id"]}/rating/{task.data["rating_type"]}/'
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/assets_rating_update
        resp_text, resp_status = None, -1
        async with session.put(url, headers=headers, json=data) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e,
            resp_text,
            resp_status,
            f"Rating {task.data['rating_type']}={task.data['rating_value']} failed",
        )
        return task.error(msg, message_detailed=detail)
    return task.finished(
        f"Rated {task.data['rating_type']}={task.data['rating_value']} successfully"
    )


async def delete_rating(task: daemon_tasks.Task, request: web.Request) -> None:
    session = request.app["SESSION_API_REQUESTS"]
    headers = daemon_utils.get_headers(task.data.get("api_key", ""))
    logger.info(
        f'Deleting rating {task.data["rating_type"]}={task.data["rating_value"]} for asset {task.data["asset_id"]}'
    )
    url = f'{daemon_globals.SERVER}/api/v1/assets/{task.data["asset_id"]}/rating/{task.data["rating_type"]}/'
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/assets_rating_delete
        resp_text, resp_status = None, -1
        async with session.delete(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e,
            resp_text,
            resp_status,
            f"Delete rating {task.data['rating_type']} failed",
        )
        return task.error(msg, message_detailed=detail)
    msg = f"Rating {task.data['rating_type']} deleted"
    logger.info(msg)
    return task.finished(msg)


async def get_bookmarks_handler(request: web.Request):
    data = await request.json()
    task = daemon_tasks.Task(
        data, data["app_id"], "ratings/get_bookmarks", message="Getting bookmarks data"
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(get_bookmarks(task, request))
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def get_bookmarks(task: daemon_tasks.Task, request: web.Request) -> None:
    session = request.app["SESSION_API_REQUESTS"]
    headers = daemon_utils.get_headers(task.data.get("api_key", ""))
    url = f"{daemon_globals.SERVER}/api/v1/search/?query=bookmarks_rating:1"
    try:
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get bookmarks failed"
        )
        return task.error(msg, message_detailed=detail)
    return task.finished("Bookmarks data obtained")
