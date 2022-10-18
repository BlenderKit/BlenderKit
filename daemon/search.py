"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os

import aiohttp
import assets
import globals
import tasks
from aiohttp import web

import utils


def report_image_finished(data, filepath, done=True):
  """Report a thumbnail is downloaded and available. Not used by now."""

  globals.tasks[filepath] = {'app_id': data['PREFS']['app_id'],
                             'type': 'thumbnail-available',
                             'task_id': filepath,
                             'done': done}


async def download_image(session: aiohttp.ClientSession, task: tasks.Task):
  """Download a single image and report to addon."""

  image_url = task.data["image_url"]
  image_path = task.data["image_path"]
  async with session.get(image_url, headers=utils.get_headers()) as resp:
    if resp and resp.status == 200:
      with open(image_path, 'wb') as file:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          file.write(chunk)
      task.finished("thumbnail downloaded")
    else:
      task.error(f"thumbnail download error: {resp.status}")


async def download_image_batch(session: aiohttp.ClientSession, tsks: list[tasks.Task], block: bool = False):
  """Download batch of images. images are tuples of file path and url."""
  
  coroutines = []
  for task in tsks:
    coroutine = asyncio.ensure_future(download_image(session, task))
    coroutine.add_done_callback(tasks.handle_async_errors)
    coroutines.append(coroutine)
  
  if block == True:
    await asyncio.gather(*coroutines)

async def parse_thumbnails(task: tasks.Task):
  """Go through results and extract correct filenames."""

  small_thumbs_tasks = []
  full_thumbs_tasks = []
  # END OF PARSING
  # get thumbnails that need downloading

  for i, search_result in enumerate(task.result.get('results', [])):
    # SMALL THUMBNAIL
    imgname = assets.extract_filename_from_url(search_result['thumbnailSmallUrl'])
    imgpath = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": imgpath,
      "image_url": search_result["thumbnailSmallUrl"],
      "assetBaseId": search_result['assetBaseId'],
      "thumbnail_type": "small",
      "index": i
    }

    small_thumb_task = tasks.Task(data, task.app_id, "thumbnail_download")
    globals.tasks.append(small_thumb_task)

    if os.path.exists(small_thumb_task.data['image_path']):
      small_thumb_task.finished("thumbnail on disk")
    else:
      small_thumbs_tasks.append(small_thumb_task)

    # FULL THUMBNAIL
    if search_result["assetType"] == 'hdr':
      large_thumb_url = search_result['thumbnailLargeUrlNonsquared']
    else:
      large_thumb_url = search_result['thumbnailMiddleUrl']

    imgname = assets.extract_filename_from_url(large_thumb_url)
    imgpath = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": imgpath,
      "image_url": large_thumb_url,
      "assetBaseId": search_result['assetBaseId'],
      "thumbnail_type": "full",
      "index": i
    }

    full_thumb_task = tasks.Task(data, task.app_id, "thumbnail_download")
    globals.tasks.append(full_thumb_task)
    if os.path.exists(full_thumb_task.data['image_path']):
      full_thumb_task.finished("thumbnail on disk")
    else:
      full_thumbs_tasks.append(full_thumb_task)

  return small_thumbs_tasks, full_thumbs_tasks


async def do_search(request: web.Request, task: tasks.Task):
  """Searches for results and download thumbnails.
  
  1. Sends search request to BlenderKit server. (Creates search task.)
  2. Reports the result to the addon. (Search task finished.)
  3. Gets small and large thumbnails. (Thumbnail tasks.)
  4. Reports paths to downloaded thumbnails. (Thumbnail task finished.)
  """

  rdata = {}
  rdata['results'] = []
  headers = utils.get_headers(task.data['PREFS']['api_key'])

  session = request.app['SESSION_API_REQUESTS']
  async with session.get(task.data['urlquery'], headers=headers) as resp:
    await resp.text()
    response = await resp.json()

    task.finished('Search results downloaded')
    task.result = response
    
    small_thumbs_tasks, full_thumbs_tasks = await parse_thumbnails(task)

    # thumbnails fetching
    await download_image_batch(request.app['SESSION_SMALL_THUMBS'], small_thumbs_tasks)
    await download_image_batch(request.app['SESSION_BIG_THUMBS'], full_thumbs_tasks)
