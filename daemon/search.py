"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os
import uuid

import aiohttp
from aiohttp import web
import globals, utils, assets, tasks


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
  async with session.get(image_url) as resp:
    if resp and resp.status == 200:
      with open(image_path, 'wb') as file:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          file.write(chunk)
          task.finished("thumbnail downloaded")
          # debug weird order of download - usually does odd numbers first
          # print(task.data['index'])
    else:
      task.error(f"thumbnail download error: {resp.status}")


async def download_image_batch(session: aiohttp.ClientSession, tsks: list[tasks.Task]):
  """Download batch of images. images are tuples of file path and url."""
  
  coroutines = []
  for task in tsks:
    coroutine = asyncio.ensure_future(download_image(session, task))
    coroutines.append(coroutine)
  await asyncio.gather(*coroutines)

async def parse_thumbnails(task: tasks.Task):
  """Go through results and extract correct filenames."""

  small_thumbs_tasks = []
  full_thumbs_tasks = []
  # END OF PARSING
  # get thumbnails that need downloading
  i=0
  for d in task.result.get('results', []):
    imgname = assets.extract_filename_from_url(d['thumbnailSmallUrl'])
    imgpath = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": imgpath,
      "image_url": d["thumbnailSmallUrl"],
      "assetBaseId": d['assetBaseId'],
      "thumbnail_type": "small",
      "index":i
    }

    task_id = str(uuid.uuid4())
    thumb_task = tasks.Task(data, task_id, task.app_id, "thumbnail_download")
    globals.tasks.append(thumb_task)
    if os.path.exists(thumb_task.data['image_path']):
      thumb_task.finished("thumbnail on disk")
    else:
      small_thumbs_tasks.append(thumb_task)


    if d["assetType"] == 'hdr':
      larege_thumb_url = d['thumbnailLargeUrlNonsquared']

    else:
      larege_thumb_url = d['thumbnailMiddleUrl']

    imgname = assets.extract_filename_from_url(larege_thumb_url)
    imgpath = os.path.join(task.data['tempdir'], imgname)
    data = {
      "image_path": imgpath,
      "image_url": larege_thumb_url,
      "assetBaseId": d['assetBaseId'],
      "thumbnail_type": "full",
      "index": i

    }

    task_id = str(uuid.uuid4())
    thumb_task = tasks.Task(data, task_id, task.app_id, "thumbnail_download")
    globals.tasks.append(thumb_task)
    if os.path.exists(thumb_task.data['image_path']):
      thumb_task.finished("thumbnail on disk")
    else:
      full_thumbs_tasks.append(thumb_task)
    i+=1

  return small_thumbs_tasks, full_thumbs_tasks


async def do_search(request: web.Request, data: dict, task_id: str):
  
  app_id = data['app_id']
  del data['app_id']
  task = tasks.Task(data, task_id, app_id, 'search', message='Searching assets')
  globals.tasks.append(task)

  rdata = {}
  rdata['results'] = []
  headers = utils.get_headers(task.data['PREFS']['api_key'])

  session = request.app['SESSION_API_REQUESTS']
  async with session.get(task.data['urlquery'], headers=headers) as resp:
    await resp.text()
    response = await resp.json()
    # except Exception as e:
    #   if hasattr(r, 'text'):
    #     error_description = parse_html_formated_error(r.text)
    #     assets.add_error_report(data, text=error_description)
    #   return

    # if not rdata.get('results'):
    # utils.pprint(rdata)
    # if the result was converted to json and didn't return results,
    # it means it's a server error that has a clear message.
    # That's why it gets processed in the update timer, where it can be passed in messages to user.
    # utils.p('end search thread')

    # save result so it can be returned to addon

    task.finished('Search results downloaded')
    task.result = response
    
    # if self.stopped():
    #   # utils.p('end search thread')
    #   return

    small_thumbs_tasks, full_thumbs_tasks = await parse_thumbnails(task)

    # thumbnails fetching
    await download_image_batch(request.app['SESSION_SMALL_THUMBS'], small_thumbs_tasks)
    await download_image_batch(request.app['SESSION_BIG_THUMBS'], full_thumbs_tasks)

