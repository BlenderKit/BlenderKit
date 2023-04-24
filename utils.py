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


import datetime
import json
import logging
import os
import platform
import re
import shutil
import sys
import uuid

import bpy
from mathutils import Vector

from . import global_vars, image_utils, paths, reports
from .daemon import daemon_tasks


bk_logger = logging.getLogger(__name__)

ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
HIGH_PRIORITY_CLASS = 0x00000080
IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020
REALTIME_PRIORITY_CLASS = 0x00000100

supported_material_click = (
    "MESH",
    "CURVE",
    "META",
    "FONT",
    "SURFACE",
    "VOLUME",
    "GPENCIL",
)
supported_material_drag = (
    "MESH",
    "CURVE",
    "META",
    "FONT",
    "SURFACE",
    "VOLUME",
    "GPENCIL",
)


# supported_material_drag = ('MESH')


def experimental_enabled():
    """experimental features will always be enabled for staff and validators"""
    preferences = bpy.context.preferences.addons["blenderkit"].preferences
    return preferences.experimental_features or profile_is_validator()


def get_process_flags():
    flags = BELOW_NORMAL_PRIORITY_CLASS
    if sys.platform != "win32":  # TODO test this on windows
        flags = 0
    return flags


def activate(ob):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def selection_get():
    aob = bpy.context.view_layer.objects.active
    selobs = bpy.context.view_layer.objects.selected[:]
    return (aob, selobs)


def selection_set(sel):
    bpy.ops.object.select_all(action="DESELECT")
    try:
        bpy.context.view_layer.objects.active = sel[0]
        for ob in sel[1]:
            ob.select_set(True)
    except Exception as e:
        print("Selectible objects not found")
        print(e)


def get_active_model():
    if bpy.context.view_layer.objects.active is not None:
        ob = bpy.context.view_layer.objects.active
        while ob.parent is not None:
            ob = ob.parent
        return ob
    return None


def get_active_HDR():
    ui_props = bpy.context.window_manager.blenderkitUI
    image = ui_props.hdr_upload_image
    return image


def get_selected_models():
    """
    Detect all hierarchies that contain asset data from selection. Only parents that have actual ['asset data'] get returned
    Returns
    list of objects containing asset data.

    """
    obs = bpy.context.selected_objects[:]
    done = {}
    parents = []
    for ob in obs:
        if ob not in done:
            while (
                ob.parent is not None
                and ob not in done
                and ob.blenderkit.asset_base_id == ""
                and ob.instance_collection is None
            ):
                done[ob] = True
                ob = ob.parent

            if ob not in parents and ob not in done:
                if ob.blenderkit.name != "" or ob.instance_collection is not None:
                    parents.append(ob)
            done[ob] = True

    # if no blenderkit - like objects were found, use the original selection.
    if len(parents) == 0:
        parents = obs
    return parents


def get_selected_replace_adepts():
    """
    Detect all hierarchies that contain either asset data from selection, or selected objects themselves.
    Returns
    list of objects for replacement.

    """
    obs = bpy.context.selected_objects[:]
    done = {}
    parents = []
    for selected_ob in obs:
        ob = selected_ob
        if ob not in done:
            while (
                ob.parent is not None
                and ob not in done
                and ob.blenderkit.asset_base_id == ""
                and ob.instance_collection is None
            ):
                done[ob] = True
                # print('step,',ob.name)
                ob = ob.parent

            # print('fin', ob.name)
            if ob not in parents and ob not in done:
                if ob.blenderkit.name != "" or ob.instance_collection is not None:
                    parents.append(ob)

            done[ob] = True
    # print(parents)
    # if no blenderkit - like objects were found, use the original selection.
    if len(parents) == 0:
        parents = obs
    pprint("replace adepts")
    pprint(str(parents))
    return parents


def exclude_collection(name, state=True):
    """
    Set the exclude state of collection
    Parameters
    ----------
    name - name of collection
    state - default True.

    Returns
    -------
    None
    """
    vl = bpy.context.view_layer.layer_collection
    cc = [vl]
    found = False
    while len(cc) > 0 and not found:
        c = cc.pop()
        if c.name == name:
            c.exclude = state
            found = True
        cc.extend(c.children)


def move_collection(child, parent):
    """
    Move a collection to a new parrent
    Parameters
    ----------
    child - collection
    parent - parent

    Returns
    -------
    None
    """
    vl = bpy.context.scene.collection
    cc = [vl]
    found = False
    while len(cc) > 0 and not found:
        c = cc.pop()
        if c.name != parent.name and c.children.find(child.name) > -1:
            c.children.unlink(child)
        if c.name == parent.name and c.children.find(child.name) == -1:
            c.children.link(child)
        cc.extend(c.children)


