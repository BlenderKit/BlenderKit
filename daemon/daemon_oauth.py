"""OAuth for login."""

import typing
from logging import getLogger

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


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
    url = f"{daemon_globals.SERVER}/o/token/"
    try:
        resp_text, resp_status = None, -1
        async with session.post(url, data=data, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            resp_json = await resp.json()
            logger.info("Token retrieval OK.")
            return resp_json, resp_status, ""
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Get download URL"
        )
        logger.warning(detail)
        return resp_json, resp_status, msg


async def refresh_tokens(request: web.Request) -> None:
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
            return task.error(
                f"Couldn't refresh API tokens, API rate exceeded: {error}"
            )
        if status == -1:
            return task.error(
                f"Couldn't refresh API tokens, server is not reachable: {error}. Please login again."
            )

        return task.error(
            f"Couldn't refresh API tokens ({status}). Error: {error}. Please login again."
        )
