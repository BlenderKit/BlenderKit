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

import addon_utils  # type: ignore[import-not-found]
import bpy


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
    # args order must match the order in blenderkit/client/main.go:PackBlendFile()!
    BLENDERKIT_EXPORT_DATA = sys.argv[-2]
    patch_imports(sys.argv[-1])
    addon_utils.enable(sys.argv[-1])

    from . import (  # we can do relative import because we set the __package__
        append_link,
    )

    try:
        # bg_blender.progress('preparing scene - append data')
        with open(BLENDERKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
            data = json.load(s)

        export_data = data["export_data"]
        upload_data = data["upload_data"]

        bpy.data.scenes.new("upload")  # type: ignore[union-attr]
        for s in bpy.data.scenes:  # type: ignore
            if s.name != "upload":
                bpy.data.scenes.remove(s)  # type: ignore

        if upload_data["assetType"] in ["model", "printable"]:
            obnames = export_data["models"]
            main_source, allobs = append_link.append_objects(
                file_name=export_data["source_filepath"],
                obnames=obnames,
                rotation=(0, 0, 0),
            )
            g = bpy.data.collections.new(upload_data["name"])  # type: ignore
            for o in allobs:
                g.objects.link(o)  # type: ignore
            bpy.context.scene.collection.children.link(g)  # type: ignore
        elif upload_data["assetType"] == "scene":
            sname = export_data["scene"]
            main_source = append_link.append_scene(
                file_name=export_data["source_filepath"], scenename=sname
            )
            bpy.data.scenes.remove(bpy.data.scenes["upload"])  # type: ignore
            main_source.name = sname
        elif upload_data["assetType"] == "material":
            matname = export_data["material"]
            main_source = append_link.append_material(
                file_name=export_data["source_filepath"], matname=matname
            )

        elif upload_data["assetType"] == "brush":
            brushname = export_data["brush"]
            main_source = append_link.append_brush(
                file_name=export_data["source_filepath"], brushname=brushname
            )
        elif upload_data["assetType"] == "nodegroup":
            toolname = export_data["nodegroup"]
            main_source, _ = append_link.append_nodegroup(
                file_name=export_data["source_filepath"], nodegroupname=toolname
            )
        if main_source.asset_data is None:
            main_source.asset_mark()

        try:
            # this needs to be in try statement because blender throws an error if not all textures aren't packed,
            # and we want to ignore that. Blender sometimes wants to pack textures that aren't actually needed
            # and are somehow still in the project.
            bpy.ops.file.pack_all()
        except Exception as e:
            print(f"Exception {type(e)} during pack_all(): {e}")

        main_source.blenderkit.uploading = False
        # write ID here.
        main_source.blenderkit.asset_base_id = export_data["assetBaseId"]
        main_source.blenderkit.id = export_data["id"]

        fpath = os.path.join(
            export_data["temp_dir"], upload_data["assetBaseId"] + ".blend"
        )

        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"

        try:
            # this needs to be in try statement because blender throws an error if not all textures aren't packed,
            # and we want to ignore that. Blender sometimes wants to pack textures that aren't actually needed
            # and are somehow still in the project. The problem might be when file isn't saved for reasons like full disk,
            # but it's much more rare.
            bpy.ops.wm.save_as_mainfile(filepath=fpath, compress=True, copy=False)
        except Exception as e:
            print(f"Exception {type(e)} during save_as_mainfile(): {e}")
        os.remove(export_data["source_filepath"])
    except Exception as e:
        print(f"Exception {type(e)} in upload_bg.py: {e}")
        sys.exit(1)