def get_search_props():
    scene = bpy.context.scene
    wm = bpy.context.window_manager
    if scene is None:
        return
    uiprops = bpy.context.window_manager.blenderkitUI
    props = None
    if uiprops.asset_type == "MODEL":
        if not hasattr(wm, "blenderkit_models"):
            return
        props = wm.blenderkit_models
    if uiprops.asset_type == "SCENE":
        if not hasattr(wm, "blenderkit_scene"):
            return
        props = wm.blenderkit_scene
    if uiprops.asset_type == "HDR":
        if not hasattr(wm, "blenderkit_HDR"):
            return
        props = wm.blenderkit_HDR
    if uiprops.asset_type == "MATERIAL":
        if not hasattr(wm, "blenderkit_mat"):
            return
        props = wm.blenderkit_mat

    if uiprops.asset_type == "TEXTURE":
        if not hasattr(wm, "blenderkit_tex"):
            return
        # props = scene.blenderkit_tex

    if uiprops.asset_type == "BRUSH":
        if not hasattr(wm, "blenderkit_brush"):
            return
        props = wm.blenderkit_brush
    return props


def get_active_asset_by_type(asset_type="model"):
    asset_type = asset_type.lower()
    if asset_type == "model":
        if bpy.context.view_layer.objects.active is not None:
            ob = get_active_model()
            return ob
    if asset_type == "scene":
        return bpy.context.scene
    if asset_type == "hdr":
        return get_active_HDR()
    if asset_type == "material":
        if (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        ):
            return bpy.context.active_object.active_material
    if asset_type == "texture":
        return None
    if asset_type == "brush":
        b = get_active_brush()
        if b is not None:
            return b
    return None


def get_active_asset():
    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type == "MODEL":
        if bpy.context.view_layer.objects.active is not None:
            ob = get_active_model()
            return ob
    if ui_props.asset_type == "SCENE":
        return bpy.context.scene
    if ui_props.asset_type == "HDR":
        return get_active_HDR()
    elif ui_props.asset_type == "MATERIAL":
        if (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        ):
            return bpy.context.active_object.active_material
    elif ui_props.asset_type == "TEXTURE":
        return None
    elif ui_props.asset_type == "BRUSH":
        b = get_active_brush()
        if b is not None:
            return b
    return None


def get_upload_props():
    """Get uploaded object properties based on the selected asset_type."""
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type == "MODEL":
        if bpy.context.view_layer.objects.active is not None:
            ob = get_active_model()
            return ob.blenderkit
    if ui_props.asset_type == "SCENE":
        s = bpy.context.scene
        return s.blenderkit
    if ui_props.asset_type == "HDR":
        hdr = (
            ui_props.hdr_upload_image
        )  # bpy.data.images.get(ui_props.hdr_upload_image)
        if not hdr:
            return None
        return hdr.blenderkit
    elif ui_props.asset_type == "MATERIAL":
        if (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        ):
            return bpy.context.active_object.active_material.blenderkit
    elif ui_props.asset_type == "TEXTURE":
        return None
    elif ui_props.asset_type == "BRUSH":
        b = get_active_brush()
        if b is not None:
            return b.blenderkit
    return None


def previmg_name(index, fullsize=False):
    if not fullsize:
        return ".bkit_preview_" + str(index).zfill(3)
    else:
        return ".bkit_preview_full_" + str(index).zfill(3)


def get_active_brush():
    context = bpy.context
    brush = None
    if context.sculpt_object:
        brush = context.tool_settings.sculpt.brush
    elif (
        context.image_paint_object
    ):  # could be just else, but for future possible more types...
        brush = context.tool_settings.image_paint.brush
    return brush


def load_XXXXXXXXXXXX_prefs():
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    wm = bpy.context.window_manager
    # if user_preferences.api_key == '':
    fpath = paths.BLENDERKIT_SETTINGS_FILENAME
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as s:
                prefs = json.load(s)
                user_preferences.api_key = prefs.get("api_key", "")
                user_preferences.api_key_refresh = prefs.get("api_key_refresh", "")
                user_preferences.global_dir = prefs.get(
                    "global_dir", paths.default_global_dict()
                )
                user_preferences.project_subdir = prefs.get(
                    "project_subdir", "//assets"
                )
                user_preferences.directory_behaviour = prefs.get("directory_behaviour")
                user_preferences.proxy_which = prefs.get("proxy_which")
                user_preferences.proxy_address = prefs.get("proxy_address", "")
                user_preferences.proxy_ca_certs = prefs.get("proxy_ca_certs", "")
                wm.blenderkit_models.resolution = prefs.get("models_resolution")
                wm.blenderkit_mat.resolution = prefs.get("materials_resolution")
                wm.blenderkit_HDR.resolution = prefs.get("hdrs_resolution")
            print("RETURNING PREFS", prefs)
            return prefs
        except Exception as e:
            print("failed to read addon preferences.")
            print(e)
            os.remove(fpath)
    else:
        return get_prefs_dir()


