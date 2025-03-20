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

import logging
import math
import os
import random

import bpy
import mathutils
from bpy.props import IntProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from . import (
    bg_blender,
    colors,
    download,
    global_vars,
    paths,
    reports,
    ui,
    ui_bgl,
    ui_panels,
    utils,
    search,
)
from .bl_ui_widgets.bl_ui_button import BL_UI_Button
from .bl_ui_widgets.bl_ui_drag_panel import BL_UI_Drag_Panel
from .bl_ui_widgets.bl_ui_draw_op import BL_UI_OT_draw_operator
from .bl_ui_widgets.bl_ui_image import BL_UI_Image


bk_logger = logging.getLogger("blenderkit")

handler_2d = None
handler_3d = None


def draw_callback_dragging(self, context):
    try:
        img = bpy.data.images.get(self.iname)
        if img is None:
            # thumbnail can be sometimes missing (probably removed by Blender) so lets add it
            directory = paths.get_temp_dir(f"{self.asset_data['assetType']}_search")
            tpath = os.path.join(directory, self.asset_data["thumbnail_small"])
            img = bpy.data.images.load(tpath)
            img.name = self.iname
    except Exception as e:
        #  self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_dragging, args, 'WINDOW', 'POST_PIXEL')
        #  self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_3d_dragging, args, 'WINDOW',
        #   bpy.types.SpaceView3D.draw_handler_remove(self._handle,
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')
        print("draw_callback_dragging error:", e)
        return
    linelength = 35
    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_bgl.draw_image(
        self.mouse_x + linelength,
        self.mouse_y - linelength - ui_props.thumb_size,
        ui_props.thumb_size,
        ui_props.thumb_size,
        img,
        1,
    )
    ui_bgl.draw_line2d(
        self.mouse_x,
        self.mouse_y,
        self.mouse_x + linelength,
        self.mouse_y - linelength,
        2,
        colors.WHITE,
    )


def draw_callback_3d_dragging(self, context):
    """Draw snapped bbox while dragging."""
    if not utils.guard_from_crash():
        return
    try:
        self.has_hit
    except:
        return
    ui_props = context.window_manager.blenderkitUI
    # print(self.asset_data["assetType"], self.has_hit, self.snapped_location)
    if self.asset_data["assetType"] in ["model", "printable"]:
        if self.has_hit:
            draw_bbox(
                self.snapped_location,
                self.snapped_rotation,
                self.snapped_bbox_min,
                self.snapped_bbox_max,
            )


def draw_bbox(
    location, rotation, bbox_min, bbox_max, progress=None, color=(0, 1, 0, 1)
):
    ui_props = bpy.context.window_manager.blenderkitUI

    rotation = mathutils.Euler(rotation)

    smin = Vector(bbox_min)
    smax = Vector(bbox_max)
    v0 = Vector(smin)
    v1 = Vector((smax.x, smin.y, smin.z))
    v2 = Vector((smax.x, smax.y, smin.z))
    v3 = Vector((smin.x, smax.y, smin.z))
    v4 = Vector((smin.x, smin.y, smax.z))
    v5 = Vector((smax.x, smin.y, smax.z))
    v6 = Vector((smax.x, smax.y, smax.z))
    v7 = Vector((smin.x, smax.y, smax.z))

    arrowx = smin.x + (smax.x - smin.x) / 2
    arrowy = smin.y - (smax.x - smin.x) / 2
    v8 = Vector((arrowx, arrowy, smin.z))

    vertices = [v0, v1, v2, v3, v4, v5, v6, v7, v8]
    for v in vertices:
        v.rotate(rotation)
        v += Vector(location)

    lines = [
        [0, 1],
        [1, 2],
        [2, 3],
        [3, 0],
        [4, 5],
        [5, 6],
        [6, 7],
        [7, 4],
        [0, 4],
        [1, 5],
        [2, 6],
        [3, 7],
        [0, 8],
        [1, 8],
    ]
    ui_bgl.draw_lines(vertices, lines, color)
    if progress != None:
        color = (color[0], color[1], color[2], 0.2)
        progress = progress * 0.01
        vz0 = (v4 - v0) * progress + v0
        vz1 = (v5 - v1) * progress + v1
        vz2 = (v6 - v2) * progress + v2
        vz3 = (v7 - v3) * progress + v3
        rects = (
            (v0, v1, vz1, vz0),
            (v1, v2, vz2, vz1),
            (v2, v3, vz3, vz2),
            (v3, v0, vz0, vz3),
        )
        for r in rects:
            ui_bgl.draw_rect_3d(r, color)


