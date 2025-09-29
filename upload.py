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
import re
import tempfile
from pathlib import Path
from typing import Optional

import bpy
from bpy.props import (  # TODO only keep the ones actually used when cleaning
    BoolProperty,
    EnumProperty,
    StringProperty,
)
from bpy.types import Operator

from . import (
    asset_bar_op,
    asset_inspector,
    autothumb,
    categories,
    client_lib,
    client_tasks,
    global_vars,
    image_utils,
    overrides,
    paths,
    reports,
    ui_panels,
    utils,
    search,
)


NAME_MINIMUM = 3
NAME_MAXIMUM = 40
TAGS_MINIMUM = 3
TAGS_MAXIMUM = 10
DESCRIPTION_MINIMUM = 20

BLENDERKIT_EXPORT_DATA_FILE = "data.json"
bk_logger = logging.getLogger(__name__)
licenses = (
    ("royalty_free", "Royalty Free", "royalty free commercial license"),
    ("cc_zero", "Creative Commons Zero", "Creative Commons Zero"),
)


def add_version(data):
    data["sourceAppName"] = "blender"
    data["sourceAppVersion"] = utils.get_blender_version()
    data["addonVersion"] = utils.get_addon_version()


def write_to_report(props, text):
    props.report = props.report + " - " + text + "\n\n"


def prevalidate_model(props):
    """Check model for possible problems:
    - check if all objects does not have asymmetrical scaling. Asymmetrical scaling is a big problem.
    Anything scaled away from (1,1,1) is a smaller problem. We do not check for that.
    """
    ob = utils.get_active_model()
    obs = utils.get_hierarchy(ob)
    for ob in obs:
        if ob.scale[0] != ob.scale[1] or ob.scale[1] != ob.scale[2]:
            write_to_report(
                props,
                f"Asymmetrical scaling in the object {ob.name} - please apply scale on all models",
            )


def get_model_materials():
    """get all materials in the asset hierarchy, will be used to validate materials in future"""
    ob = utils.get_active_model()
    obs = utils.get_hierarchy(ob)
    materials = []
    for ob in obs:
        if ob.type in ("MESH", "CURVE"):
            for mat in ob.data.materials:
                if mat not in materials:
                    materials.append(mat)
    return materials


def prevalidate_scene(props):
    """Check scene for possible problems:
    - check if user is author of all assets in scene"""
    problematic_assets = []
    for ob in bpy.context.scene.objects:
        if not ob.get("asset_data"):
            continue
        if utils.user_is_owner(ob["asset_data"]):
            continue
        asset_name = ob["asset_data"].get("name")
        author_name = ob["asset_data"].get("author", {}).get("fullName")
        problematic_assets.append(f"     - {asset_name} by {author_name}\n")

    if len(problematic_assets) == 0:
        return  # No problematic assets found

    oa_string = "".join(problematic_assets)
    write_to_report(
        props,
        f"Other author's assets are present in scene \n"
        f"   Remove assets by these authors before uploading the scene:\n"
        f"{oa_string}",
    )


def check_missing_data_model(props):
    autothumb.update_upload_model_preview(None, None)
    if props.engine == "NONE":
        write_to_report(props, "Set at least one rendering/output engine")

    # if not any(props.dimensions):
    #     write_to_report(props, 'Run autotags operator or fill in dimensions manually')


def check_missing_data_scene(props):
    autothumb.update_upload_model_preview(None, None)
    if props.engine == "NONE":
        write_to_report(props, "Set at least one rendering/output engine")


def check_missing_data_material(props):
    autothumb.update_upload_material_preview(None, None)
    if props.engine == "NONE":
        write_to_report(props, "Set rendering/output engine")


def check_missing_data_brush(props):
    autothumb.update_upload_brush_preview(None, None)


def check_missing_data(asset_type, props, upload_set):
    """Check if all required data is present and fills in the upload props with error messages."""
    props.report = ""

    if props.name == "":
        write_to_report(
            props,
            "A name is required.\n" "   Please provide a name for your asset.",
        )
    elif len(props.name) < NAME_MINIMUM:
        write_to_report(
            props,
            f"Name is too short.\n"
            f"   Please provide a name with at least {NAME_MINIMUM} characters.",
        )
    elif len(props.name) > NAME_MAXIMUM:
        write_to_report(
            props,
            f"Name is too long.\n"
            f"   Please provide a name with at most {NAME_MAXIMUM} characters.",
        )

    if props.is_private == "PUBLIC":
        category_ok = props.category == "NONE"
        subcategory_ok = props.subcategory != "EMPTY" and props.subcategory == "NONE"
        subcategory1_ok = props.subcategory1 != "EMPTY" and props.subcategory1 == "NONE"
        if category_ok or subcategory_ok or subcategory1_ok:
            write_to_report(
                props,
                "Category, subcategory, or sub-subcategory has not been selected.\n"
                "   Please ensure you select appropriate values; 'None' is not a valid selection.\n"
                "   Proper categorization significantly improves your asset's discoverability.",
            )

    if "THUMBNAIL" in upload_set:
        if asset_type in ("MODEL", "SCENE", "MATERIAL", "PRINTABLE"):
            thumb_path = bpy.path.abspath(props.thumbnail)
            if props.thumbnail == "":
                write_to_report(
                    props,
                    "A thumbnail image has not been provided.\n"
                    "   Please add a thumbnail in JPG or PNG format, ensuring at least 1024x1024 pixels.",
                )
            elif not os.path.exists(Path(thumb_path)):
                write_to_report(
                    props,
                    "Thumbnail filepath does not exist on the disk.\n"
                    "   Please check the filepath and try again.",
                )

        if asset_type == "BRUSH":
            brush = utils.get_active_brush()
            if brush is not None:
                thumb_path = bpy.path.abspath(brush.icon_filepath)
                if thumb_path == "":
                    write_to_report(
                        props,
                        "Brush Icon Filepath has not been provided.\n"
                        "   Please check Custom Icon option add a Brush Icon in JPG or PNG format, ensuring at least 1024x1024 pixels.",
                    )
                elif not os.path.exists(Path(thumb_path)):
                    write_to_report(
                        props,
                        "Brush Icon Filepath does not exist on the disk.\n"
                        "   Please check the filepath and try again.",
                    )
    if "PHOTO_THUMBNAIL" in upload_set:  # for printable assets
        # Add validation for the photo thumbnail for printable assets
        # only if it's in the upload set

        if props.photo_thumbnail_will_upload_on_website:
            pass
        else:
            foto_thumb_path = bpy.path.abspath(props.photo_thumbnail)
            if props.photo_thumbnail == "":
                write_to_report(
                    props,
                    "A photo thumbnail image has not been provided.\n"
                    "   Please add a photo of the 3D printed object in JPG or PNG format, ensuring at least 1024x1024 pixels.",
                )
            elif not os.path.exists(Path(foto_thumb_path)):
                write_to_report(
                    props,
                    "Photo thumbnail filepath does not exist on the disk.\n"
                    "   Please check the filepath and try again.",
                )

    if props.is_private == "PUBLIC":
        check_public_requirements(props)

    if asset_type in ("MODEL", "PRINTABLE"):
        prevalidate_model(props)
        check_missing_data_model(props)
    elif asset_type == "SCENE":
        prevalidate_scene(props)
        check_missing_data_scene(props)
    elif asset_type == "MATERIAL":
        check_missing_data_material(props)
    elif asset_type == "BRUSH":
        check_missing_data_brush(props)

    if props.report != "":
        props.report = (
            f"Before {props.is_private.lower()} upload, please fix:\n\n" + props.report
        )


