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
from typing import Union

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


bk_logger = logging.getLogger(__name__)

handler_2d = None
handler_3d = None


def draw_callback_dragging(self, context):
    # Only draw 2D elements in the active region where the mouse is, also check if self still exists
    if (
        self is None
        or not hasattr(self, "active_region_pointer")
        or context.region.as_pointer() != self.active_region_pointer
    ):
        return

    try:
        img = bpy.data.images.get(self.iname)
        if img is None:
            # thumbnail can be sometimes missing (probably removed by Blender) so lets add it
            directory = paths.get_temp_dir(f"{self.asset_data['assetType']}_search")
            tpath = os.path.join(directory, self.asset_data["thumbnail_small"])
            img = bpy.data.images.load(tpath)
            img.name = self.iname
    except Exception as e:
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
    # text messages in 3d view
    if context.area.type == "VIEW_3D":
        if self.asset_data["assetType"] == "material":
            ui_bgl.draw_text(
                f"Assign material to {self.object_name}",
                self.mouse_x,
                self.mouse_y - linelength - 20 - ui_props.thumb_size,
                16,
                (0.9, 0.9, 0.9, 1.0),
            )

    # Add node editor specific hints
    if hasattr(self, "in_node_editor") and self.in_node_editor:
        if self.asset_data["assetType"] not in ["material", "nodegroup"]:
            # Draw warning for incompatible asset types
            ui_bgl.draw_text(
                "Cancel Drag & Drop",
                self.mouse_x,
                self.mouse_y - linelength - 20 - ui_props.thumb_size,
                16,
                (0.9, 0.9, 0.9, 1.0),
            )
        elif (
            self.asset_data["assetType"] == "material"
            and self.node_editor_type == "shader"
        ):
            # Draw material hints for shader editor
            ui_bgl.draw_text(
                "Drop to replace active material",
                self.mouse_x,
                self.mouse_y - linelength - 20 - ui_props.thumb_size,
                16,
                (0.9, 0.9, 0.9, 1.0),
            )
        elif self.asset_data["assetType"] == "nodegroup":
            # Draw nodegroup hints
            nodegroup_type = self.asset_data["dictParameters"].get("nodeType")

            if self.is_nodegroup_compatible_with_editor(
                nodegroup_type, self.node_editor_type
            ):
                ui_bgl.draw_text(
                    "Drop to add node group",
                    self.mouse_x,
                    self.mouse_y - linelength - 20 - ui_props.thumb_size,
                    16,
                    (0.9, 0.9, 0.9, 1.0),
                )
            else:
                # More specific message about what will happen
                switch_message = f"Drop to switch to "
                if nodegroup_type == "shader":
                    switch_message += "shader editor"
                elif nodegroup_type == "geometry":
                    switch_message += "geometry nodes editor"
                elif nodegroup_type == "compositor":
                    switch_message += "compositor"
                else:
                    switch_message = "Drop to switch editor type"

                ui_bgl.draw_text(
                    switch_message,
                    self.mouse_x,
                    self.mouse_y - linelength - 20 - ui_props.thumb_size,
                    16,
                    (0.9, 0.9, 0.9, 1.0),
                )
    elif context.area.type not in ["VIEW_3D", "OUTLINER"]:
        # draw under the image
        ui_bgl.draw_text(
            "Cancel Drag & Drop",
            self.mouse_x,
            self.mouse_y - linelength - 20 - ui_props.thumb_size,
            16,
            (0.9, 0.9, 0.9, 1.0),
        )


def draw_callback_3d_dragging(self, context):
    """Draw snapped bbox while dragging."""
    if not utils.guard_from_crash():
        return

    # Only draw 3D elements in VIEW_3D areas, not in outliner
    if context.area.type != "VIEW_3D":
        return

    # Check if all required attributes are available
    required_attrs = [
        "has_hit",
        "snapped_location",
        "snapped_rotation",
        "snapped_bbox_min",
        "snapped_bbox_max",
        "asset_data",
    ]

    for attr in required_attrs:
        if not hasattr(self, attr):
            return

    # Only continue if we have a hit in a 3D view
    if not self.has_hit:
        return

    ui_props = bpy.context.window_manager.blenderkitUI
    # print(self.asset_data["assetType"], self.has_hit, self.snapped_location)
    if self.asset_data["assetType"] in ["model", "printable"]:
        draw_bbox(
            self.snapped_location,
            self.snapped_rotation,
            self.snapped_bbox_min,
            self.snapped_bbox_max,
        )


