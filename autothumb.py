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

# import blenderkit
import json
import logging
import os
import random
import subprocess
import tempfile
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    FloatVectorProperty,
)

from . import bg_blender, global_vars, paths, tasks_queue, utils, upload, search


bk_logger = logging.getLogger(__name__)
BLENDERKIT_EXPORT_DATA_FILE = "data.json"

thumbnail_resolutions = (
    ("256", "256", ""),
    ("512", "512", ""),
    ("1024", "1024 - minimum for public", ""),
    ("2048", "2048", ""),
)

thumbnail_angles = (
    ("ANGLE_1", "Angle 1", "Lower hanging camera angle"),
    ("ANGLE_2", "Angle 2", "Higher hanging camera angle"),
    ("FRONT", "front", ""),
    ("SIDE", "side", ""),
    ("TOP", "top", ""),
)

thumbnail_snap = (
    ("GROUND", "ground", ""),
    ("WALL", "wall", ""),
    ("CEILING", "ceiling", ""),
    ("FLOAT", "floating", ""),
)


def get_texture_ui(tpath, iname):
    img = bpy.data.images.get(iname)
    tex = bpy.data.textures.get(iname)
    if tpath.startswith("//"):
        tpath = bpy.path.abspath(tpath)

    if not tex or not tex.image or not tex.image.filepath == tpath:
        if img is None:
            tasks_queue.add_task(
                (utils.get_hidden_image, (tpath, iname)), only_last=True
            )

        tasks_queue.add_task((utils.get_hidden_texture, (iname, False)), only_last=True)

        return None
    return tex


def check_thumbnail(props, imgpath):
    # TODO implement check if the file exists, if size is corect etc. needs some care
    if imgpath == "":
        props.has_thumbnail = False
        return None
    img = utils.get_hidden_image(imgpath, "upload_preview", force_reload=True)
    if img is not None:  # and img.size[0] == img.size[1] and img.size[0] >= 512 and (
        # img.file_format == 'JPEG' or img.file_format == 'PNG'):
        props.has_thumbnail = True
        props.thumbnail_generating_state = ""

        utils.get_hidden_texture(img.name)
        # pcoll = icons.icon_collections["previews"]
        # pcoll.load(img.name, img.filepath, 'IMAGE')

        return img
    else:
        props.has_thumbnail = False
    output = ""
    if (
        img is None
        or img.size[0] == 0
        or img.filepath.find("thumbnail_notready.jpg") > -1
    ):
        output += "No thumbnail or wrong file path\n"
    else:
        pass
        # this is causing problems on some platforms, don't know why..
        # if img.size[0] != img.size[1]:
        #     output += 'image not a square\n'
        # if img.size[0] < 512:
        #     output += 'image too small, should be at least 512x512\n'
        # if img.file_format != 'JPEG' or img.file_format != 'PNG':
        #     output += 'image has to be a jpeg or png'
    props.thumbnail_generating_state = output


def update_upload_model_preview(self, context):
    ob = utils.get_active_model()
    if ob is not None:
        props = ob.blenderkit
        imgpath = props.thumbnail
        check_thumbnail(props, imgpath)


def update_upload_scene_preview(self, context):
    s = bpy.context.scene
    props = s.blenderkit
    imgpath = props.thumbnail
    check_thumbnail(props, imgpath)


def update_upload_material_preview(self, context):
    if (
        hasattr(bpy.context, "active_object")
        and bpy.context.view_layer.objects.active is not None
        and bpy.context.active_object.active_material is not None
    ):
        mat = bpy.context.active_object.active_material
        props = mat.blenderkit
        imgpath = props.thumbnail
        check_thumbnail(props, imgpath)


def update_upload_brush_preview(self, context):
    brush = utils.get_active_brush()
    if brush is not None:
        props = brush.blenderkit
        imgpath = bpy.path.abspath(brush.icon_filepath)
        check_thumbnail(props, imgpath)