def check_public_requirements(props):
    """Check requirements for public upload. Add error message into props.report if needed."""
    if props.description == "":
        write_to_report(
            props,
            "No asset description has been provided.\n"
            f"   Please write a description of at least {DESCRIPTION_MINIMUM} characters.\n"
            "   A comprehensive description enhances your asset's visibility\n"
            "   in relevant search results.",
        )
    elif len(props.description) < DESCRIPTION_MINIMUM:
        write_to_report(
            props,
            "The asset description provided is too brief.\n"
            f"   Please ensure your description is at least {DESCRIPTION_MINIMUM} characters long.\n"
            "   A comprehensive description enhances your asset's visibility\n"
            "   in relevant search results.",
        )

    if props.tags == "":
        write_to_report(
            props,
            "No tags have been provided for your asset.\n"
            f"   Please add at least {TAGS_MINIMUM} tags to improve its discoverability.\n"
            "   Tags enhance your asset's visibility in relevant search results.",
        )
    elif len(props.tags.split(",")) < TAGS_MINIMUM:
        write_to_report(
            props,
            "Not enough tags have been provided for your asset.\n"
            f"   Please ensure you have at least {TAGS_MINIMUM} tags to improve its discoverability.\n"
            "   Tags enhance your asset's visibility in relevant search results.",
        )


def check_tags_format(tags_string: str):
    """Check if tags string is a comma-separated list of tags consisting of only alphanumeric characters and underscores.
    Returns a bool and list of tags that do not meet the format requirement.
    """
    tags_string = tags_string.strip()
    if tags_string == "":
        return True, []
    tags = tags_string.split(",")
    problematic_tags = []
    for tag in tags:
        tag = tag.strip()
        if tag == "" or not re.match("^[0-9a-zA-Z_]+$", tag):
            problematic_tags.append(tag)

    if len(problematic_tags) > 0:
        return False, problematic_tags

    return True, problematic_tags


def sub_to_camel(content):
    replaced = re.sub(r"_.", lambda m: m.group(0)[1].upper(), content)
    return replaced


