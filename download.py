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
import logging
import os
import shutil
import traceback

from . import (
    append_link,
    daemon_lib,
    global_vars,
    paths,
    ratings_utils,
    reports,
    resolutions,
    search,
    timer,
    ui_panels,
    utils,
)
from .daemon import daemon_tasks


bk_logger = logging.getLogger(__name__)

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)


download_tasks = {}


def check_missing():
    """Checks for missing files, and possibly starts re-download of these into the scene"""
    # missing libs:
    # TODO: put these into a panel and let the user decide if these should be downloaded.
    missing = []
    for l in bpy.data.libraries:
        fp = l.filepath
        if fp.startswith("//"):
            fp = bpy.path.abspath(fp)
        if not os.path.exists(fp) and l.get("asset_data") is not None:
            missing.append(l)

    for l in missing:
        asset_data = l["asset_data"]

        downloaded = check_existing(asset_data, resolution=asset_data.get("resolution"))
        if downloaded:
            try:
                l.reload()
            except:
                download(l["asset_data"], redownload=True)
        else:
            download(l["asset_data"], redownload=True)


def check_unused():
    """Find assets that have been deleted from scene but their library is still present."""
    # this is obviously broken. Blender should take care of the extra data automaticlaly
    # first clean up collections
    for c in bpy.data.collections:
        if len(c.all_objects) == 0 and c.get("is_blenderkit_asset"):
            bpy.data.collections.remove(c)
    return
    used_libs = []
    for ob in bpy.data.objects:
        if (
            ob.instance_collection is not None
            and ob.instance_collection.library is not None
        ):
            # used_libs[ob.instance_collection.name] = True
            if ob.instance_collection.library not in used_libs:
                used_libs.append(ob.instance_collection.library)

        for ps in ob.particle_systems:
            set = ps.settings
            if (
                ps.settings.render_type == "GROUP"
                and ps.settings.instance_collection is not None
                and ps.settings.instance_collection.library not in used_libs
            ):
                used_libs.append(ps.settings.instance_collection)

    for l in bpy.data.libraries:
        if l not in used_libs and l.getn("asset_data"):
            bk_logger.info(f"attempt to remove this library: {l.filepath}")
            # have to unlink all groups, since the file is a 'user' even if the groups aren't used at all...
            for user_id in l.users_id:
                if type(user_id) == bpy.types.Collection:
                    bpy.data.collections.remove(user_id)
            l.user_clear()


@persistent
def scene_save(context):
    """Do cleanup of blenderkit props and send a message to the server about assets used."""
    # TODO this can be optimized by merging these 2 functions, since both iterate over all objects.
    if bpy.app.background:
        return
    check_unused()
    report_data = get_asset_usages()
    if report_data != {}:
        daemon_lib.report_usages(report_data)


@persistent
def scene_load(context):
    """Restart broken downloads on scene load."""
    check_missing()
    # global download_threads
    # download_threads = []

    # commenting this out - old restore broken download on scene start. Might come back if downloads get recorded in scene
    # reset_asset_ids = {}
    # reset_obs = {}
    # for ob in bpy.context.scene.collection.objects:
    #     if ob.name[:12] == 'downloading ':
    #         obn = ob.name
    #
    #         asset_data = ob['asset_data']
    #
    #         # obn.replace('#', '')
    #         # if asset_data['id'] not in reset_asset_ids:
    #
    #         if reset_obs.get(asset_data['id']) is None:
    #             reset_obs[asset_data['id']] = [obn]
    #             reset_asset_ids[asset_data['id']] = asset_data
    #         else:
    #             reset_obs[asset_data['id']].append(obn)
    # for asset_id in reset_asset_ids:
    #     asset_data = reset_asset_ids[asset_id]
    #     done = False
    #     if check_existing(asset_data, resolution = should be here):
    #         for obname in reset_obs[asset_id]:
    #             downloader = s.collection.objects[obname]
    #             done = try_finished_append(asset_data,
    #                                        model_location=downloader.location,
    #                                        model_rotation=downloader.rotation_euler)
    #
    #     if not done:
    #         downloading = check_downloading(asset_data)
    #         if not downloading:
    #             download(asset_data, downloaders=reset_obs[asset_id], delete=True)

    # check for group users that have been deleted, remove the groups /files from the file...
    # TODO scenes fixing part... download the assets not present on drive,
    # and erase from scene linked files that aren't used in the scene.


def get_asset_usages():
    """Report the usage of assets to the server."""
    sid = utils.get_scene_id()
    assets = {}
    asset_obs = []
    scene = bpy.context.scene
    asset_usages = {}

    for ob in scene.collection.objects:
        if ob.get("asset_data") != None:
            asset_obs.append(ob)

    for ob in asset_obs:
        asset_data = ob["asset_data"]
        abid = asset_data["assetBaseId"]

        if assets.get(abid) is None:
            asset_usages[abid] = {"count": 1}
            assets[abid] = asset_data
        else:
            asset_usages[abid]["count"] += 1

    # brushes
    for b in bpy.data.brushes:
        if b.get("asset_data") != None:
            abid = b["asset_data"]["assetBaseId"]
            asset_usages[abid] = {"count": 1}
            assets[abid] = b["asset_data"]
    # materials
    for ob in scene.collection.objects:
        for ms in ob.material_slots:
            m = ms.material

            if m is not None and m.get("asset_data") is not None:
                abid = m["asset_data"]["assetBaseId"]
                if assets.get(abid) is None:
                    asset_usages[abid] = {"count": 1}
                    assets[abid] = m["asset_data"]
                else:
                    asset_usages[abid]["count"] += 1

    assets_list = []
    assets_reported = scene.get("assets reported", {})

    new_assets_count = 0
    for k in asset_usages.keys():
        if k not in assets_reported.keys():
            data = asset_usages[k]
            list_item = {
                "asset": k,
                "usageCount": data["count"],
                "proximitySet": data.get("proximity", []),
            }
            assets_list.append(list_item)
            new_assets_count += 1
        if k not in assets_reported.keys():
            assets_reported[k] = True

    scene["assets reported"] = assets_reported

    if new_assets_count == 0:
        bk_logger.debug("no new assets were added")
        return {}
    usage_report = {"scene": sid, "reportType": "save", "assetusageSet": assets_list}

    au = scene.get("assets used", {})
    ad = scene.get("assets deleted", {})

    ak = assets.keys()
    for k in au.keys():
        if k not in ak:
            ad[k] = au[k]
        else:
            if k in ad:
                ad.pop(k)

    # scene['assets used'] = {}
    for k in ak:  # rewrite assets used.
        scene["assets used"][k] = assets[k]

    return usage_report


