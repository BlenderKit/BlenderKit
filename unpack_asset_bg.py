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
import urllib.request
import uuid

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

    # check if there is already an image with same name and thus also assigned path
    # (can happen easily with generated tex sets and more materials)
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


def _resolve_author_name(asset_data: dict) -> str:
    author = asset_data.get("author") or {}
    full_name = author.get("fullName") or ""
    if full_name:
        return full_name
    first = author.get("firstName") or ""
    last = author.get("lastName") or ""
    return f"{first} {last}".strip()


def _resolve_thumbnail_url(asset_data: dict) -> str:
    for key in ("thumbnailMiddleUrl", "thumbnailSmallUrl", "thumbnailLargeUrl"):
        url = asset_data.get(key)
        if url:
            return str(url)

    for file in asset_data.get("files", []):
        if file.get("fileType") not in (
            "thumbnail",
            "photo_thumbnail",
            "wire_thumbnail",
        ):
            continue
        for key in (
            "thumbnailMiddleUrl",
            "thumbnailSmallUrl",
            "fileThumbnailLarge",
            "fileThumbnail",
        ):
            url = file.get(key)
            if url:
                return str(url)

    return ""


def _download_thumbnail(url: str) -> str:
    """Download the thumbnail image from the given URL and save it to the same directory as the current .blend file.

    Returns the file path of the downloaded thumbnail, or an empty string if the download failed.
    """
    if not url:
        return ""
    base_name = "preview.png"
    target_dir = os.path.dirname(bpy.data.filepath)
    if not target_dir:
        return ""
    target_path = os.path.join(target_dir, base_name)
    if os.path.exists(target_path):
        return target_path
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "BlenderKit")
        req.add_header("Accept", "image/*")
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(target_path, "wb") as handle:
                handle.write(response.read())
        return target_path
    except Exception:
        return ""


def _sanitize_preview_image(preview_path: str) -> str:
    """Some thumbnail images have issues libEx support.

    This function tries to sanitize the image by re-saving it as PNG from the blender.
    """
    if not preview_path or not os.path.exists(preview_path):
        return ""
    base_dir = os.path.dirname(preview_path)
    base_name = os.path.splitext(os.path.basename(preview_path))[0]
    sanitized_path = os.path.join(base_dir, f"{base_name}_clean.png")
    if os.path.exists(sanitized_path):
        return sanitized_path
    img = None
    try:
        img = bpy.data.images.load(preview_path, check_existing=False)
        img.filepath_raw = sanitized_path
        img.file_format = "PNG"
        img.save()
        return sanitized_path
    except Exception:
        return ""
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass


def _op_poll(op_callable, data_block) -> bool:
    """Check if the operator can run in the context of the given data block."""
    try:
        if hasattr(bpy.context, "temp_override"):
            with bpy.context.temp_override(id=data_block):
                return op_callable.poll()
        override = bpy.context.copy()
        override["id"] = data_block
        return op_callable.poll(override)
    except Exception:
        return False


def _op_call(op_callable, data_block, **kwargs):
    """Call the operator in the context of the given data block."""
    if hasattr(bpy.context, "temp_override"):
        with bpy.context.temp_override(id=data_block):
            return op_callable(**kwargs)
    override = bpy.context.copy()
    override["id"] = data_block
    return op_callable(override, **kwargs)


def _apply_asset_preview(data_block, asset_data: dict) -> None:
    """Apply asset preview image to the asset data block.

    It first tries to download the thumbnail from the URL provided in asset data.
    If that fails, it falls back to generating a preview within Blender."""
    if data_block is None:
        return
    print("🖼️  applying asset preview")
    url = _resolve_thumbnail_url(asset_data)
    preview_path = _download_thumbnail(url) if url else ""
    if preview_path:
        clean_path = _sanitize_preview_image(preview_path)
        if clean_path:
            preview_path = clean_path
        try:
            loaded = False
            if _op_poll(bpy.ops.ed.lib_id_load_custom_preview, data_block):
                result = _op_call(
                    bpy.ops.ed.lib_id_load_custom_preview,
                    data_block,
                    filepath=preview_path,
                )
                loaded = "FINISHED" in result
            if loaded:
                print("  Thumbnail preview applied successfully.")
                return
        except Exception as e:
            print(
                "Failed to load thumbnail preview, falling back to generating preview: "
                f"{e}"
            )

    try:
        if _op_poll(bpy.ops.ed.lib_id_generate_preview, data_block):
            _op_call(bpy.ops.ed.lib_id_generate_preview, data_block)
            print("  Generated preview applied successfully.")
    except Exception:
        print("Failed to generate preview, asset will have no preview")
        return