def get_upload_data(caller=None, context=None, asset_type=None):
    """
    works though metadata from addom props and prepares it for upload to dicts.
    Parameters
    ----------
    caller - upload operator or none
    context - context
    asset_type - asset type in capitals (blender enum)

    Returns
    -------
    export_ddta- all extra data that the process needs to upload and communicate with UI from a thread.
        - eval_path_computing - string path to UI prop that denots if upload is still running
        - eval_path_state - string path to UI prop that delivers messages about upload to ui
        - eval_path - path to object holding upload data to be able to access it with various further commands
        - models - in case of model upload, list of objects
        - thumbnail_path - path to thumbnail file

    upload_data - asset_data generated from the ui properties

    """
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    export_data = {
        # "type": asset_type,
    }
    upload_params = {}
    if asset_type in ("MODEL", "PRINTABLE"):
        # Prepare to save the file
        mainmodel = utils.get_active_model()

        props = mainmodel.blenderkit

        obs = utils.get_hierarchy(mainmodel)
        obnames = []
        for ob in obs:
            obnames.append(ob.name)
        export_data["models"] = obnames
        export_data["thumbnail_path"] = bpy.path.abspath(props.thumbnail)

        # Add photo thumbnail path to export_data for printable assets
        if asset_type == "PRINTABLE" and props.photo_thumbnail:
            export_data["photo_thumbnail_path"] = bpy.path.abspath(
                props.photo_thumbnail
            )

        eval_path_computing = (
            "bpy.data.objects['%s'].blenderkit.uploading" % mainmodel.name
        )
        eval_path_state = (
            "bpy.data.objects['%s'].blenderkit.upload_state" % mainmodel.name
        )
        eval_path = "bpy.data.objects['%s']" % mainmodel.name

        upload_data = {
            "assetType": asset_type.lower(),
        }

        # Common parameters for both MODEL and PRINTABLE
        upload_params = {
            "faceCount": props.face_count,
            "modifiers": utils.string2list(props.modifiers),
            "dimensionX": round(props.dimensions[0], 4),
            "dimensionY": round(props.dimensions[1], 4),
            "dimensionZ": round(props.dimensions[2], 4),
            "boundBoxMinX": round(props.bbox_min[0], 4),
            "boundBoxMinY": round(props.bbox_min[1], 4),
            "boundBoxMinZ": round(props.bbox_min[2], 4),
            "boundBoxMaxX": round(props.bbox_max[0], 4),
            "boundBoxMaxY": round(props.bbox_max[1], 4),
            "boundBoxMaxZ": round(props.bbox_max[2], 4),
        }

        # Additional parameters only for MODEL type
        if asset_type == "MODEL":
            engines = [props.engine.lower()]
            if props.engine1 != "NONE":
                engines.append(props.engine1.lower())
            if props.engine2 != "NONE":
                engines.append(props.engine2.lower())
            if props.engine3 != "NONE":
                engines.append(props.engine3.lower())
            if props.engine == "OTHER":
                engines.append(props.engine_other.lower())

            style = props.style.lower()

            upload_params.update(
                {
                    "productionLevel": props.production_level.lower(),
                    "modelStyle": style,
                    "engines": engines,
                    "materials": utils.string2list(props.materials),
                    "shaders": utils.string2list(props.shaders),
                    "uv": props.uv,
                    "animated": props.animated,
                    "rig": props.rig,
                    "simulation": props.simulation,
                    "purePbr": props.pbr,
                    "faceCountRender": props.face_count_render,
                    "manifold": props.manifold,
                    "objectCount": props.object_count,
                    "procedural": props.is_procedural,
                    "nodeCount": props.node_count,
                    "textureCount": props.texture_count,
                    "megapixels": props.total_megapixels,
                }
            )

            if props.use_design_year:
                upload_params["designYear"] = props.design_year
            if props.condition != "UNSPECIFIED":
                upload_params["condition"] = props.condition.lower()
            if props.pbr:
                pt = props.pbr_type
                pt = pt.lower()
                upload_params["pbrType"] = pt
            if props.texture_resolution_max > 0:
                upload_params["textureResolutionMax"] = props.texture_resolution_max
                upload_params["textureResolutionMin"] = props.texture_resolution_min
            if props.mesh_poly_type != "OTHER":
                upload_params["meshPolyType"] = props.mesh_poly_type.lower()

        # Common optional parameters for both MODEL and PRINTABLE
        optional_params = [
            "manufacturer",
            "designer",
            "design_collection",
            "design_variant",
        ]
        for p in optional_params:
            if eval("props.%s" % p) != "":
                upload_params[sub_to_camel(p)] = eval("props.%s" % p)

        if props.use_design_year:
            upload_params["designYear"] = props.design_year

        if props.sexualized_content:
            upload_params["sexualizedContent"] = props.sexualized_content

    elif asset_type == "SCENE":
        # Prepare to save the file
        s = bpy.context.scene

        props = s.blenderkit

        export_data["scene"] = s.name
        export_data["thumbnail_path"] = bpy.path.abspath(props.thumbnail)

        eval_path_computing = "bpy.data.scenes['%s'].blenderkit.uploading" % s.name
        eval_path_state = "bpy.data.scenes['%s'].blenderkit.upload_state" % s.name
        eval_path = "bpy.data.scenes['%s']" % s.name

        engines = [props.engine.lower()]
        if props.engine1 != "NONE":
            engines.append(props.engine1.lower())
        if props.engine2 != "NONE":
            engines.append(props.engine2.lower())
        if props.engine3 != "NONE":
            engines.append(props.engine3.lower())
        if props.engine == "OTHER":
            engines.append(props.engine_other.lower())

        style = props.style.lower()
        # if style == 'OTHER':
        #     style = props.style_other.lower()

        upload_data = {
            "assetType": "scene",
        }
        upload_params = {
            "productionLevel": props.production_level.lower(),
            "modelStyle": style,
            "engines": engines,
            "modifiers": utils.string2list(props.modifiers),
            "materials": utils.string2list(props.materials),
            "shaders": utils.string2list(props.shaders),
            "uv": props.uv,
            "animated": props.animated,
            # "simulation": props.simulation,
            "purePbr": props.pbr,
            "faceCount": 1,  # props.face_count,
            "faceCountRender": 1,  # props.face_count_render,
            "objectCount": 1,  # props.object_count,
            # "scene": props.is_scene,
        }
        if props.use_design_year:
            upload_params["designYear"] = props.design_year
        if props.condition != "UNSPECIFIED":
            upload_params["condition"] = props.condition.lower()
        if props.pbr:
            pt = props.pbr_type
            pt = pt.lower()
            upload_params["pbrType"] = pt

        if props.texture_resolution_max > 0:
            upload_params["textureResolutionMax"] = props.texture_resolution_max
            upload_params["textureResolutionMin"] = props.texture_resolution_min
        if props.mesh_poly_type != "OTHER":
            upload_params["meshPolyType"] = (
                props.mesh_poly_type.lower()
            )  # .replace('_',' ')

    elif asset_type == "MATERIAL":
        mat = bpy.context.active_object.active_material
        props = mat.blenderkit

        # props.name = mat.name

        export_data["material"] = str(mat.name)
        export_data["thumbnail_path"] = bpy.path.abspath(props.thumbnail)
        # mat analytics happen here, since they don't take up any time...
        asset_inspector.check_material(props, mat)

        eval_path_computing = "bpy.data.materials['%s'].blenderkit.uploading" % mat.name
        eval_path_state = "bpy.data.materials['%s'].blenderkit.upload_state" % mat.name
        eval_path = "bpy.data.materials['%s']" % mat.name

        engine = props.engine
        if engine == "OTHER":
            engine = props.engine_other
        engine = engine.lower()
        style = props.style.lower()
        # if style == 'OTHER':
        #     style = props.style_other.lower()

        upload_data = {
            "assetType": "material",
        }

        upload_params = {
            "materialStyle": style,
            "engine": engine,
            "shaders": utils.string2list(props.shaders),
            "uv": props.uv,
            "animated": props.animated,
            "purePbr": props.pbr,
            "textureSizeMeters": props.texture_size_meters,
            "procedural": props.is_procedural,
            "nodeCount": props.node_count,
            "textureCount": props.texture_count,
            "megapixels": props.total_megapixels,
        }

        if props.pbr:
            upload_params["pbrType"] = props.pbr_type.lower()

        if props.texture_resolution_max > 0:
            upload_params["textureResolutionMax"] = props.texture_resolution_max
            upload_params["textureResolutionMin"] = props.texture_resolution_min

    elif asset_type == "BRUSH":
        brush = utils.get_active_brush()

        props = brush.blenderkit
        # props.name = brush.name

        export_data["brush"] = str(brush.name)
        export_data["thumbnail_path"] = bpy.path.abspath(brush.icon_filepath)

        eval_path_computing = "bpy.data.brushes['%s'].blenderkit.uploading" % brush.name
        eval_path_state = "bpy.data.brushes['%s'].blenderkit.upload_state" % brush.name
        eval_path = "bpy.data.brushes['%s']" % brush.name

        # mat analytics happen here, since they don't take up any time...

        brush_type = ""
        if bpy.context.sculpt_object is not None:
            brush_type = "sculpt"

        elif bpy.context.image_paint_object:  # could be just else, but for future p
            brush_type = "texture_paint"

        upload_params = {
            "mode": brush_type,
        }

        upload_data = {
            "assetType": "brush",
        }

    elif asset_type == "HDR":
        ui_props = bpy.context.window_manager.blenderkitUI

        # imagename = ui_props.hdr_upload_image
        image = ui_props.hdr_upload_image  # bpy.data.images.get(imagename)
        if not image:
            return None, None

        props = image.blenderkit

        image_utils.analyze_image_is_true_hdr(image)

        # props.name = brush.name
        base, ext = os.path.splitext(image.filepath)
        thumb_path = base + ".jpg"
        export_data["thumbnail_path"] = bpy.path.abspath(thumb_path)

        export_data["hdr"] = str(image.name)
        export_data["hdr_filepath"] = str(bpy.path.abspath(image.filepath))
        # export_data["thumbnail_path"] = bpy.path.abspath(brush.icon_filepath)

        eval_path_computing = "bpy.data.images['%s'].blenderkit.uploading" % image.name
        eval_path_state = "bpy.data.images['%s'].blenderkit.upload_state" % image.name
        eval_path = "bpy.data.images['%s']" % image.name

        # mat analytics happen here, since they don't take up any time...

        upload_params = {
            "textureResolutionMax": props.texture_resolution_max,
            "trueHDR": props.true_hdr,
        }

        upload_data = {
            "assetType": "hdr",
        }

    elif asset_type == "TEXTURE":
        style = props.style
        # if style == 'OTHER':
        #     style = props.style_other

        upload_data = {
            "assetType": "texture",
        }
        upload_params = {
            "style": style,
            "animated": props.animated,
            "purePbr": props.pbr,
            "resolution": props.resolution,
        }
        if props.pbr:
            pt = props.pbr_type
            pt = pt.lower()
            upload_data["pbrType"] = pt

    elif asset_type == "NODEGROUP":
        ui_props = bpy.context.window_manager.blenderkitUI
        bk_logger.info("preparing nodegroup upload")
        asset = ui_props.nodegroup_upload
        bk_logger.info("asset:" + str(asset))
        if not asset:
            return None, None

        props = asset.blenderkit

        export_data["nodegroup"] = str(asset.name)
        export_data["thumbnail_path"] = bpy.path.abspath(props.thumbnail)
        eval_path_computing = (
            f"bpy.data.node_groups['{asset.name}'].blenderkit.uploading"
        )
        eval_path_state = (
            f"bpy.data.node_groups['{asset.name}'].blenderkit.upload_state"
        )
        eval_path = f"bpy.data.node_groups['{asset.name}']"

        # mat analytics happen here, since they don't take up any time...

        upload_params = {"nodeType": asset.type.lower()}

        upload_data = {
            "assetType": "nodegroup",
        }
    add_version(upload_data)

    # caller can be upload operator, but also asset bar called from tooltip generator
    if caller and caller.properties.main_file is True:
        upload_data["name"] = props.name
        upload_data["displayName"] = props.name
    else:
        upload_data["displayName"] = props.name

    upload_data["description"] = props.description
    upload_data["tags"] = utils.string2list(props.tags)
    # category is always only one value by a slug, that's why we go down to the lowest level and overwrite.
    if props.category == "" or props.category == "NONE":
        upload_data["category"] = asset_type.lower()
    else:
        upload_data["category"] = props.category
    if props.subcategory not in (
        "NONE",
        "EMPTY",
        "OTHER",
    ):  # if OTHER category is selected, parent category will be used
        upload_data["category"] = props.subcategory
    if props.subcategory1 not in (
        "NONE",
        "EMPTY",
        "OTHER",
    ):  # if OTHER category is selected, parent category will be used
        upload_data["category"] = props.subcategory1

    upload_data["license"] = props.license
    upload_data["isFree"] = props.is_free == "FREE"
    upload_data["isPrivate"] = props.is_private == "PRIVATE"
    upload_data["token"] = user_preferences.api_key

    upload_data["parameters"] = upload_params

    # if props.asset_base_id != '':
    export_data["assetBaseId"] = props.asset_base_id
    export_data["id"] = props.id
    export_data["eval_path_computing"] = eval_path_computing
    export_data["eval_path_state"] = eval_path_state
    export_data["eval_path"] = eval_path
    bk_logger.info("export_data:" + str(export_data))

    return export_data, upload_data