def get_scene_id():
    """gets scene id and possibly also generates a new one"""
    bpy.context.scene["uuid"] = bpy.context.scene.get("uuid", str(uuid.uuid4()))
    return bpy.context.scene["uuid"]


def save_resolutions(self, context):
    wm = bpy.context.window_manager
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    if self.__class__.__name__ == "BlenderKitModelSearchProps":
        user_preferences.models_resolution = wm.blenderkit_models.resolution
    if self.__class__.__name__ == "BlenderKitMaterialSearchProps":
        user_preferences.mat_resolution = wm.blenderkit_mat.resolution
    if self.__class__.__name__ == "BlenderKitHDRSearchProps":
        user_preferences.hdr_resolution = wm.blenderkit_HDR.resolution


def get_prefs_dir():
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences

    wm = bpy.context.window_manager
    wm.blenderkit_models.resolution = user_preferences.models_resolution
    wm.blenderkit_mat.resolution = user_preferences.mat_resolution
    wm.blenderkit_HDR.resolution = user_preferences.hdr_resolution

    prefs = {
        "debug_value": bpy.app.debug_value,
        "binary_path": bpy.app.binary_path,
        "api_key": user_preferences.api_key,
        "api_key_refresh": user_preferences.api_key_refresh,
        "system_id": user_preferences.system_id,
        "global_dir": user_preferences.global_dir,
        "project_subdir": user_preferences.project_subdir,
        "directory_behaviour": user_preferences.directory_behaviour,
        "is_saved": user_preferences.directory_behaviour,
        "app_id": os.getpid(),
        "ip_version": user_preferences.ip_version,
        "ssl_context": user_preferences.ssl_context,
        "proxy_which": user_preferences.proxy_which,
        "proxy_address": user_preferences.proxy_address,
        "proxy_ca_certs": user_preferences.proxy_ca_certs,
        "unpack_files": user_preferences.unpack_files,
        "models_resolution": user_preferences.models_resolution,
        "mat_resolution": user_preferences.mat_resolution,
        "hdr_resolution": user_preferences.hdr_resolution,
    }
    return prefs


def set_proxy():
    certs = global_vars.PREFS.get("proxy_ca_certs", "")
    if certs != "":
        os.environ["REQUESTS_CA_BUNDLE"] = certs
        os.environ["CURL_CA_BUNDLE"] = certs


def save_prefs(self, context):
    # first check context, so we don't do this on registration or blender startup
    if not bpy.app.background:  # (hasattr kills blender)
        # print('saving prefs')
        bpy.ops.wm.save_userpref()
        user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
        # we test the api key for length, so not a random accidentally typed sequence gets saved.
        lk = len(user_preferences.api_key)
        if 0 < lk < 25:
            # reset the api key in case the user writes some nonsense, e.g. a search string instead of the Key
            user_preferences.api_key = ""
            props = get_search_props()
            props.report = "Login failed. Please paste a correct API Key."

        prefs = get_prefs_dir()
        global_vars.PREFS = prefs
        set_proxy()

        return
        try:
            fpath = paths.BLENDERKIT_SETTINGS_FILENAME

            if not os.path.exists(paths._presets):
                os.makedirs(paths._presets)
            with open(fpath, "w", encoding="utf-8") as s:
                json.dump(prefs, s, ensure_ascii=False, indent=4)
        except Exception as e:
            print(e)


def uploadable_asset_poll():
    """returns true if active asset type can be uploaded"""
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type == "MODEL":
        return bpy.context.view_layer.objects.active is not None
    if ui_props.asset_type == "MATERIAL":
        return (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        )
    if ui_props.asset_type == "HDR":
        return ui_props.hdr_upload_image is not None
    return True


def get_hidden_texture(name, force_reload=False):
    if name[0] != ".":
        name = f".{name}"
    t = bpy.data.textures.get(name)
    if t is None:
        t = bpy.data.textures.new(name, "IMAGE")
    if t.image is None or t.image.name != name:
        img = bpy.data.images.get(name)
        if img:
            t.image = img
    return t