def get_thumbnailer_args(script_name, thumbnailer_filepath, datafile, api_key):
    """Get the arguments to start Blender in background to render model or material thumbnails.
    Watch out: the ending arguments must match order of those in: autothumb_model_bg.py and autothumb_material_bg.py.
    """
    script_path = os.path.dirname(os.path.realpath(__file__))
    script_path = os.path.join(script_path, script_name)
    args = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--addons",
        __package__,
        "-noaudio",
        thumbnailer_filepath,
        "--python",
        script_path,
        "--",
        datafile,
        api_key,
        __package__,  # Legacy has it as "blenderkit", extensions have it like bl_ext.user_default.blenderkit or anything else
    ]
    return args


def start_model_thumbnailer(
    self=None, json_args=None, props=None, wait=False, add_bg_process=True
):
    """Start Blender in background and render the thumbnail."""
    SCRIPT_NAME = "autothumb_model_bg.py"
    if props:
        props.is_generating_thumbnail = True
        props.thumbnail_generating_state = "Saving .blend file"

    datafile = os.path.join(json_args["tempdir"], BLENDERKIT_EXPORT_DATA_FILE)
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    json_args["thumbnail_use_gpu"] = user_preferences.thumbnail_use_gpu
    if user_preferences.thumbnail_use_gpu is True:
        json_args["cycles_compute_device_type"] = bpy.context.preferences.addons[
            "cycles"
        ].preferences.compute_device_type

    try:
        with open(datafile, "w", encoding="utf-8") as s:
            json.dump(json_args, s, ensure_ascii=False, indent=4)
    except Exception as e:
        self.report({"WARNING"}, f"Error while exporting file: {e}")
        return {"FINISHED"}
    args = get_thumbnailer_args(
        SCRIPT_NAME,
        paths.get_thumbnailer_filepath(),
        datafile,
        user_preferences.api_key,
    )
    blender_user_scripts_dir = (
        Path(__file__).resolve().parents[2]
    )  # scripts/addons/blenderkit/autothumb.py
    env = {"BLENDER_USER_SCRIPTS": str(blender_user_scripts_dir)}
    env.update(os.environ)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=utils.get_process_flags(),
        env=env,
    )
    bk_logger.info(f"Started Blender executing {SCRIPT_NAME} on file {datafile}")
    eval_path_computing = f"bpy.data.objects['{json_args['asset_name']}'].blenderkit.is_generating_thumbnail"
    eval_path_state = f"bpy.data.objects['{json_args['asset_name']}'].blenderkit.thumbnail_generating_state"
    eval_path = f"bpy.data.objects['{json_args['asset_name']}']"
    name = f"{json_args['asset_name']} thumbnailer"
    bg_blender.add_bg_process(
        name=name,
        eval_path_computing=eval_path_computing,
        eval_path_state=eval_path_state,
        eval_path=eval_path,
        process_type="THUMBNAILER",
        process=proc,
    )
    if props:
        props.thumbnail_generating_state = "Started Blender instance"

    if wait:
        while proc.poll() is None:
            stdout_data, stderr_data = proc.communicate()
            bk_logger.info(stdout_data, stderr_data)