def update_free_full(self, context):
    if self.asset_type == "material":
        if self.free_full == "FULL":
            self.free_full = "FREE"
            ui_panels.ui_message(
                title="All BlenderKit materials are free",
                message="Any material uploaded to BlenderKit is free."
                " However, it can still earn money for the author,"
                " based on our fair share system. "
                "Part of subscription is sent to artists based on usage by paying users.",
            )


def can_edit_asset(active_index: int = -1, asset_data: Optional[dict] = None):
    if active_index < 0 and not asset_data:
        return False
    profile = global_vars.BKIT_PROFILE
    if profile is None:
        return False
    if utils.profile_is_validator():
        return True
    if not asset_data:
        sr = search.get_search_results()
        asset_data = dict(sr[active_index])
    if int(asset_data["author"]["id"]) == profile.id:
        return True
    return False


class FastMetadata(bpy.types.Operator):
    """Edit metadata of the asset"""

    bl_idname = "wm.blenderkit_fast_metadata"
    bl_label = "Update metadata"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    asset_id: StringProperty(  # type: ignore[valid-type]
        name="Asset Base Id",
        description="Unique name of the asset (hidden)",
        default="",
    )
    asset_type: StringProperty(name="Asset Type", description="Asset Type", default="")  # type: ignore[valid-type]
    name: StringProperty(  # type: ignore[valid-type]
        name="Name",
        description="Provide name of your asset, choose a few descriptive English words that clearly identify and distinguish your asset. Good naming helps your asset to be found on the search engine. Follow these tips:\n\n"
        "Use Descriptive Terms:\nInclude specific details such as the brand, material, or distinct features of the asset.\n\n"
        "Avoid Generic or Vague Terms:\nNames like 'Sky 01' or 'Big Tree' are too general and not helpful for search optimization. Instead, use names that provide meaningful information about the asset.\n\n"
        "Highlight Key Attributes:\nIncorporate important attributes that are likely to be used in search queries, such as the model in vehicles or the designer in furniture.\n\n"
        "Bad names: Chair 01, Nice Car, Statue\n"
        "Good names: Knoll Steel Chair, Skoda Kodiaq, Statue of Liberty",
        default="",
    )
    description: StringProperty(  # type: ignore[valid-type]
        name="Description",
        description="Provide a clear and concise description of your asset in English. To enhance searchability and discoverability of your asset, follow these tips:\n\n"
        "Be Specific:\nUse precise terms that accurately reflect the asset. Include key characteristics such as material, color, function, or designer/brand.\n\n"
        "Use Recognizable Keywords:\nIncorporate well-known and relevant keywords that users are likely to search for. This includes brand names, designer names, common usage, and industry-specific terms.\n\n"
        "Avoid Jargon:\nUnless industry-specific terms are widely understood by your target audience, use simple language that is easy to understand.\n\n"
        "Highlight Unique Features:\nMention any distinctive features that set the asset apart from others, such as a unique design, special function, or notable collaboration.\n\n"
        "Keep it Brief:\nAim for a short description that captures the essence of the asset without unnecessary details. A concise description makes it easier for Elasticsearch to process and for users to scan",
        default="",
    )
    tags: StringProperty(  # type: ignore[valid-type]
        name="Tags",
        description="Enter up to 10 tags, separated by commas. Tags may include alphanumeric characters and underscores only. For better discoverability, follow these tips:\n\n"
        "Choose Relevant Keywords:\nSelect tags that closely relate to the asset's features, usage, or industry terms. This increases the chances that your asset appears in relevant searches.\n\n"
        "Include Synonyms:\nAdd variations or synonyms to cover different ways users might search for similar items. Especially consider synonyms for terms used in the asset's name or description to broaden search relevancy.\n\n"
        "Prioritize Common Terms:\nUse commonly searched terms within your target audience. This helps connect your assets to the most likely queries.\n\n"
        "Enhance with Specificity: While common terms are essential, adding specific tags can help in uniquely identifying and categorizing the asset. This is particularly useful for users looking for particular features or attributes.",
        default="",
    )
    category: EnumProperty(  # type: ignore[valid-type]
        name="Category",
        description="Select the main category for the uploaded asset. "
        "Choose the most accurate category to enhance visibility and download rates. "
        "Proper categorization ensures your asset reaches people actively searching for assets like yours",
        items=categories.get_category_enums,
        update=categories.update_category_enums,
    )
    subcategory: EnumProperty(  # type: ignore[valid-type]
        name="Subcategory",
        description="Select a subcategory within the chosen main category",
        items=categories.get_subcategory_enums,
        update=categories.update_subcategory_enums,
    )
    subcategory1: EnumProperty(  # type: ignore[valid-type]
        name="Sub-subcategory",
        description="Select a further subcategory within the chosen subcategory",
        items=categories.get_subcategory1_enums,
    )
    license: EnumProperty(  # type: ignore[valid-type]
        items=licenses,
        default="royalty_free",
        description="License. Please read our help for choosing the right licenses",
    )
    is_private: EnumProperty(  # type: ignore[valid-type]
        name="Thumbnail Style",
        items=(
            (
                "PRIVATE",
                "Private",
                "You asset will be hidden to public. The private assets are limited by a quota.",
            ),
            (
                "PUBLIC",
                "Public",
                '"Your asset will go into the validation process automatically',
            ),
        ),
        description="If not marked private, your asset will go into the validation process automatically\n"
        "Private assets are limited by quota",
        default="PUBLIC",
    )
    sexualized_content: BoolProperty(  # type: ignore[valid-type]
        name="Sexualized content",
        description=(
            "Flag this asset if it includes explicit content, suggestive poses, or overemphasized secondary sexual characteristics. "
            "This helps users filter content according to their preferences, creating a safe and inclusive browsing experience for all.\n\n"
            "Flag not required:\n"
            "- naked base mesh model,\n"
            "- figure in underwear/swimwear in neutral position.\n\n"
            "Flag required:\n"
            "- figure in sexually suggestive pose,\n"
            "- figure with over overemphasized sexual characteristics,\n"
            "- objects related to sexual act."
        ),
        default=False,
    )
    free_full: EnumProperty(  # type: ignore[valid-type]
        name="Free or Full Plan",
        items=(
            (
                "FREE",
                "Free",
                "You consent you want to release this asset as free for everyone",
            ),
            ("FULL", "Full", "Your asset will be in the full plan"),
        ),
        description="Choose whether the asset should be free or in the Full Plan",
        default="FULL",
        update=update_free_full,
    )

    ####################

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        # col = layout.column()
        layout.label(text=self.message)
        layout.prop(self, "category")
        if self.category != "NONE" and self.subcategory != "EMPTY":
            layout.prop(self, "subcategory")
        if self.subcategory != "NONE" and self.subcategory1 != "EMPTY":
            layout.prop(self, "subcategory1")
        layout.prop(self, "name")
        layout.prop(self, "description")
        layout.prop(self, "tags")
        layout.prop(self, "is_private", expand=True)
        layout.prop(self, "free_full", expand=True)
        if self.is_private == "PUBLIC":
            layout.prop(self, "license")
        # layout.label(text="Content Flags:")
        content_flag_box = layout.box()
        content_flag_box.alignment = "EXPAND"
        content_flag_box.label(text="Sensitive Content Flags:")
        content_flag_box.prop(self, "sexualized_content")

    def execute(self, context):
        if self.subcategory1 not in ("NONE", "EMPTY"):
            category = self.subcategory1
        elif self.subcategory not in ("NONE", "EMPTY"):
            category = self.subcategory
        else:
            category = self.category
        utils.update_tags(self, context)
        metadata = {
            "category": category,
            "displayName": self.name,
            "description": self.description,
            "tags": utils.string2list(self.tags),
            "isPrivate": self.is_private == "PRIVATE",
            "isFree": self.free_full == "FREE",
            "license": self.license,
            "parameters": [
                {
                    "parameterType": "sexualizedContent",
                    "value": self.sexualized_content,
                },
            ],
        }
        url = f"{paths.BLENDERKIT_API}/assets/{self.asset_id}/"
        messages = {
            "success": "Metadata upload succeded",
            "error": "Metadata upload failed",
        }
        client_lib.nonblocking_request(url, "PATCH", {}, metadata, messages)
        return {"FINISHED"}

    def invoke(self, context, event):
        ui_props = bpy.context.window_manager.blenderkitUI
        if ui_props.active_index > -1:
            sr = search.get_search_results()
            asset_data = dict(sr[ui_props.active_index])
        else:
            active_asset = utils.get_active_asset_by_type(asset_type=self.asset_type)
            asset_data = active_asset.get("asset_data")

        if not can_edit_asset(asset_data=asset_data):
            return {"CANCELLED"}
        self.asset_id = asset_data["id"]
        self.asset_type = asset_data["assetType"]
        cat_path = categories.get_category_path(
            global_vars.DATA["bkit_categories"], asset_data["category"]
        )
        try:
            if len(cat_path) > 1:
                self.category = cat_path[1]
            if len(cat_path) > 2:
                self.subcategory = cat_path[2]
        except Exception as e:
            bk_logger.error(e)

        self.message = f"Fast edit metadata of {asset_data['displayName']}"
        self.name = asset_data["displayName"]
        self.description = asset_data["description"]
        self.tags = ",".join(asset_data["tags"])
        if asset_data["isPrivate"]:
            self.is_private = "PRIVATE"
        else:
            self.is_private = "PUBLIC"

        if asset_data["isFree"]:
            self.free_full = "FREE"
        else:
            self.free_full = "FULL"
        self.license = asset_data["license"]
        self.sexualized_content = asset_data.get("dictParameters", {}).get(
            "sexualizedContent", False
        )

        wm = context.window_manager

        return wm.invoke_props_dialog(self, width=600)