def udpate_asset_data_in_dicts(asset_data):
    """
    updates asset data in all relevant dictionaries, after a threaded download task \
    - where the urls were retrieved, and now they can be reused
    Parameters
    ----------
    asset_data - data coming back from thread, thus containing also download urls
    """
    scene = bpy.context.scene
    scene["assets used"] = scene.get("assets used", {})
    scene["assets used"][asset_data["assetBaseId"]] = asset_data.copy()
    sr = global_vars.DATA["search results"]
    if not sr:
        return
    for i, r in enumerate(sr):
        if r["assetBaseId"] == asset_data["assetBaseId"]:
            for f in asset_data["files"]:
                if f.get("url"):
                    for f1 in r["files"]:
                        if f1["fileType"] == f["fileType"]:
                            f1["url"] = f["url"]


def append_asset(asset_data, **kwargs):  # downloaders=[], location=None,
    """Link asset to the scene."""
    file_names = kwargs.get("file_paths")
    if file_names is None:
        file_names = paths.get_download_filepaths(asset_data, kwargs["resolution"])
    props = None
    #####
    # how to do particle  drop:
    # link the group we are interested in( there are more groups in File!!!! , have to get the correct one!)
    s = bpy.context.scene
    wm = bpy.context.window_manager
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences

    if user_preferences.api_key == "":
        user_preferences.asset_counter += 1

    if asset_data["assetType"] == "scene":
        sprops = wm.blenderkit_scene

        scene = append_link.append_scene(
            file_names[0], link=sprops.append_link == "LINK", fake_user=False
        )
        if scene is not None:
            props = scene.blenderkit
            asset_main = scene
            if sprops.switch_after_append:
                bpy.context.window_manager.windows[0].scene = scene

    if asset_data["assetType"] == "hdr":
        hdr = append_link.load_HDR(file_name=file_names[0], name=asset_data["name"])
        props = hdr.blenderkit
        asset_main = hdr

    if asset_data["assetType"] == "model":
        downloaders = kwargs.get("downloaders")
        sprops = wm.blenderkit_models
        # TODO this is here because combinations of linking objects or appending groups are rather not-usefull
        if sprops.append_method == "LINK_COLLECTION":
            sprops.append_link = "LINK"
            sprops.import_as = "GROUP"
        else:
            sprops.append_link = "APPEND"
            sprops.import_as = "INDIVIDUAL"

        # copy for override
        al = sprops.append_link
        # set consistency for objects already in scene, otherwise this literally breaks blender :)
        ain, resolution = asset_in_scene(asset_data)
        # this is commented out since it already happens in start_download function.
        # if resolution:
        #     kwargs['resolution'] = resolution
        # override based on history
        if ain is not False:
            if ain == "LINKED":
                al = "LINK"
            else:
                al = "APPEND"
                if asset_data["assetType"] == "model":
                    source_parent = get_asset_in_scene(asset_data)
                    if source_parent:
                        asset_main, new_obs = duplicate_asset(
                            source=source_parent, **kwargs
                        )
                        asset_main.location = kwargs["model_location"]
                        asset_main.rotation_euler = kwargs["model_rotation"]
                        # this is a case where asset is already in scene and should be duplicated instead.
                        # there is a big chance that the duplication wouldn't work perfectly(hidden or unselectable objects)
                        # so here we need to check and return if there was success
                        # also, if it was successful, no other operations are needed , basically all asset data is already ready from the original asset
                        if new_obs:
                            # update here assets rated/used because there might be new download urls?
                            udpate_asset_data_in_dicts(asset_data)
                            bpy.ops.ed.undo_push(
                                "INVOKE_REGION_WIN",
                                message="add %s to scene" % asset_data["name"],
                            )

                            return

        # first get conditions for append link
        link = al == "LINK"
        # then append link
        if downloaders:
            for downloader in downloaders:
                # this cares for adding particle systems directly to target mesh, but I had to block it now,
                # because of the sluggishnes of it. Possibly re-enable when it's possible to do this faster?
                if (
                    "particle_plants" in asset_data["tags"]
                    and kwargs["target_object"] != ""
                ):
                    append_link.append_particle_system(
                        file_names[-1],
                        target_object=kwargs["target_object"],
                        rotation=downloader["rotation"],
                        link=False,
                        name=asset_data["name"],
                    )
                    return

                if link:
                    asset_main, new_obs = append_link.link_collection(
                        file_names[-1],
                        location=downloader["location"],
                        rotation=downloader["rotation"],
                        link=link,
                        name=asset_data["name"],
                        parent=kwargs.get("parent"),
                    )

                else:
                    asset_main, new_obs = append_link.append_objects(
                        file_names[-1],
                        location=downloader["location"],
                        rotation=downloader["rotation"],
                        link=link,
                        name=asset_data["name"],
                        parent=kwargs.get("parent"),
                    )
                if asset_main.type == "EMPTY" and link:
                    bmin = asset_data["bbox_min"]
                    bmax = asset_data["bbox_max"]
                    size_min = min(
                        1.0,
                        (bmax[0] - bmin[0] + bmax[1] - bmin[1] + bmax[2] - bmin[2]) / 3,
                    )
                    asset_main.empty_display_size = size_min

        elif kwargs.get("model_location") is not None:
            if link:
                asset_main, new_obs = append_link.link_collection(
                    file_names[-1],
                    location=kwargs["model_location"],
                    rotation=kwargs["model_rotation"],
                    link=link,
                    name=asset_data["name"],
                    parent=kwargs.get("parent"),
                )
            else:
                asset_main, new_obs = append_link.append_objects(
                    file_names[-1],
                    location=kwargs["model_location"],
                    rotation=kwargs["model_rotation"],
                    link=link,
                    name=asset_data["name"],
                    parent=kwargs.get("parent"),
                )

            # scale Empty for assets, so they don't clutter the scene.
            if asset_main.type == "EMPTY" and link:
                bmin = asset_data["bbox_min"]
                bmax = asset_data["bbox_max"]
                size_min = min(
                    1.0, (bmax[0] - bmin[0] + bmax[1] - bmin[1] + bmax[2] - bmin[2]) / 3
                )
                asset_main.empty_display_size = size_min

        if link:
            group = asset_main.instance_collection

            lib = group.library
            lib["asset_data"] = asset_data

    elif asset_data["assetType"] == "brush":
        # TODO if already in scene, should avoid reappending.
        inscene = False
        for b in bpy.data.brushes:
            if b.blenderkit.id == asset_data["id"]:
                inscene = True
                brush = b
                break
        if not inscene:
            brush = append_link.append_brush(
                file_names[-1], link=False, fake_user=False
            )

            thumbnail_name = asset_data["thumbnail"].split(os.sep)[-1]
            tempdir = paths.get_temp_dir("brush_search")
            thumbpath = os.path.join(tempdir, thumbnail_name)
            asset_thumbs_dir = paths.get_download_dirs("brush")[0]
            asset_thumb_path = os.path.join(asset_thumbs_dir, thumbnail_name)
            shutil.copy(thumbpath, asset_thumb_path)
            brush.icon_filepath = asset_thumb_path

        if bpy.context.view_layer.objects.active.mode == "SCULPT":
            bpy.context.tool_settings.sculpt.brush = brush
        elif (
            bpy.context.view_layer.objects.active.mode == "TEXTURE_PAINT"
        ):  # could be just else, but for future possible more types...
            bpy.context.tool_settings.image_paint.brush = brush
        # TODO set brush by by asset data(user can be downloading while switching modes.)

        # bpy.context.tool_settings.image_paint.brush = brush
        props = brush.blenderkit
        asset_main = brush

    elif asset_data["assetType"] == "material":
        inscene = False
        sprops = wm.blenderkit_mat

        for m in bpy.data.materials:
            if m.blenderkit.id == asset_data["id"]:
                inscene = True
                material = m
                break
        if not inscene:
            link = sprops.append_method == "LINK"
            material = append_link.append_material(
                file_names[-1], matname=asset_data["name"], link=link, fake_user=False
            )
        target_object = bpy.data.objects[kwargs["target_object"]]

        if len(target_object.material_slots) == 0:
            target_object.data.materials.append(material)
        else:
            target_object.material_slots[
                kwargs["material_target_slot"]
            ].material = material

        asset_main = material

    asset_data["resolution"] = kwargs["resolution"]
    udpate_asset_data_in_dicts(asset_data)
    update_asset_metadata(asset_main, asset_data)

    bpy.ops.ed.undo_push(
        "INVOKE_REGION_WIN", message="add %s to scene" % asset_data["name"]
    )
    # moving reporting to on save.
    # report_use_success(asset_data['id'])