def img_to_preview(img, copy_original=False):
    if bpy.app.version[0] >= 3:
        img.preview_ensure()
    if not copy_original:
        return
    if img.preview.image_size != img.size:
        img.preview.image_size = (img.size[0], img.size[1])
        img.preview.image_pixels_float = img.pixels[:]
    # img.preview.icon_size = (img.size[0], img.size[1])
    # img.preview.icon_pixels_float = img.pixels[:]


def get_hidden_image(tpath, bdata_name, force_reload=False, colorspace="sRGB"):
    if bdata_name[0] == ".":
        hidden_name = bdata_name
    else:
        hidden_name = ".%s" % bdata_name
    img = bpy.data.images.get(hidden_name)

    if tpath.startswith("//"):
        tpath = bpy.path.abspath(tpath)

    if img == None or (img.filepath != tpath):
        if tpath.startswith("//"):
            tpath = bpy.path.abspath(tpath)
        if not os.path.exists(tpath) or os.path.isdir(tpath):
            tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")

        if img is None:
            img = bpy.data.images.load(tpath, check_existing=True)
            img_to_preview(img)
            img.name = hidden_name
        else:
            if img.filepath != tpath:
                if img.packed_file is not None:
                    img.unpack(method="USE_ORIGINAL")

                img.filepath = tpath
                img.reload()
                img_to_preview(img)
        image_utils.set_colorspace(img, colorspace)

    elif force_reload:
        if img.packed_file is not None:
            img.unpack(method="USE_ORIGINAL")
        img.reload()
        img_to_preview(img)
        image_utils.set_colorspace(img, colorspace)

    return img


def get_thumbnail(name):
    p = paths.get_addon_thumbnail_path(name)
    name = ".%s" % name
    img = bpy.data.images.get(name)
    if img == None:
        img = bpy.data.images.load(p, check_existing=True)
        image_utils.set_colorspace(img, "sRGB")
        img.name = name
        img.name = name

    return img


def files_size_to_text(size):
    fsmb = size / (1024 * 1024)
    fskb = size % 1024
    if fsmb == 0:
        return f"{round(fskb)}KB"
    else:
        return f"{round(fsmb, 1)}MB"


def get_brush_props(context):
    brush = get_active_brush()
    if brush is not None:
        return brush.blenderkit
    return None


def p(text, text1="", text2="", text3="", text4="", text5="", level="DEBUG"):
    """debug printing depending on blender's debug value"""

    if 1:  # bpy.app.debug_value != 0:
        # print('-----BKit debug-----\n')
        # traceback.print_stack()
        texts = [text1, text2, text3, text4, text5]
        text = str(text)
        for t in texts:
            if t != "":
                text += " " + str(t)

        bk_logger.debug(text)
        # print('---------------------\n')


def copy_asset(fp1, fp2):
    """synchronizes the asset between folders, including it's texture subdirectories"""
    if 1:
        bk_logger.debug("copy asset")
        bk_logger.debug(fp1 + " " + fp2)
        if not os.path.exists(fp2):
            shutil.copyfile(fp1, fp2)
            bk_logger.debug("copied")
        source_dir = os.path.dirname(fp1)
        target_dir = os.path.dirname(fp2)
        for subdir in os.scandir(source_dir):
            if not subdir.is_dir():
                continue
            target_subdir = os.path.join(target_dir, subdir.name)
            if os.path.exists(target_subdir):
                continue
            bk_logger.debug(str(subdir) + " " + str(target_subdir))
            shutil.copytree(subdir, target_subdir)
            bk_logger.debug("copied")

    # except Exception as e:
    #     print('BlenderKit failed to copy asset')
    #     print(fp1, fp2)
    #     print(e)


def pprint(data, data1=None, data2=None, data3=None, data4=None):
    """pretty print jsons"""
    p(json.dumps(data, indent=4, sort_keys=True))


def get_hierarchy(ob):
    """get all objects in a tree"""
    obs = []
    doobs = [ob]
    # pprint('get hierarchy')
    pprint(ob.name)
    while len(doobs) > 0:
        o = doobs.pop()
        doobs.extend(o.children)
        obs.append(o)
    return obs


def select_hierarchy(ob, state=True):
    obs = get_hierarchy(ob)
    for ob in obs:
        ob.select_set(state)
    return obs


def delete_hierarchy(ob):
    obs = get_hierarchy(ob)
    bpy.ops.object.delete({"selected_objects": obs})