def draw_downloader(x, y, percent=0, img=None, text=""):
    ui_props = bpy.context.window_manager.blenderkitUI

    if img is not None:
        ui_bgl.draw_image(x, y, ui_props.thumb_size, ui_props.thumb_size, img, 0.5)

    if percent > 0:
        ui_bgl.draw_rect(
            x, y, ui_props.thumb_size, int(0.5 * percent), (0.2, 1, 0.2, 0.3)
        )

    ui_bgl.draw_rect(x - 3, y - 3, 6, 6, (1, 0, 0, 0.3))
    # if asset_data is not None:
    #     ui_bgl.draw_text(asset_data['name'], x, y, colors.TEXT)
    #     ui_bgl.draw_text(asset_data['filesSize'])
    if text:
        ui_bgl.draw_text(text, x, y - 15, 12, colors.TEXT)
    #
    # if asset_bar_op.asset_bar_operator is not None:
    #     ab = asset_bar_op.asset_bar_operator
    #     img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
    #
    #     imgname = f".{os.path.basename(img_fp)}"
    #     img = bpy.data.images.get(imgname)
    #     if img is not None:
    #         size = ab.other_button_size
    #         offset = ui_props.thumb_size - size / 2
    #         ui_bgl.draw_image(x + offset, y + offset, size, size, img, 0.5)


def draw_callback_2d_progress(self, context):
    if not utils.guard_from_crash():
        return

    green = (0.2, 1, 0.2, 0.3)
    offset = 0
    row_height = 35

    ui = bpy.context.window_manager.blenderkitUI

    x = ui.reports_x
    y = ui.reports_y
    index = 0
    for key, task in download.download_tasks.items():
        asset_data = task["asset_data"]

        directory = paths.get_temp_dir("%s_search" % asset_data["assetType"])
        tpath = os.path.join(directory, asset_data["thumbnail_small"])
        img = utils.get_hidden_image(tpath, asset_data["id"])
        if not task.get("downloaders"):
            draw_progress(
                x,
                y - index * 30,
                text="downloading %s" % asset_data["name"],
                percent=task["progress"],
            )
            index += 1

    for process in bg_blender.bg_processes:
        tcom = process[1]
        n = ""
        if tcom.name is not None:
            n = tcom.name + ": "
        draw_progress(x, y - index * 30, "%s" % n + tcom.lasttext, tcom.progress)
        index += 1
    for report in reports.reports:
        # print('drawing reports', x, y, report.text)
        report.draw(x, y - index * 30)
        index += 1
        report.fade()


def draw_callback_3d_progress(self, context):
    # 'star trek' mode is here

    if not utils.guard_from_crash():
        return
    for key, task in download.download_tasks.items():
        asset_data = task["asset_data"]
        if task.get("downloaders"):
            for d in task["downloaders"]:
                if asset_data["assetType"] in ["model", "printable"]:
                    draw_bbox(
                        d["location"],
                        d["rotation"],
                        asset_data["bbox_min"],
                        asset_data["bbox_max"],
                        progress=task["progress"],
                    )


def draw_progress(x, y, text="", percent=None, color=colors.GREEN):
    ui_bgl.draw_rect(x, y, percent, 5, color)
    ui_bgl.draw_text(text, x, y + 8, 16, color)


def find_and_activate_instancers(object):
    for ob in bpy.context.visible_objects:
        if (
            ob.instance_type == "COLLECTION"
            and ob.instance_collection
            and object.name in ob.instance_collection.objects
        ):
            utils.activate(ob)
            return ob