def _write_metadata(data_block, asset_data: dict) -> None:
    """Write asset metadata to the asset data block.

    This includes tags, author, and description."""
    if data_block is None:
        return
    print("📝  writing asset metadata")
    tags = data_block.asset_data.tags
    for t in tags:
        tags.remove(t)
    tags = data_block.asset_data.tags
    for t in asset_data.get("tags", []):
        tags.new(str(t))

    # assign more metadata in tags, so it is searchable in asset browser, and also visible in metadata panel
    other_meta = {}

    if asset_data.get("assetBaseId"):
        other_meta["id"] = asset_data["assetBaseId"]
    if asset_data.get("assetType"):
        other_meta["asset_type"] = asset_data.get("assetType", "")
    if asset_data.get("sourceAppVersion"):
        other_meta["source_app_version"] = asset_data.get("sourceAppVersion", "")

    # further custom meta from dictParameters
    dict_parameters = asset_data.get("dictParameters", {})
    if "category" in dict_parameters:
        other_meta["category"] = dict_parameters["category"]
    if "condition" in dict_parameters:
        other_meta["condition"] = dict_parameters["condition"]
    if "pbrType" in dict_parameters:
        other_meta["pbr_type"] = dict_parameters["pbrType"]
    if "materialStyle" in dict_parameters:
        other_meta["material_style"] = dict_parameters["materialStyle"]
    if "engine" in dict_parameters:
        other_meta["engine"] = dict_parameters["engine"]
    if "animated" in dict_parameters and dict_parameters["animated"]:
        other_meta["animated"] = "yes"
    if "simulation" in dict_parameters and dict_parameters["simulation"]:
        other_meta["simulation"] = "yes"

    description = asset_data.get("description", "")
    if description:
        other_meta["description"] = description
    author_name = _resolve_author_name(asset_data)
    if author_name:
        other_meta["author"] = author_name
    # ad additional metadata to tags
    for key, value in other_meta.items():
        tags.new(f"{key}:{value}")

    data_block.asset_data.author = author_name
    data_block.asset_data.description = description
    data_block.asset_data.copyright = asset_data.get("copyright", "")
    data_block.asset_data.license = asset_data.get("license", "")


def _resolve_catalog_name(asset_data: dict) -> str:
    asset_type = (asset_data.get("assetType") or "").lower()
    catalog_map = {
        "model": "Models",
        "material": "Materials",
        "hdr": "HDRIs",
        "hdri": "HDRIs",
        "printable": "Printables",
        "scene": "Scenes",
        "brush": "Brushes",
        "texture": "Textures",
        "nodegroup": "Node Groups",
        "addon": "Add-ons",
    }
    return catalog_map.get(asset_type, "")


def _ensure_catalog_exists(library_path: str, catalog_name: str) -> str:
    """Ensure that an asset catalog with the given name exists in the specified library.

    Returns the catalog ID if it exists or was created successfully, otherwise returns an empty string.
    """
    # TODO use python exposed API,  (currently only C API is available))
    head = (
        "# This is an Asset Catalog Definition file for Blender.\n"
        "#\n"
        "# Empty lines and lines starting with `#` will be ignored.\n"
        "# The first non-ignored line should be the version indicator.\n"
        '# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"\n'
        "\n"
        "VERSION 1\n"
    )

    # check if file exists in library, if not create it
    # this is needed to assign asset to catalog, otherwise it will be assigned to "unc
    cat_path = os.path.join(library_path, "blender_assets.cats.txt")
    if not os.path.exists(cat_path):
        try:
            with open(cat_path, "w", encoding="utf-8") as f:
                f.write(head)
        except Exception as e:
            traceback.print_exc()
            return ""
    # create file if it does not exists with uuid and name
    # get all catalogs in the file, if there is one with same name, return its uuid
    cats = {}
    # read existing catalogs
    with open(cat_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) != 3:
                continue
            cat_uuid, _, cat_simple_name = parts
            cats[cat_simple_name] = cat_uuid

    # use regex to found the library name
    if catalog_name in cats:
        return cats[catalog_name]

    # create new catalog entry
    new_uuid = str(uuid.uuid4())
    cats[catalog_name] = new_uuid

    # write new catalog entry to file
    try:
        with open(cat_path, "a", encoding="utf-8") as f:
            f.write(f"{new_uuid}:{catalog_name}:{catalog_name}\n")
        return new_uuid
    except Exception as e:
        traceback.print_exc()
        return ""


