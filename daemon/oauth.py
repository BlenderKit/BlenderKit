"""OAuth for login."""

import typing
import uuid

from aiohttp import web

import globals
import tasks

async def get_tokens(request: web.Request, auth_code=None, refresh_token=None, grant_type="authorization_code") -> typing.Tuple[int, dict|str]:
  server_url = "https://www.blenderkit.com"
  data = {
    "grant_type": grant_type,
    "state": "random_state_string",
    "client_id": globals.OAUTH_CLIENT_ID,
    "scopes": "read write",
    "redirect_uri" : f"http://localhost:{globals.PORT}/consumer/exchange/",
  }

  if auth_code:
    data['code'] = auth_code
  if refresh_token:
    data['refresh_token'] = refresh_token

  session = request.app['SESSION_API_REQUESTS']
  async with session.post(f"{server_url}/o/token/", data = data) as response:
    await response.text()

    if response.status != 200:
      print(f"Error retrieving refresh tokens. Code {response.status}, content: {response.text}")
      return response.status, response.text

    response_json = await response.json()
    print("Token retrieval OK.")

    return 200, response_json

async def refresh_tokens(request: web.Request):
  data = await request.json()
  refresh_token = data["refresh_token"]
  status, response_json = await get_tokens(request, refresh_token=refresh_token, grant_type="refresh_token")
  
  for app_id in globals.active_apps:
    task = tasks.Task(None, str(uuid.uuid4()), app_id, 'login', message='Refreshing tokens')
    globals.tasks.append(task)
    task.result = response_json
    if status == 200:
      task.finished("Refreshed tokens obtained")
    else:
      task.error(f"Error refreshing tokens ({status})")
      #IF REFRESH TOKEN IS USED and not saved, it errors
      #we should try to use auth_token to get refresh token and refresh everything
