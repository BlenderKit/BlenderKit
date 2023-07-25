"""Contains utility functions for daemon server. Mix of everything."""

import asyncio
import json
import platform
import re
import sys
from logging import Formatter, StreamHandler, basicConfig, getLogger
from pathlib import Path

import aiohttp
import daemon_globals
import daemon_tasks
from aiohttp import ClientResponseError, web


logger = getLogger(f"daemon.{__name__}")


def get_headers(api_key: str = "") -> dict[str, str]:
    """Get headers with or without authorization."""
    headers = {
        "accept": "application/json",
        "Platform-Version": platform.platform(),
        "system-id": daemon_globals.SYSTEM_ID,
        "addon-version": daemon_globals.VERSION,
    }
    if api_key == "":
        return headers
    if api_key is None:
        return headers

    headers["Authorization"] = f"Bearer {api_key}"
    return headers


def extract_error_message(
    exception: Exception,
    resp_text: str,
    resp_status: int = -1,
    prefix: str = "",
) -> tuple[str, str]:
    """Extract error message from exception, response text and response json.
    Returns the best message constructed from these sources:
    1. prefers "detail" key from JSON response - report from BlenderKit server), or whole JSON,
    2. response text - usually HTML error page,
    3. exception message - usually connection error, other errors.
    """
    if prefix != "":
        prefix += ": "

    if resp_status != -1:
        status_string = f" ({resp_status}) "
    else:
        status_string = ""

    if resp_text is None:
        resp_text = ""
    try:
        resp_json = json.loads(resp_text)
    except json.decoder.JSONDecodeError:
        resp_json = {}

    # JSON not available
    if resp_json == {}:
        msg = f"{prefix}{exception}{status_string}"
        detail = f"{prefix}{type(exception)}: {exception}{status_string}{resp_text}"
        return msg, detail

    # JSON available
    detail = resp_json.get("detail")
    # detail not present
    if detail is None:
        msg = f"{prefix}{resp_json}{status_string}"
        detail = f"{prefix}{type(exception)}: {exception}{status_string}{resp_text}"
        return msg, detail

    # detail is not dict, most probably a string
    if type(detail) != dict:
        msg = f"{prefix}{detail}{status_string}"
        detail = f"{prefix}{exception}: {msg}"
        return msg, detail

    # detail is dict
    statusCode = detail.pop("statusCode", None)
    errstring = ""
    for key in detail:
        errstring += f"{key}: {detail[key]} "
    errstring.strip()

    msg = f"{prefix}{errstring}{status_string}"
    detail = f"{prefix}{exception}: {msg} ({statusCode})"
    return msg, detail


def dict_to_params(inputs, parameters=None):
    if parameters is None:
        parameters = []
    for k in inputs.keys():
        if type(inputs[k]) == list:
            strlist = ""
            for idx, s in enumerate(inputs[k]):
                strlist += s
                if idx < len(inputs[k]) - 1:
                    strlist += ","

            value = "%s" % strlist
        elif type(inputs[k]) != bool:
            value = inputs[k]
        else:
            value = str(inputs[k])
        parameters.append({"parameterType": k, "value": value})
    return parameters


def slugify(slug: str) -> str:
    """Normalizes string, converts to lowercase, removes non-alpha characters, and converts spaces to hyphens."""
    slug = slug.lower()
    characters = '<>:"/\\|?\*., ()#'
    for ch in characters:
        slug = slug.replace(ch, "_")
    slug = re.sub(r"[^a-z0-9]+.- ", "-", slug).strip("-")
    slug = re.sub(r"[-]+", "-", slug)
    slug = re.sub(r"/", "_", slug)
    slug = re.sub(r"\\\'\"", "_", slug)
    if len(slug) > 50:
        slug = slug[:50]

    return slug


def get_process_flags():
    """Get proper priority flags so background processess can run with lower priority."""
    flags = 0x00004000  # psutil.BELOW_NORMAL_PRIORITY_CLASS
    if sys.platform != "win32":  # TODO test this on windows
        flags = 0
    return flags


async def message_to_addon(
    app_id: str,
    message: str,
    destination: str = "GUI",
    level: str = "INFO",
    duration: int = 5,
):
    """Send message to addon's GUI or to its console.
    level can be INFO, WARNING, ERROR.
    destination can be GUI or CONSOLE.
    duration is in seconds, only for GUI messages.
    """
    print(f"Sending {level} message to add-on {destination}: {message} (PID{app_id})")
    result = {
        "destination": destination,
        "level": level,
        "duration": duration,
    }
    message_task = daemon_tasks.Task(
        data={},
        app_id=app_id,
        task_type="message_from_daemon",
        message=message,
        result=result,
        status="finished",
        progress=100,
    )
    daemon_globals.tasks.append(message_task)


