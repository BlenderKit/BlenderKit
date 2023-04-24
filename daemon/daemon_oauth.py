"""OAuth for login."""

import typing
from logging import getLogger

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import client_exceptions, web


logger = getLogger(__name__)


async def get_tokens(
    request: web.Request,
    auth_code=None,
    refresh_token=None,
    grant_type="authorization_code",
) -> typing.Tuple[dict, int, str]:
    data = {
        "grant_type": grant_type,
        "client_id": daemon_globals.OAUTH_CLIENT_ID,
        "scopes": "read write",
        "redirect_uri": f"http://localhost:{daemon_globals.PORT}/consumer/exchange/",
    }

    if daemon_globals.code_verifier:
        data["code_verifier"] = daemon_globals.code_verifier
    if auth_code:
        data["code"] = auth_code
    if refresh_token:
        data["refresh_token"] = refresh_token

    session = request.app["SESSION_API_REQUESTS"]
    headers = daemon_utils.get_headers()
    try:
        async with session.post(
            f"{daemon_globals.SERVER}/o/token/", data=data, headers=headers
        ) as response:
            text = await response.text()

            if response.status != 200:
                return [], response.status, text

            response_json = await response.json()
            logger.info("Token retrieval OK.")

            return response_json, 200, ""

    except client_exceptions.ClientConnectorError as err:
        return [], -1, str(err)


async def refresh_tokens(request: web.Request):
    data = await request.json()
    refresh_token = data["refresh_token"]
    response_json, status, error = await get_tokens(
        request, refresh_token=refresh_token, grant_type="refresh_token"
    )

    for app_id in daemon_globals.active_apps:
        task = daemon_tasks.Task(None, app_id, "login", message="Refreshing tokens")
        daemon_globals.tasks.append(task)
        task.result = response_json
        if status == 200:
            return task.finished("Refreshed tokens obtained")
        if status == 429:
            return task.error("Couldn't refresh API tokens, API rate exceeded.")
        if status == -1:
            return task.error(
                f"Couldn't refresh API tokens, server is not reachable: {error}. Please login again."
            )

        return task.error(
            f"Couldn't refresh API tokens ({status}). Error: {error}. Please login again."
        )
