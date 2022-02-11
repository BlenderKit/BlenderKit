"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os
import uuid

import aiohttp
import globals, utils, assets


def report_image_finished(data, filepath, done=True):
  """Report a thumbnail is downloaded and available. Not used by now."""

  globals.tasks[filepath] = {'app_id': data['PREFS']['app_id'],
                             'type': 'thumbnail-available',
                             'task_id': filepath,
                             'done': done}


async def download_image(session: aiohttp.ClientSession, task: globals.Task):
  """Download a single image and report to addon."""

  image_url = task.data["image_url"]
  image_path = task.data["image_path"]
  async with session.get(image_url) as resp:
    if resp and resp.status == 200:
      with open(image_path, 'wb') as file:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          file.write(chunk)
          task.finished("thumbnail downloaded")
    else:
      task.error(f"thumbnail download error: {resp.status}")


async def download_image_batch(session: aiohttp.ClientSession, parent_task: globals.Task, images: list[tuple] =[], limit_per_host=0):
  """Download batch of images. images are tuples of file path and url."""
  
  coroutines = []
  for imgpath, url in images:
    data = {
      "image_path" : imgpath,
      "image_url" : url,
    }
    task_id = str(uuid.uuid4())
    task = globals.Task(data, task_id, parent_task.app_id, "thumbnail_download")

    if os.path.exists(imgpath):
      task.finished("thumbnail on disk")
    else:
      coroutine = asyncio.ensure_future(download_image(session, task))
      coroutines.append(coroutine)

  await asyncio.gather(*coroutines)


async def parse_thumbnails(task: globals.Task):
  """Go through results and extract correct filenames."""

  thumb_small_urls = []
  thumb_small_filepaths = []
  thumb_full_urls = []
  thumb_full_filepaths = []
  # END OF PARSING
  # get thumbnails that need downloading
  for d in task.result.get('results', []):
    thumb_small_urls.append(d["thumbnailSmallUrl"])
    imgname = assets.extract_filename_from_url(d['thumbnailSmallUrl'])
    imgpath = os.path.join(task.data['tempdir'], imgname)
    thumb_small_filepaths.append(imgpath)

    if d["assetType"] == 'hdr':
      larege_thumb_url = d['thumbnailLargeUrlNonsquared']

    else:
      larege_thumb_url = d['thumbnailMiddleUrl']

    thumb_full_urls.append(larege_thumb_url)
    imgname = assets.extract_filename_from_url(larege_thumb_url)
    imgpath = os.path.join(task.data['tempdir'], imgname)
    thumb_full_filepaths.append(imgpath)

  small_thumbnails = zip(thumb_small_filepaths, thumb_small_urls)
  full_thumbnails = zip(thumb_full_filepaths, thumb_full_urls)

  return small_thumbnails, full_thumbnails


async def do_search(session: aiohttp.ClientSession, data: dict, task_id: str):
  
  app_id = data['app_id']
  del data['app_id']
  task = globals.Task(data, task_id, app_id, 'search', message='Looking for asset')

  rdata = {}
  rdata['results'] = []
  headers = utils.get_headers(task.data['PREFS']['api_key'])

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

    small_thumbnails, full_thumbnails = await parse_thumbnails(task)

    # thumbnails fetching
    await download_image_batch(session, task, small_thumbnails)

    # if self.stopped():
    #   # utils.p('end search thread')
    #   return
    # full size images have connection limit to get lower priority
    await download_image_batch(session, task, full_thumbnails, limit_per_host=3)
    # small thumbnail downloads