def get_bounds_snappable(obs, use_modifiers=False):
    # progress('getting bounds of object(s)')
    parent = obs[0]
    while parent.parent is not None:
        parent = parent.parent
    maxx = maxy = maxz = -10000000
    minx = miny = minz = 10000000

    s = bpy.context.scene

    obcount = 0  # calculates the mesh obs. Good for non-mesh objects
    matrix_parent = parent.matrix_world
    for ob in obs:
        # bb=ob.bound_box
        mw = ob.matrix_world
        subp = ob.parent
        # while parent.parent is not None:
        #     mw =

        if ob.type == "MESH" or ob.type == "CURVE":
            # If to_mesh() works we can use it on curves and any other ob type almost.
            # disabled to_mesh for 2.8 by now, not wanting to use dependency graph yet.
            depsgraph = bpy.context.evaluated_depsgraph_get()

            object_eval = ob.evaluated_get(depsgraph)
            if ob.type == "CURVE":
                mesh = object_eval.to_mesh()
            else:
                mesh = object_eval.data

            # to_mesh(context.depsgraph, apply_modifiers=self.applyModifiers, calc_undeformed=False)
            obcount += 1
            if mesh is not None:
                for c in mesh.vertices:
                    coord = c.co
                    parent_coord = (
                        matrix_parent.inverted()
                        @ mw
                        @ Vector((coord[0], coord[1], coord[2]))
                    )  # copy this when it works below.
                    minx = min(minx, parent_coord.x)
                    miny = min(miny, parent_coord.y)
                    minz = min(minz, parent_coord.z)
                    maxx = max(maxx, parent_coord.x)
                    maxy = max(maxy, parent_coord.y)
                    maxz = max(maxz, parent_coord.z)
                # bpy.data.meshes.remove(mesh)
            if ob.type == "CURVE":
                object_eval.to_mesh_clear()

    if obcount == 0:
        minx, miny, minz, maxx, maxy, maxz = 0, 0, 0, 0, 0, 0

    minx *= parent.scale.x
    maxx *= parent.scale.x
    miny *= parent.scale.y
    maxy *= parent.scale.y
    minz *= parent.scale.z
    maxz *= parent.scale.z

    return minx, miny, minz, maxx, maxy, maxz


def get_bounds_worldspace(obs, use_modifiers=False):
    # progress('getting bounds of object(s)')
    s = bpy.context.scene
    maxx = maxy = maxz = -10000000
    minx = miny = minz = 10000000
    obcount = 0  # calculates the mesh obs. Good for non-mesh objects
    for ob in obs:
        # bb=ob.bound_box
        mw = ob.matrix_world
        if ob.type == "MESH" or ob.type == "CURVE":
            depsgraph = bpy.context.evaluated_depsgraph_get()
            ob_eval = ob.evaluated_get(depsgraph)
            mesh = ob_eval.to_mesh()
            obcount += 1
            if mesh is not None:
                for c in mesh.vertices:
                    coord = c.co
                    world_coord = mw @ Vector((coord[0], coord[1], coord[2]))
                    minx = min(minx, world_coord.x)
                    miny = min(miny, world_coord.y)
                    minz = min(minz, world_coord.z)
                    maxx = max(maxx, world_coord.x)
                    maxy = max(maxy, world_coord.y)
                    maxz = max(maxz, world_coord.z)
            ob_eval.to_mesh_clear()

    if obcount == 0:
        minx, miny, minz, maxx, maxy, maxz = 0, 0, 0, 0, 0, 0
    return minx, miny, minz, maxx, maxy, maxz


def is_linked_asset(ob):
    return ob.get("asset_data") and ob.instance_collection != None


def get_dimensions(obs):
    minx, miny, minz, maxx, maxy, maxz = get_bounds_snappable(obs)
    bbmin = Vector((minx, miny, minz))
    bbmax = Vector((maxx, maxy, maxz))
    dim = Vector((maxx - minx, maxy - miny, maxz - minz))
    return dim, bbmin, bbmax


def get_headers(api_key: str = "") -> dict[str, str]:
    headers = {
        "accept": "application/json",
        "Platform-Version": platform.platform(),
        "system-id": bpy.context.preferences.addons["blenderkit"].preferences.system_id,
        "addon-version": f"{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}",
    }
    if api_key != "":
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


def ensure_system_ID():
    preferences = bpy.context.preferences.addons["blenderkit"].preferences
    if preferences.system_id == "":
        preferences.system_id = str(uuid.getnode())


def scale_2d(v, s, p):
    """scale a 2d vector with a pivot"""
    return (p[0] + s[0] * (v[0] - p[0]), p[1] + s[1] * (v[1] - p[1]))


def scale_uvs(ob, scale=1.0, pivot=Vector((0.5, 0.5))):
    mesh = ob.data
    if len(mesh.uv_layers) > 0:
        uv = mesh.uv_layers[mesh.uv_layers.active_index]

        # Scale a UV map iterating over its coordinates to a given scale and with a pivot point
        for uvindex in range(len(uv.data)):
            uv.data[uvindex].uv = scale_2d(uv.data[uvindex].uv, scale, pivot)


