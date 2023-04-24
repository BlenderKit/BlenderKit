"""Holds functionality for asset manipulation and download."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from logging import getLogger

import aiohttp
import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import web


logger = getLogger(__name__)


def get_res_file(data):
    """Returns closest resolution that current asset can offer.
    Returns:
        resolution file
        resolution, so that other processess can pass correctly which resolution is downloaded.
    """

    resolutions = {
        "resolution_0_5K": 512,
        "resolution_1K": 1024,
        "resolution_2K": 2048,
        "resolution_4K": 4096,
        "resolution_8K": 8192,
    }
    orig = None
    closest = None
    target_resolution = resolutions.get(data["resolution"])
    mindist = 100000000

    for f in data["asset_data"]["files"]:
        if f["fileType"] == "blend":
            orig = f
            if data["resolution"] == "blend":
                return orig, "blend"  # orig file found, return.

        if f["fileType"] == data["resolution"]:
            return f, data["resolution"]  # exact match found, return

        # find closest resolution if the exact match won't be found
        rval = resolutions.get(f["fileType"])
        if rval and target_resolution:
            rdiff = abs(target_resolution - rval)
            if rdiff < mindist:
                closest = f
                mindist = rdiff

    if closest:
        return closest, closest["fileType"]

    return orig, "blend"


async def do_asset_download(request: web.Request, task: daemon_tasks.Task):
    """Download an asset from BlenderKit.
    1. creates a Connector and Session for download, handles SSL configuration
    2. gets download URL for an asset
    3. checks whether asset exists locally
    4. gets file_path for the file
    5. downloads the file
    6. unpacks the file
    """
    can_download = await get_download_url(request.app["SESSION_API_REQUESTS"], task)
    if can_download is False:
        return

    task.result["file_paths"] = await get_download_filepaths(task)
    if task.result["file_paths"] == []:
        task.error("Download aborted: filepaths are empty.")
        return

    # This check happens only after get_download_url becase we need it to know what is the file name on hard drive.
    if await check_existing(task):
        task.finished("Asset found on hard drive")
        return

    task.change_progress(0, "Waiting in queue")
    file_path = task.result["file_paths"][0]
    await download_file(request.app["SESSION_ASSETS"], file_path, task)
    # TODO: check if resolution is written correctly into assetdata hanging on actual appended object in scene and probably remove the following line?
    task.data["asset_data"]["resolution"] = task.data["resolution"]
    if task.data["PREFS"]["unpack_files"]:
        task.change_progress(100, "Unpacking files")
        await send_to_bg(task.data, file_path, command="unpack", wait=True)

    task.change_progress(100, "Appending asset")
    task.finished("Asset downloaded and ready")


async def download_file(
    session: aiohttp.ClientSession, file_path, task: daemon_tasks.Task
):
    with open(file_path, "wb") as file:
        res_file_info, task.data["resolution"] = get_res_file(task.data)
        async with session.get(
            res_file_info["url"], headers=daemon_utils.get_headers()
        ) as resp:
            total_length = resp.headers.get("Content-Length")
            if total_length is None:  # no content length header
                logger.info("no content length: ", resp.content)
                task.error("no content length")
                delete_unfinished_file(file_path)
                return

            # bk_logger.debug(total_length)
            # if int(total_length) < 1000:  # means probably no file returned.
            # tasks_queue.add_task((reports.add_report, (response.content, 20, 'ERROR')))
            #
            #   tcom.report = response.content
            file_size = int(total_length)
            fsmb = file_size // (1024 * 1024)
            fskb = file_size % 1024
            if fsmb == 0:
                t = "%iKB" % fskb
            else:
                t = " %iMB" % fsmb
            task.change_progress(
                progress=0, message=f"Downloading {t} {task.data['resolution']}"
            )
            downloaded = 0

            async for chunk in resp.content.iter_chunked(4096 * 32):
                # for rdata in response.iter_content(chunk_size=4096 * 32):  # crashed here... why? investigate:
                downloaded += len(chunk)
                progress = int(100 * downloaded / file_size)
                task.change_progress(
                    progress=progress,
                    message=f"Downloading {t} {task.data['resolution']}",
                )
                file.write(chunk)
                # if globals.tasks[data['task_id']].get('kill'):
                #   delete_unfinished_file(file_path)
                #   return


async def get_download_url_wrapper(request: web.Request):
    """Handle get_download_url request. This serves as a wrapper around get_download_url so this can be called from addon.
    Returns the results directly so it is a blocking on add-on side (as add-on uses blocking Requests for this).
    """
    data = await request.json()
    task = daemon_tasks.Task(data, data["app_id"], "wrappers/get_download_url")
    has_url = await get_download_url(request.app["SESSION_API_REQUESTS"], task)
    return web.json_response(
        {"has_url": has_url, "asset_data": task.data["asset_data"]}
    )


async def get_download_url(
    session: aiohttp.ClientSession, task: daemon_tasks.Task
) -> bool:
    """Retrieve the download url. The server checks if user can download the item and returns url with a key."""
    headers = daemon_utils.get_headers(task.data["PREFS"]["api_key"])
    req_data = {"scene_uuid": task.data["PREFS"]["scene_id"]}
    res_file_info, _ = get_res_file(task.data)
    try:
        async with session.get(
            res_file_info["downloadUrl"], params=req_data, headers=headers
        ) as resp:
            resp_data = await resp.json()
    except aiohttp.ClientConnectorError as e:
        task.error(f"Could not get download URL: {e}")
        return False
    except aiohttp.ContentTypeError as e:
        task.error(f"Get download URL error: {e}")
        return False

    if resp.status >= 400:
        error_message = resp_data.get(
            "detail", f"Get download URL status code: {resp.status}"
        )
        task.error(error_message)
        return False

    url = resp_data.get("filePath")
    if url is None:
        task.error("filePath is None")
        return False

    res_file_info["url"] = url
    res_file_info["file_name"] = extract_filename_from_url(url)
    return True


def extract_filename_from_url(url: str) -> str:
    """Extract filename from URL."""

    if url is not None:
        imgname = url.split("/")[-1]
        imgname = imgname.split("?")[0]
        return imgname
    return ""


def server_2_local_filename(asset_data, filename):
    """Convert file name on server to file name local. This should get replaced."""

    fn = filename.replace("blend_", "")
    fn = fn.replace("resolution_", "")
    n = daemon_utils.slugify(asset_data["name"]) + "_" + fn
    return n


async def get_download_filepaths(task) -> list:
    """Get all possible paths of the asset and resolution. Usually global and local directory."""
    file_names = []
    data = task.data
    windows_path_limit = 250
    asset_data = data["asset_data"]

    res_file, _ = get_res_file(data)
    if not res_file:
        task.error("No resolution file found")
        return []

    name_slug = daemon_utils.slugify(asset_data["name"])
    if len(name_slug) > 16:
        name_slug = name_slug[:16]
    asset_folder_name = f"{name_slug}_{asset_data['id']}"

    error_message = "Project path is too long, will save the asset in global directory only. Move your .blend file to store assets locally in the project directory."
    # fn = asset_data['file_name'].replace('blend_', '')
    if res_file.get("url") is not None:
        # Tweak the names a bit: remove resolution and blend words in names
        fn = extract_filename_from_url(res_file["url"])
        n = server_2_local_filename(asset_data, fn)
        for dir in data["download_dirs"]:
            asset_folder_path = os.path.join(dir, asset_folder_name)
            if sys.platform == "win32" and len(asset_folder_path) > windows_path_limit:
                await daemon_utils.message_to_addon(
                    task.app_id,
                    message=error_message,
                    level="ERROR",
                    destination="GUI",
                    duration=5,
                )
                continue
            if not os.path.exists(asset_folder_path):
                os.makedirs(asset_folder_path)

            file_name = os.path.join(asset_folder_path, n)
            file_names.append(file_name)

    for file_name in file_names:
        if sys.platform != "win32":
            break
        if len(file_name) > windows_path_limit:
            await daemon_utils.message_to_addon(
                task.app_id,
                message=error_message,
                level="ERROR",
                destination="GUI",
                duration=5,
            )
            file_names.remove(file_name)

    return file_names


# TODO: better naming, is used only in do_asset_download for command "unpack"
async def send_to_bg(data, fpath, command="generate_resolutions", wait=True):
    """Send various tasks to a new blender instance that runs and closes after finishing the task.

    This function waits until the process finishes.
    The function tries to set the same bpy.app.debug_value in the instance of Blender that is run.

    Parameters
    ----------
    data
    fpath - file that will be processed
    command - command which should be run in background.

    Returns
    -------
    None
    """

    process_data = {
        "fpath": fpath,
        "debug_value": data["PREFS"]["debug_value"],
        "asset_data": data["asset_data"],
        "command": command,
    }
    binary_path = data["PREFS"]["binary_path"]
    tempdir = tempfile.mkdtemp()
    datafile = os.path.join(tempdir + "resdata.json")
    script_path = os.path.dirname(os.path.realpath(__file__))
    with open(datafile, "w", encoding="utf-8") as s:
        json.dump(process_data, s, ensure_ascii=False, indent=4)

    args = [
        "--background",
        "-noaudio",
        # "--no-addons",
        fpath,
        "--python",
        os.path.join(script_path, "..", "resolutions_bg.py"),
        "--",
        datafile,
    ]
    logger.info(f"Running in BG: {command}")
    proc = await asyncio.create_subprocess_exec(
        binary_path,
        *args,
        creationflags=daemon_utils.get_process_flags(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if wait:
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            out = stdout.decode()
            logger.error(
                f"Command {command} failed ({proc.returncode}) in background:\n{out}"
            )
    return proc


async def copy_asset(fp1, fp2):
    """Synchronize the asset between folders, including it's texture subdirectories."""

    if 1:
        # bk_logger.debug('copy asset')
        # bk_logger.debug(fp1 + ' ' + fp2)
        if not os.path.exists(fp2):
            shutil.copyfile(fp1, fp2)
            # bk_logger.debug('copied')
        source_dir = os.path.dirname(fp1)
        target_dir = os.path.dirname(fp2)
        for subdir in os.scandir(source_dir):
            if not subdir.is_dir():
                continue
            target_subdir = os.path.join(target_dir, subdir.name)
            if os.path.exists(target_subdir):
                continue
            # bk_logger.debug(str(subdir) + ' ' + str(target_subdir))
            shutil.copytree(subdir, target_subdir)
            # bk_logger.debug('copied')

    # except Exception as e:
    #     print('BlenderKit failed to copy asset')
    #     print(fp1, fp2)
    #     print(e)