def update_asset_metadata(asset_main, asset_data):
    """Update downloaded asset_data on the asset_main placed in the scene."""
    asset_main.blenderkit.asset_base_id = asset_data["assetBaseId"]
    asset_main.blenderkit.id = asset_data["id"]
    asset_main.blenderkit.description = asset_data["description"]
    asset_main.blenderkit.tags = utils.list2string(asset_data["tags"])
    # BUG #554: categories needs update, but are not in asset_data
    asset_main[
        "asset_data"
    ] = asset_data  # TODO remove this??? should write to blenderkit Props?


def replace_resolution_linked(file_paths, asset_data):
    # replace one asset resolution for another.
    # this is the much simpler case
    #  - find the library,
    #  - replace the path and name of the library, reload.
    file_name = os.path.basename(file_paths[-1])

    for l in bpy.data.libraries:
        if not l.get("asset_data"):
            continue
        if not l["asset_data"]["assetBaseId"] == asset_data["assetBaseId"]:
            continue

        bk_logger.debug("try to re-link library")

        if not os.path.isfile(file_paths[-1]):
            bk_logger.debug("library file doesnt exist")
            break
        l.filepath = os.path.join(os.path.dirname(l.filepath), file_name)
        l.name = file_name
        udpate_asset_data_in_dicts(asset_data)


