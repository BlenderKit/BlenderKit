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

import bpy
from bpy.props import StringProperty
from bpy.types import Gizmo, GizmoGroup, Operator
from mathutils import Matrix

from . import daemon_lib, global_vars, icons, ratings_utils, ui, ui_panels, utils


bk_logger = logging.getLogger(__name__)


def get_assets_for_rating():
    """Get assets from scene that could/should be rated by the user. TODO: this is only a draft"""
    assets = []
    for ob in bpy.context.scene.objects:
        if should_be_rated(ob):
            assets.append(ob)
    for m in bpy.data.materials:
        if m.get("asset_data"):
            assets.append(m)
    for b in bpy.data.brushes:
        if b.get("asset_data"):
            assets.append(b)
    return assets


asset_types = (
    ("MODEL", "Model", "set of objects"),
    ("SCENE", "Scene", "scene"),
    ("HDR", "HDR", "hdr"),
    ("MATERIAL", "Material", "any .blend Material"),
    ("TEXTURE", "Texture", "a texture, or texture set"),
    ("BRUSH", "Brush", "brush, can be any type of blender brush"),
    ("ADDON", "Addon", "addnon"),
)


def draw_ratings_menu(self, context, layout):
    pcoll = icons.icon_collections["main"]

    if not utils.user_logged_in():
        user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
        if user_preferences.login_attempt:
            ui_panels.draw_login_progress(layout)
        else:
            layout.operator_context = "EXEC_DEFAULT"
            layout.operator(
                "wm.blenderkit_login",
                text="Login to Rate and Comment assets",
                icon="URL",
            ).signup = False
        return

    col = layout.column()
    # layout.template_icon_view(bkit_ratings, property, show_labels=False, scale=6.0, scale_popup=5.0)
    row = col.row()

    if self.asset_data.get("canDownload") is not True:
        row.label(text="Asset in Full Plan. Subscribe to rate it.", icon="SOLO_ON")
        return

    profile_name = ""
    profile = global_vars.DATA.get("bkit profile")
    if profile and len(profile["user"]["firstName"]) > 0:
        profile_name = " " + profile["user"]["firstName"]

    row.label(text="Rate Quality:", icon="SOLO_ON")
    # row = col.row()
    # row.label(text='Please help the community by rating quality:')

    row = col.row()
    row.prop(self, "rating_quality_ui", expand=True, icon_only=True, emboss=False)
    if self.rating_quality > 0:
        row.label(text=f"    Thanks{profile_name}!", icon="FUND")

    col.separator()
    col.separator()

    row = col.row()
    row.label(text="Rate Complexity:", icon_value=pcoll["dumbbell"].icon_id)
    row = col.row()
    row.label(text=f"How many hours did this {self.asset_type} save you?")

    if utils.profile_is_validator():
        row = col.row()
        row.prop(self, "rating_work_hours")

    row = col.row()

    row.prop(self, "rating_work_hours_ui", expand=True, icon_only=False, emboss=True)
    if float(self.rating_work_hours_ui) > 100:
        utils.label_multiline(
            col,
            text=f"\nThat's huge! please be sure to give such rating only to godly {self.asset_type}s.\n",
            width=300,
        )
    elif float(self.rating_work_hours_ui) > 18:
        col.separator()
        utils.label_multiline(
            col,
            text=f"\nThat's a lot! please be sure to give such rating only to amazing {self.asset_type}s.\n",
            width=300,
        )

    if self.rating_work_hours > 0:
        row = col.row()
        row.label(text=f"Thanks{profile_name}, you are amazing!", icon="FUND")