def get_upload_location(props):
    """
    not used by now, gets location of uploaded asset - potentially usefull if we draw a nice upload gizmo in viewport.
    Parameters
    ----------
    props

    Returns
    -------

    """
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type == "MODEL":
        if bpy.context.view_layer.objects.active is not None:
            ob = utils.get_active_model()
            return ob.location
    if ui_props.asset_type == "SCENE":
        return None
    elif ui_props.asset_type == "MATERIAL":
        if (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        ):
            return bpy.context.active_object.location
    elif ui_props.asset_type == "TEXTURE":
        return None
    elif ui_props.asset_type == "BRUSH":
        return None
    return None


def storage_quota_available(props) -> bool:
    """Check the storage quota if there is available space to upload."""
    profile = global_vars.BKIT_PROFILE
    if profile is None:
        props.report = "Please log-in first."
        return False

    if props.is_private == "PUBLIC":
        return True

    if profile.remainingPrivateQuota is not None and profile.remainingPrivateQuota > 0:
        return True

    props.report = "Private storage quota exceeded."
    return False


def auto_fix(asset_type=""):
    # this applies various procedures to ensure coherency in the database.
    asset = utils.get_active_asset()
    props = utils.get_upload_props()
    if asset_type == "MATERIAL":
        overrides.ensure_eevee_transparency(asset)
        asset.name = props.name


