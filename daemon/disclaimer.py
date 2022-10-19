"""Holds functionality for getting disclaimers."""


import uuid

import globals
import tasks
from aiohttp import web

import utils


async def get_disclaimer(request: web.Request):
  """Get disclaimer from the server."""
  data = await request.json()
  app_id = data['app_id']
  task = tasks.Task(data, app_id, 'disclaimer', str(uuid.uuid4()), message='Getting disclaimer')
  globals.tasks.append(task)

  session = request.app['SESSION_API_REQUESTS']
  async with session.get(f'{globals.SERVER}/api/v1/disclaimer/active/', headers=utils.get_headers()) as resp:
    await resp.text()
    response = await resp.json()
    if len(response["results"])>0:
      task.result = response
      task.finished('Disclaimer retrieved')
      return

    task.result = None
    task.finished('Disclaimer not retrieved, serve a tip to user')