def replace_resolution_appended(file_paths, asset_data, resolution):
    # In this case the texture paths need to be replaced.
    # Find the file path pattern that is present in texture paths
    # replace the pattern with the new one.
    file_name = os.path.basename(file_paths[-1])

    new_filename_pattern = os.path.splitext(file_name)[0]
    all_patterns = []
    for suff in paths.resolution_suffix.values():
        pattern = f"{asset_data['id']}{os.sep}textures{suff}{os.sep}"
        all_patterns.append(pattern)
    new_pattern = f"{asset_data['id']}{os.sep}textures{paths.resolution_suffix[resolution]}{os.sep}"

    # replace the pattern with the new one.
    for i in bpy.data.images:
        for old_pattern in all_patterns:
            if i.filepath.find(old_pattern) > -1:
                fp = i.filepath.replace(old_pattern, new_pattern)
                fpabs = bpy.path.abspath(fp)
                if not os.path.exists(fpabs):
                    # this currently handles .png's that have been swapped to .jpg's during resolution generation process.
                    # should probably also handle .exr's and similar others.
                    # bk_logger.debug('need to find a replacement')
                    base, ext = os.path.splitext(fp)
                    if resolution == "blend" and i.get("original_extension"):
                        fp = base + i.get("original_extension")
                    elif ext in (".png", ".PNG"):
                        fp = base + ".jpg"
                i.filepath = fp
                i.filepath_raw = fp  # bpy.path.abspath(fp)
                for pf in i.packed_files:
                    pf.filepath = fp
                i.reload()
    udpate_asset_data_in_dicts(asset_data)


# TODO: keep this until we check resolution replacement and other features from this one are supported in daemon.
# @bpy.app.handlers.persistent
# def download_timer():
#     # TODO might get moved to handle all blenderkit stuff, not to slow down.
#     '''
#     check for running and finished downloads.
#     Running downloads get checked for progress which is passed to UI.
#     Finished downloads are processed and linked/appended to scene.
#      '''
#     global download_threads
#     # utils.p('start download timer')
#
#     # bk_logger.debug('timer download')
#     print(len(download_threads))
#     if len(download_threads) == 0:
#         # utils.p('end download timer')
#
#         return 2
#     s = bpy.context.scene
#
#     for threaddata in download_threads:
#         t = threaddata[0]
#         asset_data = threaddata[1]
#         tcom = threaddata[2]
#
#         progress_bars = []
#         downloaders = []
#
#         if t.is_alive():  # set downloader size
#             sr = global_vars.DATA.get('search results')
#             if sr is not None:
#                 for r in sr:
#                     if asset_data['id'] == r['id']:
#                         r['downloaded'] = 0.5  # tcom.progress
#         if not t.is_alive():
#             if tcom.error:
#                 sprops = utils.get_search_props()
#                 sprops.report = tcom.report
#                 download_threads.remove(threaddata)
#                 # utils.p('end download timer')
#                 return
#
#             file_paths = paths.get_download_filepaths(asset_data, tcom.passargs['resolution'])
#             if len(file_paths) == 0:
#                 bk_logger.debug('library names not found in asset data after download')
#                 download_threads.remove(threaddata)
#                 break
#
#             wm = bpy.context.window_manager
#
#             at = asset_data['assetType']
#             if ((bpy.context.mode == 'OBJECT' and \
#                  (at == 'model' or at == 'material'))) \
#                     or ((at == 'brush') \
#                         and wm.get('appendable') == True) or at == 'scene' or at == 'hdr':
#                 # don't do this stuff in editmode and other modes, just wait...
#                 download_threads.remove(threaddata)
#
#                 # duplicate file if the global and subdir are used in prefs
#                 if len(file_paths) == 2:  # todo this should try to check if both files exist and are ok.
#                     utils.copy_asset(file_paths[0], file_paths[1])
#                     # shutil.copyfile(file_paths[0], file_paths[1])
#
#                 bk_logger.debug('appending asset')
#                 # progress bars:
#
#                 # we need to check if mouse isn't down, which means an operator can be running.
#                 # Especially for sculpt mode, where appending a brush during a sculpt stroke causes crasehes
#                 #
#
#                 if tcom.passargs.get('redownload'):
#                     # handle lost libraries here:
#                     for l in bpy.data.libraries:
#                         if l.get('asset_data') is not None and l['asset_data']['id'] == asset_data['id']:
#                             l.filepath = file_paths[-1]
#                             l.reload()
#
#                 if tcom.passargs.get('replace_resolution'):
#                     # try to relink
#                     # HDRs are always swapped, so their swapping is handled without the replace_resolution option
#
#                     ain, resolution = asset_in_scene(asset_data)
#
#                     if ain == 'LINKED':
#                         replace_resolution_linked(file_paths, asset_data)
#
#
#                     elif ain == 'APPENDED':
#                         replace_resolution_appended(file_paths, asset_data, tcom.passargs['resolution'])
#
#
#
#                 else:
#                     done = try_finished_append(asset_data, **tcom.passargs)
#                     if not done:
#                         at = asset_data['assetType']
#                         tcom.passargs['retry_counter'] = tcom.passargs.get('retry_counter', 0) + 1
#                         download(asset_data, **tcom.passargs)
#
#                     if global_vars.DATA['search results'] is not None and done:
#                         for sres in global_vars.DATA['search results']:
#                             if asset_data['id'] == sres['id']:
#                                 sres['downloaded'] = 100
#
#                 bk_logger.debug('finished download thread')
#     # utils.p('end download timer')
#
#     return .5