def prepare_asset_data(self, context, asset_type, reupload, upload_set):
    """Process asset and its data for upload."""
    props = utils.get_upload_props()
    utils.name_update(props)  # fix the name first

    if storage_quota_available(props) is False:
        self.report({"ERROR_INVALID_INPUT"}, props.report)
        return False, None, None

    auto_fix(asset_type=asset_type)

    # do this for fixing long tags in some upload cases
    props.tags = props.tags[:]

    # check for missing metadata

    check_missing_data(asset_type, props, upload_set=upload_set)
    # if previous check did find any problems then
    if props.report != "":
        return False, None, None

    if not reupload:
        props.asset_base_id = ""
        props.id = ""

    export_data, upload_data = get_upload_data(
        caller=self, context=context, asset_type=asset_type
    )

    # check if thumbnail exists, generate for HDR:
    if "THUMBNAIL" in upload_set:
        if asset_type == "HDR":
            image_utils.generate_hdr_thumbnail()
            # get upload data because the image utils function sets true_hdr
            export_data, upload_data = get_upload_data(
                caller=self, context=context, asset_type=asset_type
            )

        elif not os.path.exists(export_data["thumbnail_path"]):
            props.upload_state = "0% - thumbnail not found"
            props.uploading = False
            return False, None, None

    # Check if photo thumbnail exists for printable assets when it's included in upload_set
    if "photo_thumbnail" in upload_set:
        if asset_type == "PRINTABLE" and "photo_thumbnail_path" in export_data:
            if not os.path.exists(export_data["photo_thumbnail_path"]):
                props.upload_state = "0% - photo thumbnail not found"
                props.uploading = False
                return False, None, None

    # save a copy of the file for processing. Only for blend files
    _, ext = os.path.splitext(bpy.data.filepath)
    if not ext:
        ext = ".blend"
    export_data["temp_dir"] = tempfile.mkdtemp()
    export_data["source_filepath"] = os.path.join(
        export_data["temp_dir"], "export_blenderkit" + ext
    )
    if asset_type != "HDR":
        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"

        bpy.ops.wm.save_as_mainfile(
            filepath=export_data["source_filepath"], compress=False, copy=True
        )

    export_data["binary_path"] = bpy.app.binary_path
    export_data["debug_value"] = bpy.app.debug_value

    return True, upload_data, export_data


asset_types = (
    ("MODEL", "Model", "Set of objects"),
    ("SCENE", "Scene", "Scene"),
    ("HDR", "HDR", "HDR image"),
    ("MATERIAL", "Material", "Any .blend Material"),
    ("TEXTURE", "Texture", "A texture, or texture set"),
    ("BRUSH", "Brush", "Brush, can be any type of blender brush"),
    ("NODEGROUP", "Tool", "Geometry nodes tool"),
    ("PRINTABLE", "Printable", "3D printable model"),
    ("ADDON", "Addon", "Addon"),
)