def draw_bbox(
    location, rotation, bbox_min, bbox_max, progress=None, color=(0, 1, 0, 1)
):
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


def mouse_raycast(region, rv3d, mx, my):
    coord = mx, my

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    if rv3d.view_perspective == "CAMERA" and rv3d.is_perspective == False:
        #  ortographic cameras don'w work with region_2d_to_origin_3d
        view_position = rv3d.view_matrix.inverted().translation
        ray_origin = view3d_utils.region_2d_to_location_3d(
            region, rv3d, coord, depth_location=view_position
        )
    else:
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord, clamp=1.0)

    ray_target = ray_origin + (view_vector * 1000000000)

    vec = ray_target - ray_origin

    (
        has_hit,
        snapped_location,
        snapped_normal,
        face_index,
        object,
        matrix,
    ) = deep_ray_cast(ray_origin, vec)

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


def floor_raycast(r, rv3d, mx, my):
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


def deep_ray_cast(ray_origin, vec):
    # this allows to ignore some objects, like objects with bounding box draw style or particle objects
    object = None
    # while object is None or object.draw
    depsgraph = bpy.context.view_layer.depsgraph
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
        or not try_object.visible_get(viewport=bpy.context.space_data)
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
        """Remove all draw handlers."""
        # Remove specific handlers for VIEW_3D and Outliner
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")

        # Remove handlers for all other space types
        if hasattr(self, "_handlers_universal"):
            for space_type, handler in self._handlers_universal.items():
                if handler:
                    getattr(bpy.types, space_type).draw_handler_remove(
                        handler, "WINDOW"
                    )

    def is_nodegroup_compatible_with_editor(self, nodegroup_type, editor_type):
        """Check if a nodegroup of a specific type is compatible with the given editor type."""
        # Direct matches
        if nodegroup_type == editor_type:
            return True
        # Generic nodegroups can work in any editor
        elif nodegroup_type is None:
            return True
        # Otherwise, not compatible
        return False

    def handle_view3d_drop(self, context):
        """Handle dropping assets in the 3D view."""
        scene = context.scene
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
                object = context.active_object
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
                    depsgraph = context.evaluated_depsgraph_get()
                    object_eval = object.evaluated_get(depsgraph)

                    if object.type == "MESH":
                        temp_mesh = object_eval.to_mesh()
                        mapping = create_material_mapping(object, temp_mesh)
                        target_slot = temp_mesh.polygons[self.face_index].material_index
                        object_eval.to_mesh_clear()
                    else:
                        self.snapped_location = object.location
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
                invoke_resolution=True,
                use_resolution_operator=True,
                max_resolution=self.asset_data.get("max_resolution", 0),
            )

        if self.asset_data["assetType"] == "scene":
            bpy.ops.scene.blenderkit_download(
                "INVOKE_DEFAULT",
                asset_index=self.asset_search_index,
                invoke_resolution=False,
                invoke_scene_settings=True,
            )

        if self.asset_data["assetType"] == "brush":
            bpy.ops.scene.blenderkit_download(
                asset_index=self.asset_search_index,
            )

        if self.asset_data["assetType"] in ["material", "model"]:
            bpy.ops.view3d.blenderkit_download_gizmo_widget(
                "INVOKE_REGION_WIN",
                asset_base_id=self.asset_data["assetBaseId"],
            )

    def handle_outliner_drop(self, context):
        """Handle dropping assets in the outliner."""
        if self.asset_data["assetType"] in ["model", "printable"]:
            target_object = ""
            target_collection = ""

            # Check what type of element we're dropping on
            element_type = type(self.hovered_outliner_element).__name__

            # If dropping on a collection, set target_collection parameter
            if isinstance(self.hovered_outliner_element, bpy.types.Collection):
                target_collection = self.hovered_outliner_element.name
            # Otherwise if dropping on an object, set it as parent
            elif isinstance(self.hovered_outliner_element, bpy.types.Object):
                target_object = self.hovered_outliner_element.name
            else:
                # Unsupported element type - just continue with default values
                pass

            # Place the asset at the origin or at a default location
            self.snapped_location = (0, 0, 0)
            self.snapped_rotation = (0, 0, 0)

            # Download the asset with the target collection or parent
            bpy.ops.scene.blenderkit_download(
                True,
                asset_index=self.asset_search_index,
                model_location=self.snapped_location,
                model_rotation=self.snapped_rotation,
                target_object=target_object,
                target_collection=target_collection,
            )

            # Restore original selection
            self.restore_original_selection()

        elif self.asset_data["assetType"] == "material":
            # If dropping a material on an object in the outliner
            target_object = self.hovered_outliner_element.name

            # Check if object supports materials, it can also be a collection
            if not (
                type(self.hovered_outliner_element) == bpy.types.Object
                and self.hovered_outliner_element.type in ["MESH", "CURVE"]
            ):
                reports.add_report(
                    f"Can't assign materials to this outliner element.",
                    type="ERROR",
                )
                return

            # Use active material slot or create one
            target_slot = self.hovered_outliner_element.active_material_index

            # Position is for downloader
            loc = (0, 0, 0)
            rotation = (0, 0, 0)

            # Try to automap if it's a mesh
            if self.hovered_outliner_element.type == "MESH":
                utils.automap(
                    target_object,
                    target_slot=target_slot,
                    tex_size=self.asset_data.get("texture_size_meters", 1.0),
                )

            # Download the material
            bpy.ops.scene.blenderkit_download(
                True,
                asset_index=self.asset_search_index,
                model_location=loc,
                model_rotation=rotation,
                target_object=target_object,
                material_target_slot=target_slot,
            )

            # Restore original selection
            self.restore_original_selection()

    def make_node_editor_switch(self, nodegroup_type, node_editor_type):
        """Make a node editor switch."""
        print("making node editor switch")
        print(nodegroup_type, node_editor_type)
        nodeTypes2NodeEditorType = {
            "shader": "ShaderNodeTree",
            "geometry": "GeometryNodeTree",
            "compositor": "CompositorNodeTree",
        }
        node_editor_type = nodeTypes2NodeEditorType[nodegroup_type]
        area = self.find_active_area(self.mouse_x, self.mouse_y, bpy.context)
        area.ui_type = node_editor_type
        print(node_editor_type)

    def handle_node_editor_drop_material(self, context):
        """Handle dropping materials in the node editor."""
        active_object = context.active_object

        if not active_object:
            # No active object, can't assign material
            reports.add_report("No active object to assign material to", type="ERROR")
            return

        if active_object.type not in utils.supported_material_drag:
            # Object type doesn't support materials
            reports.add_report(
                f"Can't assign materials to {active_object.type.lower()} object",
                type="ERROR",
            )
            return

        # Use active material slot or create one
        target_slot = active_object.active_material_index

        # Download the material
        bpy.ops.scene.blenderkit_download(
            True,
            asset_index=self.asset_search_index,
            model_location=(0, 0, 0),
            model_rotation=(0, 0, 0),
            target_object=active_object.name,
            material_target_slot=target_slot,
        )
        return

    def handle_node_editor_drop(self, context):
        """Handle dropping assets in the node editor."""
        # Check if asset type is compatible with the node editor
        if self.asset_data["assetType"] not in ["material", "nodegroup"]:
            reports.add_report(
                f"{self.asset_data['assetType'].capitalize()} assets cannot be used in node editors",
                type="ERROR",
            )
            return

        # Handle material drop in shader editor
        if (
            self.asset_data["assetType"] == "material"
            and self.node_editor_type == "shader"
        ):
            self.handle_node_editor_drop_material(context)
            return

        # Handle nodegroup drop
        if self.asset_data["assetType"] == "nodegroup":
            # Get the mouse position in the node editor
            node_space = self.find_active_area(self.mouse_x, self.mouse_y, context)
            nodegroup_type = self.asset_data["dictParameters"].get("nodeType")

            # Check if the nodegroup type is compatible with the current editor
            if not self.is_nodegroup_compatible_with_editor(
                nodegroup_type, self.node_editor_type
            ):
                self.make_node_editor_switch(nodegroup_type, self.node_editor_type)

            if nodegroup_type == "geometry":
                # Try to switch to geometry nodes
                active_object = context.active_object
                if active_object and active_object.type in ["MESH", "CURVE"]:

                    # Check if there's a geometry nodes modifier
                    gn_mod = None
                    for mod in active_object.modifiers:
                        if mod.type == "NODES":
                            gn_mod = mod
                            if gn_mod.node_group:  # Only use it if it has a node group
                                break
                            # Otherwise keep looking for a better one

                    # If no geometry nodes modifier, add one
                    if not gn_mod:
                        # Create a new one
                        reports.add_report(
                            "No geometry nodes modifier found, adding one", type="INFO"
                        )
                        gn_mod = active_object.modifiers.new(
                            name="GeometryNodes", type="NODES"
                        )

                    if not gn_mod.node_group:
                        # Modifier exists but doesn't have a node group
                        # Create a new node group
                        node_group = bpy.data.node_groups.new(
                            "Geometry Nodes", "GeometryNodeTree"
                        )
                        # Add input and output nodes
                        input_node = node_group.nodes.new("NodeGroupInput")
                        output_node = node_group.nodes.new("NodeGroupOutput")
                        # Add a geometry socket to the group
                        node_group.interface.new_socket(
                            "Geometry",
                            description="Geometry",
                            in_out="OUTPUT",
                            socket_type="NodeSocketGeometry",
                        )
                        node_group.interface.new_socket(
                            "Geometry",
                            description="Geometry",
                            in_out="INPUT",
                            socket_type="NodeSocketGeometry",
                        )
                        # Position nodes
                        input_node.location = (-200, 0)
                        output_node.location = (200, 0)
                        # Link the nodes
                        node_group.links.new(
                            input_node.outputs["Geometry"],
                            output_node.inputs["Geometry"],
                        )
                        # Assign the node group to the modifier
                        gn_mod.node_group = node_group

                    # Make sure we have a node tree to work with
                    node_tree = gn_mod.node_group
                    # redraw the area so we get correct coordinates
                    node_space.tag_redraw()

                else:
                    reports.add_report(
                        "Need an active object for geometry nodes",
                        type="ERROR",
                    )
                    return

            # Third case: need to switch to shader nodes for shader nodegroup
            elif nodegroup_type == "shader":
                # Try to find a material to edit
                active_object = context.active_object
                node_tree = None

                if not active_object:
                    reports.add_report("No active object", type="ERROR")
                    return

                if not active_object.active_material:
                    temp_material = bpy.data.materials.new("Temporary Material")
                    active_object.active_material = temp_material

                active_material = active_object.active_material
                # Use active material
                if not active_material.use_nodes:
                    active_material.use_nodes = True
                node_tree = active_material.node_tree

                # Set the node tree AFTER changing the editor type
                node_space.spaces[0].node_tree = node_tree

            # Fourth case: need to switch to compositor nodes for compositor nodegroup
            elif nodegroup_type == "compositor":

                # Try to find the compositor node tree
                if context.scene.use_nodes and context.scene.node_tree:
                    node_tree = context.scene.node_tree
                else:
                    # Enable compositor nodes if not already enabled
                    context.scene.use_nodes = True
                    node_tree = context.scene.node_tree

                # Set the node tree AFTER changing the editor type
                node_space.spaces[0].node_tree = node_tree
                # Force a redraw to make sure the editor updates

            # Finally doing the real stuff
            # Get node position
            region = context.region
            node_pos = self.get_node_editor_cursor_position(context, region)

            # Download the nodegroup
            bpy.ops.scene.blenderkit_download(
                True,
                asset_index=self.asset_search_index,
                node_x=node_pos[0],
                node_y=node_pos[1],
            )
            return

    def mouse_release(self, context):
        """Main mouse release handler that delegates to specific handlers based on area type."""

        # In any other area than 3D view and outliner, we just cancel the drag&drop
        if self.prev_area_type not in ["VIEW_3D", "OUTLINER", "NODE_EDITOR"]:
            return

        # Handle Node Editor drop
        if self.in_node_editor:
            self.handle_node_editor_drop(context)
            return

        # Handle Outliner drop
        if (
            hasattr(self, "hovered_outliner_element")
            and self.hovered_outliner_element is not None
        ):
            self.handle_outliner_drop(context)
            return

        # Handle 3D View drop
        self.handle_view3d_drop(context)

    def find_active_region(self, x, y, context=None, window=None):
        """Find the region and area under the mouse cursor in the specified window."""
        if context is None:
            context = bpy.context
        if window is None:
            window = context.window
        for area in window.screen.areas:
            for region in area.regions:
                if region.type != "WINDOW":
                    continue
                if (
                    region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height
                ):
                    return region, area
        return None, None

    def find_active_area(self, x, y, context=None, window=None):
        """Find the area under the mouse cursor in the specified window."""
        if context is None:
            context = bpy.context
        if window is None:
            window = context.window
        for area in window.screen.areas:
            if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
                return area
        return None

    def find_outliner_element_under_mouse(
        self, context: Union[bpy.types.Context, dict], x, y
    ):
        """Find and select the element under the mouse in the outliner.
        Returns the selected object, collection, or None."""
        if isinstance(context, dict):
            area = context["area"]
            region = context["region"]
            window = context["window"]
            selected_objects = context["selected_objects"]
            active_object = context["active_object"]
            view_layer = context["view_layer"]
        else:
            area = context.area
            region = context.region
            window = context.window
            selected_objects = context.selected_objects
            active_object = context.active_object
            view_layer = context.view_layer

        if not area or area.type != "OUTLINER":
            return None

        # Store original selection to restore if needed
        orig_selected_objects = selected_objects.copy()
        orig_active_object = active_object
        # Store original active collection
        orig_active_collection = view_layer.active_layer_collection

        # Use outliner's built-in selection to find what's under the mouse
        if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
            override = {
                "window": window,
                "screen": window.screen,
                "area": area,
                "region": region,
                "scene": context["scene"],
                "view_layer": view_layer,
            }
            rel_x = x - region.x
            rel_y = y - region.y
            bpy.ops.outliner.select_box(
                override,
                xmin=rel_x - 1,
                xmax=rel_x + 1,
                ymin=rel_y - 1,
                ymax=rel_y + 1,
                wait_for_input=False,
                mode="SET",
            )
        else:  # B3.2+ can use context.temp_override()
            with bpy.context.temp_override(
                region=region,
                area=area,
                window=window,
            ):
                # Calculate coordinates relative to region
                rel_x = x - region.x
                rel_y = y - region.y

                # Try to select what's under the mouse
                bpy.ops.outliner.select_box(
                    xmin=rel_x - 1,
                    xmax=rel_x + 1,
                    ymin=rel_y - 1,
                    ymax=rel_y + 1,
                    wait_for_input=False,
                    mode="SET",
                )

        # Get the newly selected element using selected_ids
        selected_element = None
        if hasattr(bpy.context, "selected_ids") and len(bpy.context.selected_ids) > 0:
            selected_element = bpy.context.selected_ids[0]

        # Keep the highlight for visual feedback, but store the original selection
        self.orig_selected_objects = orig_selected_objects
        self.orig_active_object = orig_active_object
        self.orig_active_collection = orig_active_collection

        return selected_element

    def restore_original_selection(self):
        """Restore the original object selection that was active before entering the outliner."""
        if (
            hasattr(self, "orig_selected_objects")
            and self.orig_selected_objects is not None
        ):
            # Deselect all objects
            bpy.ops.object.select_all(action="DESELECT")
            # Restore original selection
            for obj in self.orig_selected_objects:
                if obj:  # Check if object still exists
                    obj.select_set(True)
            if self.orig_active_object:
                bpy.context.view_layer.objects.active = self.orig_active_object

            # Reset the stored selection to avoid restoring it multiple times
            self.orig_selected_objects = None
            self.orig_active_object = None

        # Restore original active collection
        if (
            hasattr(self, "orig_active_collection")
            and self.orig_active_collection is not None
        ):
            # Restore the original active layer collection
            if hasattr(bpy.context, "view_layer"):
                bpy.context.view_layer.active_layer_collection = (
                    self.orig_active_collection
                )
            self.orig_active_collection = None

        # Clear outliner selection
        if hasattr(bpy.context, "selected_ids"):
            # This is a read-only property, so we can't directly clear it
            # Instead, we can deselect in the outliner
            if self.prev_area_type == "OUTLINER":
                # need to create a new context to deselect in the outliner
                if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                    context = bpy.context
                    override = {
                        "window": context.window,
                        "screen": context.screen,
                        "area": self.outliner_area,
                        "region": self.outliner_region,
                        "scene": context.scene,
                        "view_layer": context.view_layer,
                    }
                    # Only try to deselect if we have valid area and region
                    if self.outliner_area and self.outliner_region:
                        bpy.ops.outliner.select_box(
                            override,
                            xmin=0,
                            xmax=1,
                            ymin=0,
                            ymax=1,
                            wait_for_input=False,
                            mode="SET",
                        )  # Use a very small selection box in the corner to deselect everything
                else:  # B3.2+ can use context.temp_override()
                    with bpy.context.temp_override(
                        area=self.outliner_area, region=self.outliner_region
                    ):
                        bpy.ops.outliner.select_box(
                            xmin=0,
                            xmax=1,
                            ymin=0,
                            ymax=1,
                            wait_for_input=False,
                            mode="SET",
                        )  # Use a very small selection box in the corner to deselect everything

    def modal(self, context, event):
        ui_props = bpy.context.window_manager.blenderkitUI

        # if event.type == 'MOUSEMOVE':
        if not hasattr(self, "start_mouse_x"):
            self.start_mouse_x = event.mouse_region_x
            self.start_mouse_y = event.mouse_region_y

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        # Store the actual screen coordinates for finding the active region
        self.mouse_screen_x = event.mouse_x
        self.mouse_screen_y = event.mouse_y

        # Find the active region under the mouse cursor
        active_region, active_area = self.find_active_region(
            event.mouse_x, event.mouse_y, context, context.window
        )

        # --- CURSOR VISIBILITY FIX ---
        if active_region is None or active_area is None:
            bpy.context.window.cursor_set("DEFAULT")
        else:
            if self.drag:
                bpy.context.window.cursor_set("NONE")

        # --- REDRAW ALL WINDOWS/AREAS FOR MULTI-WINDOW DRAG ---
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        if active_area is not None:
            active_area.tag_redraw()

        current_area_type = active_area.type if active_area else None

        # Check if we're transitioning out of the outliner
        if (
            hasattr(self, "prev_area_type")
            and self.prev_area_type == "OUTLINER"
            and current_area_type != "OUTLINER"
        ):
            # If we're leaving the outliner, restore the original selection
            self.restore_original_selection()

        # Track if we're in a node editor
        self.in_node_editor = False
        self.node_editor_type = None

        if current_area_type == "NODE_EDITOR":
            self.in_node_editor = True
            if active_area.spaces.active.tree_type == "ShaderNodeTree":
                self.node_editor_type = "shader"
            elif active_area.spaces.active.tree_type == "GeometryNodeTree":
                self.node_editor_type = "geometry"
            elif active_area.spaces.active.tree_type == "CompositorNodeTree":
                self.node_editor_type = "compositor"
            elif active_area.spaces.active.tree_type == "TextureNodeTree":
                self.node_editor_type = "texture"

        # Update the previous area type for the next frame
        if current_area_type:
            self.prev_area_type = current_area_type

        if active_region and active_area:
            # Recalculate mouse_region_x and mouse_region_y for the new region
            self.mouse_x = event.mouse_x - active_region.x
            self.mouse_y = event.mouse_y - active_region.y
            # Store the active region pointer for drawing 2D elements only in this region
            self.active_region_pointer = active_region.as_pointer()
            # Make sure all 3D views get redrawn
            for area in context.screen.areas:
                # if area.type in ['VIEW_3D', 'OUTLINER']:
                area.tag_redraw()

            # Handle outliner interaction
            if active_area.type == "OUTLINER":
                # Need to temporarily override context to work with the outliner
                if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                    context_override = {
                        "window": context.window,
                        "screen": context.screen,
                        "area": active_area,
                        "region": active_region,
                        "scene": context.scene,
                        "view_layer": context.view_layer,
                        "selected_objects": context.selected_objects,
                        "active_object": context.active_object,
                    }
                    self.hovered_outliner_element = (
                        self.find_outliner_element_under_mouse(
                            context_override, event.mouse_x, event.mouse_y
                        )
                    )
                    # Store outliner area and region for mouse release handling
                    self.outliner_area = active_area
                    self.outliner_region = active_region
                else:  # B3.2+ can use context.temp_override()
                    with bpy.context.temp_override(
                        area=active_area, region=active_region
                    ):
                        # Find and highlight the element under the mouse
                        self.hovered_outliner_element = (
                            self.find_outliner_element_under_mouse(
                                bpy.context, event.mouse_x, event.mouse_y
                            )
                        )
                        # Store outliner area and region for mouse release handling
                        self.outliner_area = active_area
                        self.outliner_region = active_region
            else:
                # Reset outliner tracking
                self.hovered_outliner_element = None
                self.outliner_area = None
                self.outliner_region = None
        else:
            # If no active 3D region is found, use the context region
            self.active_region_pointer = context.region.as_pointer()

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

        if event.type in {"RIGHTMOUSE", "ESC"}:
            # Restore original selection if we changed it
            self.restore_original_selection()

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
            # Find active region for raycasting
            active_region, active_area = self.find_active_region(
                event.mouse_x, event.mouse_y, context, context.window
            )
            # sometimes active area can be None, so we need to check for that
            if active_area is None:
                return {"RUNNING_MODAL"}

            # Only perform raycasting in 3D view areas
            if active_region and active_area and active_area.type == "VIEW_3D":
                # Use mouse coordinates relative to the active region
                region_mouse_x = event.mouse_x - active_region.x
                region_mouse_y = event.mouse_y - active_region.y

                for space in active_area.spaces:
                    if space.type == "VIEW_3D":
                        region_data = space.region_3d
                # Need to temporarily override context for raycasting
                if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                    override = {
                        "window": context.window,
                        "screen": context.screen,
                        "area": active_area,
                        "region": active_region,
                        "region_data": active_area.spaces[
                            0
                        ].region_3d,  # Get region_data from space_data
                        "scene": context.scene,
                        "view_layer": context.view_layer,
                    }
                    (
                        self.has_hit,
                        self.snapped_location,
                        self.snapped_normal,
                        self.snapped_rotation,
                        self.face_index,
                        object,
                        self.matrix,
                    ) = mouse_raycast(
                        active_region, region_data, region_mouse_x, region_mouse_y
                    )
                    if object is not None:
                        self.object_name = object.name
                else:  # B3.2+ can use context.temp_override()
                    with bpy.context.temp_override(
                        area=active_area, region=active_region
                    ):
                        (
                            self.has_hit,
                            self.snapped_location,
                            self.snapped_normal,
                            self.snapped_rotation,
                            self.face_index,
                            object,
                            self.matrix,
                        ) = mouse_raycast(
                            active_region, region_data, region_mouse_x, region_mouse_y
                        )
                        if object is not None:
                            self.object_name = object.name

            # MODELS can be dragged on scene floor
            if not self.has_hit and self.asset_data["assetType"] in [
                "model",
                "printable",
            ]:
                # Use mouse coordinates relative to the active region
                region_mouse_x = event.mouse_x - active_region.x
                region_mouse_y = event.mouse_y - active_region.y

                # Need to temporarily override context for raycasting
                if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                    override = {
                        "window": context.window,
                        "screen": context.screen,
                        "area": active_area,
                        "region": active_region,
                        "region_data": active_area.spaces[
                            0
                        ].region_3d,  # Get region_data from space_data
                        "scene": context.scene,
                        "view_layer": context.view_layer,
                    }
                    (
                        self.has_hit,
                        self.snapped_location,
                        self.snapped_normal,
                        self.snapped_rotation,
                        self.face_index,
                        object,
                        self.matrix,
                    ) = floor_raycast(
                        active_region, region_data, region_mouse_x, region_mouse_y
                    )
                    if object is not None:
                        self.object_name = object.name
                else:  # B3.2+ can use context.temp_override()
                    with bpy.context.temp_override(
                        area=active_area, region=active_region
                    ):
                        (
                            self.has_hit,
                            self.snapped_location,
                            self.snapped_normal,
                            self.snapped_rotation,
                            self.face_index,
                            object,
                            self.matrix,
                        ) = floor_raycast(
                            active_region, region_data, region_mouse_x, region_mouse_y
                        )
                        if object is not None:
                            self.object_name = object.name

            if self.asset_data["assetType"] in ["model", "printable"]:
                self.snapped_bbox_min = Vector(self.asset_data["bbox_min"])
                self.snapped_bbox_max = Vector(self.asset_data["bbox_max"])
            elif active_area.type != "VIEW_3D":
                # In outliner, don't do raycasting, but keep has_hit to avoid errors
                self.has_hit = False

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self.mouse_release(context)  # Pass context here
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")

            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
            ui_props.dragging = False
            return {"FINISHED"}

        self.steps += 1

        # pass event to assetbar so it can close itself
        if ui_props.assetbar_on and ui_props.turn_off:
            return {"PASS_THROUGH"}

        # --- WINDOW HANDOVER LOGIC ---
        # Find which window the mouse is currently over
        mouse_window = None
        for window in bpy.context.window_manager.windows:
            # Window bounds are in screen coordinates
            x, y = window.x, window.y
            width, height = window.width, window.height
            if (x <= event.mouse_x < x + width) and (y <= event.mouse_y < y + height):
                mouse_window = window
                break
        if mouse_window is not None and mouse_window != context.window:
            # Cancel in old window
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.dragging = False
            # Start the operator in the new window
            bpy.ops.view3d.asset_drag_drop("INVOKE_DEFAULT")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        # We now accept all area types
        # if context.area.type not in ["VIEW_3D", "OUTLINER"]:
        #     self.report({"WARNING"}, "View3D or Outliner not found, cannot run operator")
        #     return {"CANCELLED"}

        # the arguments we pass the the callback
        args = (self, context)

        # Register callback for VIEW_3D spaces
        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_3d_dragging, args, "WINDOW", "POST_VIEW"
        )

        # Register callbacks for all other space types
        # List of space types we want to support
        space_types = [
            "SpaceTextEditor",
            "SpaceConsole",
            "SpaceInfo",
            "SpacePreferences",
            "SpaceFileBrowser",
            "SpaceNLA",
            "SpaceDopeSheetEditor",
            "SpaceGraphEditor",
            "SpaceNodeEditor",
            "SpaceProperties",
            "SpaceSequenceEditor",
            "SpaceImageEditor",
            "SpaceView3D",
            "SpaceOutliner",
        ]

        # Initialize a dictionary to store handlers
        self._handlers_universal = {}

        # Register a handler for each space type
        for space_type in space_types:
            try:
                space_class = getattr(bpy.types, space_type)
                handler = space_class.draw_handler_add(
                    draw_callback_dragging, args, "WINDOW", "POST_PIXEL"
                )
                self._handlers_universal[space_type] = handler
            except (AttributeError, TypeError) as e:
                print(f"Could not register handler for {space_type}: {e}")
                self._handlers_universal[space_type] = None

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_screen_x = 0
        self.mouse_screen_y = 0
        self.steps = 0
        # Store the initial active region pointer
        self.active_region_pointer = context.region.as_pointer()

        # Initialize outliner tracking variables
        self.hovered_outliner_element = None
        self.outliner_area = None
        self.outliner_region = None
        self.orig_selected_objects = None
        self.orig_active_object = None
        self.orig_active_collection = None
        self.prev_area_type = context.area.type  # Track previous area type

        # Initialize node editor tracking
        self.in_node_editor = False
        self.node_editor_type = None

        # Initialize has_hit to False, and set other 3D properties
        # We'll only use these in 3D views, not in outliner
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
                    self.mouse_release(context)  # does the main job with assets

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

        bpy.context.window.cursor_set("NONE")
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.dragging = True
        self.drag = False
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def get_node_editor_cursor_position(self, context, region):
        """Get the cursor position in the node editor space."""
        # Convert mouse position to node editor space
        area = self.find_active_area(self.mouse_x, self.mouse_y, context)
        for region_check in area.regions:
            if region_check.type == "WINDOW":
                region = region_check

        # Get view2d from region
        ui_scale = context.preferences.system.ui_scale

        # Convert region coordinates to view coordinates using view2d
        x, y = region.view2d.region_to_view(float(self.mouse_x), float(self.mouse_y))

        # Scale by UI scale
        x = x / ui_scale
        y = y / ui_scale
        return (x, y)


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