def mouse_raycast(context, mx, my):
    r = context.region
    rv3d = context.region_data
    coord = mx, my
    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(r, rv3d, coord)
    if rv3d.view_perspective == "CAMERA" and rv3d.is_perspective == False:
        #  ortographic cameras don'w work with region_2d_to_origin_3d
        view_position = rv3d.view_matrix.inverted().translation
        ray_origin = view3d_utils.region_2d_to_location_3d(
            r, rv3d, coord, depth_location=view_position
        )
    else:
        ray_origin = view3d_utils.region_2d_to_origin_3d(r, rv3d, coord, clamp=1.0)

    ray_target = ray_origin + (view_vector * 1000000000)

    vec = ray_target - ray_origin

    (
        has_hit,
        snapped_location,
        snapped_normal,
        face_index,
        object,
        matrix,
    ) = deep_ray_cast(context, ray_origin, vec)

    # backface snapping inversion
    if view_vector.angle(snapped_normal) < math.pi / 2:
        snapped_normal = -snapped_normal
    # print(has_hit, snapped_location, snapped_normal, face_index, object, matrix)
    # rote = mathutils.Euler((0, 0, math.pi))
    randoffset = math.pi
    if has_hit:
        props = bpy.context.window_manager.blenderkit_models
        up = Vector((0, 0, 1))

        if props.perpendicular_snap:
            if snapped_normal.z > 1 - props.perpendicular_snap_threshold:
                snapped_normal = Vector((0, 0, 1))
            elif snapped_normal.z < -1 + props.perpendicular_snap_threshold:
                snapped_normal = Vector((0, 0, -1))
            elif abs(snapped_normal.z) < props.perpendicular_snap_threshold:
                snapped_normal.z = 0
                snapped_normal.normalize()

        snapped_rotation = snapped_normal.to_track_quat("Z", "Y").to_euler()

        if props.randomize_rotation and snapped_normal.angle(up) < math.radians(10.0):
            randoffset = (
                props.offset_rotation_amount
                + math.pi
                + (random.random() - 0.5) * props.randomize_rotation_amount
            )
        else:
            randoffset = (
                props.offset_rotation_amount
            )  # we don't rotate this way on walls and ceilings. + math.pi
        # snapped_rotation.z += math.pi + (random.random() - 0.5) * .2

    else:
        snapped_rotation = mathutils.Quaternion((0, 0, 0, 0)).to_euler()

    snapped_rotation.rotate_axis("Z", randoffset)

    return (
        has_hit,
        snapped_location,
        snapped_normal,
        snapped_rotation,
        face_index,
        object,
        matrix,
    )