class UploadOperator(Operator):
    """Tooltip"""

    bl_idname = "object.blenderkit_upload"
    bl_description = "Upload or re-upload asset + thumbnail + metadata"

    bl_label = "BlenderKit Asset Upload"
    bl_options = {"REGISTER", "INTERNAL"}

    # type of upload - model, material, textures, e.t.c.
    asset_type: EnumProperty(  # type: ignore[valid-type]
        name="Type",
        items=asset_types,
        description="Type of upload",
        default="MODEL",
    )

    reupload: BoolProperty(  # type: ignore[valid-type]
        name="reupload",
        description="reupload but also draw so that it asks what to reupload",
        default=False,
        options={"SKIP_SAVE"},
    )

    metadata: BoolProperty(name="metadata", default=True, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    thumbnail: BoolProperty(name="thumbnail", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    # Add new property for photo thumbnail
    photo_thumbnail: BoolProperty(name="photo thumbnail", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    main_file: BoolProperty(name="main file", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context):
        return utils.uploadable_asset_poll()

    def execute(self, context):
        bpy.ops.object.blenderkit_auto_tags()
        props = utils.get_upload_props()

        upload_set = []
        if not self.reupload:
            upload_set = ["METADATA", "THUMBNAIL", "MAINFILE"]
            # Add photo_thumbnail to the upload set for printable assets
            if self.asset_type == "PRINTABLE" and props.photo_thumbnail:
                upload_set.append("photo_thumbnail")
        else:
            if self.metadata:
                upload_set.append("METADATA")
            if self.thumbnail:
                upload_set.append("THUMBNAIL")
            if self.photo_thumbnail:
                upload_set.append("photo_thumbnail")
            if self.main_file:
                upload_set.append("MAINFILE")

        # this is accessed later in get_upload_data and needs to be written.
        # should pass upload_set all the way to it probably
        if "MAINFILE" in upload_set:
            self.main_file = True

        ok, upload_data, export_data = prepare_asset_data(
            self, context, self.asset_type, self.reupload, upload_set=upload_set
        )
        if not ok:
            self.report({"ERROR_INVALID_INPUT"}, props.report)
            props.upload_state = ""
            return {"CANCELLED"}

        props.upload_state = "Upload initiating..."
        props.uploading = True

        client_lib.asset_upload(upload_data, export_data, upload_set)
        return {"FINISHED"}

    def draw(self, context):
        props = utils.get_upload_props()
        layout = self.layout

        if self.reupload:
            utils.label_multiline(
                layout,
                text="To update only metadata of the model, keep checkboxes unchecked",
                width=500,
            )
            # layout.prop(self, 'metadata')
            layout.prop(self, "main_file")
            layout.prop(self, "thumbnail")

            # Show photo_thumbnail option only for printable assets
            if self.asset_type == "PRINTABLE":
                layout.prop(self, "photo_thumbnail")

        if props.asset_base_id != "" and not self.reupload:
            utils.label_multiline(
                layout,
                text="Really upload as new?\n\n"
                "Do this only when you create a new asset from an old one.\n"
                "For updates of thumbnail or model use reupload.\n",
                width=400,
                icon="ERROR",
            )

        if props.is_private == "PUBLIC":
            if self.asset_type == "MODEL":
                utils.label_multiline(
                    layout,
                    text="\nYou marked the asset as public. "
                    "This means it will be validated by our team.\n\n"
                    "Please test your upload after it finishes:\n"
                    "-   Open a new file\n"
                    "-   Find the asset and download it\n"
                    "-   Check if it snaps correctly to surfaces\n"
                    "-   Check if it has all textures and renders as expected\n"
                    "-   Check if it has correct size in world units (for models)",
                    width=400,
                )
            elif self.asset_type == "HDR":
                if not props.true_hdr:
                    utils.label_multiline(
                        layout,
                        text="This image isn't HDR,\n"
                        "It has a low dynamic range.\n"
                        "BlenderKit library accepts 360 degree images\n"
                        "however the default filter setting for search\n"
                        "is to show only true HDR images\n",
                        icon="ERROR",
                        width=500,
                    )

                utils.label_multiline(
                    layout,
                    text="You marked the asset as public. "
                    "This means it will be validated by our team.\n\n"
                    "Please test your upload after it finishes:\n"
                    "-   Open a new file\n"
                    "-   Find the asset and download it\n"
                    "-   Check if it works as expected\n",
                    width=500,
                )
            else:
                utils.label_multiline(
                    layout,
                    text="You marked the asset as public."
                    "This means it will be validated by our team.\n\n"
                    "Please test your upload after it finishes:\n"
                    "-   Open a new file\n"
                    "-   Find the asset and download it\n"
                    "-   Check if it works as expected\n",
                    width=500,
                )

        if props.is_private == "PRIVATE":
            utils.label_multiline(
                layout,
                width=500,
                text="Would you like tu upload your asset to BlenderKit?",
            )

    def invoke(self, context, event):
        if not utils.user_logged_in():
            ui_panels.draw_not_logged_in(
                self, message="To upload assets you need to login/signup."
            )
            return {"CANCELLED"}

        if self.asset_type == "HDR":
            # getting upload data for images ensures true_hdr check so users can be informed about their handling
            # simple 360 photos or renders with LDR are hidden by default..
            export_data, upload_data = get_upload_data(asset_type="HDR")

        # if props.is_private == 'PUBLIC':
        return context.window_manager.invoke_props_dialog(self, width=500)
        # else:
        #     return self.execute(context)


class AssetDebugPrint(Operator):
    """Change verification status"""

    bl_idname = "object.blenderkit_print_asset_debug"
    bl_description = "BlenderKit print asset data for debug purposes"
    bl_label = "BlenderKit print asset data"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    # type of upload - model, material, textures, e.t.c.
    asset_id: StringProperty(  # type: ignore[valid-type]
        name="asset id",
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        if not search.get_search_results():
            print("no search results found")
            return {"CANCELLED"}
        # update status in search results for validator's clarity
        sr = search.get_search_results()

        result = None
        for r in sr:
            if r["id"] == self.asset_id:
                result = r
        if not result:
            ad = bpy.context.active_object.get("asset_data")
            if ad:
                result = ad.to_dict()
        if result:
            t = bpy.data.texts.new(result["displayName"])
            t.write(json.dumps(result, indent=4, sort_keys=True))
            print(json.dumps(result, indent=4, sort_keys=True))
        return {"FINISHED"}


class AssetVerificationStatusChange(Operator):
    """Change verification status"""

    bl_idname = "object.blenderkit_change_status"
    bl_description = "Change asset status"
    bl_label = "Change verification status"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    # type of upload - model, material, textures, e.t.c.
    asset_id: StringProperty(  # type: ignore[valid-type]
        name="asset id",
    )

    state: StringProperty(name="verification_status", default="uploaded")  # type: ignore[valid-type]

    original_state: StringProperty(name="verification_status", default="uploaded")  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        # if self.state == 'deleted':
        message = "Really delete asset from BlenderKit online storage?"
        if self.original_state == "on_hold":
            message += (
                "\n\nThis asset is on hold. If you want to upload it again,"
                " please reupload the asset instead of deleting it and "
                "uploading it as a new one. "
                "This will preserve the validation history in the comments and avoid any misunderstandings."
            )
        utils.label_multiline(layout, text=message, width=300)

        # layout.prop(self, 'state')

    def execute(self, context):
        if not search.get_search_results():
            return {"CANCELLED"}
        # update status in search results for validator's clarity
        search_results = search.get_search_results()
        for result in search_results:
            if result["id"] == self.asset_id:
                result["verificationStatus"] = self.state

        url = paths.BLENDERKIT_API + "/assets/" + str(self.asset_id) + "/"
        upload_data = {"verificationStatus": self.state}
        messages = {
            "success": "Verification status changed",
            "error": "Verification status change failed",
        }
        client_lib.nonblocking_request(url, "PATCH", {}, upload_data, messages)

        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.update_layout(context, None)
        return {"FINISHED"}

    def invoke(self, context, event):
        # print(self.state)
        if self.state == "deleted":
            wm = context.window_manager
            return wm.invoke_props_dialog(self)
        return {"RUNNING_MODAL"}


def handle_asset_upload(task: client_tasks.Task):
    asset = eval(f"{task.data['export_data']['eval_path']}.blenderkit")
    asset.upload_state = task.message
    if task.status == "error":
        asset.uploading = False
        if task.result == {}:
            return reports.add_report(
                task.message, type="ERROR", details=task.message_detailed
            )

        # crazy shit to parse stupid Django incosistent error messages
        if "detail" in task.result:
            if type(task.result["detail"]) == dict:
                for key in task.result["detail"]:
                    bk_logger.info("detail key " + str(key))
                    if type(task.result["detail"][key]) == list:
                        for item in task.result["detail"][key]:
                            asset.upload_state += f"\n- {key}: {item}"
                    else:
                        asset.upload_state += f"\n- {key}: {task.result['detail'][key]}"
                return reports.add_report(
                    f"{task.message}: {task.result['detail']}",
                    type="ERROR",
                    details=task.message_detailed,
                )
            if type(task.result["detail"]) == list:
                for item in task.result["detail"]:
                    asset.upload_state += f"\n- {item}"
                return reports.add_report(
                    f"{task.message}: {task.result['detail']}",
                    type="ERROR",
                    details=task.message_detailed,
                )
        else:
            asset.upload_state += f"\n {task.result}"
            return reports.add_report(
                f"{task.message}: {task.result}",
                type="ERROR",
                details=task.message_detailed,
            )

    if task.status == "finished":
        asset.uploading = False
        return reports.add_report("Upload successfull")


def handle_asset_metadata_upload(task: client_tasks.Task):
    if task.status != "finished":
        return

    asset = eval(f"{task.data['export_data']['eval_path']}.blenderkit")
    new_asset_base_id = task.result.get("assetBaseId", "")
    if new_asset_base_id != "":
        asset.asset_base_id = new_asset_base_id
        bk_logger.info(f"Assigned new asset.asset_base_id: {new_asset_base_id}")
    else:
        asset.asset_base_id = task.data["export_data"]["assetBaseId"]
        bk_logger.info(f"Assigned original asset.asset_base_id: {asset.asset_base_id}")

    new_asset_id = task.result.get("id", "")
    if new_asset_id != "":
        asset.id = new_asset_id
        bk_logger.info(f"Assigned new asset.id: {new_asset_id}")
    else:
        asset.id = task.data["export_data"]["id"]
        bk_logger.info(f"Assigned original asset.id: {asset.id}")

    return reports.add_report("Metadata upload successfull")


def patch_individual_parameter(asset_id="", param_name="", param_value="", api_key=""):
    """Changes individual parameter in the parameters dictionary of the assets.

    Args:
        asset_id (str): ID of the asset to update
        param_name (str): Name of the parameter to update
        param_value (str): New value for the parameter
        api_key (str): BlenderKit API key

    Returns:
        bool: True if successful, False otherwise
    """
    url = f"{paths.BLENDERKIT_API}/assets/{asset_id}/parameter/{param_name}/"
    headers = utils.get_headers(api_key)
    metadata_dict = {"value": param_value}
    messages = {
        "success": f"Successfully updated {param_name}",
        "error": f"Failed to update {param_name}",
    }

    client_lib.nonblocking_request(
        url=url,
        method="PUT",
        headers=headers,
        json_data=metadata_dict,
        messages=messages,
    )
    return True


def mark_for_thumbnail(
    asset_id: str,
    api_key: str,
    # Common parameters
    use_gpu: bool = None,
    samples: int = None,
    resolution: int = None,
    denoising: bool = None,
    background_lightness: float = None,
    # Model-specific parameters
    angle: str = None,  # DEFAULT, FRONT, SIDE, TOP
    snap_to: str = None,  # GROUND, WALL, CEILING, FLOAT
    # Material-specific parameters
    thumbnail_type: str = None,  # BALL, BALL_COMPLEX, FLUID, CLOTH, HAIR
    scale: float = None,
    background: bool = None,
    adaptive_subdivision: bool = None,
) -> bool:
    """Mark an asset for thumbnail regeneration.

    This function creates a JSON with thumbnail parameters and stores it in the
    markThumbnailRender parameter of the asset. Only non-None parameters will be included.

    Args:
        asset_id (str): The ID of the asset to update
        api_key (str): BlenderKit API key
        use_gpu (bool, optional): Use GPU for rendering
        samples (int, optional): Number of render samples
        resolution (int, optional): Resolution of render
        denoising (bool, optional): Use denoising
        background_lightness (float, optional): Background lightness (0-1)
        angle (str, optional): Camera angle for models (DEFAULT, FRONT, SIDE, TOP)
        snap_to (str, optional): Object placement for models (GROUND, WALL, CEILING, FLOAT)
        thumbnail_type (str, optional): Type of material preview (BALL, BALL_COMPLEX, FLUID, CLOTH, HAIR)
        scale (float, optional): Scale of preview object for materials
        background (bool, optional): Use background for transparent materials
        adaptive_subdivision (bool, optional): Use adaptive subdivision for materials

    Returns:
        bool: True if successful, False otherwise
    """
    # Build parameters dict with only non-None values
    params = {}

    # Common parameters
    if use_gpu is not None:
        params["thumbnail_use_gpu"] = use_gpu
    if samples is not None:
        params["thumbnail_samples"] = samples
    if resolution is not None:
        params["thumbnail_resolution"] = resolution
    if denoising is not None:
        params["thumbnail_denoising"] = denoising
    if background_lightness is not None:
        params["thumbnail_background_lightness"] = background_lightness

    # Model-specific parameters
    if angle is not None:
        params["thumbnail_angle"] = angle
    if snap_to is not None:
        params["thumbnail_snap_to"] = snap_to

    # Material-specific parameters
    if thumbnail_type is not None:
        params["thumbnail_type"] = thumbnail_type
    if scale is not None:
        params["thumbnail_scale"] = scale
    if background is not None:
        params["thumbnail_background"] = background
    if adaptive_subdivision is not None:
        params["thumbnail_adaptive_subdivision"] = adaptive_subdivision

    try:
        json_data = json.dumps(params)
        return patch_individual_parameter(
            asset_id, "markThumbnailRender", json_data, api_key
        )
    except Exception as e:
        bk_logger.error(f"Failed to mark asset for thumbnail regeneration: {e}")
        return False


def register_upload():
    bpy.utils.register_class(UploadOperator)
    bpy.utils.register_class(FastMetadata)
    bpy.utils.register_class(AssetDebugPrint)
    bpy.utils.register_class(AssetVerificationStatusChange)


def unregister_upload():
    bpy.utils.unregister_class(UploadOperator)
    bpy.utils.unregister_class(FastMetadata)
    bpy.utils.unregister_class(AssetDebugPrint)
    bpy.utils.unregister_class(AssetVerificationStatusChange)
