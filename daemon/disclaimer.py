"""Holds functionality for getting disclaimers and notifications."""


import uuid
from logging import getLogger

import globals
import tasks
from aiohttp import web

import utils


logger = getLogger(__name__)

async def get_disclaimer(request: web.Request):
  """Get disclaimer from the server."""
  data = await request.json()
  app_id = data['app_id']
  task = tasks.Task(data, app_id, 'disclaimer', str(uuid.uuid4()), message='Getting disclaimer')
  globals.tasks.append(task)
  headers = utils.get_headers(data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  try:
    async with session.get(f'{globals.SERVER}/api/v1/disclaimer/active/', headers=headers) as resp:
      await resp.text()
      response = await resp.json()
      if len(response["results"])>0:
        task.result = response
        task.finished('Disclaimer retrieved')
        return
  except Exception as e:
    logger.error(str(e))

  task.finished('Disclaimer not retrieved, serve a tip to user')


async def get_notifications(request: web.Request):
  """Retrieve unread notifications from the server."""
  data = await request.json()
  task = tasks.Task(data, data['app_id'], 'notifications', str(uuid.uuid4()), message='Getting notifications')
  globals.tasks.append(task)
  headers = utils.get_headers(data['api_key'])
  session = request.app['SESSION_API_REQUESTS']
  try:
    async with session.get(f'{globals.SERVER}/api/v1/notifications/unread/', headers=headers) as resp:
      await resp.text()
      task.result = await resp.json()
  except Exception as e:
    logger.error(str(e))
    return task.error(str(e))

  if resp.status == 200:
    return task.finished('Notifications retrieved')
    
  return task.error(f'GET notifications status code: {resp.status_code}')

