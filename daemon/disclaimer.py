"""Holds functionality for search and thumbnail fetching."""

import asyncio

import aiohttp
import globals
import tasks
import uuid
from aiohttp import web

import utils


async def get_disclaimer(request: web.Request):
  """
  Gets disclaimer from the server
  """
  server_url = 'www.blenderkit.com'

  data = await request.json()
  app_id = data['app_id']
  task = tasks.Task(data, str(uuid.uuid4()), app_id, 'disclaimer', message='Getting disclaimer')
  globals.tasks.append(task)

  session = request.app['SESSION_API_REQUESTS']
  async with session.get(f"https://{server_url}/api/v1/disclaimer/active/") as resp:
    await resp.text()
    response = await resp.json()
    if len(response["results"])>0:

      task.finished('Disclaimer retrieved')
      task.result = response
    else:
      #remove the task and don't report to Blender, not needed
      task.finished('Disclaimer not retrieved, serve a tip to user')
      task.result = response