def _assign_asset_catalog(data_block, asset_data: dict) -> None:
    """Assign the asset to a catalog based on its type.

    The catalog is determined by the asset type (e.g. "model" assets go to "Models" catalog).
    The function ensures that the appropriate catalog exists in the library and assigns the asset to it.
    """
    if data_block is None or data_block.asset_data is None:
        return
    print("📁  assigning asset to catalog")
    # TODO get this somehow from the asset data, or pass it as argument, or use some convention to find it
    library_dir = os.path.join(os.path.expanduser("~"), "blenderkit_data")
    if not os.path.exists(library_dir):
        # check also two folders up from current blend file,
        # if user modified the default path to library in addon preferences,
        # we can not find it in user home dir
        this_blend_dir = os.path.dirname(bpy.data.filepath)
        library_dir = os.path.abspath(
            os.path.join(
                this_blend_dir,
                "..",
                "..",
            )
        )
        if not os.path.exists(library_dir):
            print(
                f"Asset catalog assignment skipped: library '{library_dir}' not found."
            )
            return
    print(f"Ensuring asset catalog exists in library '{library_dir}'")
    # create sub-catalog name based on asset type
    catalog_name = _resolve_catalog_name(asset_data)
    if not catalog_name:
        print(
            "Asset catalog assignment skipped: could not resolve catalog name from asset type."
        )
        return

    catalog_id = _ensure_catalog_exists(library_dir, catalog_name)
    if not catalog_id:
        print("Asset catalog assignment skipped: failed to create catalog entry.")
        return
    print(f"Assigning asset to catalog '{catalog_name}' with ID {catalog_id}")
    asset_meta = data_block.asset_data
    if hasattr(asset_meta, "catalog_id"):
        try:
            asset_meta.catalog_id = catalog_id
        except AttributeError:
            print("Asset catalog assignment skipped: catalog_id is read-only.")
    else:
        print(
            "Asset catalog assignment skipped: asset_data does not have catalog_id attribute."
        )
    if hasattr(asset_meta, "catalog_simple_name"):
        try:
            asset_meta.catalog_simple_name = catalog_name
        except AttributeError:
            print("Asset catalog assignment skipped: catalog_simple_name is read-only.")


def unpack_asset(data):
    """Unpack asset data into the current Blender file.

    This function handles unpacking textures, writing metadata,
    applying previews, and assigning the asset to a catalog based on its type.
    """
    asset_data = data["asset_data"]

    # assume unpack is true
    unpack = True
    if data.get("prefs", {}).get("unpack_files") is False:
        unpack = False

    # assume write_metadata is true
    write_metadata = True
    if data.get("prefs", {}).get("write_asset_metadata") is False:
        write_metadata = False

    if unpack:
        print("🗃️  unpacking asset")
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
    print("🏷️  marking asset")
    data_block = None
    if asset_data["assetType"] in ("model", "printable"):
        for ob in bpy.data.objects:
            if ob.parent is None and ob in bpy.context.visible_objects:
                if bpy.app.version >= (3, 0, 0):
                    ob.asset_mark()
                data_block = ob
    elif asset_data["assetType"] == "material":
        for m in bpy.data.materials:
            if bpy.app.version >= (3, 0, 0):
                m.asset_mark()
            data_block = m
    elif asset_data["assetType"] == "scene":
        if bpy.app.version >= (3, 0, 0):
            bpy.context.scene.asset_mark()
            data_block = bpy.context.scene
    elif asset_data["assetType"] == "brush":
        for b in bpy.data.brushes:
            if hasattr(b, "asset_data") and b.asset_data is not None:
                if bpy.app.version >= (3, 0, 0):
                    b.asset_mark()
                data_block = b
    elif asset_data["assetType"] == "nodegroup":
        for ng in bpy.data.node_groups:
            if hasattr(ng, "asset_data") and ng.asset_data is not None:
                if (
                    ng.asset_data.copyright == "Blender Foundation"
                    or ng.asset_data.is_property_readonly("author")
                ):
                    continue  # skip official node groups, they are not assets
                if bpy.app.version >= (3, 0, 0):
                    ng.asset_mark()
                data_block = ng

    if bpy.app.version >= (3, 0, 0) and data_block is not None and write_metadata:
        _write_metadata(data_block, asset_data)
        _apply_asset_preview(data_block, asset_data)
        _assign_asset_catalog(data_block, asset_data)

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