def start_material_thumbnailer(
    self=None, json_args=None, props=None, wait=False, add_bg_process=True
):
    """Start Blender in background and render the thumbnail.

    Parameters
    ----------
    self
    json_args - all arguments:
    props - blenderkit upload props with thumbnail settings, to communicate back, if not present, not used.
    wait - wait for the rendering to finish

    Returns
    -------

    """
    SCRIPT_NAME = "autothumb_material_bg.py"
    if props:
        props.is_generating_thumbnail = True
        props.thumbnail_generating_state = "Saving .blend file"

    datafile = os.path.join(json_args["tempdir"], BLENDERKIT_EXPORT_DATA_FILE)
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    json_args["thumbnail_use_gpu"] = user_preferences.thumbnail_use_gpu
    if user_preferences.thumbnail_use_gpu is True:
        json_args["cycles_compute_device_type"] = bpy.context.preferences.addons[
            "cycles"
        ].preferences.compute_device_type
    try:
        with open(datafile, "w", encoding="utf-8") as s:
            json.dump(json_args, s, ensure_ascii=False, indent=4)
    except Exception as e:
        self.report({"WARNING"}, f"Error while exporting file: {e}")
        return {"FINISHED"}

    args = get_thumbnailer_args(
        SCRIPT_NAME,
        paths.get_material_thumbnailer_filepath(),
        datafile,
        user_preferences.api_key,
    )
    blender_user_scripts_dir = (
        Path(__file__).resolve().parents[2]
    )  # scripts/addons/blenderkit/autothumb.py
    env = {"BLENDER_USER_SCRIPTS": str(blender_user_scripts_dir)}
    env.update(os.environ)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=utils.get_process_flags(),
        env=env,
    )
    bk_logger.info(f"Started Blender executing {SCRIPT_NAME} on file {datafile}")

    eval_path_computing = f"bpy.data.materials['{json_args['asset_name']}'].blenderkit.is_generating_thumbnail"
    eval_path_state = f"bpy.data.materials['{json_args['asset_name']}'].blenderkit.thumbnail_generating_state"
    eval_path = f"bpy.data.materials['{json_args['asset_name']}']"
    name = f"{json_args['asset_name']} thumbnailer"
    bg_blender.add_bg_process(
        name=name,
        eval_path_computing=eval_path_computing,
        eval_path_state=eval_path_state,
        eval_path=eval_path,
        process_type="THUMBNAILER",
        process=proc,
    )
    if props:
        props.thumbnail_generating_state = "Started Blender instance"

    if wait:
        while proc.poll() is None:
            stdout_data, stderr_data = proc.communicate()
            bk_logger.info(stdout_data, stderr_data)