def handle_download_task(task: daemon_tasks.Task):
    """Handle incoming task information.
    Update progress. Print messages. Fire post-download functions.
    """
    global download_tasks
    if task.status == "finished":
        # we still write progress since sometimes the progress bars wouldn't end on 100%
        download_write_progress(task.task_id, task)
        # try to parse, in some states task gets returned to be pending (e.g. in editmode)
        done = download_post(task)
        if not done:
            timer.pending_tasks.append(task)
    elif task.status == "error":
        reports.add_report(task.message, 15, "ERROR")
        download_tasks.pop(task.task_id)
    else:
        download_write_progress(task.task_id, task)


def clear_downloads():
    """Cancel all downloads."""
    global download_tasks
    download_tasks.clear()


def download_write_progress(task_id, task):
    """writes progress from daemon_lib reports to addon tasks list"""
    global download_tasks
    task_addon = download_tasks.get(task.task_id)
    if task_addon is None:
        print("couldnt write progress", task.progress)
        return
    task_addon["progress"] = task.progress
    task_addon["text"] = task.message

    # go through search results to write progress to display progress bars
    sr = global_vars.DATA.get("search results")
    if sr is not None:
        for r in sr:
            if task.data["asset_data"]["id"] == r["id"]:
                r["downloaded"] = task.progress


# TODO might get moved to handle all blenderkit stuff, not to slow down.
def download_post(task: daemon_tasks.Task):
    """
    Check for running and finished downloads.
    Running downloads get checked for progress which is passed to UI.
    Finished downloads are processed and linked/appended to scene.
    Finished downloads can become pending tasks, if Blender isn't ready to append the files.
    """
    global download_tasks

    orig_task = download_tasks.get(task.task_id)
    if orig_task is None:
        return

    done = False

    file_paths = task.result.get("file_paths", [])
    if file_paths == []:
        bk_logger.debug("library names not found in asset data after download")
        done = True

    wm = bpy.context.window_manager
    at = task.data["asset_data"]["assetType"]
    if not (
        ((bpy.context.mode == "OBJECT" and (at == "model" or at == "material")))
        or ((at == "brush") and wm.get("appendable") == True)
        or at == "scene"
        or at == "hdr"
    ):
        return done
    if (
        ((bpy.context.mode == "OBJECT" and (at == "model" or at == "material")))
        or ((at == "brush") and wm.get("appendable") == True)
        or at == "scene"
        or at == "hdr"
    ):
        # don't do this stuff in editmode and other modes, just wait...
        # we don't remove the task before it's actually possible to remove it.

        # duplicate file if the global and subdir are used in prefs
        if (
            len(file_paths) == 2
        ):  # todo this should try to check if both files exist and are ok.
            utils.copy_asset(file_paths[0], file_paths[1])
            # shutil.copyfile(file_paths[0], file_paths[1])

        bk_logger.debug("appending asset")
        # progress bars:

        # we need to check if mouse isn't down, which means an operator can be running.
        # Especially for sculpt mode, where appending a brush during a sculpt stroke causes crasehes
        #
        # TODO use redownload in data, this is used for downloading/ copying missing libraries.
        if task.data.get("redownload"):
            # handle lost libraries here:
            for l in bpy.data.libraries:
                if (
                    l.get("asset_data") is not None
                    and l["asset_data"]["id"] == task.data["asset_data"]["id"]
                ):
                    l.filepath = file_paths[-1]
                    l.reload()

        if task.data.get("replace_resolution"):
            # try to relink
            # HDRs are always swapped, so their swapping is handled without the replace_resolution option
            ain, _ = asset_in_scene(task.data["asset_data"])
            if ain == "LINKED":
                replace_resolution_linked(file_paths, task.data["asset_data"])
            elif ain == "APPENDED":
                replace_resolution_appended(
                    file_paths, task.data["asset_data"], task.data["resolution"]
                )
            done = True
        else:
            orig_task.update(task.data)
            done = try_finished_append(file_paths=file_paths, **task.data)
            # if not done:
            # TODO add back re-download capability for deamon - used for lost libraries
            # tcom.passargs['retry_counter'] = tcom.passargs.get('retry_counter', 0) + 1
            # download(asset_data, **tcom.passargs)
            #

        bk_logger.debug("finished download thread")
    # utils.p('end download timer')
    if done:
        download_tasks.pop(task.task_id)
    return done


def download(asset_data, **kwargs):
    """Init download data and request task from daemon"""

    if kwargs.get("retry_counter", 0) > 3:
        sprops = utils.get_search_props()
        report = f"Maximum retries exceeded for {asset_data['name']}"
        sprops.report = report
        reports.add_report(report, 5, "ERROR")

        bk_logger.debug(sprops.report)
        return

    # incoming data can be either directly dict from python, or blender id property
    # (recovering failed downloads on reload)
    if type(asset_data) == dict:
        asset_data = copy.deepcopy(asset_data)
    else:
        asset_data = asset_data.to_dict()
    data = {
        "asset_data": asset_data,
        "PREFS": utils.get_prefs_dir(),
        "progress": 0,
        "text": f'downloading {asset_data["name"]}',
    }
    for arg, value in kwargs.items():
        data[arg] = value
    data["PREFS"]["scene_id"] = utils.get_scene_id()
    data["download_dirs"] = paths.get_download_dirs(asset_data["assetType"])
    if "downloaders" in kwargs:
        data["downloaders"] = kwargs["downloaders"]
    response = daemon_lib.download_asset(data)

    download_tasks[response["task_id"]] = data


