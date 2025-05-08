# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import copy
import json
import logging
import math
import os
import re
import unicodedata
import urllib.parse
import uuid
from typing import Optional, Union

import bpy
from bpy.app.handlers import persistent
from bpy.props import (  # TODO only keep the ones actually used when cleaning
    BoolProperty,
    StringProperty,
)
from bpy.types import Operator

from . import (
    asset_bar_op,
    client_lib,
    client_tasks,
    comments_utils,
    datas,
    global_vars,
    image_utils,
    paths,
    ratings_utils,
    reports,
    resolutions,
    tasks_queue,
    utils,
)


bk_logger = logging.getLogger(__name__)
search_tasks = {}


def update_ad(ad):
    if not ad.get("assetBaseId"):
        try:
            ad["assetBaseId"] = ad[
                "asset_base_id"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["assetType"] = ad[
                "asset_type"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["verificationStatus"] = ad[
                "verification_status"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["author"] = {}
            ad["author"]["id"] = ad[
                "author_id"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["canDownload"] = ad[
                "can_download"
            ]  # this should stay ONLY for compatibility with older scenes
        except Exception as e:
            bk_logger.error("BlenderKit failed to update older asset data")
    return ad


def update_assets_data():  # updates assets data on scene load.
    """updates some properties that were changed on scenes with older assets.
    The properties were mainly changed from snake_case to CamelCase to fit the data that is coming from the server.
    """
    datablocks = [
        bpy.data.objects,
        bpy.data.materials,
        bpy.data.brushes,
    ]
    for dtype in datablocks:
        for block in dtype:
            if block.get("asset_data") is not None:
                update_ad(block["asset_data"])

    dicts = [
        "assets used",
    ]
    for s in bpy.data.scenes:
        for bkdict in dicts:
            d = s.get(bkdict)
            if not d:
                continue

            for asset_id in d.keys():
                update_ad(d[asset_id])
                # bpy.context.scene['assets used'][ad] = ad


@persistent
def undo_post_reload_previews(context):
    load_previews()


@persistent
def undo_pre_end_assetbar(context):
    ui_props = bpy.context.window_manager.blenderkitUI

    ui_props.turn_off = True
    ui_props.assetbar_on = False


@persistent
def scene_load(context):
    """Load categories, check timers registration, and update scene asset data.
    Should (probably) also update asset data from server (after user consent).
    """
    update_assets_data()


last_clipboard = ""


def check_clipboard():
    """Check clipboard for an exact string containing asset ID.
    The string is generated on www.blenderkit.com as for example here:
    https://www.blenderkit.com/get-blenderkit/54ff5c85-2c73-49e9-ba80-aec18616a408/
    """
    global last_clipboard
    try:  # could be problematic on Linux
        current_clipboard = bpy.context.window_manager.clipboard
    except Exception as e:
        bk_logger.warning(f"Failed to get clipboard: {e}")
        return

    if current_clipboard == last_clipboard:
        return
    last_clipboard = current_clipboard

    asset_type_index = last_clipboard.find("asset_type:")
    if asset_type_index == -1:
        return

    if not last_clipboard.startswith("asset_base_id:"):
        return

    asset_type_string = current_clipboard[asset_type_index:].lower()
    if asset_type_string.find("model") > -1:
        target_asset_type = "MODEL"
    elif asset_type_string.find("material") > -1:
        target_asset_type = "MATERIAL"
    elif asset_type_string.find("brush") > -1:
        target_asset_type = "BRUSH"
    elif asset_type_string.find("scene") > -1:
        target_asset_type = "SCENE"
    elif asset_type_string.find("hdr") > -1:
        target_asset_type = "HDR"
    elif asset_type_string.find("printable") > -1:
        target_asset_type = "PRINTABLE"
    elif asset_type_string.find("nodegroup") > -1:
        target_asset_type = "NODEGROUP"
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type != target_asset_type:
        ui_props.asset_type = target_asset_type  # switch asset type before placing keywords, so it does not search under wrong asset type

    # all modifications in
    ui_props.search_keywords = current_clipboard[:asset_type_index].rstrip()


# TODO: type annotate and check this crazy function!
# Are we sure it behaves correctly on network issues, malfunctioning search etc?
def parse_result(r) -> dict:
    """Needed to generate some extra data in the result(by now)
    Parameters
    ----------
    r - search result, also called asset_data
    """
    scene = bpy.context.scene
    # TODO remove this fix when filesSize is fixed.
    # this is a temporary fix for too big numbers from the server.
    # can otherwise get the Python int too large to convert to C int
    try:
        r["filesSize"] = int(r["filesSize"] / 1024)
    except:
        utils.p("asset with no files-size")

    asset_type = r["assetType"]
    # TODO remove this condition so all assets are parsed?
    if len(r["files"]) == 0:
        return {}

    adata = r["author"]
    social_networks = datas.parse_social_networks(adata.pop("socialNetworks", []))
    author = datas.UserProfile(**adata, socialNetworks=social_networks)
    generate_author_profile(author)

    r["available_resolutions"] = []
    use_webp = True
    if bpy.app.version < (3, 4, 0) or r.get("webpGeneratedTimestamp", 0) == 0:
        use_webp = False  # WEBP was optimized in Blender 3.4.0

    # BIG THUMB - HDR CASE
    if r["assetType"] == "hdr":
        if use_webp:
            thumb_url = r.get("thumbnailLargeUrlNonsquaredWebp")
        else:
            thumb_url = r.get("thumbnailLargeUrlNonsquared")
    # BIG THUMB - NON HDR CASE
    else:
        if use_webp:
            thumb_url = r.get("thumbnailMiddleUrlWebp")
        else:
            thumb_url = r.get("thumbnailMiddleUrl")

    # SMALL THUMB
    if use_webp:
        small_thumb_url = r.get("thumbnailSmallUrlWebp")
    else:
        small_thumb_url = r.get("thumbnailSmallUrl")

    tname = paths.extract_filename_from_url(thumb_url)
    small_tname = paths.extract_filename_from_url(small_thumb_url)
    for f in r["files"]:
        # if f['fileType'] == 'thumbnail':
        #     tname = paths.extract_filename_from_url(f['fileThumbnailLarge'])
        #     small_tname = paths.extract_filename_from_url(f['fileThumbnail'])
        #     allthumbs.append(tname)  # TODO just first thumb is used now.

        if f["fileType"] == "blend":
            durl = f["downloadUrl"].split("?")[0]
            # fname = paths.extract_filename_from_url(f['filePath'])

        if f["fileType"].find("resolution") > -1:
            r["available_resolutions"].append(resolutions.resolutions[f["fileType"]])

    # code for more thumbnails
    # tdict = {}
    # for i, t in enumerate(allthumbs):
    #     tdict['thumbnail_%i'] = t

    r["max_resolution"] = 0
    if r["available_resolutions"]:  # should check only for non-empty sequences
        r["max_resolution"] = max(r["available_resolutions"])

    # tooltip = generate_tooltip(r)
    # for some reason, the id was still int on some occurances. investigate this.
    r["author"]["id"] = str(r["author"]["id"])

    # some helper props, but generally shouldn't be renaming/duplifiying original properties,
    # so blender's data is same as on server.
    asset_data = {
        "thumbnail": tname,
        "thumbnail_small": small_tname,
        # 'tooltip': tooltip,
    }
    asset_data["downloaded"] = 0

    # parse extra params needed for blender here
    params = r["dictParameters"]  # utils.params_to_dict(r['parameters'])

    if asset_type in ["model", "printable"]:
        if params.get("boundBoxMinX") != None:
            bbox = {
                "bbox_min": (
                    float(params["boundBoxMinX"]),
                    float(params["boundBoxMinY"]),
                    float(params["boundBoxMinZ"]),
                ),
                "bbox_max": (
                    float(params["boundBoxMaxX"]),
                    float(params["boundBoxMaxY"]),
                    float(params["boundBoxMaxZ"]),
                ),
            }

        else:
            bbox = {"bbox_min": (-0.5, -0.5, 0), "bbox_max": (0.5, 0.5, 1)}
        asset_data.update(bbox)
    if asset_type == "material":
        asset_data["texture_size_meters"] = params.get("textureSizeMeters", 1.0)

    # asset_data.update(tdict)

    au = scene.get("assets used", {})  # type: ignore
    if au == {}:
        scene["assets used"] = au  # type: ignore
    if r["assetBaseId"] in au.keys():
        asset_data["downloaded"] = 100
        # transcribe all urls already fetched from the server
        r_previous = au[r["assetBaseId"]]
        if r_previous.get("files"):
            for f in r_previous["files"]:
                if f.get("url"):
                    for f1 in r["files"]:
                        if f1["fileType"] == f["fileType"]:
                            f1["url"] = f["url"]

    # attempt to switch to use original data gradually, since the parsing as itself should become obsolete.
    asset_data.update(r)
    return asset_data


def clear_searches():
    global search_tasks
    search_tasks.clear()


def cleanup_search_results():
    """Cleanup all search results in history steps and global vars."""
    # First clean up history steps
    for history_step in get_history_steps().values():
        history_step.pop("search_results", None)
        history_step.pop("search_results_orig", None)


def handle_search_task_error(task: client_tasks.Task) -> None:
    """Handle incomming search task error."""
    # First find the history step that the task belongs to
    for history_step in get_history_steps().values():
        if task.task_id in history_step.get("search_tasks", {}).keys():
            history_step["is_searching"] = False
            break
    return reports.add_report(task.message, type="ERROR", details=task.message_detailed)


def handle_search_task(task: client_tasks.Task) -> bool:
    """Parse search results, try to load all available previews."""
    global search_tasks

    if len(search_tasks) == 0:
        # First find the history step that the task belongs to
        history_step = get_history_step(task.history_id)
        history_step["is_searching"] = False
        return True

    # don't do anything while dragging - this could switch asset during drag, and make results list length different,
    # causing a lot of throuble.
    if bpy.context.window_manager.blenderkitUI.dragging:  # type: ignore[attr-defined]
        return False

    # if original task was already removed (because user initiated another search), results are dropped- Returns True
    # because that's OK.
    orig_task = search_tasks.get(task.task_id)

    search_tasks.pop(task.task_id)

    # this fixes black thumbnails in asset bar, test if this bug still persist in blender and remove if it's fixed
    if bpy.app.version < (3, 3, 0):
        sys_prefs = bpy.context.preferences.system
        sys_prefs.gl_texture_limit = "CLAMP_OFF"

    ###################

    asset_type = task.data["asset_type"]
    props = utils.get_search_props()
    search_name = f"bkit {asset_type} search"

    # Get current history step
    history_step = get_history_step(orig_task.history_id)

    if not task.data.get("get_next"):
        result_field = []  # type: ignore
    else:
        result_field = []
        for r in history_step.get("search_results", []):  # type: ignore
            result_field.append(r)

    ui_props = bpy.context.window_manager.blenderkitUI  # type: ignore[attr-defined]
    for result in task.result["results"]:
        asset_data = parse_result(result)
        if not asset_data:
            bk_logger.warning("Parsed asset data are empty for search result", result)
            continue

        result_field.append(asset_data)
        if not utils.profile_is_validator():
            continue
        # VALIDATORS
        # fetch all comments if user is validator to preview them faster
        # these comments are also shown as part of the tooltip oh mouse hover in asset bar.
        comments = comments_utils.get_comments_local(asset_data["assetBaseId"])
        if comments is None:
            client_lib.get_comments(asset_data["assetBaseId"])

    # Store results in history step
    history_step["search_results"] = result_field
    history_step["search_results_orig"] = task.result
    history_step["is_searching"] = False

    if len(result_field) < ui_props.scroll_offset or not (task.data.get("get_next")):
        # jump back
        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.scroll_offset = 0
        ui_props.scroll_offset = 0

    # show asset bar automatically, but only on first page - others are loaded also when asset bar is hidden.
    if not ui_props.assetbar_on and not task.data.get("get_next"):
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]

    if len(result_field) < ui_props.scroll_offset or not (task.data.get("get_next")):
        # jump back
        ui_props.scroll_offset = 0
    props.report = f"Found {task.result['count']} results."
    if len(result_field) == 0:
        tasks_queue.add_task((reports.add_report, ("No matching results found.",)))
    else:
        tasks_queue.add_task(
            (
                reports.add_report,
                (f"Found {task.result['count']} results.",),
            )
        )
    # show asset bar automatically, but only on first page - others are loaded also when asset bar is hidden.
    if not ui_props.assetbar_on and not task.data.get("get_next"):
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]

    return True


def handle_thumbnail_download_task(task: client_tasks.Task) -> None:
    if task.status == "finished":
        global_vars.DATA["images available"][task.data["image_path"]] = True
    elif task.status == "error":
        global_vars.DATA["images available"][task.data["image_path"]] = False
        if task.message != "":
            reports.add_report(task.message, timeout=5, type="ERROR")
    else:
        return
    if asset_bar_op.asset_bar_operator is None:
        return

    if task.data["thumbnail_type"] == "small":
        asset_bar_op.asset_bar_operator.update_image(task.data["assetBaseId"])
        return

    if task.data["thumbnail_type"] == "full":
        asset_bar_op.asset_bar_operator.update_tooltip_image(task.data["assetBaseId"])


def load_preview(asset):
    # FIRST START SEARCH
    props = bpy.context.window_manager.blenderkitUI
    directory = paths.get_temp_dir("%s_search" % props.asset_type.lower())

    tpath = os.path.join(directory, asset["thumbnail_small"])
    tpath_exists = os.path.exists(tpath)
    if (
        not asset["thumbnail_small"]
        or asset["thumbnail_small"] == ""
        or not tpath_exists
    ):
        # tpath = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
        asset["thumb_small_loaded"] = False

    iname = f".{asset['thumbnail_small']}"
    # if os.path.exists(tpath):  # sometimes we are unlucky...
    img = bpy.data.images.get(iname)

    if img is None or len(img.pixels) == 0:
        if not tpath_exists:
            return False
        # wrap into try statement since sometimes
        try:
            img = bpy.data.images.load(tpath, check_existing=True)
            img.name = iname
            if len(img.pixels) > 0:
                return True
        except Exception as e:
            print(f"search.py: could not load image {iname}: {e}")
        return False
    elif img.filepath != tpath:
        if not tpath_exists:
            # unload loaded previews from previous results
            bpy.data.images.remove(img)
            return False
        # had to add this check for autopacking files...
        if bpy.data.use_autopack and img.packed_file is not None:
            img.unpack(method="USE_ORIGINAL")
        img.filepath = tpath
        try:
            img.reload()
        except Exception as e:
            print(f"search.py: could not reload image {iname}: {e}")
            return False

    image_utils.set_colorspace(img)
    asset["thumb_small_loaded"] = True
    return True


def load_previews():
    results = get_search_results()
    if results is None:
        return
    for _, result in enumerate(results):
        load_preview(result)


#  line splitting for longer texts...
def split_subs(text, threshold=40):
    if text == "":
        return []
    # temporarily disable this, to be able to do this in drawing code

    text = text.rstrip()
    text = text.replace("\r\n", "\n")

    lines = []

    while len(text) > threshold:
        # first handle if there's an \n line ending
        i_rn = text.find("\n")
        if 1 < i_rn < threshold:
            i = i_rn
            text = text.replace("\n", "", 1)
        else:
            i = text.rfind(" ", 0, threshold)
            i1 = text.rfind(",", 0, threshold)
            i2 = text.rfind(".", 0, threshold)
            i = max(i, i1, i2)
            if i <= 0:
                i = threshold
        lines.append(text[:i])
        text = text[i:]
    lines.append(text)
    return lines


def list_to_str(input):
    output = ""
    for i, text in enumerate(input):
        output += text
        if i < len(input) - 1:
            output += ", "
    return output


def writeblock(t, input, width=40):  # for longer texts
    dlines = split_subs(input, threshold=width)
    for i, l in enumerate(dlines):
        t += "%s\n" % l
    return t


def write_block_from_value(tooltip, value, pretext="", width=2000):  # for longer texts
    if not value:
        return tooltip

    if type(value) == list:
        intext = list_to_str(value)
    elif type(value) == float:
        intext = round(intext, 3)
    else:
        intext = value

    intext = str(intext)
    if intext.rstrip() == "":
        return tooltip

    if pretext != "":
        pretext = pretext + ": "

    text = pretext + intext
    dlines = split_subs(text, threshold=width)
    for _, line in enumerate(dlines):
        tooltip += f"{line}\n"

    return tooltip


def has(mdata, prop):
    if (
        mdata.get(prop) is not None
        and mdata[prop] is not None
        and mdata[prop] is not False
    ):
        return True
    else:
        return False


def generate_tooltip(mdata):
    col_w = 40
    if type(mdata["parameters"]) == list:
        mparams = utils.params_to_dict(mdata["parameters"])
    else:
        mparams = mdata["parameters"]
    t = ""
    t = writeblock(t, mdata["displayName"], width=int(col_w * 0.6))
    # t += '\n'

    # t = writeblockm(t, mdata, key='description', pretext='', width=col_w)
    return t


def generate_author_textblock(first_name: str, last_name: str, about_me: str):
    if len(first_name + last_name) == 0:
        return ""

    text = f"{first_name} {last_name}\n"
    if about_me:
        text = write_block_from_value(text, about_me)

    return text


def handle_fetch_gravatar_task(task: client_tasks.Task):
    """Handle incomming fetch_gravatar_task which contains path to author's image on the disk."""
    if task.status == "finished":
        author_id = int(task.data["id"])
        gravatar_path = task.result["gravatar_path"]
        global_vars.BKIT_AUTHORS[author_id].gravatarImg = gravatar_path


def generate_author_profile(author_data: datas.UserProfile):
    """Generate author profile by creating author textblock and fetching gravatar image if needed.
    Gravatar download is started in BlenderKit-Client and handled later."""
    author_id = int(author_data.id)
    if author_id in global_vars.BKIT_AUTHORS:
        return
    resp = client_lib.download_gravatar_image(author_data)
    if resp.status_code != 200:
        bk_logger.warning(resp.text)

    # TODO: tooltip generation could be part of the __init__, right?
    author_data.tooltip = generate_author_textblock(
        author_data.firstName, author_data.lastName, author_data.aboutMe
    )
    global_vars.BKIT_AUTHORS[author_id] = author_data
    return


def handle_get_user_profile(task: client_tasks.Task):
    """Handle incomming get_user_profile task which contains data about current logged-in user."""
    if task.status not in ["finished", "error"]:
        return

    if task.status == "error":
        bk_logger.warning(f"Could not load user profile: {task.message}")
        return

    user_data = task.result.get("user")
    if not user_data:
        bk_logger.warning("Got empty user profile")
        return

    can_edit_all_assets = task.result.get("canEditAllAssets", False)
    social_networks = datas.parse_social_networks(user_data.pop("socialNetworks", []))

    user = datas.MineProfile(
        socialNetworks=social_networks,
        canEditAllAssets=can_edit_all_assets,
        **user_data,
    )
    user.tooltip = generate_author_textblock(
        user.firstName, user.lastName, user.aboutMe
    )
    global_vars.BKIT_PROFILE = user

    public_user = datas.UserProfile(
        aboutMe=user.aboutMe,
        aboutMeUrl=user.aboutMeUrl,
        avatar128=user.avatar128,
        firstName=user.firstName,
        fullName=user.fullName,
        gravatarHash=user.gravatarHash,
        id=user.id,
        lastName=user.lastName,
        socialNetworks=user.socialNetworks,
        avatar256=user.avatar256,
        gravatarImg=user.gravatarImg,
        tooltip=user.tooltip,
    )
    global_vars.BKIT_AUTHORS[user.id] = public_user

    # after profile arrives, we can check for gravatar image
    resp = client_lib.download_gravatar_image(public_user)
    if resp.status_code != 200:
        bk_logger.warning(resp.text)

    if user.canEditAllAssets:  # IS VALIDATOR
        utils.enforce_prerelease_update_check()


def query_to_url(
    query: Optional[dict] = None,
    addon_version: str = "",
    blender_version: str = "",
    scene_uuid: str = "",
    page_size: int = 15,
) -> str:
    """Build a new search request by parsing query dictionaty into appropriate URL.
    Also modifies query and adds some stuff in there which is very misleading anti-pattern.
    TODO: just convert to URL here and move the sorting and adding of params to separate function.
    https://www.blenderkit.com/api/v1/search/
    """
    if query is None:
        query = {}

    url = f"{paths.BLENDERKIT_API}/search/"
    if query is None:
        query = {}

    requeststring = "?query="
    if query.get("query") not in ("", None):
        requeststring += urllib.parse.quote_plus(query["query"])  # .lower()
    for q in query:
        if q != "query" and q != "free_first":
            requeststring += (
                f"+{q}:{urllib.parse.quote_plus(str(query[q]))}"  # .lower()
            )

    # add dict_parameters to make results smaller
    # result ordering: _score - relevance, score - BlenderKit score
    order = []
    if query.get("free_first", False):
        order = [
            "-is_free",
        ]

    # query with category_subtree:model etc gives irrelevant results
    if query.get("category_subtree") in (
        "model",
        "material",
        "scene",
        "brush",
        "hdr",
        "nodegroup",
        "printable",
    ):
        query["category_subtree"] = None

    if query.get("query") is None and query.get("category_subtree") == None:
        # assumes no keywords and no category, thus an empty search that is triggered on start.
        # orders by last core file upload
        if query.get("verification_status") == "uploaded":
            # for validators, sort uploaded from oldest
            order.append("last_blend_upload")
        else:
            order.append("-last_blend_upload")
    elif (
        query.get("author_id") is not None
        or query.get("query", "").find("+author_id:") > -1
    ) and utils.profile_is_validator():
        order.append("-created")
    else:
        if query.get("category_subtree") is not None:
            order.append("-score,_score")
        else:
            order.append("_score")
    if requeststring.find("+order:") == -1:
        requeststring += "+order:" + ",".join(order)
    requeststring += "&dict_parameters=1"

    requeststring += "&page_size=" + str(page_size)
    requeststring += f"&addon_version={addon_version}"
    if not (query.get("query") and query.get("query", "").find("asset_base_id") > -1):
        requeststring += f"&blender_version={blender_version}"
    if scene_uuid:
        requeststring += f"&scene_uuid={scene_uuid}"

    urlquery = url + requeststring
    return urlquery


def build_query_common(query: dict, props, ui_props) -> dict:
    """Pure function to add shared parameters based on props to query dict.
    Returns the updated version of the query dict.
    """
    query = copy.deepcopy(query)
    query_common = {}
    if ui_props.search_keywords != "":
        keywords = ui_props.search_keywords.replace("&", "%26")
        query_common["query"] = keywords

    if props.search_verification_status != "ALL" and utils.profile_is_validator():
        query_common["verification_status"] = props.search_verification_status.lower()

    if props.unrated_quality_only and utils.profile_is_validator():
        query["quality_count"] = 0

    if props.unrated_wh_only and utils.profile_is_validator():
        query["working_hours_count"] = 0

    if props.search_file_size:
        query_common["files_size_gte"] = props.search_file_size_min * 1024 * 1024
        query_common["files_size_lte"] = props.search_file_size_max * 1024 * 1024

    if ui_props.quality_limit > 0:
        query["quality_gte"] = ui_props.quality_limit

    if ui_props.search_bookmarks:
        query["bookmarks_rating"] = 1

    if ui_props.search_license != "ANY":
        query["license"] = ui_props.search_license

    if ui_props.search_blender_version == True:
        query["source_app_version_gte"] = ui_props.search_blender_version_min
        query["source_app_version_lt"] = ui_props.search_blender_version_max

    query.update(query_common)
    return query


def build_query_model(props, ui_props, preferences) -> dict:
    """Use all search inputs (props) and add-on preferences
    to build search query request to get results from server.
    """
    query: dict[str, Union[str, bool]] = {"asset_type": "model"}
    if props.search_style != "ANY":
        if props.search_style != "OTHER":
            query["modelStyle"] = props.search_style
        else:
            query["modelStyle"] = props.search_style_other

    if props.search_condition != "UNSPECIFIED":
        query["condition"] = props.search_condition
    if props.search_design_year:
        query["designYear_gte"] = props.search_design_year_min
        query["designYear_lte"] = props.search_design_year_max
    if props.search_polycount:
        query["faceCount_gte"] = props.search_polycount_min
        query["faceCount_lte"] = props.search_polycount_max
    if props.search_texture_resolution:
        query["textureResolutionMax_gte"] = props.search_texture_resolution_min
        query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    if props.search_animated:
        query["animated"] = True
    if props.search_geometry_nodes:
        query["modifiers"] = "nodes"
    if (
        preferences.nsfw_filter
    ):  # nsfw_filter is toggle for predefined subsets (users could fine-tune in future)
        query["sexualizedContent"] = False
        # TODO: add here more subsets, NSFW is general switch for subsets defined by user (sexualized, violence, etc)
    else:
        query["sexualizedContent"] = ""
    return build_query_common(query, props, ui_props)


def build_query_scene(
    props,
    ui_props,
) -> dict:
    """Use all search input to request results from server."""
    query = {
        "asset_type": "scene",
    }
    return build_query_common(query, props, ui_props)


def build_query_HDR(props, ui_props) -> dict:
    """Use all search input to request results from server."""
    query = {
        "asset_type": "hdr",
    }
    if props.search_texture_resolution:
        query["textureResolutionMax_gte"] = props.search_texture_resolution_min
        query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    if props.true_hdr:
        query["trueHDR"] = props.true_hdr
    return build_query_common(query, props, ui_props)


def build_query_material(
    props,
    ui_props,
) -> dict:
    query: dict[str, Union[str, int]] = {"asset_type": "material"}
    if props.search_style != "ANY":
        if props.search_style != "OTHER":
            query["style"] = props.search_style
        else:
            query["style"] = props.search_style_other
    if props.search_procedural == "TEXTURE_BASED":
        # todo this procedural hack should be replaced with the parameter
        query["textureResolutionMax_gte"] = 0
        # query["procedural"] = False
        if props.search_texture_resolution:
            query["textureResolutionMax_gte"] = props.search_texture_resolution_min
            query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    elif props.search_procedural == "PROCEDURAL":
        # todo this procedural hack should be replaced with the parameter
        query["files_size_lte"] = 1024 * 1024
        # query["procedural"] = True
    return build_query_common(query, props, ui_props)


def build_query_brush(props, ui_props, image_paint_object) -> dict:
    """Pure function to construct search query dict for brushes."""
    if image_paint_object:  # could be just else, but for future p
        brush_type = "texture_paint"
    # automatically fallback to sculpt since most brushes are sculpt anyway.
    else:  # if bpy.context.sculpt_object is not None:
        brush_type = "sculpt"

    query = {"asset_type": "brush", "mode": brush_type}
    return build_query_common(query, props, ui_props)


def build_query_nodegroup(
    props,
    ui_props,
) -> dict:
    """Pure function to construct search query dict for nodegroups."""
    query = {"asset_type": "nodegroup"}
    return build_query_common(query, props, ui_props)


def add_search_process(
    query, get_next: bool, page_size: int, next_url: str, history_id: str
):
    global search_tasks
    addon_version = utils.get_addon_version()
    blender_version = utils.get_blender_version()
    scene_uuid = bpy.context.scene.get("uuid", "")  # type: ignore[attr-defined]

    tempdir = paths.get_temp_dir("%s_search" % query["asset_type"])
    if get_next and next_url:
        urlquery = next_url
    else:
        urlquery = query_to_url(
            query, addon_version, blender_version, scene_uuid, page_size
        )

    search_data = datas.SearchData(
        PREFS=utils.get_preferences(),  # change this
        tempdir=tempdir,
        urlquery=urlquery,
        asset_type=query["asset_type"],
        scene_uuid=scene_uuid,
        get_next=get_next,
        page_size=page_size,
        blender_version=blender_version,
        is_validator=utils.profile_is_validator(),
        history_id=history_id,
    )
    response = client_lib.asset_search(search_data)
    search_tasks[response["task_id"]] = search_data


def get_search_simple(
    parameters, filepath=None, page_size=100, max_results=100000000, api_key=""
):
    """Searches and returns the search results.

    Parameters
    ----------
    parameters - dict of blenderkit elastic parameters
    filepath - a file to save the results. If None, results are returned
    page_size - page size for retrieved results
    max_results - max results of the search
    api_key - BlenderKit api key

    Returns
    -------
    Returns search results as a list, and optionally saves to filepath
    """
    headers = utils.get_headers(api_key)
    url = f"{paths.BLENDERKIT_API}/search/"
    requeststring = url + "?query="
    for p in parameters.keys():
        requeststring += f"+{p}:{parameters[p]}"

    requeststring += "&page_size=" + str(page_size)
    requeststring += "&dict_parameters=1"

    bk_logger.debug(requeststring)
    response = client_lib.blocking_request(requeststring, "GET", headers)

    # print(response.json())
    search_results = response.json()

    results = []
    results.extend(search_results["results"])
    page_index = 2
    page_count = math.ceil(search_results["count"] / page_size)
    while search_results.get("next") and len(results) < max_results:
        bk_logger.info(f"getting page {page_index} , total pages {page_count}")
        response = client_lib.blocking_request(search_results["next"], "GET", headers)
        search_results = response.json()
        results.extend(search_results["results"])
        page_index += 1

    if not filepath:
        return results

    with open(filepath, "w", encoding="utf-8") as s:
        json.dump(results, s, ensure_ascii=False, indent=4)
    bk_logger.info(f"retrieved {len(results)} assets from elastic search")
    return results


def search(get_next=False, query=None, author_id=""):
    """Initialize searching
    query : submit an already built query from search history
    """
    if global_vars.CLIENT_ACCESSIBLE != True:
        reports.add_report(
            "Cannot search, Client is not accessible.", timeout=5, type="ERROR"
        )
        return

    user_preferences = bpy.context.preferences.addons[__package__].preferences
    wm = bpy.context.window_manager
    ui_props = bpy.context.window_manager.blenderkitUI

    # if search is locked, don't trigger search update
    if ui_props.search_lock:
        return

    props = utils.get_search_props()
    active_history_step = get_active_history_step()

    # it's possible get_next was requested more than once.
    if active_history_step.get("is_searching") and get_next == True:
        # search already running, skipping
        return

    if not query:
        if ui_props.asset_type == "MODEL":
            if not hasattr(wm, "blenderkit_models"):
                return
            query = build_query_model(
                bpy.context.window_manager.blenderkit_models,
                ui_props=bpy.context.window_manager.blenderkitUI,
                preferences=bpy.context.preferences.addons[__package__].preferences,
            )

        if ui_props.asset_type == "PRINTABLE":
            if not hasattr(wm, "blenderkit_models"):
                return
            query = build_query_model(
                bpy.context.window_manager.blenderkit_models,
                ui_props=bpy.context.window_manager.blenderkitUI,
                preferences=bpy.context.preferences.addons[__package__].preferences,
            )
            query["asset_type"] = "printable"  # Override the asset type for PRINTABLE

        if ui_props.asset_type == "SCENE":
            if not hasattr(wm, "blenderkit_scene"):
                return
            query = build_query_scene(
                bpy.context.window_manager.blenderkit_scene,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "HDR":
            if not hasattr(wm, "blenderkit_HDR"):
                return
            query = build_query_HDR(
                bpy.context.window_manager.blenderkit_HDR,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "MATERIAL":
            if not hasattr(wm, "blenderkit_mat"):
                return
            query = build_query_material(
                bpy.context.window_manager.blenderkit_mat,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "TEXTURE":
            if not hasattr(wm, "blenderkit_tex"):
                return
            # props = scene.blenderkit_tex
            # query = build_query_texture()

        if ui_props.asset_type == "BRUSH":
            if not hasattr(wm, "blenderkit_brush"):
                return
            query = build_query_brush(
                bpy.context.window_manager.blenderkit_brush,
                bpy.context.window_manager.blenderkitUI,
                bpy.context.image_paint_object,
            )

        if ui_props.asset_type == "NODEGROUP":
            if not hasattr(wm, "blenderkit_nodegroup"):
                return
            query = build_query_nodegroup(
                props=bpy.context.window_manager.blenderkit_nodegroup,
                ui_props=bpy.context.window_manager.blenderkitUI,
            )

        # crop long searches
        if query.get("query"):
            if len(query["query"]) > 50:
                query["query"] = strip_accents(query["query"])

            if len(query["query"]) > 150:
                idx = query["query"].find(" ", 142)
                query["query"] = query["query"][:idx]

        if props.search_category != "":
            if utils.profile_is_validator() and user_preferences.categories_fix:
                query["category"] = props.search_category
            else:
                query["category_subtree"] = props.search_category

        if author_id != "":
            query["author_id"] = author_id

        elif ui_props.own_only:
            # if user searches for [another] author, 'only my assets' is invalid. that's why in elif.
            profile = global_vars.BKIT_PROFILE
            if profile is not None:
                query["author_id"] = str(profile.id)

        # free first has to by in query to be evaluated as changed as another search, otherwise the filter is not updated.
        query["free_first"] = ui_props.free_only

    active_history_step["is_searching"] = True

    page_size = min(40, ui_props.wcount * user_preferences.max_assetbar_rows + 5)

    next_url = ""
    if get_next and active_history_step.get("search_results_orig"):
        next_url = active_history_step["search_results_orig"].get("next", "")

    add_search_process(query, get_next, page_size, next_url, active_history_step["id"])
    props.report = "BlenderKit searching...."


def clean_filters():
    """Cleanup filters in case search needs to be reset, typicaly when asset id is copy pasted."""
    sprops = utils.get_search_props()
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.property_unset("own_only")
    sprops.property_unset("search_texture_resolution")
    sprops.property_unset("search_file_size")
    sprops.property_unset("search_procedural")
    ui_props.property_unset("free_only")
    ui_props.property_unset("quality_limit")
    ui_props.property_unset("search_bookmarks")
    if ui_props.asset_type == "MODEL":
        sprops.property_unset("search_style")
        sprops.property_unset("search_condition")
        sprops.property_unset("search_design_year")
        sprops.property_unset("search_polycount")
        sprops.property_unset("search_animated")
        sprops.property_unset("search_geometry_nodes")
    if ui_props.asset_type == "HDR":
        # Set without triggering update functions:
        sprops["true_hdr"] = False
        while True:  # Wait until true_hdr is updated
            sprops = utils.get_search_props()
            if sprops["true_hdr"] == False:
                break
            print("waiting for sprops.true_hdr to be updated")


def update_filters():
    """Update filters for 2 reasons
    - first to show if filters are active
    - second to show login popup if user needs to log in

    returns True if search should proceed, False to bounce search(like in the case of bookmarks)
    """

    sprops = utils.get_search_props()
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_bookmarks and not utils.user_logged_in():
        ui_props.search_bookmarks = False
        bpy.ops.wm.blenderkit_login_dialog(
            "INVOKE_DEFAULT", message="Please login to use bookmarks."
        )
        return False
    if ui_props.own_only and not utils.user_logged_in():
        ui_props.own_only = False
        bpy.ops.wm.blenderkit_login_dialog(
            "INVOKE_DEFAULT",
            message="Please login to upload and filter your own assets.",
        )
        return False

    fcommon = (
        ui_props.own_only
        or sprops.search_texture_resolution
        or sprops.search_file_size
        or sprops.search_procedural != "BOTH"
        or ui_props.free_only
        or ui_props.quality_limit > 0
        or ui_props.search_bookmarks
        or ui_props.search_license != "ANY"
        or ui_props.search_blender_version
        # NSFW filter is signaled in a special way and should not affect the filter icon
    )

    if ui_props.asset_type == "MODEL":
        sprops.use_filters = (
            fcommon
            or sprops.search_style != "ANY"
            or sprops.search_condition != "UNSPECIFIED"
            or sprops.search_design_year
            or sprops.search_polycount
            or sprops.search_animated
            or sprops.search_geometry_nodes
        )
    elif ui_props.asset_type == "SCENE":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "MATERIAL":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "BRUSH":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "HDR":
        sprops.use_filters = sprops.true_hdr
    elif ui_props.asset_type == "NODEGROUP":
        sprops.use_filters = fcommon
    return True


def search_update_delayed(self, context):
    """run search after user changes a search parameter,
    but with a delay.
    This reduces number of calls during slider UI interaction (like texture resolution, polycount)
    """

    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_lock:
        return

    tasks_queue.add_task((search_update, (None, None)), wait=0.5, only_last=True)


def search_update_verification_status(self, context):
    """run search after user changes a search parameter"""
    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_lock:
        return

    # if there is an author_id in search_keywords, we want to clear those for validators
    if ui_props.search_keywords.find("+author_id:") > -1:
        ui_props.search_keywords = ""
    search_update(self, context)


def detect_asset_type_from_keywords(keywords: str) -> tuple[str, str]:
    """Detect asset type from keywords and return tuple of (asset_type, cleaned_keywords).
    Returns ('', original_keywords) if no asset type is detected."""

    # Dictionary mapping keyword variations to asset types
    asset_type_map = {
        "model": "MODEL",
        "material": "MATERIAL",
        "mat": "MATERIAL",
        "brush": "BRUSH",
        "scene": "SCENE",
        "hdr": "HDR",
        "hdri": "HDR",
        "nodegroup": "NODEGROUP",
        "node": "NODEGROUP",
        "printable": "PRINTABLE",
    }

    # Convert to lowercase for matching
    keywords_lower = keywords.lower()

    # Check each word in the search string
    for word in keywords_lower.split():
        if word in asset_type_map:
            # Remove the asset type word from keywords
            cleaned_keywords = keywords_lower.replace(word, "").strip()
            return asset_type_map[word], cleaned_keywords

    return "", keywords


def search_update(self, context):
    """run search after user changes a search parameter"""

    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_lock:
        return

    # update filters
    go_on = update_filters()
    if not go_on:
        return

    ui_props = bpy.context.window_manager.blenderkitUI

    # Check if keywords contain asset type before processing clipboard
    if ui_props.search_keywords != "":
        detected_type, cleaned_keywords = detect_asset_type_from_keywords(
            ui_props.search_keywords
        )
        if detected_type and detected_type != ui_props.asset_type:
            # Store keywords before switching
            ui_props.search_lock = True
            ui_props.search_keywords = cleaned_keywords
            # Switch asset type
            ui_props.asset_type = detected_type
            ui_props.search_lock = False
            # Return since changing keywords will trigger this function again
            # not now - let's try it with lock

    # if ui_props.down_up != "SEARCH":
    #     ui_props.down_up = "SEARCH"

    # Input tweaks if user manually placed asset-link from website -> we need to get rid of asset type and set it in UI.
    # This is not normally needed as check_clipboard() asset_type switching but without recursive shit.
    instr = "asset_base_id:"
    atstr = "asset_type:"
    kwds = ui_props.search_keywords
    id_index = kwds.find(instr)
    if id_index > -1:
        asset_type_index = kwds.find(atstr)
        # if the asset type already isn't there it means this update function
        # was triggered by it's last iteration and needs to cancel
        if asset_type_index > -1:
            asset_type_string = kwds[asset_type_index:].lower()
            # uncertain length of the remaining string -  find as better method to check the presence of asset type
            if asset_type_string.find("model") > -1:
                target_asset_type = "MODEL"
            elif asset_type_string.find("material") > -1:
                target_asset_type = "MATERIAL"
            elif asset_type_string.find("brush") > -1:
                target_asset_type = "BRUSH"
            elif asset_type_string.find("scene") > -1:
                target_asset_type = "SCENE"
            elif asset_type_string.find("hdr") > -1:
                target_asset_type = "HDR"
            elif asset_type_string.find("nodegroup") > -1:
                target_asset_type = "NODEGROUP"
            elif asset_type_string.find("printable") > -1:
                target_asset_type = "PRINTABLE"

            if ui_props.asset_type != target_asset_type:
                ui_props.search_keywords = ""
                ui_props.asset_type = target_asset_type

            # now we trim the input copypaste by anything extra that is there,
            # this is also a way for this function to recognize that it already has parsed the clipboard
            # the search props can have changed and this needs to transfer the data to the other field
            # this complex behaviour is here for the case where the user needs to paste manually into blender,
            # Otherwise it could be processed directly in the clipboard check function.
            sprops = utils.get_search_props()
            clean_filters()
            ui_props.search_keywords = kwds[:asset_type_index].rstrip()
            # return here since writing into search keywords triggers this update function once more.
            return

    if global_vars.CLIENT_ACCESSIBLE:
        reports.add_report(f"Searching for: '{kwds}'", 2)

    # create history step
    active_tab = get_active_tab()
    create_history_step(active_tab)
    search()


# accented_string is of type 'unicode'
def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def refresh_search():
    """Refresh search results. Useful after login/logout."""
    props = utils.get_search_props()
    if props is not None:
        props.report = ""

    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.assetbar_on:
        ui_props.turn_off = True
        ui_props.assetbar_on = False
    cleanup_search_results()  # TODO: is it possible to start this from Client automatically? probably YEA


# TODO: fix the tooltip?
class SearchOperator(Operator):
    """Tooltip"""

    bl_idname = "view3d.blenderkit_search"
    bl_label = "BlenderKit asset search"
    bl_description = "Search online for assets"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    esc: BoolProperty(  # type: ignore[valid-type]
        name="Escape window",
        description="Escape window right after start",
        default=False,
        options={"SKIP_SAVE"},
    )

    own: BoolProperty(  # type: ignore[valid-type]
        name="own assets only",
        description="Find all own assets",
        default=False,
        options={"SKIP_SAVE"},
    )

    # category: StringProperty(
    #     name="category",
    #     description="search only subtree of this category",
    #     default="",
    #     options={"SKIP_SAVE"},
    # )

    author_id: StringProperty(  # type: ignore[valid-type]
        name="Author ID",
        description="Author ID - search only assets by this author",
        default="",
        options={"SKIP_SAVE"},
    )

    get_next: BoolProperty(  # type: ignore[valid-type]
        name="next page",
        description="get next page from previous search",
        default=False,
        options={"SKIP_SAVE"},
    )

    keywords: StringProperty(  # type: ignore[valid-type]
        name="Keywords", description="Keywords", default="", options={"SKIP_SAVE"}
    )

    # close_window: BoolProperty(name='Close window',
    #                            description='Try to close the window below mouse before download',
    #                            default=False)

    tooltip: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        # TODO ; this should all get transferred to properties of the search operator, so sprops don't have to be fetched here at all.
        if self.esc:
            bpy.ops.view3d.close_popup_button("INVOKE_DEFAULT")
        ui_props = bpy.context.window_manager.blenderkitUI
        if self.author_id != "":
            bk_logger.info(f"Author ID: {self.author_id}")
            # if there is already an author id in the search keywords, remove it first, the author_id can be any so
            # use regex to find it
            ui_props.search_keywords = re.sub(
                r"\+author_id:\d+", "", ui_props.search_keywords
            )
            ui_props.search_keywords += f"+author_id:{self.author_id}"
        if self.keywords != "":
            ui_props.search_keywords = self.keywords

        search(get_next=self.get_next)

        return {"FINISHED"}


class UrlOperator(Operator):
    """"""

    bl_idname = "wm.blenderkit_url"
    bl_label = ""
    bl_description = "Search online for assets"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooltip: bpy.props.StringProperty(default="Open a web page")  # type: ignore[valid-type]
    url: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def execute(self, context):
        bpy.ops.wm.url_open(url=self.url)
        return {"FINISHED"}


class TooltipLabelOperator(Operator):
    """"""

    bl_idname = "wm.blenderkit_tooltip"
    bl_label = ""
    bl_description = "Empty operator to be able to create tooltips on labels in UI"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooltip: bpy.props.StringProperty(default="Open a web page")  # type: ignore[valid-type]

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def execute(self, context):
        return {"FINISHED"}


def get_search_similar_keywords(asset_data: dict) -> str:
    """Generate search similar keywords from the given asset_data.
    Could be tuned in the future to provide better search results.
    """
    keywords = asset_data["name"]
    if asset_data.get("description"):
        keywords += f" {asset_data.get('description')} "
    keywords += " ".join(asset_data.get("tags", []))
    return keywords


classes = [SearchOperator, UrlOperator, TooltipLabelOperator]


def register_search():
    bpy.app.handlers.load_post.append(scene_load)
    bpy.app.handlers.load_post.append(undo_post_reload_previews)
    bpy.app.handlers.undo_post.append(undo_post_reload_previews)
    bpy.app.handlers.undo_pre.append(undo_pre_end_assetbar)

    for c in classes:
        bpy.utils.register_class(c)


def unregister_search():
    bpy.app.handlers.load_post.remove(scene_load)

    for c in classes:
        bpy.utils.unregister_class(c)


# Storing history steps
# History step is a dictionary with the following keys:
# - id: uuid
# - ui_state: dict
# - search_results: list
# - search_results_orig: list
# - scroll_offset: int - this is separate since it doesn't influence when a new history step can be created

# ui_state contains search_keywords, asset_type, all search filters, common ones and also those from advanced search panels for all asset types.
# if anything in UI that influences search and is in ui_state changes, a new history step is created.
# a history step isn't created when search results land or when more pages get retrieved
# each history step has own id. This id is used to identify the history step when a new search is started. It gets sent to the client.
# After the search results land, the results are written to the respective history step.

# first let's try to setup storing of ui_state


def get_ui_state():
    """Get the current UI state."""
    ui_props = bpy.context.window_manager.blenderkitUI

    ui_state = {
        "ui_props": {
            "search_keywords": ui_props.search_keywords,
            "asset_type": ui_props.asset_type,
            "free_only": ui_props.free_only,
            "own_only": ui_props.own_only,
            "search_bookmarks": ui_props.search_bookmarks,
            "quality_limit": ui_props.quality_limit,
            "search_license": ui_props.search_license,
            "search_blender_version": ui_props.search_blender_version,
            "search_blender_version_min": ui_props.search_blender_version_min,
            "search_blender_version_max": ui_props.search_blender_version_max,
        },
        "search_props": {},
    }

    # we need to add all props manually since they are a mess now and some should not be stored.
    # model props
    common_search_props = [
        "search_category",
        "search_texture_resolution",
        "search_texture_resolution_min",
        "search_texture_resolution_max",
        "search_file_size",
        "search_file_size_min",
        "search_file_size_max",
        "search_procedural",
        "search_verification_status",
        "unrated_quality_only",
        "unrated_wh_only",
    ]

    store_model_props = [
        "search_animated",
        "search_condition",
        "search_design_year",
        "search_design_year_max",
        "search_design_year_min",
        "search_engine",
        "search_engine_other",
        "search_geometry_nodes",
        "search_polycount",
        "search_polycount_max",
        "search_polycount_min",
        "search_style",
        "search_style_other",
    ]
    store_material_props = [
        "search_style",
        "search_style_other",
    ]
    store_brush_props = []
    store_nodegroup_props = []
    store_hdr_props = [
        "true_hdr",
    ]
    store_scene_props = [
        "search_style",
    ]
    store_props = []
    # we could use match here but older blender versions have older python and don't support it
    asset_type = ui_props.asset_type
    if asset_type == "MODEL":
        store_props = store_model_props
    elif asset_type == "MATERIAL":
        store_props = store_material_props
    elif asset_type == "BRUSH":
        store_props = store_brush_props
    elif asset_type == "NODEGROUP":
        store_props = store_nodegroup_props
    elif asset_type == "HDR":
        store_props = store_hdr_props
    elif asset_type == "SCENE":
        store_props = store_scene_props
    elif asset_type == "PRINTABLE":
        store_props = store_model_props

    search_props = utils.get_search_props()

    store_props.extend(common_search_props)
    # Store all properties from each property group
    for prop_name in store_props:
        if prop_name != "rna_type":
            ui_state["search_props"][prop_name] = getattr(search_props, prop_name)

    return ui_state


def update_tab_name(active_tab):
    """Update the name of the active tab."""
    history_step = get_active_history_step()
    ui_state = history_step.get("ui_state", {})

    # Update tab name based on search or category
    search_keywords = ui_state.get("ui_props", {}).get("search_keywords", "").strip()
    # if there's author_id let's get the author's name from db of authors
    # we need to get the number after +author_id:
    author_id = re.search(r"\+author_id:(\d+)", search_keywords)
    author_name = None
    if author_id is not None:
        author_id = author_id.group(1)
        author = global_vars.BKIT_AUTHORS.get(int(author_id))
        if author:
            author_name = author.fullName

    search_category = (
        ui_state.get("search_props", {}).get("search_category", "").strip()
    )
    asset_type = ui_state.get("ui_props", {}).get("asset_type", "").strip()
    if author_name is not None:
        tab_name = author_name
    elif search_keywords:
        # Use search keywords for tab name
        tab_name = search_keywords
    elif search_category:
        # Use category name if no search keywords
        tab_name = search_category.split("/")[-1]  # Get last part of category path
    else:
        # Keep existing name if no keywords or category
        tab_name = asset_type.lower()

    # Crop name to max 9 characters
    if len(tab_name) > 9:
        tab_name = tab_name[:8] + "…"

    # Update tab name
    active_tab["name"] = tab_name

    # Update UI if asset bar exists
    asset_bar = asset_bar_op.asset_bar_operator
    if asset_bar and hasattr(asset_bar, "tab_buttons"):
        active_tab_index = global_vars.TABS["active_tab"]
        if 0 <= active_tab_index < len(asset_bar.tab_buttons):
            asset_bar.tab_buttons[active_tab_index].text = tab_name
            # Force redraw of the region
            if asset_bar.area:
                asset_bar.area.tag_redraw()

    return history_step


# now let's create a history function that creates a new history step
def create_history_step(active_tab):
    """Create a new history step and update tab name."""
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_state = get_ui_state()
    history_step = {
        "id": str(uuid.uuid4()),
        "ui_state": ui_state,
        "scroll_offset": ui_props.scroll_offset,
    }

    # Delete any future history steps
    if active_tab["history_index"] < len(active_tab["history"]) - 1:
        # Remove future steps from global history steps dict first
        for step in active_tab["history"][active_tab["history_index"] + 1 :]:
            global_vars.DATA["history steps"].pop(step["id"], None)
        # Then truncate the tab's history list
        active_tab["history"] = active_tab["history"][: active_tab["history_index"] + 1]

    active_tab["history"].append(history_step)
    active_tab["history_index"] = len(active_tab["history"]) - 1

    # Add this history step to the global history steps dictionary
    global_vars.DATA["history steps"][history_step["id"]] = history_step
    print(f"Created history step {history_step['id']}")
    reports.add_report("Created new search history step", 1, "INFO")

    # Update tab name and history button visibility
    update_tab_name(active_tab)

    # Update history button visibility if asset bar exists
    # if history length is 1, hide the back button

    asset_bar = asset_bar_op.asset_bar_operator
    if asset_bar and hasattr(asset_bar, "history_back_button"):
        asset_bar.history_back_button.visible = active_tab["history_index"] > 0
        asset_bar.history_forward_button.visible = (
            False  # forward is never possible if we create new history step
        )
        asset_bar.update_tab_icons()

    return history_step


def get_history_step(history_step_id):
    return global_vars.DATA["history steps"].get(history_step_id)


def get_history_steps():
    return global_vars.DATA["history steps"]


def get_active_history_step():
    """Get the currently active history step from the active tab."""
    active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
    # if there's no history step, create one
    if len(active_tab["history"]) == 0:
        history_step = create_history_step(active_tab)
    else:
        history_step = active_tab["history"][active_tab["history_index"]]
    return history_step


def get_search_results() -> list[dict]:
    """Get search results from the active history step."""
    history_step = get_active_history_step()
    return history_step.get("search_results", [])


def get_active_tab():
    """Get the active tab."""
    return global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