class GenerateThumbnailOperator(bpy.types.Operator):
    """Generate Cycles thumbnail for model assets"""

    bl_idname = "object.blenderkit_generate_thumbnail"
    bl_label = "BlenderKit Thumbnail Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bpy.context.view_layer.objects.active is not None

    def draw(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        asset_type = ui_props.asset_type

        ob = utils.get_active_model()
        props = ob.blenderkit
        layout = self.layout
        layout.label(text="thumbnailer settings")
        layout.prop(props, "thumbnail_background_lightness")
        # for printable models
        if asset_type == "PRINTABLE":
            layout.prop(props, "thumbnail_material_color")
        layout.prop(props, "thumbnail_angle")
        layout.prop(props, "thumbnail_snap_to")
        layout.prop(props, "thumbnail_samples")
        layout.prop(props, "thumbnail_resolution")
        layout.prop(props, "thumbnail_denoising")
        preferences = bpy.context.preferences.addons[__package__].preferences
        layout.prop(preferences, "thumbnail_use_gpu")

    def execute(self, context):
        asset = utils.get_active_model()
        asset.blenderkit.is_generating_thumbnail = True
        asset.blenderkit.thumbnail_generating_state = "starting blender instance"
        tempdir = tempfile.mkdtemp()
        ext = ".blend"
        filepath = os.path.join(tempdir, "thumbnailer_blenderkit" + ext)

        path_can_be_relative = True
        thumb_dir = os.path.dirname(bpy.data.filepath)
        if thumb_dir == "":
            thumb_dir = tempdir
            path_can_be_relative = False

        an_slug = paths.slugify(asset.name)

        thumb_path = os.path.join(thumb_dir, an_slug)

        if path_can_be_relative:
            rel_thumb_path = f"//{an_slug}"
        else:
            rel_thumb_path = thumb_path

        i = 0
        while os.path.isfile(thumb_path + ".jpg"):
            thumb_name = f"{an_slug}_{str(i).zfill(4)}"
            thumb_path = os.path.join(thumb_dir, thumb_name)
            if path_can_be_relative:
                rel_thumb_path = f"//{thumb_name}"

            i += 1
        bkit = asset.blenderkit

        bkit.thumbnail = rel_thumb_path + ".jpg"
        bkit.thumbnail_generating_state = "Saving .blend file"

        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"
        # save a copy of actual scene but don't interfere with the users models

        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=False, copy=True)
        # get all included objects
        obs = utils.get_hierarchy(asset)
        obnames = []
        for ob in obs:
            obnames.append(ob.name)
        # asset type can be model or printable
        ui_props = bpy.context.window_manager.blenderkitUI
        asset_type = ui_props.asset_type
        args_dict = {
            "type": asset_type,
            "asset_name": asset.name,
            "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
        }
        thumbnail_args = {
            "type": asset_type,
            "models": str(obnames),
            "thumbnail_angle": bkit.thumbnail_angle,
            "thumbnail_snap_to": bkit.thumbnail_snap_to,
            "thumbnail_background_lightness": bkit.thumbnail_background_lightness,
            "thumbnail_material_color": (
                bkit.thumbnail_material_color[0],
                bkit.thumbnail_material_color[1],
                bkit.thumbnail_material_color[2],
            ),
            "thumbnail_resolution": bkit.thumbnail_resolution,
            "thumbnail_samples": bkit.thumbnail_samples,
            "thumbnail_denoising": bkit.thumbnail_denoising,
        }
        args_dict.update(thumbnail_args)

        start_model_thumbnailer(
            self, json_args=args_dict, props=asset.blenderkit, wait=False
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager

        return wm.invoke_props_dialog(self, width=400)


class ReGenerateThumbnailOperator(bpy.types.Operator):
    """
    Generate default thumbnail with Cycles renderer and upload it.
    Works also for assets from search results, without being downloaded before.
    By default marks the asset for server-side thumbnail regeneration.
    """

    bl_idname = "object.blenderkit_regenerate_thumbnail"
    bl_label = "BlenderKit Thumbnail Re-generate"
    bl_options = {"REGISTER", "INTERNAL"}

    asset_index: IntProperty(  # type: ignore[valid-type]
        name="Asset Index", description="asset index in search results", default=-1
    )

    render_locally: BoolProperty(  # type: ignore[valid-type]
        name="Render Locally",
        description="Render thumbnail locally instead of using server-side rendering",
        default=False,
    )

    thumbnail_background_lightness: FloatProperty(  # type: ignore[valid-type]
        name="Thumbnail Background Lightness",
        description="Set to make your asset stand out",
        default=1.0,
        min=0.01,
        max=10,
    )

    thumbnail_material_color: FloatVectorProperty(
        name="Thumbnail Material Color",
        description="Color of the material for printable models",
        default=(random.random(), random.random(), random.random()),
        subtype="COLOR",
    )

    thumbnail_angle: EnumProperty(  # type: ignore[valid-type]
        name="Thumbnail Angle",
        items=thumbnail_angles,
        default="ANGLE_1",
        description="thumbnailer angle",
    )

    thumbnail_snap_to: EnumProperty(  # type: ignore[valid-type]
        name="Model Snaps To",
        items=thumbnail_snap,
        default="GROUND",
        description="typical placing of the interior. Leave on ground for most objects that respect gravity",
    )

    thumbnail_resolution: EnumProperty(  # type: ignore[valid-type]
        name="Resolution",
        items=thumbnail_resolutions,
        description="Thumbnail resolution",
        default="1024",
    )

    thumbnail_samples: IntProperty(  # type: ignore[valid-type]
        name="Cycles Samples",
        description="cycles samples setting",
        default=100,
        min=5,
        max=5000,
    )
    thumbnail_denoising: BoolProperty(  # type: ignore[valid-type]
        name="Use Denoising", description="Use denoising", default=True
    )

    @classmethod
    def poll(cls, context):
        return True  # bpy.context.view_layer.objects.active is not None

    def draw(self, context):
        props = self
        layout = self.layout
        layout.prop(props, "render_locally")
        layout.label(text="Server-side rendering may take several hours", icon="INFO")
        layout.label(text="thumbnailer settings")
        layout.prop(props, "thumbnail_background_lightness")
        # for printable models
        if self.asset_type == "PRINTABLE":
            layout.prop(props, "thumbnail_material_color")
        layout.prop(props, "thumbnail_angle")
        layout.prop(props, "thumbnail_snap_to")
        layout.prop(props, "thumbnail_samples")
        layout.prop(props, "thumbnail_resolution")
        layout.prop(props, "thumbnail_denoising")
        preferences = bpy.context.preferences.addons[__package__].preferences
        layout.prop(preferences, "thumbnail_use_gpu")

    def execute(self, context):
        if not self.asset_index > -1:
            return {"CANCELLED"}

        preferences = bpy.context.preferences.addons[__package__].preferences

        if not self.render_locally:
            # Use server-side thumbnail regeneration
            success = upload.mark_for_thumbnail(
                asset_id=self.asset_data["id"],
                api_key=preferences.api_key,
                use_gpu=preferences.thumbnail_use_gpu,
                samples=self.thumbnail_samples,
                resolution=int(self.thumbnail_resolution),
                denoising=self.thumbnail_denoising,
                background_lightness=self.thumbnail_background_lightness,
                angle=self.thumbnail_angle,
                snap_to=self.thumbnail_snap_to,
            )
            if success:
                self.report(
                    {"INFO"}, "Asset marked for server-side thumbnail regeneration"
                )
            else:
                self.report(
                    {"ERROR"}, "Failed to mark asset for thumbnail regeneration"
                )
            return {"FINISHED"}

        # Local thumbnail generation (original functionality)
        tempdir = tempfile.mkdtemp()

        an_slug = paths.slugify(self.asset_data["name"])
        thumb_path = os.path.join(tempdir, an_slug)

        # asset type can be model or printable
        ui_props = bpy.context.window_manager.blenderkitUI
        self.asset_type = ui_props.asset_type
        args_dict = {
            "type": self.asset_type,
            "asset_name": self.asset_data["name"],
            "asset_data": self.asset_data,
            # "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
            "do_download": True,
            "upload_after_render": True,
        }
        thumbnail_args = {
            "type": self.asset_type,
            "thumbnail_angle": self.thumbnail_angle,
            "thumbnail_snap_to": self.thumbnail_snap_to,
            "thumbnail_background_lightness": self.thumbnail_background_lightness,
            "thumbnail_resolution": self.thumbnail_resolution,
            "thumbnail_samples": self.thumbnail_samples,
            "thumbnail_denoising": self.thumbnail_denoising,
        }

        args_dict.update(thumbnail_args)
        start_model_thumbnailer(self, json_args=args_dict, wait=False)
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        # Get search results from history
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        self.asset_data = sr[self.asset_index]

        return wm.invoke_props_dialog(self, width=400)


class GenerateMaterialThumbnailOperator(bpy.types.Operator):
    """Generate default thumbnail with Cycles renderer"""

    bl_idname = "object.blenderkit_generate_material_thumbnail"
    bl_label = "BlenderKit Material Thumbnail Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bpy.context.view_layer.objects.active is not None

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        props = bpy.context.active_object.active_material.blenderkit
        layout.prop(props, "thumbnail_generator_type")
        layout.prop(props, "thumbnail_scale")
        layout.prop(props, "thumbnail_background")
        if props.thumbnail_background:
            layout.prop(props, "thumbnail_background_lightness")
        layout.prop(props, "thumbnail_resolution")
        layout.prop(props, "thumbnail_samples")
        layout.prop(props, "thumbnail_denoising")
        layout.prop(props, "adaptive_subdivision")
        preferences = bpy.context.preferences.addons[__package__].preferences
        layout.prop(preferences, "thumbnail_use_gpu")

    def execute(self, context):
        asset = bpy.context.active_object.active_material
        tempdir = tempfile.mkdtemp()
        filepath = os.path.join(tempdir, "material_thumbnailer_cycles.blend")
        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"

        # save a copy of actual scene but don't interfere with the users models
        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=False, copy=True)

        path_can_be_relative = True
        thumb_dir = os.path.dirname(bpy.data.filepath)
        if thumb_dir == "":  # file not saved
            thumb_dir = tempdir
            path_can_be_relative = False
        an_slug = paths.slugify(asset.name)

        thumb_path = os.path.join(thumb_dir, an_slug)

        if path_can_be_relative:
            rel_thumb_path = os.path.join("//", an_slug)
        else:
            rel_thumb_path = thumb_path

        # auto increase number of the generated thumbnail.
        i = 0
        while os.path.isfile(thumb_path + ".png"):
            thumb_path = os.path.join(thumb_dir, an_slug + "_" + str(i).zfill(4))
            rel_thumb_path = os.path.join("//", an_slug + "_" + str(i).zfill(4))
            i += 1

        asset.blenderkit.thumbnail = rel_thumb_path + ".png"
        bkit = asset.blenderkit

        args_dict = {
            "type": "material",
            "asset_name": asset.name,
            "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
        }

        thumbnail_args = {
            "thumbnail_type": bkit.thumbnail_generator_type,
            "thumbnail_scale": bkit.thumbnail_scale,
            "thumbnail_background": bkit.thumbnail_background,
            "thumbnail_background_lightness": bkit.thumbnail_background_lightness,
            "thumbnail_resolution": bkit.thumbnail_resolution,
            "thumbnail_samples": bkit.thumbnail_samples,
            "thumbnail_denoising": bkit.thumbnail_denoising,
            "adaptive_subdivision": bkit.adaptive_subdivision,
            "texture_size_meters": bkit.texture_size_meters,
        }
        args_dict.update(thumbnail_args)
        start_material_thumbnailer(
            self, json_args=args_dict, props=asset.blenderkit, wait=False
        )

        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)