def check_downloading(asset_data, **kwargs) -> bool:
    """Check if the asset is already being downloaded.
    If not, return False.
    If yes, just make a progress bar with downloader object and return True.
    """
    global download_tasks
    downloading = False

    for _, task in download_tasks.items():
        p_asset_data = task["asset_data"]
        if p_asset_data["id"] == asset_data["id"]:
            at = asset_data["assetType"]
            if at in ("model", "material"):
                downloader = {
                    "location": kwargs["model_location"],
                    "rotation": kwargs["model_rotation"],
                }
                task["downloaders"].append(downloader)
            downloading = True

    return downloading


def check_existing(asset_data, resolution="blend", can_return_others=False):
    """Check if the object exists on the hard drive."""
    if asset_data.get("files") == None:
        return False  # this is because of some very odl files where asset data had no files structure.

    file_names = paths.get_download_filepaths(
        asset_data, resolution, can_return_others=can_return_others
    )
    if len(file_names) == 0:
        return False

    if len(file_names) == 2:
        # TODO this should check also for failed or running downloads.
        # If download is running, assign just the running thread. if download isn't running but the file is wrong size,
        #  delete file and restart download (or continue downoad? if possible.)
        if os.path.isfile(file_names[0]):  # and not os.path.isfile(file_names[1])
            utils.copy_asset(file_names[0], file_names[1])
        elif not os.path.isfile(file_names[0]) and os.path.isfile(
            file_names[1]
        ):  # only in case of changed settings or deleted/moved global dict.
            utils.copy_asset(file_names[1], file_names[0])

    if os.path.isfile(file_names[0]):
        return True

    return False


def try_finished_append(asset_data, **kwargs):  # location=None, material_target=None):
    """Try to append asset, if not successfully delete source files.
    This means probably wrong download, so download should restart
    """
    file_names = kwargs.get("file_paths")
    if file_names is None:
        file_names = paths.get_download_filepaths(asset_data, kwargs["resolution"])

    bk_logger.debug("try to append already existing asset")
    if len(file_names) == 0:
        return False

    if not os.path.isfile(file_names[-1]):
        return False

    kwargs["name"] = asset_data["name"]
    try:
        append_asset(asset_data, **kwargs)
        return True
    except Exception as e:
        # TODO: this should distinguis if the appending failed (wrong file)
        # or something else happened(shouldn't delete the files)
        traceback.print_exc(limit=20)
        reports.add_report(f"Append failed: {e}", 15, "ERROR")
        for f in file_names:
            try:
                os.remove(f)
            except Exception as e:
                bk_logger.error(f"{e}")
    return False


def get_asset_in_scene(asset_data):
    """tries to find an appended copy of particular asset and duplicate it - so it doesn't have to be appended again."""
    scene = bpy.context.scene
    for ob in bpy.context.scene.objects:
        ad1 = ob.get("asset_data")
        if not ad1:
            continue
        if ad1.get("assetBaseId") == asset_data["assetBaseId"]:
            return ob
    return None


def check_all_visible(obs):
    """checks all objects are visible, so they can be manipulated/copied."""
    for ob in obs:
        if not ob.visible_get():
            return False
    return True


def check_selectible(obs):
    """checks if all objects can be selected and selects them if possible.
    this isn't only select_hide, but all possible combinations of collections e.t.c. so hard to check otherwise.
    """
    for ob in obs:
        ob.select_set(True)
        if not ob.select_get():
            return False
    return True


def duplicate_asset(source, **kwargs):
    """
    Duplicate asset when it's already appended in the scene,
    so that blender's append doesn't create duplicated data.
    """
    bk_logger.debug("duplicate asset instead")
    # we need to save selection
    sel = utils.selection_get()
    bpy.ops.object.select_all(action="DESELECT")

    # check visibility
    obs = utils.get_hierarchy(source)
    if not check_all_visible(obs):
        return None
    # check selectability and select in one run
    if not check_selectible(obs):
        return None

    # duplicate the asset objects
    bpy.ops.object.duplicate(linked=True)

    nobs = bpy.context.selected_objects[:]
    # get asset main object
    for ob in nobs:
        if ob.parent not in nobs:
            asset_main = ob
            break

    # in case of replacement,there might be a paarent relationship that can be restored
    if kwargs.get("parent"):
        parent = bpy.data.objects[kwargs["parent"]]
        asset_main.parent = (
            parent  # even if parent is None this is ok without if condition
        )
    else:
        asset_main.parent = None
    # restore original selection
    utils.selection_set(sel)
    return asset_main, nobs


def asset_in_scene(asset_data):
    """checks if the asset is already in scene. If yes, modifies asset data so the asset can be reached again."""
    scene = bpy.context.scene
    au = scene.get("assets used", {})

    id = asset_data["assetBaseId"]
    if id in au.keys():
        ad = au[id]
        if ad.get("files"):
            for fi in ad["files"]:
                if fi.get("file_name") != None:
                    for fi1 in asset_data["files"]:
                        if fi["fileType"] == fi1["fileType"]:
                            fi1["file_name"] = fi["file_name"]
                            fi1["url"] = fi["url"]

                            # browse all collections since linked collections can have same name.
                            if asset_data["assetType"] == "MODEL":
                                for c in bpy.data.collections:
                                    if c.name == ad["name"]:
                                        # there can also be more linked collections with same name, we need to check id.
                                        if (
                                            c.library
                                            and c.library.get("asset_data")
                                            and c.library["asset_data"]["assetBaseId"]
                                            == id
                                        ):
                                            bk_logger.info("asset linked")
                                            return "LINKED", ad.get("resolution")
                            elif asset_data["assetType"] == "MATERIAL":
                                for m in bpy.data.materials:
                                    if not m.get("asset_data"):
                                        continue
                                    if (
                                        m["asset_data"]["assetBaseId"]
                                        == asset_data["assetBaseId"]
                                        and bpy.context.active_object.active_material.library
                                    ):
                                        return "LINKED", ad.get("resolution")

                            bk_logger.info("asset appended")
                            return "APPENDED", ad.get("resolution")
    return False, None