def floor_raycast(context, mx, my):
    r = context.region
    rv3d = context.region_data
    coord = mx, my

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(r, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(r, rv3d, coord)
    ray_target = ray_origin + (view_vector * 1000)

    # various intersection plane normals are needed for corner cases that might actually happen quite often - in front and side view.
    # default plane normal is scene floor.
    plane_normal = (0, 0, 1)
    if math.isclose(view_vector.x, 0, abs_tol=1e-4) and math.isclose(
        view_vector.z, 0, abs_tol=1e-4
    ):
        plane_normal = (0, 1, 0)
    elif math.isclose(view_vector.z, 0, abs_tol=1e-4):
        plane_normal = (1, 0, 0)

    snapped_location = mathutils.geometry.intersect_line_plane(
        ray_origin, ray_target, (0, 0, 0), plane_normal, False
    )
    if snapped_location != None:
        has_hit = True
        snapped_normal = Vector((0, 0, 1))
        face_index = None
        object = None
        matrix = None
        snapped_rotation = snapped_normal.to_track_quat("Z", "Y").to_euler()
        props = bpy.context.window_manager.blenderkit_models
        if props.randomize_rotation:
            randoffset = (
                props.offset_rotation_amount
                + math.pi
                + (random.random() - 0.5) * props.randomize_rotation_amount
            )
        else:
            randoffset = props.offset_rotation_amount + math.pi
        snapped_rotation.rotate_axis("Z", randoffset)

    return (
        has_hit,
        snapped_location,
        snapped_normal,
        snapped_rotation,
        face_index,
        object,
        matrix,
    )


def deep_ray_cast(context, ray_origin, vec):
    # this allows to ignore some objects, like objects with bounding box draw style or particle objects
    object = None
    # while object is None or object.draw
    depsgraph = context.view_layer.depsgraph
    (
        has_hit,
        snapped_location,
        snapped_normal,
        face_index,
        object,
        matrix,
    ) = bpy.context.scene.ray_cast(depsgraph, ray_origin, vec)
    empty_set = False, Vector((0, 0, 0)), Vector((0, 0, 1)), None, None, None
    if not object:
        return empty_set
    try_object = object
    while try_object and (
        try_object.display_type == "BOUNDS"
        or object_in_particle_collection(try_object)
        or not try_object.visible_get(viewport=context.space_data)
    ):
        ray_origin = snapped_location + vec.normalized() * 0.0003
        (
            try_has_hit,
            try_snapped_location,
            try_snapped_normal,
            try_face_index,
            try_object,
            try_matrix,
        ) = bpy.context.scene.ray_cast(depsgraph, ray_origin, vec)
        if try_has_hit:
            # this way only good hits are returned, otherwise
            has_hit, snapped_location, snapped_normal, face_index, object, matrix = (
                try_has_hit,
                try_snapped_location,
                try_snapped_normal,
                try_face_index,
                try_object,
                try_matrix,
            )
    if not (
        object.display_type == "BOUNDS" or object_in_particle_collection(try_object)
    ):  # or not object.visible_get()):
        return has_hit, snapped_location, snapped_normal, face_index, object, matrix
    return empty_set


def object_in_particle_collection(o):
    """checks if an object is in a particle system as instance, to not snap to it and not to try to attach material."""
    for p in bpy.data.particles:
        if p.render_type == "COLLECTION":
            if p.instance_collection:
                for o1 in p.instance_collection.objects:
                    if o1 == o:
                        return True
        if p.render_type == "COLLECTION":
            if p.instance_object == o:
                return True
    return False


class AssetDragOperator(bpy.types.Operator):
    """Drag & drop assets into scene. Operator being drawn when dragging asset."""

    bl_idname = "view3d.asset_drag_drop"
    bl_label = "BlenderKit asset drag drop"

    asset_search_index: IntProperty(name="Active Index", default=0)  # type: ignore
    drag_length: IntProperty(name="Drag_length", default=0)  # type: ignore

    object_name = None

    def handlers_remove(self):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")

    def mouse_release(self):
        scene = bpy.context.scene
        ui_props = bpy.context.window_manager.blenderkitUI

        if self.asset_data["assetType"] in ["model", "printable"]:
            if not self.drag:
                self.snapped_location = scene.cursor.location
                self.snapped_rotation = (0, 0, 0)

            target_object = ""
            if self.object_name is not None:
                target_object = self.object_name
                target_slot = ""

            if "particle_plants" in self.asset_data["tags"]:
                bpy.ops.object.blenderkit_particles_drop(
                    "INVOKE_DEFAULT",
                    asset_search_index=self.asset_search_index,
                    model_location=self.snapped_location,
                    model_rotation=self.snapped_rotation,
                    target_object=target_object,
                )
            else:
                bpy.ops.scene.blenderkit_download(
                    True,
                    # asset_type=self.asset_data["assetType"],
                    asset_index=self.asset_search_index,
                    model_location=self.snapped_location,
                    model_rotation=self.snapped_rotation,
                    target_object=target_object,
                )
        if self.asset_data["assetType"] == "material":
            object = None
            target_object = ""
            target_slot = ""
            if not self.drag:
                # click interaction
                object = bpy.context.active_object
                if object is None:
                    ui_panels.ui_message(
                        title="Nothing selected",
                        message=f"Select something to assign materials by clicking.",
                    )
                    return
                target_object = object.name
                target_slot = object.active_material_index
                self.snapped_location = object.location
            elif self.object_name is not None and self.has_hit:
                # first, test if object can have material applied.
                object = bpy.data.objects[self.object_name]
                # this enables to run Bring to scene automatically when dropping on a linked objects.
                if (
                    object is not None
                    and not object.is_library_indirect
                    and object.type in utils.supported_material_drag
                ):
                    target_object = object.name
                    # create final mesh to extract correct material slot
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                    object_eval = object.evaluated_get(depsgraph)

                    if object.type == "MESH":
                        temp_mesh = object_eval.to_mesh()
                        mapping = create_material_mapping(object, temp_mesh)
                        target_slot = temp_mesh.polygons[self.face_index].material_index
                        object_eval.to_mesh_clear()
                    else:
                        ui_props.snapped_location = object.location
                        target_slot = object.active_material_index

            if not object:
                return
            if object.is_library_indirect:
                ui_panels.ui_message(
                    title="This object is linked from outer file",
                    message="Please select the model,"
                    "go to the 'Selected Model' panel "
                    "in BlenderKit and hit 'Bring to Scene' first.",
                )
                return
            if object.type not in utils.supported_material_drag:
                if object.type in utils.supported_material_click:
                    ui_panels.ui_message(
                        title="Unsupported object type",
                        message=f"Use click interaction for {object.type.lower()} object.",
                    )
                    return
                else:
                    ui_panels.ui_message(
                        title="Unsupported object type",
                        message=f"Can't assign materials to {object.type.lower()} object.",
                    )
                    return

            if target_object != "":
                # position is for downloader:
                loc = self.snapped_location
                rotation = (0, 0, 0)

                utils.automap(
                    target_object,
                    target_slot=target_slot,
                    tex_size=self.asset_data.get("texture_size_meters", 1.0),
                )
                bpy.ops.scene.blenderkit_download(
                    True,
                    asset_index=self.asset_search_index,
                    model_location=loc,
                    model_rotation=rotation,
                    target_object=target_object,
                    material_target_slot=target_slot,
                )

        if self.asset_data["assetType"] == "hdr":
            bpy.ops.scene.blenderkit_download(
                "INVOKE_DEFAULT",
                asset_index=self.asset_search_index,
                # replace_resolution=True,
                invoke_resolution=True,
                use_resolution_operator=True,
                max_resolution=self.asset_data.get("max_resolution", 0),
            )

        if self.asset_data["assetType"] == "scene":
            bpy.ops.scene.blenderkit_download(
                "INVOKE_DEFAULT",
                asset_index=self.asset_search_index,
                # replace_resolution=True,
                invoke_resolution=False,
                invoke_scene_settings=True,
            )

        if self.asset_data["assetType"] == "brush":
            bpy.ops.scene.blenderkit_download(  # asset_type=self.asset_data["assetType"],
                asset_index=self.asset_search_index,
            )

        if self.asset_data["assetType"] in ["material", "model"]:
            bpy.ops.view3d.blenderkit_download_gizmo_widget(
                "INVOKE_REGION_WIN",
                asset_base_id=self.asset_data["assetBaseId"],
            )
        if self.asset_data["assetType"] == "nodegroup":
            bpy.ops.scene.blenderkit_download(  # asset_type=ui_props.asset_type,
                asset_index=self.asset_search_index,
            )

        if self.asset_data["assetType"] in ["model", "material"]:
            bpy.ops.view3d.blenderkit_download_gizmo_widget(
                "INVOKE_REGION_WIN",
                asset_base_id=self.asset_data["assetBaseId"],
            )

    def modal(self, context, event):
        scene = bpy.context.scene
        ui_props = bpy.context.window_manager.blenderkitUI
        context.area.tag_redraw()

        # if event.type == 'MOUSEMOVE':
        if not hasattr(self, "start_mouse_x"):
            self.start_mouse_x = event.mouse_region_x
            self.start_mouse_y = event.mouse_region_y

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        # are we dragging already?
        drag_threshold = 10
        if not self.drag and (
            abs(self.start_mouse_x - self.mouse_x) > drag_threshold
            or abs(self.start_mouse_y - self.mouse_y) > drag_threshold
        ):
            self.drag = True

        if self.drag and ui_props.assetbar_on:
            # turn off asset bar here, shout start again after finishing drag drop.
            ui_props.turn_off = True

        if (
            event.type == "ESC"
            or not ui.mouse_in_region(context.region, self.mouse_x, self.mouse_y)
        ) and (not self.drag or self.steps < 5):
            # this case is for canceling from inside popup card when there's an escape attempt to close the window
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"} or not ui.mouse_in_region(
            context.region, self.mouse_x, self.mouse_y
        ):
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")
            ui_props.dragging = False
            bpy.ops.view3d.blenderkit_asset_bar_widget(
                "INVOKE_REGION_WIN", do_search=False
            )

            return {"CANCELLED"}

        sprops = bpy.context.window_manager.blenderkit_models
        if event.type == "WHEELUPMOUSE":
            sprops.offset_rotation_amount += sprops.offset_rotation_step
        elif event.type == "WHEELDOWNMOUSE":
            sprops.offset_rotation_amount -= sprops.offset_rotation_step

        if (
            event.type == "MOUSEMOVE"
            or event.type == "WHEELUPMOUSE"
            or event.type == "WHEELDOWNMOUSE"
        ):
            #### TODO - this snapping code below is 3x in this file.... refactor it.
            (
                self.has_hit,
                self.snapped_location,
                self.snapped_normal,
                self.snapped_rotation,
                self.face_index,
                object,
                self.matrix,
            ) = mouse_raycast(context, event.mouse_region_x, event.mouse_region_y)
            if object is not None:
                self.object_name = object.name

            # MODELS can be dragged on scene floor
            if not self.has_hit and self.asset_data["assetType"] in [
                "model",
                "printable",
            ]:
                (
                    self.has_hit,
                    self.snapped_location,
                    self.snapped_normal,
                    self.snapped_rotation,
                    self.face_index,
                    object,
                    self.matrix,
                ) = floor_raycast(context, event.mouse_region_x, event.mouse_region_y)
                if object is not None:
                    self.object_name = object.name

            if self.asset_data["assetType"] in ["model", "printable"]:
                self.snapped_bbox_min = Vector(self.asset_data["bbox_min"])
                self.snapped_bbox_max = Vector(self.asset_data["bbox_max"])
            # return {'RUNNING_MODAL'}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self.mouse_release()  # does the main job with assets
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")

            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
            ui_props.dragging = False
            return {"FINISHED"}

        self.steps += 1

        # pass event to assetbar so it can close itself
        if ui_props.assetbar_on and ui_props.turn_off:
            return {"PASS_THROUGH"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.area.type != "VIEW_3D":
            self.report({"WARNING"}, "View3D not found, cannot run operator")
            return {"CANCELLED"}

        # the arguments we pass the the callback
        args = (self, context)
        # Add the region OpenGL drawing callback
        # draw in view space with 'POST_VIEW' and 'PRE_VIEW'

        self.mouse_x = 0
        self.mouse_y = 0
        self.steps = 0

        self.has_hit = False
        self.snapped_location = (0, 0, 0)
        self.snapped_normal = (0, 0, 1)
        self.snapped_rotation = (0, 0, 0)
        self.face_index = 0
        self.matrix = None

        ui_props = bpy.context.window_manager.blenderkitUI
        sr = search.get_search_results()
        self.asset_data = dict(sr[ui_props.active_index])

        self.iname = f'.{self.asset_data["thumbnail_small"]}'
        self.iname = (self.iname[:63]) if len(self.iname) > 63 else self.iname

        if not self.asset_data.get("canDownload"):
            message = "Let's support asset creators and Open source."
            link_text = "Unlock the asset."
            url = f'{global_vars.SERVER}/get-blenderkit/{self.asset_data["id"]}/?from_addon=True'
            bpy.ops.wm.blenderkit_url_dialog(
                "INVOKE_REGION_WIN", url=url, message=message, link_text=link_text
            )
            return {"CANCELLED"}

        dir_behaviour = bpy.context.preferences.addons[
            __package__
        ].preferences.directory_behaviour
        if dir_behaviour == "LOCAL" and bpy.data.filepath == "":
            message = "Save the project to download in local directory mode."
            link_text = "See documentation"
            url = "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-Preferences#use-directories"
            bpy.ops.wm.blenderkit_url_dialog(
                "INVOKE_REGION_WIN", url=url, message=message, link_text=link_text
            )
            return {"CANCELLED"}

        if self.asset_data.get("assetType") == "brush":
            if not (context.sculpt_object or context.image_paint_object):
                # either switch to sculpt mode and layout automatically or show a popup message
                if context.active_object and context.active_object.type == "MESH":
                    bpy.ops.object.mode_set(mode="SCULPT")
                    self.mouse_release()  # does the main job with assets

                    if bpy.data.workspaces.get("Sculpting") is not None:
                        bpy.context.window.workspace = bpy.data.workspaces["Sculpting"]
                    reports.add_report(
                        "Automatically switched to sculpt mode to use brushes."
                    )
                else:
                    message = "Select a mesh and switch to sculpt or image paint modes to use the brushes."
                    bpy.ops.wm.blenderkit_popup_dialog(
                        "INVOKE_REGION_WIN", message=message, width=500
                    )
                return {"CANCELLED"}

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_dragging, args, "WINDOW", "POST_PIXEL"
        )
        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_3d_dragging, args, "WINDOW", "POST_VIEW"
        )

        bpy.context.window.cursor_set("NONE")
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.dragging = True
        self.drag = False
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