class FastRateMenu(Operator, ratings_utils.RatingProperties):
    """Rating of the assets , also directly from the asset bar - without need to download assets"""

    bl_idname = "wm.blenderkit_menu_rating_upload"
    bl_label = "Ratings"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        # when rating gets recieved while the window is already open, we need to prefill.
        self.prefill_ratings()

        layout = self.layout
        layout.label(text=f"Rating of the {self.asset_type}: {self.asset_data['name']}")
        draw_ratings_menu(self, context, layout)
        layout.template_icon(icon_value=self.img.preview.icon_id, scale=12)

    def execute(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        # get asset id
        if ui_props.active_index > -1:
            sr = global_vars.DATA["search results"]
            self.asset_data = dict(sr[ui_props.active_index])
            self.asset_id = self.asset_data["id"]
            self.asset_type = self.asset_data["assetType"]
        else:
            if bpy.context.view_layer.objects.active is not None:
                ob = utils.get_active_model()
                ad = ob.get("asset_data")
                if ad:
                    self.asset_data = ad
                    self.asset_id = self.asset_data["id"]
                    self.asset_type = self.asset_data["assetType"]
                self.asset = ob
        if self.asset_id == "":
            return {"CANCELLED"}

        wm = context.window_manager

        self.img = ui.get_large_thumbnail_image(self.asset_data)
        utils.img_to_preview(self.img, copy_original=True)

        ratings_utils.ensure_rating(self.asset_id)
        self.prefill_ratings()

        if self.asset_type in ("model", "scene"):
            # spawn a wider one for validators for the enum buttons
            return wm.invoke_popup(self, width=400)
        else:
            return wm.invoke_popup(self, width=250)


class SetBookmark(bpy.types.Operator):
    """Add or remove bookmarking of the asset"""

    bl_idname = "wm.blenderkit_bookmark_asset"
    bl_label = "BlenderKit bookmark assest"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    asset_id: StringProperty(
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    # bookmark: bpy.props.BoolProperty(
    #     name="bookmark",
    #     description="Pass current state of bookmark, gets inverted",
    #     default=True)

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        r = ratings_utils.get_rating_local(self.asset_id, "bookmarks")
        if r == 1:
            bookmark_value = 0
        else:
            bookmark_value = 1
        ratings_utils.store_rating_local(
            self.asset_id, type="bookmarks", value=bookmark_value
        )
        daemon_lib.send_rating(self.asset_id, "bookmarks", bookmark_value)
        return {"FINISHED"}


def rating_menu_draw(self, context):
    layout = self.layout

    ui_props = context.window_manager.blenderkitUI
    sr = global_vars.DATA["search results"]

    asset_search_index = ui_props.active_index
    if asset_search_index > -1:
        asset_data = dict(sr["results"][asset_search_index])

    col = layout.column()
    layout.label(text="Admin rating Tools:")
    col.operator_context = "INVOKE_DEFAULT"

    op = col.operator("wm.blenderkit_menu_rating_upload", text="Add Rating")
    op.asset_id = asset_data["id"]
    op.asset_name = asset_data["name"]
    op.asset_type = asset_data["assetType"]


# Coordinates (each one is a triangle).
custom_shape_verts = (
    (0.1896940916776657, 0.2608509361743927, 0.0),
    (0.2438376545906067, 0.09421423077583313, 0.0),
    (0.2979812026023865, 0.2608509361743927, 0.0),
    (0.1896940916776657, 0.2608509361743927, 0.0),
    (0.052547797560691833, 0.2484826147556305, 0.0),
    (0.15623150765895844, 0.1578637957572937, 0.0),
    (0.15623150765895844, 0.1578637957572937, 0.0),
    (0.12561391294002533, 0.023607879877090454, 0.0),
    (0.2438376545906067, 0.09421423077583313, 0.0),
    (0.2438376545906067, 0.09421423077583313, 0.0),
    (0.36206138134002686, 0.023607879877090454, 0.0),
    (0.33144378662109375, 0.1578637957572937, 0.0),
    (0.33144378662109375, 0.1578637957572937, 0.0),
    (0.4351276159286499, 0.2484826147556305, 0.0),
    (0.2979812026023865, 0.2608509361743927, 0.0),
    (0.2979812026023865, 0.2608509361743927, 0.0),
    (0.2438376396894455, 0.3874630033969879, 0.0),
    (0.1896940916776657, 0.2608509361743927, 0.0),
    (0.1896940916776657, 0.2608509361743927, 0.0),
    (0.15623150765895844, 0.1578637957572937, 0.0),
    (0.2438376545906067, 0.09421423077583313, 0.0),
    (0.2438376545906067, 0.09421423077583313, 0.0),
    (0.33144378662109375, 0.1578637957572937, 0.0),
    (0.2979812026023865, 0.2608509361743927, 0.0),
)


class RatingStarWidget(Gizmo):
    bl_idname = "VIEW3D_GT_custom_shape_widget"
    __slots__ = (
        "custom_shape",
        "init_mouse_y",
        "init_value",
    )

    def _update_draw_matrix(self):
        R = bpy.context.region_data.view_rotation.to_matrix().to_4x4()
        loc, _, scale = self.matrix_basis.decompose()
        self.matrix_basis = Matrix.Translation(loc) @ R @ Matrix.Diagonal(scale.to_4d())

    def draw(self, context):
        self._update_draw_matrix()
        self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context, select_id):
        self._update_draw_matrix()
        self.draw_custom_shape(self.custom_shape, select_id=select_id)

    def setup(self):
        if not hasattr(self, "custom_shape"):
            self.custom_shape = self.new_custom_shape("TRIS", custom_shape_verts)

    def invoke(self, context, event):
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        pass

    def modal(self, context, event, tweak):
        return {"FINISHED"}


def should_be_rated(ob):
    ad = ob.get("asset_data")
    if ad is None:
        return False
    r = ratings_utils.get_rating_local(ad["id"], "quality")
    ratings_utils.ensure_rating(ad["id"])
    if (
        r == {}
    ):  # is None would work too, but would show rating option and then hide it when the assets are already rated
        return True


class RatingStarWidgetGroup(GizmoGroup):
    bl_idname = "OBJECT_GGT_light_test"
    bl_label = "Test Light Widget"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        if not utils.profile_is_validator():
            return False
        if bpy.context.view_layer.objects.active is not None:
            ob = utils.get_active_model()
            return should_be_rated(ob)
        return False

    def setup(self, context):
        ob = utils.get_active_model()
        gz = self.gizmos.new(RatingStarWidget.bl_idname)
        props = gz.target_set_operator("wm.blenderkit_menu_rating_upload")
        props.asset_id = ob["asset_data"]["assetBaseId"]
        gz.color = 0.5, 0.5, 0.0
        gz.alpha = 0.5

        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 0.5

        gz.scale_basis = 1
        gz.use_draw_modal = True

        self.energy_gizmo = gz

    def refresh(self, context):
        ob = utils.get_active_model()
        gz = self.energy_gizmo

        R = bpy.context.region_data.view_rotation.to_matrix().to_4x4()

        loc, _, _ = ob.matrix_world.decompose()
        _, _, scale = gz.matrix_basis.decompose()

        gz.matrix_basis = Matrix.Translation(loc) @ R @ Matrix.Diagonal(scale.to_4d())


classes = (
    FastRateMenu,
    SetBookmark,
    RatingStarWidget,
    RatingStarWidgetGroup,
    ratings_utils.RatingProperties,
    # ratings_utils.RatingPropsCollection,
)


def register_ratings():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister_ratings():
    for cls in classes:
        bpy.utils.unregister_class(cls)
