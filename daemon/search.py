"""Holds functionality for search and thumbnail fetching."""

import asyncio
import os
import json
import shutil
import ssl
import sys
import tempfile
import subprocess

import aiohttp
import certifi
import globals, utils, assets

global reports_queue, thumb_sml_download_threads, thumb_full_download_threads


def report_image_finished(data, filepath, done=True):
  '''reports a thumbnail is downloaded and available. Not used by now.'''
  globals.tasks[filepath] = {'app_id': data['PREFS']['app_id'],
                             'type': 'thumbnail-available',
                             'task_id': filepath,
                             'done': done}


async def download_image(session, url, filepath, data):
  '''download a single image and report to addon.'''
  async with session.get(url) as resp:
    if resp and resp.status == 200:
      with open(filepath, 'wb') as f:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          f.write(chunk)
          report_image_finished(data, filepath)
    else:
      report_image_finished(data, filepath, done=False)


async def download_image_batch(images=[], data={}, limit_per_host=0):
  '''Download batch of images. images are tuples of file path and url.'''
  sslcontext = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
  sslcontext.load_verify_locations(certifi.where())
  async with aiohttp.TCPConnector(ssl=sslcontext) as conn:
    async with aiohttp.ClientSession(connector=conn) as session:
      download_tasks = []
      for imgpath, url in images:
        if not os.path.exists(imgpath):
          task = asyncio.ensure_future(download_image(session, url, imgpath, data))
          download_tasks.append(task)
        else:
          report_image_finished(data, imgpath, done=True)

      await asyncio.gather(*download_tasks)


async def parse_thumbnails(data):
  '''go through results and extract correct filenames'''
  thumb_small_urls = []
  thumb_small_filepaths = []
  thumb_full_urls = []
  thumb_full_filepaths = []
  # END OF PARSING
  # get thumbnails that need downloading
  for d in data['result'].get('results', []):
    thumb_small_urls.append(d["thumbnailSmallUrl"])
    imgname = assets.extract_filename_from_url(d['thumbnailSmallUrl'])
    imgpath = os.path.join(data['tempdir'], imgname)
    thumb_small_filepaths.append(imgpath)

    if d["assetType"] == 'hdr':
      larege_thumb_url = d['thumbnailLargeUrlNonsquared']

    else:
      larege_thumb_url = d['thumbnailMiddleUrl']

    thumb_full_urls.append(larege_thumb_url)
    imgname = assets.extract_filename_from_url(larege_thumb_url)
    imgpath = os.path.join(data['tempdir'], imgname)
    thumb_full_filepaths.append(imgpath)

  sml_thbs = zip(thumb_small_filepaths, thumb_small_urls)
  full_thbs = zip(thumb_full_filepaths, thumb_full_urls)
  return sml_thbs, full_thbs


async def do_search(data):
  rdata = {}
  rdata['results'] = []
  headers = utils.get_headers(data['PREFS']['api_key'])
  async with aiohttp.ClientSession() as session:
    async with session.get(data['urlquery'], headers=headers) as resp:
      await resp.text()
      rdata = await resp.json()
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

      report = {
        "app_id": data['PREFS']['app_id'],
        'type': 'search-finished',
        'result': rdata
      }
      data.update(report)
      globals.tasks[data['task_id']] = data
      # if self.stopped():
      #   # utils.p('end search thread')
      #
      #   return

      sml_thbs, full_thbs = await parse_thumbnails(data)

      # thumbnails fetching
      await download_image_batch( images=sml_thbs, data=data)

      # if self.stopped():
      #   # utils.p('end search thread')
      #   return
      # full size images have connection limit to get lower priority
      await download_image_batch(images=full_thbs, data=data, limit_per_host=3)
      # small thumbnail downloads