# map uv cubic and switch of auto tex space and set it to 1,1,1
def automap(
    target_object=None,
    target_slot=None,
    tex_size=1,
    bg_exception=False,
    just_scale=False,
):
    wm = bpy.context.window_manager
    mat_props = wm.blenderkit_mat
    if mat_props.automap:
        tob = bpy.data.objects[target_object]
        # only automap mesh models
        if tob.type == "MESH" and len(tob.data.polygons) > 0:
            # check polycount for a rare case where no polys are in editmesh
            actob = bpy.context.active_object
            bpy.context.view_layer.objects.active = tob

            # auto tex space
            if tob.data.use_auto_texspace:
                tob.data.use_auto_texspace = False

            if not just_scale:
                tob.data.texspace_size = (1, 1, 1)

            if "automap" not in tob.data.uv_layers:
                bpy.ops.mesh.uv_texture_add()
                uvl = tob.data.uv_layers[-1]
                uvl.name = "automap"

            # TODO limit this to active material
            # tob.data.uv_textures['automap'].active = True

            scale = tob.scale.copy()

            if target_slot is not None:
                tob.active_material_index = target_slot
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="DESELECT")

            # this exception is just for a 2.8 background thunmbnailer crash, can be removed when material slot select works...
            if bg_exception:
                bpy.ops.mesh.select_all(action="SELECT")
            else:
                bpy.ops.object.material_slot_select()

            scale = (scale.x + scale.y + scale.z) / 3.0

            if (
                tex_size == 0
            ):  # prevent division by zero, it's possible to have 0 in tex size by unskilled uploaders
                tex_size = 1

            if not just_scale:
                # compensate for the undocumented operator change in blender 3.2
                if bpy.app.version >= (3, 2, 0):
                    cube_size = (tex_size) / scale
                else:
                    cube_size = (
                        scale * 2.0 / (tex_size)
                    )  # it's * 2.0 because blender can't tell size of a unit cube :)

                bpy.ops.uv.cube_project(cube_size=cube_size, correct_aspect=False)

            bpy.ops.object.editmode_toggle()
            tob.data.uv_layers.active = tob.data.uv_layers["automap"]
            tob.data.uv_layers["automap"].active_render = True
            # this by now works only for thumbnail preview, but should be extended to work on arbitrary objects.
            # by now, it takes the basic uv map = 1 meter. also, it now doeasn't respect more materials on one object,
            # it just scales whole UV.
            if just_scale:
                scale_uvs(tob, scale=Vector((1 / tex_size, 1 / tex_size)))
            bpy.context.view_layer.objects.active = actob


def name_update(props, context=None):
    """Update asset name function, gets run also before upload. Makes sure name doesn't change in case of reuploads,
    and only displayName gets written to server.
    Checks for name change, because it decides if whole asset has to be re-uploaded. Name is stored in the blend file
    and that's the reason.
    """
    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI

    # props = get_upload_props()
    if props.name_old != props.name:
        props.name_changed = True
        props.name_old = props.name
        nname = props.name.strip()
        nname = nname.replace("_", " ")

        if nname.isupper():
            nname = nname.lower()
        nname = nname[0].upper() + nname[1:]
        props.name = nname
        # here we need to fix the name for blender data = ' or " give problems in path evaluation down the road.
    fname = props.name
    fname = fname.replace("'", "")
    fname = fname.replace('"', "")
    asset = get_active_asset()
    if ui_props.asset_type != "HDR":
        # Here we actually rename assets datablocks, but don't do that with HDR's and possibly with others
        asset.name = fname


def fmt_dimensions(p):
    """formats dimensions to correct string"""
    dims = [p["dimensionX"], p["dimensionY"], p["dimensionZ"]]
    maxl = max(dims)
    if maxl > 1:
        unit = "m"
        unitscale = 1
    elif maxl > 0.01:
        unit = "cm"
        unitscale = 100
    else:
        unit = "mm"
        unitscale = 1000
    s = f"{fmt_length(dims[0]*unitscale)}×{fmt_length(dims[1]*unitscale)}×{fmt_length(dims[2]*unitscale)} {unit}"
    return s


def fmt_length(prop):
    prop = str(round(prop, 2))
    return prop


def get_param(asset_data, parameter_name, default=None):
    if not asset_data.get("dictParameters"):
        # this can appear in older version files.
        return default

    return asset_data["dictParameters"].get(parameter_name, default)

    # for p in asset_data['parameters']:
    #     if p.get('parameterType') == parameter_name:
    #         return p['value']
    # return default


