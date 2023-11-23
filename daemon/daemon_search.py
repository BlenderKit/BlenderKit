"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os
import uuid
from logging import getLogger

import aiohttp
import daemon_assets
import daemon_globals
import daemon_tasks
import daemon_utils
import yarl
from aiohttp import ClientResponseError, web


logger = getLogger(f"daemon.{__name__}")


def report_image_finished(data, filepath, done=True):
    """Report a thumbnail is downloaded and available. Not used by now."""
    daemon_globals.tasks[filepath] = {
        "app_id": data["PREFS"]["app_id"],
        "type": "thumbnail-available",
        "task_id": filepath,
        "done": done,
    }


async def download_image(session: aiohttp.ClientSession, task: daemon_tasks.Task):
    """Download a single image and report to addon."""
    image_url = task.data["image_url"]
    image_path = task.data["image_path"]
    headers = daemon_utils.get_headers()
    iurl = yarl.URL(image_url, encoded=True)
    try:
        async with session.get(iurl, headers=headers, raise_for_status=True) as resp:
            with open(image_path, "wb") as file:
                async for chunk in resp.content.iter_chunked(4096 * 32):
                    file.write(chunk)
                return task.finished("thumbnail downloaded")
    except ClientResponseError as e:
        msg = f"Thumbnail download failed: {e.message} ({e.status})"
        detail = f'Thumbnail download ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        return task.error(msg, message_detailed=detail)
    except Exception as e:
        msg = f"Thumbnail download failed: {e}"
        detail = f"Thumbnail download {type(e)}: {e}"
        return task.error(msg, message_detailed=detail)


async def download_image_batch(
    session: aiohttp.ClientSession, tsks: list[daemon_tasks.Task], block: bool = False
):
    """Download batch of images. images are tuples of file path and url."""
    atasks = []
    for task in tsks:
        task.async_task = asyncio.ensure_future(download_image(session, task))
        task.async_task.set_name(f"{task.task_type}-{task.task_id}")
        task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
        atasks.append(task.async_task)

    if block is True:
        await asyncio.gather(*atasks)


async def parse_thumbnails(task: daemon_tasks.Task):
    """Go through results and extract correct filenames and URLs. Use webp versions if available.
    Check if file is on disk, if not start a download.
    """
    small_thumbs_tasks = []
    full_thumbs_tasks = []
    blender_version = task.data["blender_version"].split(".")
    blender_version = (
        int(blender_version[0]),
        int(blender_version[1]),
        (int(blender_version[2])),
    )
    for i, search_result in enumerate(task.result.get("results", [])):
        use_webp = True
        if (
            blender_version < (3, 4, 0)
            or search_result.get("webpGeneratedTimestamp") is None
        ):
            use_webp = False  # WEBP was optimized in Blender 3.4.0

        # SMALL THUMBNAIL
        if use_webp:
            image_url = search_result.get("thumbnailSmallUrlWebp")
        else:
            image_url = search_result.get("thumbnailSmallUrl")

        imgname = daemon_assets.extract_filename_from_url(image_url)
        image_path = os.path.join(task.data["tempdir"], imgname)
        data = {
            "image_path": image_path,
            "image_url": image_url,
            "assetBaseId": search_result["assetBaseId"],
            "thumbnail_type": "small",
            "index": i,
        }
        small_thumb_task = daemon_tasks.Task(data, task.app_id, "thumbnail_download")
        daemon_globals.tasks.append(small_thumb_task)
        if os.path.exists(small_thumb_task.data["image_path"]):
            small_thumb_task.finished("thumbnail on disk")
        else:
            small_thumbs_tasks.append(small_thumb_task)
        # FULL THUMBNAIL
        # HDR CASE
        if search_result["assetType"] == "hdr":
            if use_webp:
                image_url = search_result.get("thumbnailLargeUrlNonsquaredWebp")
            else:
                image_url = search_result.get("thumbnailLargeUrlNonsquared")
        # NON-HDR CASE
        else:
            if use_webp:
                image_url = search_result.get("thumbnailMiddleUrlWebp")
            else:
                image_url = search_result.get("thumbnailMiddleUrl")

        imgname = daemon_assets.extract_filename_from_url(image_url)
        image_path = os.path.join(task.data["tempdir"], imgname)
        data = {
            "image_path": image_path,
            "image_url": image_url,
            "assetBaseId": search_result["assetBaseId"],
            "thumbnail_type": "full",
            "index": i,
        }
        full_thumb_task = daemon_tasks.Task(data, task.app_id, "thumbnail_download")
        daemon_globals.tasks.append(full_thumb_task)
        if os.path.exists(full_thumb_task.data["image_path"]):
            full_thumb_task.finished("thumbnail on disk")
        else:
            full_thumbs_tasks.append(full_thumb_task)
    return small_thumbs_tasks, full_thumbs_tasks


async def do_search(request: web.Request, task: daemon_tasks.Task):
    """Searches for results and download thumbnails.
    1. Sends search request to BlenderKit server. (Creates search task.)
    2. Reports the result to the addon. (Search task finished.)
    3. Gets small and large thumbnails. (Thumbnail tasks.)
    4. Reports paths to downloaded thumbnails. (Thumbnail task finished.)
    """
    headers = daemon_utils.get_headers(task.data["PREFS"]["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        resp_text, resp_status = None, -1
        async with session.get(task.data["urlquery"], headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            task.result = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Search failed"
        )
        return task.error(msg, message_detailed=detail)

    task.finished("Search results downloaded")
    # Post-search tasks
    small_thumbs_tasks, full_thumbs_tasks = await parse_thumbnails(task)
    await download_image_batch(request.app["SESSION_SMALL_THUMBS"], small_thumbs_tasks)
    await download_image_batch(request.app["SESSION_BIG_THUMBS"], full_thumbs_tasks)


async def fetch_categories(request: web.Request) -> None:
    data = await request.json()
    headers = daemon_utils.get_headers(data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "categories_update",
        task_id=str(uuid.uuid4()),
        message="Getting updated categories",
    )
    daemon_globals.tasks.append(task)
    url = f"{daemon_globals.SERVER}/api/v1/categories/"
    try:  # https://www.blenderkit.com/api/v1/docs/#operation/categories_list
        resp_text, resp_status = None, -1
        async with session.get(url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            resp_json = await resp.json()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get categories failed"
        )
        return task.error(msg, message_detailed=detail)

    categories = resp_json["results"]
    fix_category_counts(categories)
    # filter_categories(categories) #TODO this should filter categories for search, but not for upload. by now off.
    task.result = categories
    return task.finished("Categories fetched")


def count_to_parent(parent):
    for c in parent["children"]:
        count_to_parent(c)
        parent["assetCount"] += c["assetCount"]


def fix_category_counts(categories):
    for c in categories:
        count_to_parent(c)
