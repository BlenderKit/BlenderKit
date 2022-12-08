import asyncio
import logging

import globals
import tasks
from aiohttp import web

import utils


async def get_comments(request: web.Request, task: tasks.Task):
  """Retrieve comments from server."""
  asset_id = task.data['asset_id']
  headers = utils.get_headers(task.data.get('api_key',''))
  session = request.app['SESSION_API_REQUESTS']
  url = f'{globals.SERVER}/api/v1/comments/assets-uuidasset/{asset_id}/'
  try:
    async with session.get(url, headers=headers) as resp:
      task.result = await resp.json()
  except Exception as e:
    logging.warning(str(e))
    task.error(f'{e}')
  task.finished('comments downloaded')


async def create_comment(request: web.Request, task: tasks.Task):
  """Create and upload the comment online."""
  asset_id = task.data['asset_id']
  headers = utils.get_headers(task.data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  url = f'{globals.SERVER}/api/v1/comments/asset-comment/{asset_id}/'
  try:
    async with session.get(url, headers=headers) as resp:
      comment_data = await resp.json()
  except Exception as e:
    logging.error(str(e))
    task.error(f'{e}')

  if resp.status != 200:
    return task.error(f'GET request status code: {resp.status}')

  post_data = {
    'name': '',
    'email': '',
    'url': '',
    'followup': task.data['reply_to_id'] > 0,
    'reply_to': task.data['reply_to_id'],
    'honeypot': '',
    'content_type': 'assets.uuidasset',
    'object_pk': asset_id,
    'timestamp': comment_data['form']['timestamp'],
    'security_hash': comment_data['form']['securityHash'],
    'comment': task.data['comment_text'],
  }
  url = f'{globals.SERVER}/api/v1/comments/comment/'
  try:
    async with session.post(url, headers=headers, data=post_data) as resp:
      task.result = await resp.json()
  except Exception as e:
    logging.error(str(e))
    task.error(f'{e}')

  if resp.status != 201:
    return task.error(f'POST request status code: {resp.status}')

  task.finished('comment created')
  followup_task = tasks.Task(task.data, task.data['app_id'], f'comments/get_comments')
  globals.tasks.append(followup_task)
  get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
  get_comments_task.add_done_callback(tasks.handle_async_errors)


async def feedback_comment(request: web.Request, task: tasks.Task):
  """Upload feedback flag on the comment to the server. Flag is like/dislike but can be also a different flag."""
  headers = utils.get_headers(task.data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  data = {
    'comment': task.data['comment_id'],
    'flag': task.data['flag'],
  }
  url = f'{globals.SERVER}/api/v1/comments/feedback/'
  try:
    async with session.post(url, data=data, headers=headers) as resp:
      task.result = await resp.json()
  except Exception as e:
    logging.warning(str(e))
    task.error(f'{e}')

  if resp.status not in [200,201]:
    return task.error(f'POST request failed ({resp.status})')

  task.finished('flag uploaded')
  followup_task = tasks.Task(task.data, task.data['app_id'], f'comments/get_comments')
  globals.tasks.append(followup_task)
  get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
  get_comments_task.add_done_callback(tasks.handle_async_errors)


async def mark_comment_private(request: web.Request, task: tasks.Task):
  """Update visibility of the comment."""
  headers = utils.get_headers(task.data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  data = {'is_private': task.data['is_private']}
  url = f'{globals.SERVER}/api/v1/comments/is_private/{task.data["comment_id"]}/'
  try:
    async with session.post(url, data=data, headers=headers) as resp:
      task.result = await resp.json()
  except Exception as e:
    logging.error(f'{e}')
    task.error(f'{e}')

  if resp.status not in [200,201]:
    return task.error(f'POST request failed ({resp.status})')

  task.finished('comment visibility updated')
  followup_task = tasks.Task(task.data, task.data['app_id'], f'comments/get_comments')
  globals.tasks.append(followup_task)
  get_comments_task = asyncio.ensure_future(get_comments(request, followup_task))
  get_comments_task.add_done_callback(tasks.handle_async_errors)