def start_download(asset_data, **kwargs) -> bool:
    """Check if file isn't downloading or is not in scene, then start new download.
    Return true if new download was started.
    """
    # first check if the asset is already in scene. We can use that asset without checking with server
    ain, _ = asset_in_scene(asset_data)
    # quota_ok = ain is not False
    # if resolution:
    #     kwargs['resolution'] = resolution
    # otherwise, check on server

    if check_downloading(asset_data, **kwargs):
        return False

    if ain and not kwargs.get("replace_resolution"):
        # this goes to appending asset - where it should duplicate the original asset already in scene.
        append_ok = try_finished_append(asset_data, **kwargs)
        if append_ok:
            return False

    if asset_data["assetType"] in ("model", "material"):
        downloader = {
            "location": kwargs["model_location"],
            "rotation": kwargs["model_rotation"],
        }
        download(asset_data, downloaders=[downloader], **kwargs)
        return True

    download(asset_data, **kwargs)
    return True


asset_types = (
    ("MODEL", "Model", "set of objects"),
    ("SCENE", "Scene", "scene"),
    ("HDR", "Hdr", "hdr"),
    ("MATERIAL", "Material", "any .blend Material"),
    ("TEXTURE", "Texture", "a texture, or texture set"),
    ("BRUSH", "Brush", "brush, can be any type of blender brush"),
    ("ADDON", "Addon", "addnon"),
)


class BlenderkitKillDownloadOperator(bpy.types.Operator):
    """Kill a download"""

    bl_idname = "scene.blenderkit_download_kill"
    bl_label = "BlenderKit Kill Asset Download"
    bl_options = {"REGISTER", "INTERNAL"}

    task_index: StringProperty(
        name="Task ID", description="ID of the task to kill", default=""
    )

    def execute(self, context):
        global download_tasks
        download_tasks.pop(self.task_index)
        daemon_lib.kill_download(self.task_index)
        return {"FINISHED"}


def available_resolutions_callback(self, context):
    """Checks active asset for available resolutions and offers only those available
    TODO: this currently returns always the same list of resolutions, make it actually work
    """

    pat_items = (
        ("512", "512", "", 1),
        ("1024", "1024", "", 2),
        ("2048", "2048", "", 3),
        ("4096", "4096", "", 4),
        ("8192", "8192", "", 5),
    )
    items = []
    for item in pat_items:
        if int(self.max_resolution) >= int(item[0]):
            items.append(item)
    items.append(("ORIGINAL", "Original", "", 6))
    return items


def has_asset_files(asset_data):
    """Check if asset has files."""
    for f in asset_data["files"]:
        if f["fileType"] == "blend":
            return True
    return False