class DownloadGizmoOperator(BL_UI_OT_draw_operator):
    bl_idname = "view3d.blenderkit_download_gizmo_widget"
    bl_label = "BlenderKit download gizmo"
    bl_description = (
        "BlenderKit download gizmo - draws download and enables to cancel it."
    )
    bl_options = {"REGISTER"}
    instances = []

    asset_base_id: StringProperty(name="asset base id", default="")  # type: ignore

    def cancel_press(self, widget):
        self.finish()
        cancel_download = False
        for key, t in download.download_tasks.items():
            if key == self.task_key:
                for d in t.get("downloaders", []):
                    if d["location"] == self.downloader["location"]:
                        download.download_tasks[key]["downloaders"].remove(d)
                        if len(download.download_tasks[key]["downloaders"]) == 0:
                            cancel_download = True
                        break
        if cancel_download:
            bpy.ops.scene.blenderkit_download_kill(task_id=self.task_key)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # get downloader
        self.task = None
        for key, t in download.download_tasks.items():
            if t["asset_data"]["assetBaseId"] == self.asset_base_id:
                self.task = t
                self.task_key = key
                break

        if self.task is None:
            self._finished = True
            return

        self.asset_data = self.task["asset_data"]

        if self.task.get("downloaders"):
            self.downloader = self.task["downloaders"][-1]
        else:
            self.downloader = None

        ui_scale = bpy.context.preferences.view.ui_scale

        text_size = int(10 * ui_scale)
        margin = int(5 * ui_scale)
        area_margin = int(50 * ui_scale)

        self.bg_color = (0.05, 0.05, 0.05, 0.3)
        self.hover_bg_color = (0.05, 0.05, 0.05, 0.5)

        self.text_color = (0.9, 0.9, 0.9, 1)

        ui_props = bpy.context.window_manager.blenderkitUI

        pix_size = ui_bgl.get_text_size(
            font_id=1,
            text=self.task["text"],
            text_size=text_size,
            dpi=int(bpy.context.preferences.system.dpi / ui_scale),
        )
        self.height = pix_size[1] + 2 * margin
        self.button_size = int(ui_props.thumb_size)
        self.width = pix_size[0] + 2 * margin  # adding image and cancel button to width

        a = bpy.context.area

        if bpy.context.space_data is not None and hasattr(self, "downloader"):
            loc = view3d_utils.location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.space_data.region_3d,
                self.downloader["location"],
            )
            if loc is None:
                loc = Vector((0, 0))
        else:
            loc = Vector((0, 0))

        self.panel = BL_UI_Drag_Panel(
            loc.x, bpy.context.region.height - loc.y, self.width, self.height
        )
        self.panel.bg_color = (0.2, 0.2, 0.2, 0.02)

        self.image = BL_UI_Image(
            0, -self.button_size, self.button_size, self.button_size
        )

        self.label = BL_UI_Button(0, 0, pix_size[0] + 2 * margin, self.height)
        self.label.text = self.task["text"]
        self.label.text_size = text_size
        self.label.text_color = self.text_color

        self.label.bg_color = self.bg_color
        self.label.hover_bg_color = self.hover_bg_color
        # self.label.set_mouse_down(self.open_link)

        self.button_close = BL_UI_Button(
            self.button_size * 0.75,
            -self.button_size * 1.25,
            self.button_size / 2,
            self.button_size / 2,
        )
        self.button_close.bg_color = self.bg_color
        self.button_close.hover_bg_color = self.hover_bg_color
        self.button_close.text = ""
        self.button_close.set_mouse_down(self.cancel_press)
        self._timer_interval = 0.04

    def on_invoke(self, context, event):
        # Add new widgets here (TODO: perhaps a better, more automated solution?)
        self.context = context
        self.instances.append(self)

        # no task, no downloader...
        if self._finished:
            return {"FINISHED"}

        widgets_panel = [self.label, self.image, self.button_close]
        widgets = [self.panel]

        widgets += widgets_panel

        # assign image to the cancel button
        img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
        img_size = self.button_size
        button_size = int(self.button_size / 2)
        button_pos = self.button_size * 0.75

        self.button_close.set_image(img_fp)
        self.button_close.set_image_size((button_size, button_size))
        self.button_close.set_image_position((0, 0))

        directory = paths.get_temp_dir("%s_search" % self.asset_data["assetType"])
        tpath = os.path.join(directory, self.asset_data["thumbnail_small"])

        self.image.set_image(tpath)
        self.image.set_image_size((img_size, img_size))
        self.image.set_image_position((0, 0))

        self.init_widgets(context, widgets)
        self.panel.add_widgets(widgets_panel)

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}

        if self.task is None or self.task_key not in download.download_tasks:
            self.finish()
            return {"PASS_THROUGH"}

        if not context.area:
            # end if area disappears
            self.finish()
            return {"PASS_THROUGH"}

        # if event.type == "MOUSEMOVE":
        if bpy.context.space_data is not None:
            loc = view3d_utils.location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.space_data.region_3d,
                self.downloader["location"],
            )
            if loc is None:
                loc = Vector((0, 0))
        else:
            loc = Vector((0, 0))

        self.panel.set_location(loc.x, context.region.height - loc.y)
        self.label.text = self.task["text"]
        if self.handle_widget_events(event):
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def on_finish(self, context):
        self._finished = True

    @classmethod
    def unregister(cls):
        bk_logger.debug(f"unregistering class {cls}")
        instances_copy = cls.instances.copy()
        for instance in instances_copy:
            bk_logger.debug(f"- class instance {instance}")
            try:
                instance.unregister_handlers(instance.context)
            except Exception as e:
                bk_logger.debug(f"-- error unregister_handlers(): {e}")
            try:
                instance.on_finish(instance.context)
            except Exception as e:
                bk_logger.debug(f"-- error calling on_finish() {e}")
            if bpy.context.region is not None:
                bpy.context.region.tag_redraw()

            cls.instances.remove(instance)