async def check_existing(task) -> bool:
    """Check if the object exists on the hard drive."""
    data = task.data
    file_paths = task.result.get("file_paths", [])
    if data["asset_data"].get("files") is None:
        return False  # this is because of some very old files where asset data had no files structure.

    if len(file_paths) == 2:
        # TODO this should check also for failed or running downloads.
        # If download is running, assign just the running thread. if download isn't running but the file is wrong size,
        #  delete file and restart download (or continue downoad? if possible.)
        if os.path.isfile(file_paths[0]):  # and not os.path.isfile(file_names[1])
            await copy_asset(file_paths[0], file_paths[1])
        elif not os.path.isfile(file_paths[0]) and os.path.isfile(
            file_paths[1]
        ):  # only in case of changed settings or deleted/moved global dict.
            await copy_asset(file_paths[1], file_paths[0])

    if len(file_paths) > 0 and os.path.isfile(file_paths[0]):
        return True

    return False


def delete_unfinished_file(file_path: str) -> None:
    """Delete downloaded file if it wasn't finished.
    If the folder it's containing is empty, it also removes the directory.
    """
    try:
        os.remove(file_path)
    except Exception as e:
        logger.error(str(e))
    asset_dir = os.path.dirname(file_path)
    if len(os.listdir(asset_dir)) == 0:
        os.rmdir(asset_dir)


