"""OAuth for login."""

import typing

from aiohttp import web

import globals

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
    refresh_token = response_json['refresh_token']
    access_token = response_json['access_token']

    print("TYPE", type(response_json))
    print("REFRESH_TOKEN", refresh_token)
    print("ACCESS_TOKEN", access_token)

    return 200, response_json