def analyze_gn_tree(tree, materials):
    """Recursively analyze GN tree and its node groups for Set Material nodes"""
    current_mapping = {}

    print("\nAnalyzing GN tree:", tree.name)
    for node in tree.nodes:
        print(f"Checking node: {node.name}, type: {node.type}")
        if node.type == "SET_MATERIAL":
            # Find material index in evaluated mesh
            mat = node.inputs["Material"].default_value
            print(
                f"Found Set Material node with material: {mat.name if mat else 'None'}"
            )
            if mat:
                for mat_idx, temp_mat in enumerate(materials):
                    if compare_material_names(temp_mat, mat):
                        print(f"Matched material to index {mat_idx}")
                        current_mapping[mat_idx] = {
                            "type": "GN",
                            "node_name": node.name,
                            "tree_name": tree.name,
                        }
            else:
                # If no material is set, we can use this node for a new material
                # Find first available index that isn't mapped
                used_indices = set(current_mapping.keys())
                for i in range(len(materials)):
                    if i not in used_indices:
                        print(f"Using empty Set Material node for index {i}")
                        current_mapping[i] = {
                            "type": "GN",
                            "node_name": node.name,
                            "tree_name": tree.name,
                        }
                        break

        # Check node groups recursively
        elif node.type == "GROUP" and node.node_tree:
            nested_mapping = analyze_gn_tree(node.node_tree, materials)
            current_mapping.update(nested_mapping)

    return current_mapping