def params_to_dict(params):
    params_dict = {}
    for p in params:
        params_dict[p["parameterType"]] = p["value"]
    return params_dict


def update_tags(self, context):
    props = self

    commasep = props.tags.split(",")
    ntags = []
    for tag in commasep:
        if len(tag) > 19:
            short_tags = tag.split(" ")
            for short_tag in short_tags:
                if len(short_tag) > 19:
                    short_tag = short_tag[:18]
                ntags.append(short_tag)
        else:
            ntags.append(tag)
    if len(ntags) == 1:
        ntags = ntags[0].split(" ")
    ns = ""
    for t in ntags:
        if t != "":
            ns += t + ","
    ns = ns[:-1]
    if props.tags != ns:
        props.tags = ns


def user_logged_in():
    """User is currently logged in successfully"""
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    a = global_vars.DATA.get("bkit profile")
    # Check both profile and token, profile sometimes isn't cleaned up after logout
    # vilem - removed (a is not None) - the profile isn't always ready on start of blender,
    # it can take a while, and e.g. bookmark popup could be spawned.
    if user_preferences.api_key != "":
        return True
    return False


def profile_is_validator():
    """currently logged in profile is validator"""
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    profile = global_vars.DATA.get("bkit profile")
    if profile is None or user_preferences.api_key == "":
        return False
    result = profile.get("canEditAllAssets", False)
    return result


def user_is_owner(asset_data=None):
    """Checks if the current logged in user is owner of the asset"""
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    profile = global_vars.DATA.get("bkit profile")
    if profile is None or user_preferences.api_key == "":
        return False
    if int(asset_data["author"]["id"]) == int(profile["user"]["id"]):
        return True
    return False


def asset_from_newer_blender_version(asset_data):
    """checks if asset is from a newer blender version, to avoid incompatibility"""
    bver = bpy.app.version
    aver = asset_data["sourceAppVersion"].split(".")
    bver_f = bver[0] + bver[1] * 0.01 + bver[2] * 0.0001
    if len(aver) >= 3:
        aver_f = int(aver[0]) + int(aver[1]) * 0.01 + int(aver[2]) * 0.0001
        return aver_f > bver_f
    return False


def guard_from_crash():
    """
    Blender tends to crash when trying to run some functions
     with the addon going through unregistration process.
     This function is used in these functions (like draw callbacks)
     so these don't run during unregistration.
    """
    if bpy.context.preferences.addons.get("blenderkit") is None:
        return False
    if bpy.context.preferences.addons["blenderkit"].preferences is None:
        return False
    return True


def get_largest_area(context=None, area_type="VIEW_3D"):
    maxsurf = 0
    maxa = None
    maxw = None
    region = None
    if context is None:
        windows = bpy.data.window_managers[0].windows
    else:
        windows = context.window_manager.windows
    for w in windows:
        for a in w.screen.areas:
            if a.type == area_type:
                asurf = a.width * a.height
                if asurf > maxsurf:
                    maxa = a
                    maxw = w
                    maxsurf = asurf

                    region = a.regions[-1]
                    # for r in a.regions:
                    #     if r.type == 'WINDOW':
                    #         region = r

    if maxw is None or maxa is None:
        return None, None, None
    return maxw, maxa, region


def check_context(context, area_type="VIEW_3D"):
    return (
        hasattr(context, "window")
        and hasattr(context, "screen")
        and hasattr(context, "area")
        and hasattr(context, "region")
    )


def get_fake_context(context=None, area_type="VIEW_3D"):
    C_dict = (
        {}
    )  # context.copy() #context.copy was a source of problems - incompatibility with addons that also define context
    C_dict.update(region="WINDOW")

    # if hasattr(context,'window') and hasattr(context,'screen') and hasattr(context,'area') and hasattr(context,'region'):
    #     w = context.window
    #     s = context.screen
    #     a = context.area
    #     r = context.region
    #     if not None in (w, s, a, r) and a.type == area_type and r.type == 'WINDOW':
    #         override = {'window': w, 'screen': s, 'area': a, 'region': r}
    #
    #         C_dict.update(override)
    #         print('returning almost original context')
    #         return C_dict

    # new context
    w, a, r = get_largest_area(context=context, area_type=area_type)
    if w:
        # sometimes there is no area of the requested type. Let's face it, some people use Blender without 3d view.
        override = {
            "window": w,
            "screen": w.screen,
            "area": a,
            "space_data": a.spaces.active,
            "region": r,
        }

        C_dict.update(override)
    return C_dict