class BlenderkitDownloadOperator(bpy.types.Operator):
    """Download and link asset to scene. Only link if asset already available locally"""

    bl_idname = "scene.blenderkit_download"
    bl_label = "Download"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    # asset_type: EnumProperty(
    #     name="Type",
    #     items=asset_types,
    #     description="Type of download",
    #     default="MODEL",
    # )
    asset_index: IntProperty(
        name="Asset Index", description="asset index in search results", default=-1
    )

    asset_base_id: StringProperty(
        name="Asset base Id",
        description="Asset base id, used instead of search result index",
        default="",
    )

    target_object: StringProperty(
        name="Target Object",
        description="Material or object target for replacement",
        default="",
    )

    material_target_slot: IntProperty(
        name="Asset Index", description="asset index in search results", default=0
    )
    model_location: FloatVectorProperty(name="Asset Location", default=(0, 0, 0))
    model_rotation: FloatVectorProperty(name="Asset Rotation", default=(0, 0, 0))

    replace: BoolProperty(
        name="Replace",
        description="replace selection with the asset",
        default=False,
        options={"SKIP_SAVE"},
    )

    replace_resolution: BoolProperty(
        name="Replace resolution",
        description="replace resolution of the active asset",
        default=False,
        options={"SKIP_SAVE"},
    )

    invoke_resolution: BoolProperty(
        name="Replace resolution popup",
        description="pop up to ask which resolution to download",
        default=False,
        options={"SKIP_SAVE"},
    )

    invoke_scene_settings: BoolProperty(
        name="Scene import settings popup",
        description="pop up scene import settings",
        default=False,
        options={"SKIP_SAVE"},
    )

    use_resolution_operator: BoolProperty(
        name="Use operator resolution set by the operator",
        description="Use resolution set by the operator",
        default=False,
        options={"SKIP_SAVE"},
    )

    resolution: EnumProperty(
        items=available_resolutions_callback,
        default=6,
        description="Replace resolution",
        options={"SKIP_SAVE"},
    )

    # needs to be passed to the operator to not show all resolution possibilities
    max_resolution: IntProperty(name="Max resolution", description="", default=0)
    # has_res_0_5k: BoolProperty(name='512',
    #                                 description='', default=False)

    cast_parent: StringProperty(
        name="Particles Target Object", description="", default=""
    )

    # close_window: BoolProperty(name='Close window',
    #                            description='Try to close the window below mouse before download',
    #                            default=False)
    # @classmethod
    # def poll(cls, context):
    #     return bpy.context.window_manager.BlenderKitModelThumbnails is not ''
    tooltip: bpy.props.StringProperty(
        default="Download and link asset to scene. Only link if asset already available locally"
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def get_asset_data(self, context):
        """Get asset data - it can come from scene, or from search results."""
        scene = bpy.context.scene
        if self.asset_index > -1:  # Getting the data from search results
            sr = global_vars.DATA["search results"]
            asset_data = sr[
                self.asset_index
            ]  # TODO CHECK ALL OCCURRENCES OF PASSING BLENDER ID PROPS TO THREADS!
            asset_base_id = asset_data["assetBaseId"]
            return asset_data

        # Getting the data from scene
        asset_base_id = self.asset_base_id
        assets_used = scene.get("assets used", {})
        if (
            asset_base_id in assets_used
        ):  # already used assets have already download link and especially file link.
            asset_data = scene["assets used"][asset_base_id].to_dict()
            return asset_data

        # when not in scene nor in search results, we need to get it from the server
        params = {"asset_base_id": self.asset_base_id}
        preferences = bpy.context.preferences.addons["blenderkit"].preferences
        results = search.get_search_simple(
            params, page_size=1, max_results=1, api_key=preferences.api_key
        )
        asset_data = search.parse_result(results[0])
        return asset_data

    def execute(self, context):
        preferences = bpy.context.preferences.addons["blenderkit"].preferences
        self.asset_data = self.get_asset_data(context)

        if not has_asset_files(self.asset_data):
            reports.add_report(
                f"Asset {self.asset_data['displayName']} has no files. Author should reupload the asset.",
                15,
                "ERROR",
            )
            return {"CANCELLED"}

        asset_type = self.asset_data["assetType"]
        if (
            (asset_type == "model" or asset_type == "material")
            and (bpy.context.mode != "OBJECT")
            and (bpy.context.view_layer.objects.active is not None)
        ):
            bpy.ops.object.mode_set(mode="OBJECT")

        # either settings resolution is used, or the one set by operator.
        # all operator calls need to set use_resolution_operator True if they want to define/swap resolution
        if not self.use_resolution_operator:
            resolution = preferences.resolution
        else:
            resolution = self.resolution

        resolution = resolutions.resolution_props_to_server[resolution]
        if self.replace:  # cleanup first, assign later.
            obs = utils.get_selected_replace_adepts()
            for ob in obs:
                if self.asset_base_id != "":
                    # this is for a case when replace is called from a panel,
                    # this uses active object as replacement source instead of target.
                    if ob.get("asset_data") is not None and (
                        ob["asset_data"]["assetBaseId"] == self.asset_base_id
                        and ob["asset_data"]["resolution"] == resolution
                    ):
                        continue
                parent = ob.parent
                if parent:
                    parent = (
                        ob.parent.name
                    )  # after this, parent is either name or None.

                kwargs = {
                    "cast_parent": self.cast_parent,
                    "target_object": ob.name,
                    "material_target_slot": ob.active_material_index,
                    "model_location": tuple(ob.matrix_world.translation),
                    "model_rotation": tuple(ob.matrix_world.to_euler()),
                    "replace": True,
                    "replace_resolution": False,
                    "parent": parent,
                    "resolution": resolution,
                }
                # TODO - move this After download, not before, so that the replacement
                utils.delete_hierarchy(ob)
                start_download(self.asset_data, **kwargs)
                return {"FINISHED"}

        # replace resolution needs to replace all instances of the resolution in the scene
        # and deleting originals has to be thus done after the downlaod

        kwargs = {
            "cast_parent": self.cast_parent,
            "target_object": self.target_object,
            "material_target_slot": self.material_target_slot,
            "model_location": tuple(self.model_location),
            "model_rotation": tuple(self.model_rotation),
            "replace": False,
            "replace_resolution": self.replace_resolution,
            "resolution": resolution,
        }

        start_download(self.asset_data, **kwargs)
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        if self.invoke_resolution:
            layout.prop(self, "resolution", expand=True, icon_only=False)
        if self.invoke_scene_settings:
            ui_panels.draw_scene_import_settings(self, context)

    def invoke(self, context, event):
        # if self.close_window:
        #     context.window.cursor_warp(event.mouse_x-1000, event.mouse_y - 1000);
        wm = context.window_manager
        # only make a pop up in case of switching resolutions
        if self.invoke_resolution:
            self.asset_data = self.get_asset_data(context)
            preferences = bpy.context.preferences.addons["blenderkit"].preferences

            # set initial resolutions enum activation
            if preferences.resolution != "ORIGINAL" and int(
                preferences.resolution
            ) <= int(self.max_resolution):
                self.resolution = preferences.resolution
            elif int(self.max_resolution) > 0:
                self.resolution = str(self.max_resolution)
            else:
                self.resolution = "ORIGINAL"
            return wm.invoke_props_dialog(self)

        if self.invoke_scene_settings:
            return wm.invoke_props_dialog(self)
        # if self.close_window:
        #     time.sleep(0.1)
        #     context.region.tag_redraw()
        #     time.sleep(0.1)
        #
        #     context.window.cursor_warp(event.mouse_x, event.mouse_y);

        return self.execute(context)


def register_download():
    bpy.utils.register_class(BlenderkitDownloadOperator)
    bpy.utils.register_class(BlenderkitKillDownloadOperator)
    bpy.app.handlers.load_post.append(scene_load)
    bpy.app.handlers.save_pre.append(scene_save)
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences


def unregister_download():
    bpy.utils.unregister_class(BlenderkitDownloadOperator)
    bpy.utils.unregister_class(BlenderkitKillDownloadOperator)
    bpy.app.handlers.load_post.remove(scene_load)
    bpy.app.handlers.save_pre.remove(scene_save)
