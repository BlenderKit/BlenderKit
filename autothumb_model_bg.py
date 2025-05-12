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
# type: ignore


import json
import math
import os
import random
import colorsys
import sys
from traceback import print_exc

import bpy


def get_obnames(BLENDERKIT_EXPORT_DATA: str):
    with open(BLENDERKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
        data = json.load(s)
    obnames = eval(data["models"])
    return obnames


def center_obs_for_thumbnail(obs):
    s = bpy.context.scene
    # obs = bpy.context.selected_objects
    parent = obs[0]
    if parent.type == "EMPTY" and parent.instance_collection is not None:
        obs = parent.instance_collection.objects[:]

    while parent.parent is not None:
        parent = parent.parent
    # reset parent rotation, so we see how it really snaps.
    parent.rotation_euler = (0, 0, 0)
    parent.location = (0, 0, 0)
    bpy.context.view_layer.update()
    minx, miny, minz, maxx, maxy, maxz = utils.get_bounds_worldspace(obs)

    cx = (maxx - minx) / 2 + minx
    cy = (maxy - miny) / 2 + miny
    for ob in s.collection.objects:
        ob.select_set(False)

    bpy.context.view_layer.objects.active = parent
    # parent.location += mathutils.Vector((-cx, -cy, -minz))
    parent.location = (-cx, -cy, 0)

    camZ = s.camera.parent.parent
    # camZ.location.z = (maxz - minz) / 2
    camZ.location.z = (maxz) / 2
    dx = maxx - minx
    dy = maxy - miny
    dz = maxz - minz
    r = math.sqrt(dx * dx + dy * dy + dz * dz)

    scaler = bpy.context.view_layer.objects["scaler"]
    scaler.scale = (r, r, r)
    coef = 0.7
    r *= coef
    camZ.scale = (r, r, r)
    bpy.context.view_layer.update()


def render_thumbnails():
    bpy.ops.render.render(write_still=True, animation=False)


def patch_imports(addon_module_name: str):
    """Patch the python configuration, so the relative imports work as expected. There are few problems to fix:
    1. Script is not recognized as module which would break at relative import. We need to set __package__ = "blenderkit" for legacy addon.
    Or __package__ = "bl_ext.user_default.blenderkit"/"bl_ext.blenderkit_com.blenderkit_com". Otherwise we would see:
       from . import paths
       ImportError: attempted relative import with no known parent package
    2. External repository (e.g. blenderkit_com) is not available as we start with --factory-startup, we need to enable it.
    We can add it as LOCAL repo as the add-on is installed and we do not care about updates or anything in this BG script. Otherwise we would see:
       from . import paths
       ModuleNotFoundError: No module named 'bl_ext.blenderkit_com'; 'bl_ext' is not a package
    """
    print(f"- Setting __package__ = '{addon_module_name}'")
    global __package__
    __package__ = addon_module_name

    if bpy.app.version < (4, 2, 0):
        print(
            f"- Skipping, Blender version {bpy.app.version} < (4,2,0), no need to handle repositories"
        )
        return

    parts = addon_module_name.split(".")
    if len(parts) != 3:
        print("- Skipping, addon_module_name does not contain 3 parts")
        return

    bpy.ops.preferences.extension_repo_add(
        name=parts[1], type="LOCAL"
    )  # Local is enough
    print(f"- Local repository {parts[1]} added")


def replace_materials(obs, material_name):
    """Replace all materials on objects with the specified material
    Args:
        obs: List of objects to process
        material_name: Name of the material to apply to all objects
    """
    material = bpy.data.materials.get(material_name)
    if not material:
        bg_blender.progress(f"Material {material_name} not found")
        return

    for ob in obs:
        if ob.type == "MESH":
            # Clear all material slots and add the specified material
            ob.data.materials.clear()
            ob.data.materials.append(material)
    return material


if __name__ == "__main__":
    try:
        # args order must match the order in blenderkit/autothumb.py:get_thumbnailer_args()!
        BLENDERKIT_EXPORT_DATA = sys.argv[-3]
        BLENDERKIT_EXPORT_API_KEY = sys.argv[-2]
        patch_imports(sys.argv[-1])
        bpy.ops.preferences.addon_enable(module=sys.argv[-1])

        from . import append_link, bg_blender, bg_utils, client_lib, utils

        with open(BLENDERKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
            data = json.load(s)
        thumbnail_use_gpu = data.get("thumbnail_use_gpu")

        if data.get("do_download"):
            # if this isn't here, blender crashes.
            if bpy.app.version >= (3, 0, 0):
                bpy.context.preferences.filepaths.file_preview_type = "NONE"

            # need to save the file, so that asset doesn't get downloaded into addon directory
            temp_blend_path = os.path.join(data["tempdir"], "temp.blend")
            bpy.ops.wm.save_as_mainfile(filepath=temp_blend_path)

            bg_blender.progress("Downloading asset")
            asset_data = data["asset_data"]
            has_url, download_url, file_name = client_lib.get_download_url(
                asset_data, utils.get_scene_id(), BLENDERKIT_EXPORT_API_KEY
            )
            asset_data["files"][0]["url"] = download_url
            asset_data["files"][0]["file_name"] = file_name
            if has_url is not True:
                bg_blender.progress(
                    "couldn't download asset for thumnbail re-rendering"
                )
            bg_blender.progress("downloading asset")
            fpath = bg_utils.download_asset_file(
                asset_data, api_key=BLENDERKIT_EXPORT_API_KEY
            )
            data["filepath"] = fpath
            main_object, allobs = append_link.link_collection(
                fpath,
                location=(0, 0, 0),
                rotation=(0, 0, 0),
                link=True,
                name=asset_data["name"],
                parent=None,
            )
            allobs = [main_object]
        else:
            bg_blender.progress("preparing thumbnail scene")
            obnames = get_obnames(BLENDERKIT_EXPORT_DATA)
            main_object, allobs = append_link.append_objects(
                file_name=data["filepath"], obnames=obnames, link=True
            )
        bpy.context.view_layer.update()

        camdict = {
            "GROUND": "camera ground",
            "WALL": "camera wall",
            "CEILING": "camera ceiling",
            "FLOAT": "camera float",
        }

        bpy.context.scene.camera = bpy.data.objects[camdict[data["thumbnail_snap_to"]]]
        center_obs_for_thumbnail(allobs)
        bpy.context.scene.render.filepath = data["thumbnail_path"]
        if thumbnail_use_gpu is True:
            bpy.context.scene.cycles.device = "GPU"
            compute_device_type = data.get("cycles_compute_device_type")
            if compute_device_type is not None:
                # DOCS:https://github.com/dfelinto/blender/blob/master/intern/cycles/blender/addon/properties.py
                bpy.context.preferences.addons[
                    "cycles"
                ].preferences.compute_device_type = compute_device_type
                bpy.context.preferences.addons["cycles"].preferences.refresh_devices()

        fdict = {
            "ANGLE_1": 1,
            "ANGLE_2": 2,
            "FRONT": 3,
            "SIDE": 4,
            "TOP": 5,
        }
        s = bpy.context.scene
        s.frame_set(fdict[data["thumbnail_angle"]])

        snapdict = {
            "GROUND": "Ground",
            "WALL": "Wall",
            "CEILING": "Ceiling",
            "FLOAT": "Float",
        }

        collection = bpy.context.scene.collection.children[
            snapdict[data["thumbnail_snap_to"]]
        ]
        collection.hide_viewport = False
        collection.hide_render = False
        collection.hide_select = False

        main_object.rotation_euler = (0, 0, 0)

        # Add material replacement for printable assets
        # works directly with the specific material that has a color node for input
        if data.get("type") == "PRINTABLE":
            material = replace_materials(allobs, "PrintableMaterial")
            # Find the BaseColor node in this material
            base_color_node = material.node_tree.nodes.get("BaseColor")
            if base_color_node:
                # randomize the color value, needs to be defined by random hue and saturation = 0.95, we need to convert it to RGB then
                # random_color = (random.random(), 0.95, 0.5)
                # # convert to RGB
                # random_color = colorsys.hsv_to_rgb(
                #     random_color[0], random_color[1], random_color[2]
                # )
                random_color = data["thumbnail_material_color"]
                base_color_node.outputs[0].default_value = (
                    random_color[0],
                    random_color[1],
                    random_color[2],
                    1,
                )
                # now let's make background color complementary to the material color
                bpy.data.materials["bkit background"].node_tree.nodes[
                    "BaseColor"
                ].outputs["Color"].default_value = (
                    1 - random_color[0],
                    1 - random_color[1],
                    1 - random_color[2],
                    1,
                )

        bpy.data.materials["bkit background"].node_tree.nodes["Value"].outputs[
            "Value"
        ].default_value = data["thumbnail_background_lightness"]

        s.cycles.samples = data["thumbnail_samples"]
        bpy.context.view_layer.cycles.use_denoising = data["thumbnail_denoising"]
        bpy.context.view_layer.update()

        # import blender's HDR here
        # hdr_path = Path('datafiles/studiolights/world/interior.exr')
        # bpath = Path(bpy.utils.resource_path('LOCAL'))
        # ipath = bpath / hdr_path
        # ipath = str(ipath)

        # this  stuff is for mac and possibly linux. For blender // means relative path.
        # for Mac, // means start of absolute path
        # if ipath.startswith('//'):
        #     ipath = ipath[1:]
        #
        # img = bpy.data.images['interior.exr']
        # img.filepath = ipath
        # img.reload()

        bpy.context.scene.render.resolution_x = int(data["thumbnail_resolution"])
        bpy.context.scene.render.resolution_y = int(data["thumbnail_resolution"])

        bg_blender.progress("rendering thumbnail")
        render_thumbnails()
        if not data.get("upload_after_render") or not data.get("asset_data"):
            bg_blender.progress(
                "background autothumbnailer finished successfully (no upload)"
            )

            sys.exit(0)

        bg_blender.progress("uploading thumbnail")
        fpath = data["thumbnail_path"] + ".jpg"
        ok = client_lib.complete_upload_file_blocking(
            api_key=BLENDERKIT_EXPORT_API_KEY,
            asset_id=data["asset_data"]["id"],
            filepath=fpath,
            filetype=f"thumbnail",
            fileindex=0,
        )
        if not ok:
            bg_blender.progress("thumbnail upload failed, exiting")
            sys.exit(1)

        bg_blender.progress(
            "background autothumbnailer finished successfully (with upload)"
        )

    except Exception as e:
        print(f"background autothumbnailer failed: {e}")
        print_exc()
        sys.exit(1)
