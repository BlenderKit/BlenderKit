"""OAuth for login."""

import asyncio
import typing
from logging import getLogger
from uuid import uuid4

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


logger = getLogger(f"daemon.{__name__}")


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
            e, resp_text, resp_status, "Get tokens"
        )
        logger.error(f"{msg}: {detail}.")

        try:
            certs = session.connector._ssl.get_ca_certs()
            logger.info(f"Certs used: {certs}")
        except Exception as e:
            logger.warning(f"Could not get certs to print them here: {e}")

        return {}, resp_status, msg


async def refresh_tokens(request: web.Request) -> None:
    data = await request.json()
    refresh_token = data["refresh_token"]
    if refresh_token in daemon_globals.token_refresh_list:
        logger.info("Refresh token already used.")
        return
    logger.info("Token refresh requested.")
    daemon_globals.token_refresh_list.append(refresh_token)
    response_json, status, error = await get_tokens(
        request, refresh_token=refresh_token, grant_type="refresh_token"
    )

    for app_id in daemon_globals.active_apps:
        task = daemon_tasks.Task(
            data, app_id, "token_refresh", message="Refreshing tokens"
        )
        daemon_globals.tasks.append(task)
        task.result = response_json
        if status == 200:
            return task.finished("Refreshed tokens obtained")
        if status == 429:
            return task.error(
                f"Couldn't refresh API tokens, API rate exceeded. Please login again.",
                message_detailed=str(error),
            )
        if status == -1:
            return task.error(
                f"Couldn't refresh API tokens, server is not reachable. Please login again.",
                message_detailed=str(error),
            )

        return task.error(
            f"Couldn't refresh API tokens ({status}). Please login again.",
            message_detailed=str(error),
        )


async def refresh_token(request: web.Request):
    """Create asyncio task for refreshal of the API key token of the add-on."""
    atask = asyncio.ensure_future(refresh_tokens(request))
    atask.set_name(f"refresh_token-{uuid4()}")
    atask.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")
