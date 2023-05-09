"""Holds functionality for asset uploads.
Extends upload.py on addon side."""

import asyncio
import json
import os
import typing
from logging import getLogger
from pathlib import Path

import daemon_globals
import daemon_tasks
import daemon_utils
from aiohttp import ClientSession, web


logger = getLogger(__name__)
BLENDERKIT_EXPORT_DATA_FILE = "data.json"


async def do_upload(request: web.Request, task: daemon_tasks.Task):
    task.change_progress(1, "posting metadata")
    error, metadata_response = await upload_metadata(
        request.app["SESSION_API_REQUESTS"], task
    )
    if error != "":
        task.error(f"Metadata upload failed: {error}")
        return

    data_asset_data = {
        "asset_data": metadata_response,
    }
    task.data.update(data_asset_data)

    metadata_upload_task = daemon_tasks.Task(
        task.data, task.app_id, "asset_metadata_upload"
    )
    metadata_upload_task.finished("Metadata successfully uploaded")
    daemon_globals.tasks.append(metadata_upload_task)

    task.change_progress(5, "packing files")
    error, files = await pack_blend_file(task, metadata_response)
    if error != "":
        return task.error(error)

    task.change_progress(20, "uploading files")
    error = await upload_asset_data(
        request.app["SESSION_UPLOADS"], task, files, metadata_response
    )
    if error != "":
        task.error(f"Asset upload failed: {error}")
        return

    task.finished("Asset successfully uploaded.")


async def upload_metadata(session: ClientSession, task: daemon_tasks.Task):
    """Upload metadata to server, so it can be saved inside the current file."""
    url = f"{daemon_globals.SERVER}/api/v1/assets/"
    upload_data = task.data["upload_data"]
    export_data = task.data["export_data"]
    upload_set = task.data["upload_set"]

    upload_data["parameters"] = daemon_utils.dict_to_params(
        upload_data["parameters"]
    )  # weird array conversion only for upload, not for tooltips.
    headers = daemon_utils.get_headers(upload_data["token"])
    json_metadata = upload_data

    if export_data["assetBaseId"] == "":
        try:
            resp_text, resp_status = None, -1
            async with session.post(url, json=json_metadata, headers=headers) as resp:
                resp_status = resp.status
                resp_text = await resp.text()
                resp.raise_for_status()
                logger.info(f"Got response ({resp.status}) for {url}")
                resp_json = await resp.json()
                return "", resp_json
        except Exception as e:
            msg, detail = daemon_utils.extract_error_message(
                e, resp_text, resp_status, "Upload metadata"
            )
            logger.error(detail)
            return msg, None

    url = f'{url}{export_data["id"]}/'
    if "MAINFILE" in upload_set:
        json_metadata["verificationStatus"] = "uploading"
    try:
        resp_text, resp_status = None, -1
        async with session.patch(url, json=json_metadata, headers=headers) as response:
            resp_status = response.status
            resp_text = await response.text()
            response.raise_for_status()
            logger.info(f"Got response ({response.status}) for {url}")
            resp_json = await response.json()
            return "", resp_json
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Metadata upload"
        )
        logger.error(detail)
        return msg, None