def compare_material_names(mat1, mat2):
    """Compare two materials by name, but if one is None, use 'None' instead of mat1.name"""
    if mat1 is None:
        return mat2 is None
    elif mat2 is None:  #
        return False
    return mat1.name == mat2.name


def create_material_mapping(object, temp_mesh):
    """Creates mapping between material indices and their sources (slots or GN nodes)"""
    mapping = {}

    print(f"\nCreating mapping for {object.name}")
    print(f"Material slots: {len(object.material_slots)}")
    print(f"Has GN: {any(mod.type == 'NODES' for mod in object.modifiers)}")

    # 1. First map regular material slots
    for slot_idx, slot in enumerate(object.material_slots):
        # Find matching material in evaluated mesh
        for mat_idx, mat in enumerate(temp_mesh.materials):
            if compare_material_names(mat, slot.material):
                mapping[mat_idx] = {"type": "SLOT", "index": slot_idx}
                break  # Stop after finding first match

    # 2. Check Geometry Nodes
    has_gn = False
    for modifier in object.modifiers:
        if modifier.type == "NODES":
            has_gn = True
            gn_mapping = analyze_gn_tree(modifier.node_group, temp_mesh.materials)
            if gn_mapping:
                # Only add GN mappings for indices that aren't already mapped to slots
                for idx, map_data in gn_mapping.items():
                    if idx not in mapping:
                        mapping[idx] = map_data

    # 3. If no material slots and no GN, create a mapping for slot 0
    if len(object.material_slots) == 0 and not has_gn:
        print("Creating default mapping to slot 0")
        mapping[0] = {"type": "SLOT", "index": 0}

    print(f"Final mapping: {mapping}")

    # Store mapping as custom property (convert to serializable format)
    mapping_data = {str(k): v for k, v in mapping.items()}
    object["material_mapping"] = mapping_data

    return mapping


