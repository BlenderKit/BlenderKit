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


async def download_file(session, file_path, data):
  print("DOWNLOADING FILE_PATH:", file_path)

  with open(file_path, "wb") as file:
    res_file_info, data['resolution'] = get_res_file(data)
    async with session.get(res_file_info['url']) as resp:
      total_length = resp.headers.get('Content-Length')
      if total_length is None:  # no content length header
        print('no content length: ', resp.content)
        # tcom.report = response.content
        delete_unfinished_file(file_path)
        return

      # bk_logger.debug(total_length)
      # if int(total_length) < 1000:  # means probably no file returned.
      # tasks_queue.add_task((reports.add_report, (response.content, 20, colors.RED)))
      #
      #   tcom.report = response.content
      file_size = int(total_length)
      fsmb = file_size // (1024 * 1024)
      fskb = file_size % 1024
      if fsmb == 0:
        t = '%iKB' % fskb
      else:
        t = ' %iMB' % fsmb
      # tcom.report = f'Downloading {t} {self.resolution}'
      report_download_progress(data, text=f"Downloading {t} {data['resolution']}", progress=0)
      downloaded = 0

      async for chunk in resp.content.iter_chunked(4096 * 32):
        # for rdata in response.iter_content(chunk_size=4096 * 32):  # crashed here... why? investigate:
        downloaded += len(chunk)
        progress = int(100 * downloaded / file_size)
        report_download_progress(data, text=f"Downloading {t} {data['resolution']}", progress=progress)
        file.write(chunk)

        if globals.tasks[data['task_id']].get('kill'):
          delete_unfinished_file(file_path)
          return


def report_image_finished(data, filepath, done=True):
  globals.tasks[filepath] = {'app_id': data['PREFS']['app_id'],
                             'task_id': filepath,
                             'done': done}


async def download_image(session, url, filepath, data):
  async with session.get(url) as resp:
    if resp and resp.status == 200:
      with open(filepath, 'wb') as f:
        async for chunk in resp.content.iter_chunked(4096 * 32):
          f.write(chunk)
          report_image_finished(data, filepath)
    else:
      report_image_finished(data, filepath, done=False)


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

      thumb_small_urls = []
      thumb_small_filepaths = []
      thumb_full_urls = []
      thumb_full_filepaths = []
      # END OF PARSING
      # get thumbnails that need downloading
      for d in rdata.get('results', []):
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

      # thumbnails fetching

      # small thumbnail downloads
      small_thumbs_tasks = []
      sslcontext = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
      sslcontext.load_verify_locations(certifi.where())
      async with aiohttp.TCPConnector(ssl=sslcontext) as conn:
        async with aiohttp.ClientSession(connector=conn) as session:
          for imgpath, url in sml_thbs:
            if not os.path.exists(imgpath):
              task = asyncio.ensure_future(download_image(session, url, imgpath, data))
              small_thumbs_tasks.append(task)
            else:
              report_image_finished(data, imgpath, done=True)

          await asyncio.gather(*small_thumbs_tasks)
      #
      # if self.stopped():
      #   # utils.p('end search thread')
      #   return

      # large images should be lower priority, trying it with limit_per_host in connector
      big_thumbs_tasks = []
      sslcontext = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
      sslcontext.load_verify_locations(certifi.where())
      async with aiohttp.TCPConnector(ssl=sslcontext, limit_per_host=3) as conn:
        async with aiohttp.ClientSession(connector=conn) as session:
          for imgpath, url in full_thbs:
            if not os.path.exists(imgpath):
              task = asyncio.ensure_future(download_image(session, url, imgpath, data))
              big_thumbs_tasks.append(task)
          await asyncio.gather(*big_thumbs_tasks)