async def pack_blend_file(task: daemon_tasks.Task, metadata_response: dict):
    """Pack the asset data into a separate clean blend file.
    This runs a script inside Blender in separate process.
    """
    addon_path = Path(__file__).resolve().parents[1]  # ../daemon/uploads.py
    script_path = str(addon_path.joinpath("upload_bg.py"))
    cleanfile_path = str(addon_path.joinpath("blendfiles", "cleaned.blend"))
    upload_data = task.data["upload_data"]
    export_data = task.data["export_data"]
    upload_set = task.data["upload_set"]

    if export_data["assetBaseId"] == "":
        export_data["assetBaseId"] = metadata_response["assetBaseId"]
        export_data["id"] = metadata_response["id"]
    upload_data["assetBaseId"] = export_data["assetBaseId"]
    upload_data["id"] = export_data["id"]

    if "MAINFILE" in upload_set:
        if upload_data["assetType"] == "hdr":
            fpath = export_data["hdr_filepath"]
        else:
            fpath = os.path.join(
                export_data["temp_dir"], upload_data["assetBaseId"] + ".blend"
            )
            data = {
                "export_data": export_data,
                "upload_data": upload_data,
                "upload_set": upload_set,
            }
            datafile = os.path.join(
                export_data["temp_dir"], BLENDERKIT_EXPORT_DATA_FILE
            )
            logger.info("opening file @ pack_blend_file()")
            with open(datafile, "w", encoding="utf-8") as s:
                json.dump(data, s, ensure_ascii=False, indent=4)

            task.change_progress(10, "preparing scene - running blender instance")
            logger.info("Running asset packing")
            process = await asyncio.create_subprocess_exec(
                export_data["binary_path"],
                "--background",
                "-noaudio",
                cleanfile_path,
                "--python",
                script_path,
                "--",
                datafile,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0:
                msg = f"Asset packing failed ({process.returncode}) - check daemon log for details."
                out = stdout.decode()
                logger.error(f"Packing failed ({process.returncode}):\n{out}")
                return msg, None

    files = []
    if "THUMBNAIL" in upload_set:
        files.append(
            {
                "type": "thumbnail",
                "index": 0,
                "file_path": export_data["thumbnail_path"],
            }
        )
    if "MAINFILE" in upload_set:
        files.append({"type": "blend", "index": 0, "file_path": fpath})
        if not os.path.exists(fpath):
            return "packed file does not exist, please try manual packing first", None

    return "", files


async def upload_asset_data(
    session: ClientSession,
    task: daemon_tasks.Task,
    files: list,
    metadata_response: dict,
) -> str:
    """Upload .blend file and/or thumbnail to the server."""
    for file in files:
        upload_info_json, ok = await get_S3_upload_JSON(task, session, file)
        if not ok:
            return "failed to get S3 upload info"

        ok, error = await upload_file_to_S3(session, task, file, upload_info_json)
        if not ok:
            return error

    # Check the status if only thumbnail or metadata gets reuploaded.
    # the logic is that on hold assets might be switched to uploaded state for validators,
    # if the asset was put on hold because of thumbnail only.
    set_uploaded_status = False
    if "MAINFILE" not in task.data["upload_set"]:
        if metadata_response.get("verificationStatus") in (
            "on_hold",
            "deleted",
            "rejected",
        ):
            set_uploaded_status = True

    if "MAINFILE" in task.data["upload_set"]:
        set_uploaded_status = True

    if not set_uploaded_status:
        return ""

    # mark on server as uploaded
    confirm_data = {"verificationStatus": "uploaded"}
    headers = daemon_utils.get_headers(task.data["upload_data"]["token"])
    url = f"{daemon_globals.SERVER}/api/v1/assets/{task.data['upload_data']['id']}/"
    try:
        resp_text, resp_status = None, -1
        async with session.patch(url, json=confirm_data, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
            return ""
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "Patch assset failed"
        )
        logger.error(detail)
        return msg


async def get_S3_upload_JSON(
    task: daemon_tasks.Task, session: ClientSession, file: dict
) -> tuple[dict, bool]:
    url = f"{daemon_globals.SERVER}/api/v1/uploads/"
    headers = daemon_utils.get_headers(task.data["upload_data"]["token"])
    upload_info = {
        "assetId": task.data["upload_data"]["id"],
        "fileType": file["type"],
        "fileIndex": file["index"],
        "originalFilename": os.path.basename(file["file_path"]),
    }
    try:
        resp_text, resp_json = None, None
        async with session.post(url, json=upload_info, headers=headers) as resp:
            resp_text = await resp.text()
            resp.raise_for_status()
            resp_json = await resp.json()
            return resp_json, True
    except Exception as e:
        logger.error(f"{type(e)}: {e}, {resp_text}, {resp_json}")
        return None, False


async def upload_file_to_S3(
    session: ClientSession, task: daemon_tasks.Task, file: dict, upload_info_json: dict
) -> typing.Tuple[bool, str]:
    """Uploads file to S3, returns True if successful, error message returned as second value.
    First try to upload file, then validate the upload on server, server returns error if upload failed (wrong file).
    """
    headers = daemon_utils.get_headers(task.data["upload_data"]["token"])

    # FILE UPLOAD
    with open(file["file_path"], "rb") as binary_file:
        logger.info(f"Uploading {file['type']} file {file['file_path']} to S3")
        try:
            resp_text, resp_status = None, -1
            async with session.put(
                upload_info_json["s3UploadUrl"],
                data=binary_file,
            ) as resp:
                resp_status = resp.status
                resp_text = await resp.text()
                resp.raise_for_status()
        except Exception as e:
            msg, detail = daemon_utils.extract_error_message(
                e, resp_text, resp_status, "S3 upload"
            )
            logger.warning(detail)
            return False, msg
    logger.info("File uploaded to S3")

    # UPLOAD VALIDATION
    upload_done_url = f'{daemon_globals.SERVER}/api/v1/uploads_s3/{upload_info_json["id"]}/upload-file/'
    try:
        resp_text, resp_status = None, -1
        async with await session.post(upload_done_url, headers=headers) as resp:
            resp_status = resp.status
            resp_text = await resp.text()
            resp.raise_for_status()
    except Exception as e:
        msg, detail = daemon_utils.extract_error_message(
            e, resp_text, resp_status, "S3 confirmation"
        )
        logger.warning(detail)
        return False, msg

    task.change_progress(task.progress + 15)
    logger.info("File upload confirmed with BlenderKit server")
    return True, ""
