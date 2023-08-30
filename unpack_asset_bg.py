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
import logging
import os
import sys
import time

import bpy

from blenderkit import paths, utils


bk_logger = logging.getLogger(__name__)


def get_texture_filepath(tex_dir_path, image, resolution="blend"):
    if len(image.packed_files) > 0:
        image_file_name = bpy.path.basename(image.packed_files[0].filepath)
    else:
        image_file_name = bpy.path.basename(image.filepath)
    if image_file_name == "":
        image_file_name = image.name.split(".")[0]

    suffix = paths.resolution_suffix[resolution]

    fp = os.path.join(tex_dir_path, image_file_name)
    # check if there is allready an image with same name and thus also assigned path
    # (can happen easily with genearted tex sets and more materials)
    done = False
    fpn = fp
    i = 0
    while not done:
        is_solo = True
        for image1 in bpy.data.images:
            if image != image1 and image1.filepath == fpn:
                is_solo = False
                fpleft, fpext = os.path.splitext(fp)
                fpn = fpleft + str(i).zfill(3) + fpext
                i += 1
        if is_solo:
            done = True

    return fpn


def unpack_asset(data):
    utils.p("unpacking asset")
    asset_data = data["asset_data"]

    resolution = asset_data.get("resolution", "blend")
    # TODO - passing resolution inside asset data might not be the best solution
    tex_dir_path = paths.get_texture_directory(asset_data, resolution=resolution)
    tex_dir_abs = bpy.path.abspath(tex_dir_path)
    if not os.path.exists(tex_dir_abs):
        try:
            os.mkdir(tex_dir_abs)
        except Exception as e:
            print(e)
    bpy.data.use_autopack = False
    for image in bpy.data.images:
        if image.name != "Render Result":
            # suffix = paths.resolution_suffix(data['suffix'])
            fp = get_texture_filepath(tex_dir_path, image, resolution=resolution)
            utils.p("unpacking file", image.name)
            utils.p(image.filepath, fp)

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
    if asset_data["assetType"] == "model":
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
        tags.new("description: " + asset_data["description"])
        tags.new("tags: " + ",".join(asset_data["tags"]))
    #
    # if this isn't here, blender crashes when saving file.
    if bpy.app.version >= (3, 0, 0):
        bpy.context.preferences.filepaths.file_preview_type = "NONE"

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, compress=False)
    # now try to delete the .blend1 file
    try:
        os.remove(bpy.data.filepath + "1")
    except Exception as e:
        print(e)
    bpy.ops.wm.quit_blender()
    sys.exit()


with open(sys.argv[-1], "r", encoding="utf-8") as f:
    data = json.load(f)

if __name__ == "__main__":
    unpack_asset(data)