def has_url(text):
    # first remove markdown *
    text = text.replace("*", "")
    # Anything that isn't a square closing bracket
    name_regex = "[^]]+"
    # http:// or https:// followed by anything but a closing paren
    url_regex = "http[s]?://[^)]+"
    markup_regex = f"\[({name_regex})]\(\s*({url_regex})\s*\)"
    urls = re.findall(markup_regex, text)
    replacechars = "[]()"
    for url in urls:
        text = re.sub(markup_regex, "", text)
        for ch in replacechars:
            text.replace(ch, "")
    return urls, text


def line_with_urls(row, text, urls, icon="NONE", use_urls=False):
    used_urls = []
    if use_urls:
        for i, url in enumerate(urls):
            op = row.operator("wm.blenderkit_url", text=url[0])
            op.url = url[1]
            op.tooltip = "Go online to read more"
            # text = text.replace(url, '')
            # used_urls.append(url)
        if len(urls) > 0:
            return

    row.label(text=text, icon=icon)


def label_multiline(
    layout, text="", icon="NONE", width=-1, max_lines=10, split_last=0, use_urls=False
):
    """
     draw a ui label, but try to split it in multiple lines.

    Parameters
    ----------
    layout
    text
    icon
    width width to split by in character count
    max_lines maximum lines to draw
    split_last - split last row to enable a button after it on the right side. The parameter is a ratio where to split.
    use_urls - automatically parse urls to buttons
    Returns
    -------
    rows of the text(to add extra elements)
    """
    rows = []
    if text.strip() == "":
        return [layout.row()]
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if width > 0:
        threshold = int(width / 5.5)
    else:
        threshold = 35
    line_index = 0
    for line in lines:
        urls = []

        if use_urls:
            urls, line = has_url(line)

        line_index += 1
        while len(line) > threshold:
            # find line split close to the end of line
            i = line.rfind(" ", 0, threshold)
            # split long words
            if i < 1:
                i = threshold
            l1 = line[:i]
            row = layout.row()
            line_with_urls(row, l1, urls, icon=icon, use_urls=use_urls)
            rows.append(row)
            icon = "NONE"
            line = line[i:].lstrip()
            line_index += 1
            if line_index > max_lines:
                break
        if line_index > max_lines:
            break
        row = layout.row()
        if split_last > 0:
            row = row.split(factor=split_last)
        line_with_urls(row, line, urls, icon=icon, use_urls=use_urls)

        rows.append(row)
        icon = "NONE"
    return rows


def is_upload_old(asset_data):
    """
    estimates if the asset is far too long in the 'uploaded' state
    This returns the number of days the validation is over the limit.
    """
    date_time_str = asset_data["created"][:10]
    # date_time_str = 'Jun 28 2018 7:40AM'
    date_time_obj = datetime.datetime.strptime(date_time_str, "%Y-%m-%d")
    today = date_time_obj.today()
    age = today - date_time_obj
    old = datetime.timedelta(days=5)
    if age > old:
        return age.days - old.days
    return 0


def handle_nonblocking_request_task(task: daemon_tasks.Task):
    if task.status == "finished":
        reports.add_report(task.message)
    if task.status == "error":
        reports.add_report(task.message, type="ERROR")


def string2list(text: str) -> list:
    """Convert a comma separated string to a list of strings."""
    items = text.split(",")
    lst = []
    for item in items:
        item = item.strip()
        if item != "":
            lst.append(item)
    return lst


def list2string(lst: list) -> str:
    """Convert a list of strings to a comma separated string."""
    text = ""
    for item in lst:
        text += item + ", "
    return text[:-2]


def check_globaldir_permissions():
    """Check if the user has the required permissions to upload assets."""
    global_dir = bpy.context.preferences.addons["blenderkit"].preferences.global_dir
    if os.path.isfile(global_dir):
        reports.add_report(
            "Global dir is a file. Please remove it or change global dir path in preferences.",
            10,
            type="ERROR",
        )
        return False
    if not os.path.isdir(global_dir):
        bk_logger.info(f"Global dir does not exist. Creating it at {global_dir}")
        try:
            os.mkdir(global_dir)
        except Exception as e:
            reports.add_report(
                f"Cannot create Global dir. Check global dir path in preferences. {e}",
                10,
                type="ERROR",
            )
            return False

    exists = os.access(global_dir, os.F_OK)
    can_write = os.access(global_dir, os.W_OK)
    can_execute = os.access(global_dir, os.X_OK)
    if exists and can_write and can_execute:
        bk_logger.info("Global dir permissions are OK.")
        return True
    reports.add_report(
        f"Change path or give permissions to Global dir, wrong permissions now: exists={exists}, write={can_write}, execute={can_execute}.",
        15,
        type="ERROR",
    )