class ReGenerateMaterialThumbnailOperator(bpy.types.Operator):
    """
    Generate default thumbnail with Cycles renderer and upload it.
    Works also for assets from search results, without being downloaded before.
    By default marks the asset for server-side thumbnail regeneration.
    """

    bl_idname = "object.blenderkit_regenerate_material_thumbnail"
    bl_label = "BlenderKit Material Thumbnail Re-Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    asset_index: IntProperty(  # type: ignore[valid-type]
        name="Asset Index", description="asset index in search results", default=-1
    )

    render_locally: BoolProperty(  # type: ignore[valid-type]
        name="Render Locally",
        description="Render thumbnail locally instead of using server-side rendering",
        default=False,
    )

    thumbnail_scale: FloatProperty(  # type: ignore[valid-type]
        name="Thumbnail Object Size",
        description="Size of material preview object in meters."
        "Change for materials that look better at sizes different than 1m",
        default=1,
        min=0.00001,
        max=10,
    )
    thumbnail_background: BoolProperty(  # type: ignore[valid-type]
        name="Thumbnail Background (for Glass only)",
        description="For refractive materials, you might need a background.\n"
        "Don't use for other types of materials.\n"
        "Transparent background is preferred",
        default=False,
    )
    thumbnail_background_lightness: FloatProperty(  # type: ignore[valid-type]
        name="Thumbnail Background Lightness",
        description="Set to make your material stand out with enough contrast",
        default=0.9,
        min=0.00001,
        max=1,
    )
    thumbnail_samples: IntProperty(  # type: ignore[valid-type]
        name="Cycles Samples",
        description="Cycles samples",
        default=100,
        min=5,
        max=5000,
    )
    thumbnail_denoising: BoolProperty(  # type: ignore[valid-type]
        name="Use Denoising", description="Use denoising", default=True
    )
    adaptive_subdivision: BoolProperty(  # type: ignore[valid-type]
        name="Adaptive Subdivide",
        description="Use adaptive displacement subdivision",
        default=False,
    )

    thumbnail_resolution: EnumProperty(  # type: ignore[valid-type]
        name="Resolution",
        items=thumbnail_resolutions,
        description="Thumbnail resolution",
        default="1024",
    )

    thumbnail_generator_type: EnumProperty(  # type: ignore[valid-type]
        name="Thumbnail Style",
        items=(
            ("BALL", "Ball", ""),
            (
                "BALL_COMPLEX",
                "Ball complex",
                "Complex ball to highlight edgewear or material thickness",
            ),
            ("FLUID", "Fluid", "Fluid"),
            ("CLOTH", "Cloth", "Cloth"),
            ("HAIR", "Hair", "Hair  "),
        ),
        description="Style of asset",
        default="BALL",
    )

    @classmethod
    def poll(cls, context):
        return True  # bpy.context.view_layer.objects.active is not None

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        props = self
        layout.prop(props, "render_locally")
        layout.label(text="Server-side rendering may take several hours", icon="INFO")
        layout.prop(props, "thumbnail_generator_type")
        layout.prop(props, "thumbnail_scale")
        layout.prop(props, "thumbnail_background")
        if props.thumbnail_background:
            layout.prop(props, "thumbnail_background_lightness")
        layout.prop(props, "thumbnail_resolution")
        layout.prop(props, "thumbnail_samples")
        layout.prop(props, "thumbnail_denoising")
        layout.prop(props, "adaptive_subdivision")
        preferences = bpy.context.preferences.addons[__package__].preferences
        layout.prop(preferences, "thumbnail_use_gpu")

    def execute(self, context):
        if not self.asset_index > -1:
            return {"CANCELLED"}

        # Get search results from history
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[self.asset_index]

        preferences = bpy.context.preferences.addons[__package__].preferences

        if not self.render_locally:
            # Use server-side thumbnail regeneration
            success = upload.mark_for_thumbnail(
                asset_id=asset_data["id"],
                api_key=preferences.api_key,
                use_gpu=preferences.thumbnail_use_gpu,
                samples=self.thumbnail_samples,
                resolution=int(self.thumbnail_resolution),
                denoising=self.thumbnail_denoising,
                background_lightness=self.thumbnail_background_lightness,
                thumbnail_type=self.thumbnail_generator_type,
                scale=self.thumbnail_scale,
                background=self.thumbnail_background,
                adaptive_subdivision=self.adaptive_subdivision,
            )
            if success:
                self.report(
                    {"INFO"}, "Asset marked for server-side thumbnail regeneration"
                )
            else:
                self.report(
                    {"ERROR"}, "Failed to mark asset for thumbnail regeneration"
                )
            return {"FINISHED"}

        # Local thumbnail generation (original functionality)
        an_slug = paths.slugify(asset_data["name"])

        tempdir = tempfile.mkdtemp()

        thumb_path = os.path.join(tempdir, an_slug)

        args_dict = {
            "type": "material",
            "asset_name": asset_data["name"],
            "asset_data": asset_data,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
            "do_download": True,
            "upload_after_render": True,
        }
        thumbnail_args = {
            "thumbnail_type": self.thumbnail_generator_type,
            "thumbnail_scale": self.thumbnail_scale,
            "thumbnail_background": self.thumbnail_background,
            "thumbnail_background_lightness": self.thumbnail_background_lightness,
            "thumbnail_resolution": self.thumbnail_resolution,
            "thumbnail_samples": self.thumbnail_samples,
            "thumbnail_denoising": self.thumbnail_denoising,
            "adaptive_subdivision": self.adaptive_subdivision,
            "texture_size_meters": utils.get_param(
                asset_data, "textureSizeMeters", 1.0
            ),
        }
        args_dict.update(thumbnail_args)
        start_material_thumbnailer(self, json_args=args_dict, wait=False)

        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)


def register_thumbnailer():
    bpy.utils.register_class(GenerateThumbnailOperator)
    bpy.utils.register_class(ReGenerateThumbnailOperator)
    bpy.utils.register_class(GenerateMaterialThumbnailOperator)
    bpy.utils.register_class(ReGenerateMaterialThumbnailOperator)


def unregister_thumbnailer():
    bpy.utils.unregister_class(GenerateThumbnailOperator)
    bpy.utils.unregister_class(ReGenerateThumbnailOperator)
    bpy.utils.unregister_class(GenerateMaterialThumbnailOperator)
    bpy.utils.unregister_class(ReGenerateMaterialThumbnailOperator)