def add_set_material_node(tree):
    """Add a Set Material node at the end of the node tree"""
    # Find output node
    output_node = None
    for node in tree.nodes:
        if node.type == "GROUP_OUTPUT":
            output_node = node
            break

    if output_node:
        # Create Set Material node
        set_mat_node = tree.nodes.new("GeometryNodeSetMaterial")
        # Position it before output
        set_mat_node.location = (output_node.location.x - 200, output_node.location.y)

        # Connect nodes
        last_geometry_socket = None
        for input in output_node.inputs:
            if input.type == "GEOMETRY":
                if input.is_linked:
                    last_geometry_socket = input.links[0].from_socket
                break

        if last_geometry_socket:
            tree.links.new(last_geometry_socket, set_mat_node.inputs["Geometry"])
            tree.links.new(set_mat_node.outputs["Geometry"], output_node.inputs[0])

        return set_mat_node
    return None


classes = (
    AssetDragOperator,
    DownloadGizmoOperator,
)


def register():
    # register the classes
    global handler_2d, handler_3d

    for c in classes:
        bpy.utils.register_class(c)

    args = (None, bpy.context)

    handler_2d = bpy.types.SpaceView3D.draw_handler_add(
        draw_callback_2d_progress, args, "WINDOW", "POST_PIXEL"
    )
    handler_3d = bpy.types.SpaceView3D.draw_handler_add(
        draw_callback_3d_progress, args, "WINDOW", "POST_VIEW"
    )


def unregister():
    global handler_2d, handler_3d

    bpy.types.SpaceView3D.draw_handler_remove(handler_2d, "WINDOW")
    bpy.types.SpaceView3D.draw_handler_remove(handler_3d, "WINDOW")

    # unregister the classes
    for c in classes:
        bpy.utils.unregister_class(c)
