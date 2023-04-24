"""Functions for background processes.
Not used directly in BlenderKit addon, but in BlenderKit background processes.
"""

import logging
import os
from time import sleep

from . import daemon_lib, download, paths, reports, utils


bk_logger = logging.getLogger(__name__)


def upload_file(upload_data, f):
    """Upload file to BlenderKit server. Only for background uploads!
    - autothumb_material_bg.py
    - autothumb_model_bg.py
    """
    message = f"uploading {f['type']} {os.path.basename(f['file_path'])}"
    reports.add_report(message)
    headers = utils.get_headers(upload_data["token"])
    version_id = upload_data["id"]
    upload_info = {
        "assetId": version_id,
        "fileType": f["type"],
        "fileIndex": f["index"],
        "originalFilename": os.path.basename(f["file_path"]),
    }
    url = f"{paths.BLENDERKIT_API}/uploads/"
    upload = daemon_lib.blocking_request(url, "POST", headers, upload_info)
    upload = upload.json()
    for _ in range(0, 5):
        try:
            upload_response = daemon_lib.blocking_file_upload(
                upload["s3UploadUrl"], f["file_path"]
            )
            status_code = upload_response.status_code
            if 250 > status_code > 199:
                upload_done_url = (
                    paths.BLENDERKIT_API
                    + "/uploads_s3/"
                    + upload["id"]
                    + "/upload-file/"
                )
                upload_response = daemon_lib.blocking_request(
                    upload_done_url, "POST", headers, timeout=(1, 10)
                )
                reports.add_report(
                    f"Finished file upload: {os.path.basename(f['file_path'])}"
                )
                return True
            message = f"Upload of {f['type']} {os.path.basename(f['file_path'])} failed ({status_code})"
            reports.add_report(message)
        except Exception as e:
            reports.add_report(
                f"Upload of {f['type']} {os.path.basename(f['file_path'])} failed, err:{e}"
            )
            sleep(1)
    return False


def download_asset_file(asset_data, resolution="blend", api_key=""):
    """This is a simple non-threaded way to download files for background resolution geneneration tool."""
    file_names = paths.get_download_filepaths(asset_data, resolution)
    if len(file_names) == 0:
        return None
    file_name = file_names[0]

    if download.check_existing(asset_data, resolution=resolution):
        # this sends the thread for processing, where another check should occur, since the file might be corrupted.
        bk_logger.debug("not downloading, already in db")
        return file_name
    headers = utils.get_headers(api_key=api_key)
    with open(file_name, "wb") as f:
        bk_logger.info(f"Downloading {file_name}")
        res_file_info, resolution = paths.get_res_file(asset_data, resolution)
        response = daemon_lib.blocking_request(
            "GET", res_file_info["url"], headers=headers
        )
        total_length = response.headers.get("Content-Length")

        if total_length is None or int(total_length) < 1000:  # no content length header
            bk_logger.info(f"{response.content}")
            delete_unfinished_file(file_name)
            return None

        total_length = int(total_length)
        dl = 0
        last_percent = 0
        percent = 0
        for data in response.iter_content(chunk_size=4096 * 10):
            dl += len(data)

            # the exact output you're looking for:
            fs_str = utils.files_size_to_text(total_length)

            percent = int(dl * 100 / total_length)
            if percent > last_percent:
                last_percent = percent
                # sys.stdout.write('\r')
                # sys.stdout.write(f'Downloading {asset_data['name']} {fs_str} {percent}% ')  # + int(dl * 50 / total_length) * 'x')
                bk_logger.info(
                    f'Downloading {asset_data["name"]} {fs_str} {percent}%'
                )  # + int(dl * 50 / total_length) * 'x')
                # sys.stdout.flush()
            f.write(data)
    return file_name


def delete_unfinished_file(file_name):
    """Deletes download if it wasn't finished. If the folder it's containing is empty, it also removes the directory."""
    try:
        os.remove(file_name)
    except Exception as e:
        bk_logger.error(f"{e}")
    asset_dir = os.path.dirname(file_name)
    if len(os.listdir(asset_dir)) == 0:
        os.rmdir(asset_dir)
    return
