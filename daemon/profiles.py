"""Contains functions for work with profiles - profile of current user and also profiles of authors.
TODO: We should find a better vocabulary for this.
"""

import asyncio
import os
import tempfile
from logging import getLogger
from urllib.parse import urljoin

import globals
import tasks
from aiohttp import web

import utils


logger = getLogger(__name__)

async def fetch_gravatar_image_handler(request: web.Request):
  data = await request.json()
  task = tasks.Task(data, data['app_id'], 'profiles/fetch_gravatar_image', message='Fetching gravatar image')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(fetch_gravatar_image(task, request))
  task.async_task.add_done_callback(tasks.handle_async_errors)
  return web.Response(text='ok')

async def get_user_profile_handler(request: web.Request):
  data = await request.json()
  task = tasks.Task(data, data['app_id'], 'profiles/get_user_profile', message='Getting user profile')
  globals.tasks.append(task)
  task.async_task = asyncio.ensure_future(get_user_profile(task, request))
  task.async_task.add_done_callback(tasks.handle_async_errors)
  return web.Response(text='ok')


async def fetch_gravatar_image(task: tasks.Task, request: web.Request):
  """Get gravatar image from blenderkit server.
  - task.data - author data from elastic search result + task.data['app_id']
  """
  if 'avatar128' not in task.data:
    return fetch_gravatar_image_old(task, request)
  
  gravatar_path = os.path.join(tempfile.gettempdir(), 'bkit_temp', 'bkit_g', f'{task.data["id"]}.jpg')
  if os.path.exists(gravatar_path):
    task.result = {'gravatar_path': gravatar_path}
    return task.finished('Found on disk')

  url = urljoin(globals.SERVER, task.data["avatar128"])
  session = request.app['SESSION_SMALL_THUMBS']
  try:
    await utils.download_file(url, gravatar_path, session)
  except Exception as e:
    return task.error(f'Download error: {e}')

  task.result = {'gravatar_path': gravatar_path}
  return task.finished('Downloaded')


async def fetch_gravatar_image_old(task: tasks.Task, request: web.Request):
  """Older way of getting gravatar image. May be needed for some users with old gravatars.""" #TODO: is this still in use?
  if task.data.get('gravatarHash') is None:
    return
  gravatar_path = os.path.join(tempfile.gettempdir(), 'bkit_temp', 'bkit_g', f'{task.data["gravatarHash"]}.jpg')
  if os.path.exists(gravatar_path):
    task.result = {'gravatar_path': gravatar_path}
    return task.finished('Found on disk')

  url = urljoin('https://www.gravatar.com/avatar', f'{task.data["gravatarHash"]}?d=404')
  session = request.app['SESSION_SMALL_THUMBS']
  try:
    await utils.download_file(url, gravatar_path, session)
  except Exception as e:
    return task.error(f'Download error: {e}')

  task.result = {'gravatar_path': gravatar_path}
  return task.finished('Downloaded')


async def get_user_profile(task: tasks.Task, request: web.Request):
  """Get profile data for currently logged-in user. Data are cleaned a little bit and then reported to the add-on."""
  api_key = task.data['api_key']
  headers = utils.get_headers(api_key)
  url = f'{globals.SERVER}/api/v1/me/'
  session = request.app['SESSION_API_REQUESTS']
  try:
    async with session.get(url, headers=headers) as resp:
      data = await resp.json()
  except Exception as e:
    return task.error(f'request failed {e}')
  if resp.status != 200:
    return task.error(f'request returned code ({resp.status})')  
  if data.get('user') is None:
    return task.error('profile is None')

  task.result = convert_user_data(data)
  return task.finished('data suceessfully fetched')


def convert_user_data(data: dict):
  """Convert user data quotas to MiB, otherwise numbers would be too big for Python int type"""
  user = data['user']
  if user.get('sumAssetFilesSize') is not None:
    user['sumAssetFilesSize'] /= (1024 * 1024)
  if user.get('sumPrivateAssetFilesSize') is not None:
    user['sumPrivateAssetFilesSize'] /= (1024 * 1024)
  if user.get('remainingPrivateQuota') is not None:
    user['remainingPrivateQuota'] /= (1024 * 1024)
  data['user'] = user
  return data