async def download_file(
    url: str, destination: str, session: aiohttp.ClientSession, api_key: str = ""
) -> str:
    """Download a file from url into destination on the disk, creates directory structure if needed.
    With api_key the request will be authorized for BlenderKit server.
    """
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    headers = get_headers(api_key)
    try:
        async with session.get(url, headers=headers, raise_for_status=True) as resp:
            with open(destination, "wb") as file:
                async for chunk in resp.content.iter_chunked(4096 * 32):
                    file.write(chunk)
            return ""
    except ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return f"ClientResponseError: {e.message} ({e.status})"
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return f"{type(e)}: {e}"


async def blocking_request_handler(request: web.Request):
    """Handle request for blocking HTTP request.
    Function do not return until results are available. No task is created.
    """
    data = await request.json()
    session = request.app["SESSION_API_REQUESTS"]
    try:
        resp_text, resp_json, resp_status = None, None, -1
        async with session.request(
            data["method"], data["url"], headers=data["headers"], json=data.get("json")
        ) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            resp_json = await resp.json()
            return web.json_response(resp_json)
    except ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return web.Response(
            status=resp_status, text=f"ClientResponseError: {e.message} ({e.status})"
        )
    except Exception as e:
        logger.warning(f"{type(e)}: {e}, {resp_text}")
        return web.Response(status=resp_status, text=f"{type(e)}: {e}")


async def nonblocking_request_handler(request: web.Request):
    """Handle request for nonblocking HTTP request."""
    data = await request.json()
    task = daemon_tasks.Task(data, data["app_id"], "wrappers/nonblocking_request")
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(make_request(request, task))
    task.async_task.set_name(f"{task.task_type}-{task.task_id}")
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.json_response({"task_id": task.task_id})


async def make_request(request: web.Request, task: daemon_tasks.Task):
    session = request.app["SESSION_API_REQUESTS"]
    url = task.data.get("url")
    method = task.data.get("method")
    headers = task.data.get("headers")
    json_data = task.data.get("json")
    messages = task.data.get("messages", {})
    error_message = messages.get("error", "Request failed")
    success_message = messages.get("success", "Request succeeded")
    try:
        resp_text, resp_json = None, None
        async with session.request(
            method, url, headers=headers, json=json_data
        ) as resp:
            resp_text = await resp.text()
            if resp.content_type == "application/json":
                resp.raise_for_status()
                resp_json = await resp.json()
                task.result = resp_json
            else:
                resp.raise_for_status()
                task.result = resp_text
            return task.finished(success_message)
    except ClientResponseError as e:
        logger.warning(
            f'ClientResponseError: {e.message} ({e.status}) on {e.request_info.method} to "{e.request_info.real_url}", headers:{e.headers}, history:{e.history}'
        )
        return task.error(f"{error_message}: {e.message} ({e.status})")
    except Exception as e:
        logger.warning(f"{type(e)}: {e}")
        return task.error(f"{error_message}: {e}")


class SensitiveFormatter(Formatter):
    """Formatter that masks API key tokens. Replace temporary tokens with *** and permanent tokens with *****."""

    def format(self, record):
        msg = Formatter.format(self, record)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{30}\b(?=["\'\s])', r"***", msg)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{40}\b(?=["\'\s])', r"*****", msg)
        return msg


def get_sensitive_formatter():
    """Get default sensitive formatter for daemon loggers."""
    return SensitiveFormatter(
        fmt="%(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
        datefmt="%H:%M:%S",
    )


def configure_logger():
    """Configure 'daemon' logger to which all other logs defined as `logger = logging.getLogger(f"daemon.{__name__}")` writes.
    Sets it logging level to `daemon_globals.LOGGING_LEVEL_DAEMON`.
    """
    basicConfig(level=daemon_globals.LOGGING_LEVEL_DAEMON)
    logger = getLogger("daemon")
    logger.propagate = False
    logger.handlers = []
    handler = StreamHandler()
    handler.stream = sys.stdout  # 517
    handler.setFormatter(get_sensitive_formatter())
    logger.addHandler(handler)


def configure_imported_loggers():
    """Configure loggers for imported modules so they can have different logging level `globals.LOGGING_LEVEL_IMPORTED`
    than main bk_daemon logger."""
    aiohttp_logger = getLogger("aiohttp")
    aiohttp_logger.propagate = False
    aiohttp_logger.handlers = []
    aiohttp_handler = StreamHandler()
    aiohttp_handler.stream = sys.stdout  # 517
    aiohttp_handler.setLevel(daemon_globals.LOGGING_LEVEL_IMPORTED)
    aiohttp_handler.setFormatter(get_sensitive_formatter())
    aiohttp_logger.addHandler(aiohttp_handler)


def configure_loggers():
    """Configure all loggers for BlenderKit addon. See called functions for details."""
    configure_logger()
    configure_imported_loggers()
