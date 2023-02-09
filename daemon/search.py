"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os
import uuid
from logging import getLogger

import aiohttp
import assets
import globals
import tasks
from aiohttp import web

import utils


logger = getLogger(__name__)

def report_image_finished(data, filepath, done=True):
  """Report a thumbnail is downloaded and available. Not used by now."""
  globals.tasks[filepath] = {
    'app_id': data['PREFS']['app_id'],
    'type': 'thumbnail-available',
    'task_id': filepath,
    'done': done
  }


async def download_image(session: aiohttp.ClientSession, task: tasks.Task):
  """Download a single image and report to addon."""
  image_url = task.data["image_url"]
  image_path = task.data["image_path"]
  try:
    async with session.get(image_url, headers=utils.get_headers()) as resp:
      if resp and resp.status != 200:
        task.error(f"thumbnail download error: {resp.status}")
      with open(image_path, 'wb') as file:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          file.write(chunk)
      task.finished("thumbnail downloaded")
  except Exception as e:
    task.error(f"thumbnail download error: {e}")


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
  """Go through results and extract correct filenames and URLs. Use webp versions if available.
  Check if file is on disk, if not start a download.
  """
  small_thumbs_tasks = []
  full_thumbs_tasks = []
  blender_version = task.data['blender_version'].split('.')
  blender_version = (int(blender_version[0]), int(blender_version[1]), (int(blender_version[2])))
  for i, search_result in enumerate(task.result.get('results', [])):
    use_webp = True
    if blender_version < (3,4,0) or search_result.get('webpGeneratedTimestamp') == None:
      use_webp = False #WEBP was optimized in Blender 3.4.0

    # SMALL THUMBNAIL
    if use_webp: 
      image_url = search_result.get('thumbnailSmallUrlWebp')
    else:
      image_url = search_result.get('thumbnailSmallUrl')

    imgname = assets.extract_filename_from_url(image_url)
    image_path = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": image_path,
      "image_url": image_url,
      "assetBaseId": search_result['assetBaseId'],
      "thumbnail_type": "small",
      "index": i,
    }
    small_thumb_task = tasks.Task(data, task.app_id, "thumbnail_download")
    globals.tasks.append(small_thumb_task)
    if os.path.exists(small_thumb_task.data['image_path']):
      small_thumb_task.finished("thumbnail on disk")
    else:
      small_thumbs_tasks.append(small_thumb_task)
    # FULL THUMBNAIL
    # HDR CASE
    if search_result["assetType"] == 'hdr':
      if use_webp:
        image_url = search_result.get('thumbnailLargeUrlNonsquaredWebp')
      else:
        image_url = search_result.get('thumbnailLargeUrlNonsquared')
    #NON-HDR CASE
    else:
      if use_webp:
        image_url = search_result.get('thumbnailMiddleUrlWebp')
      else:
        image_url = search_result.get('thumbnailMiddleUrl')

    imgname = assets.extract_filename_from_url(image_url)
    image_path = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": image_path,
      "image_url": image_url,
      "assetBaseId": search_result['assetBaseId'],
      "thumbnail_type": "full",
      "index": i,
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
  try:
    async with session.get(task.data['urlquery'], headers=headers) as resp:
      await resp.text()
      if resp.status != 429:
        task.error(f'Search request failed (429), API limit exceeded, please search again in 10 seconds')
      if resp.status != 200:
        task.error(f'Search request failed, status code:{resp.status}')

      response = await resp.json()
      task.finished('Search results downloaded')
      task.result = response
      
      small_thumbs_tasks, full_thumbs_tasks = await parse_thumbnails(task)
      # thumbnails fetching
      await download_image_batch(request.app['SESSION_SMALL_THUMBS'], small_thumbs_tasks)
      await download_image_batch(request.app['SESSION_BIG_THUMBS'], full_thumbs_tasks)
  except Exception as e:
    task.error(f'Search task failed: {str(e)}')


async def fetch_categories(request: web.Request):
  data = await request.json()
  task = tasks.Task(data, data['app_id'], 'categories_update', str(uuid.uuid4()), message='Getting updated categories')
  globals.tasks.append(task)

  headers = utils.get_headers(data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  try:
    async with session.get(f'{globals.SERVER}/api/v1/categories/', headers=headers) as resp:
      data = await resp.json()
      categories = data['results']
      fix_category_counts(categories)           # filter_categories(categories) #TODO this should filter categories for search, but not for upload. by now off.
      task.result = categories
      task.finished('Categories fetched')

  except Exception as e:
    logger.error(e)
    task.error('Failed to download categories: {e}')


def count_to_parent(parent):
  for c in parent['children']:
    count_to_parent(c)
    parent['assetCount'] += c['assetCount']


def fix_category_counts(categories):
  for c in categories:
    count_to_parent(c)