async def report_usages_handler(request: web.Request):
    """Handle order to report asset usages."""
    data = await request.json()
    task = daemon_tasks.Task(
        data,
        data["app_id"],
        "report_usages",
        message="Uploading the usage report data.",
    )
    daemon_globals.tasks.append(task)
    task.async_task = asyncio.ensure_future(report_usages(request, task))
    task.async_task.add_done_callback(daemon_tasks.handle_async_errors)
    return web.Response(text="ok")


async def report_usages(request: web.Request, task: daemon_tasks.Task):
    """Upload the usage report to the server. Result of the task is not handled in add-on as we do not care so much..."""
    url = f"{daemon_globals.SERVER}/api/v1/usage_report"
    headers = daemon_utils.get_headers(task.data["api_key"])
    session = request.app["SESSION_API_REQUESTS"]
    try:
        async with session.post(url, headers=headers, data=task.data) as resp:
            await resp.text()
    except Exception as e:
        logger.error(f"Error reporting the usage: {e}")
        task.error(f"Error reporting the usage: {e}")
    if resp.status not in [200, 201]:
        logger.error(f"Error reporting the usage ({resp.status})")
        task.error(f"Error reporting the usage ({resp.status})")
    task.finished("Usage successfully reported")


async def blocking_file_upload_handler(request: web.Request):
    """Handle request for blocking file upload. Will not return until the file is uploaded."""
    session = request.app["SESSION_API_REQUESTS"]
    data = await request.json()
    try:
        with open(data["filepath"], "rb") as file:
            resp = await session.put(data["url"], data=file)
            text = await resp.text()
            return web.Response(status=resp.status, text=text)
    except Exception as e:
        logger.error(f"Error in blocking file upload: {e}")
        return web.Response(status=500, text=f"Error in blocking file upload: {e}")
