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
      task.finished('comments downloaded')
  except Exception as e:
    logging.warning(str(e))
    task.error(f'{e}')


async def create_comment(request: web.Request, task: tasks.Task):
  """Create and upload the comment online."""
  comment = task.data['comment_text']
  asset_id = task.data['asset_id']
  reply_to_id = task.data['reply_to_id']
  headers = utils.get_headers(task.data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  url = f'{globals.SERVER}/api/v1/comments/asset-comment/{asset_id}/'
  try:
    async with session.get(url, headers=headers) as resp:
      comment_data = await resp.json()
      data = {
        'name': '',
        'email': '',
        'url': '',
        'followup': reply_to_id > 0,
        'reply_to': reply_to_id,
        'honeypot': '',
        'content_type': 'assets.uuidasset',
        'object_pk': asset_id,
        'timestamp': comment_data['form']['timestamp'],
        'security_hash': comment_data['form']['securityHash'],
        'comment': comment,
      }
  except Exception as e:
    logging.error(str(e))

  try:
    url = f'{globals.SERVER}/api/v1/comments/comment/'
    async with session.post(url, headers=headers, data=data) as resp:
      task.result = await resp.json()
      if resp.status != 201:
        return task.error(f'request status code: {resp.status}')

      task.finished('comment created')
      ###TODO: create a new task here - update the comments
      ###or can we just update the comments with the new comment?
      #get_comments(request) 
  except Exception as e:
    logging.error(str(e))
    task.error(f'{e}')


async def feedback_comment(request: web.Request, task: tasks.Task):
  """Upload feeback on the comment to the server. Like/dislike but can be also a different flag."""
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
      if resp.status != 201:
        return task.error(f'request status code: {resp.status}')
  except Exception as e:
    logging.warning(str(e))
    task.error(f'{e}')

  # here it's important we read back, so likes are updated accordingly:
  #TODO: create a new task here which gets comments for fresh data
  print(task.result)
  return task.finished('flag uploaded')



async def mark_comment_private(request: web.Request, task: tasks.Task):
  """Update visibility of the comment."""
  headers = utils.get_headers(task.data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  data = {'is_private': task.data['is_private']}
  url = f'{globals.SERVER}/api/v1/comments/is_private/{task.data["comment_id"]}/'
  try:
    async with session.post(url, data=data, headers=headers) as resp:
      task.result = await resp.json()
      task.finished('comment visibility updated')
      # here it's important we read back, so likes are updated accordingly:
      #TODO: create a new task here which gets comments for fresh data
  except Exception as e:
    logging.error(f'{e}')
    task.error(f'{e}')



