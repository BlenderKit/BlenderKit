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


import json
import os
import sys
import traceback

import bpy


def get_texture_filepath(tex_dir_path, image, resolution="blend"):
    if len(image.packed_files) > 0:
        path = image.packed_files[0].filepath
    else:
        path = image.filepath
    # backslashes needs to be replaced because bpy.path.basename(path)
    # does not work on Mac for Windows paths
    path = path.replace("\\", "/")
    image_file_name = bpy.path.basename(path)
    if image_file_name == "":
        image_file_name = image.name.split(".")[0]

    # check if there is allready an image with same name and thus also assigned path
    # (can happen easily with genearted tex sets and more materials)
    file_path_original = os.path.join(tex_dir_path, image_file_name)
    file_path_final = file_path_original

    i = 0
    done = False
    while not done:
        is_solo = True
        for image1 in bpy.data.images:
            if image != image1 and image1.filepath == file_path_final:
                is_solo = False
                fpleft, fpext = os.path.splitext(file_path_original)
                file_path_final = fpleft + str(i).zfill(3) + fpext
                i += 1
        if is_solo:
            done = True

    return file_path_final


def get_resolution_from_file_path(file_path):
    possible_resolutions = {
        "_0_5K_": "resolution_0_5K",
        "_1K_": "resolution_1K",
        "_2K_": "resolution_2K",
        "_4K_": "resolution_4K",
        "_8K_": "resolution_8K",
    }
    for res in possible_resolutions:
        if res in file_path:
            return possible_resolutions[res]
    return "blend"


def unpack_asset(data):
    print("🗃️  unpacking asset")
    asset_data = data["asset_data"]
    resolution = get_resolution_from_file_path(bpy.data.filepath)

    # TODO - passing resolution inside asset data might not be the best solution
    tex_dir_path = paths.get_texture_directory(asset_data, resolution=resolution)
    tex_dir_abs = bpy.path.abspath(tex_dir_path)
    if not os.path.exists(tex_dir_abs):
        try:
            os.mkdir(tex_dir_abs)
        except Exception as e:
            traceback.print_exc()

    bpy.data.use_autopack = False
    for image in bpy.data.images:
        if image.name == "Render Result":
            continue  # skip rendered images

        # suffix = paths.resolution_suffix(data['suffix'])
        fp = get_texture_filepath(tex_dir_path, image, resolution=resolution)
        print(f"🖼️  unpacking file: {image.name} - {image.filepath}, {fp}")

        for pf in image.packed_files:
            pf.filepath = fp  # bpy.path.abspath(fp)
        image.filepath = fp  # bpy.path.abspath(fp)
        image.filepath_raw = fp  # bpy.path.abspath(fp)
        # image.save()
        if len(image.packed_files) > 0:
            # image.unpack(method='REMOVE')
            image.unpack(method="WRITE_ORIGINAL")

    # mark asset browser asset
    data_block = None
    if asset_data["assetType"] in ("model", "printable"):
        for ob in bpy.data.objects:
            if ob.parent is None and ob in bpy.context.visible_objects:
                if bpy.app.version >= (3, 0, 0):
                    ob.asset_mark()
        # for c in bpy.data.collections:
        #     if c.get('asset_data') is not None:
        #         if bpy.app.version >= (3, 0, 0):

        #         c.asset_mark()
        #         data_block = c
    elif asset_data["assetType"] == "material":
        for m in bpy.data.materials:
            if bpy.app.version >= (3, 0, 0):
                m.asset_mark()
            data_block = m
    elif asset_data["assetType"] == "scene":
        if bpy.app.version >= (3, 0, 0):
            bpy.context.scene.asset_mark()
    elif asset_data["assetType"] == "brush":
        for b in bpy.data.brushes:
            if b.get("asset_data") is not None:
                if bpy.app.version >= (3, 0, 0):
                    b.asset_mark()
                data_block = b
    if bpy.app.version >= (3, 0, 0) and data_block is not None:
        tags = data_block.asset_data.tags
        for t in tags:
            tags.remove(t)
        tags.new("description: " + asset_data.get("description", ""))
        tags.new("tags: " + ",".join(asset_data.get("tags", [])))

    # if this isn't here, blender crashes when saving file.
    if bpy.app.version >= (3, 0, 0):
        bpy.context.preferences.filepaths.file_preview_type = "NONE"

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, compress=False)
    # now try to delete the .blend1 file
    try:
        os.remove(bpy.data.filepath + "1")
    except Exception as e:
        traceback.print_exc()

    bpy.ops.wm.quit_blender()
    sys.exit()


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

    bpy.ops.preferences.extension_repo_add(  # type: ignore[attr-defined]
        name=parts[1], type="LOCAL"
    )  # Local is enough
    print(f"- Local repository {parts[1]} added")


if __name__ == "__main__":
    # args order must match the order in blenderkit/client/download.go:UnpackAsset()!
    json_path = sys.argv[-2]
    patch_imports(
        sys.argv[-1]
    )  # will be something like: "bl_ext.user_default.blenderkit" or "bl_ext.blenderkit_com.blenderkit", or just "blenderkit" on Blender < 4.2

    from . import paths

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    unpack_asset(data)
