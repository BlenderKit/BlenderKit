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

# mainly update functions and callbacks for ratings properties, here to avoid circular imports.
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import daemon_lib, global_vars, icons, tasks_queue, utils
from .daemon import daemon_tasks


bk_logger = logging.getLogger(__name__)


def handle_get_rating_task(task: daemon_tasks.Task):
    """Handle incomming get_rating task by saving the results into global_vars."""
    if task.status == "created":
        return
    if task.status == "error":
        return bk_logger.warning(f"{task.task_type} task failed: {task.message}")

    asset_id = task.data["asset_id"]
    ratings = task.result["results"]
    if len(ratings) == 0:
        store_rating_local_empty(asset_id, "quality")
        store_rating_local_empty(asset_id, "working_hours")
        return

    for rating in ratings:
        store_rating_local(asset_id, rating["ratingType"], rating["score"])


def handle_get_bookmarks_task(task: daemon_tasks.Task):
    """Handle incomming get_bookmarks task by saving the results into global_vars.
    This is different from standard ratings - the results come from elastic search API
    instead of ratings API.
    """
    if task.status == "created":
        return
    if task.status == "error":
        return bk_logger.warning(f"{task.task_type} task failed: {task.message}")

    ratings = task.result["results"]
    for asset_data in ratings:
        store_rating_local(asset_data["id"], "bookmarks", 1)


def store_rating_local_empty(asset_id, rating_type):
    """Store the empty rating results to the global_vars so add-on does not search it again.
    This function could be replaced with store_rating_local(asset_id, rating_type, None)
    but it is more readable this way."""
    ratings = global_vars.DATA["asset ratings"]
    ratings[asset_id] = ratings.get(asset_id, {})
    if rating_type not in ratings[asset_id].keys():
        ratings[asset_id][rating_type] = None


def store_rating_local(asset_id, type="quality", value=0):
    """Store the rating locally in the global_vars."""
    ratings = global_vars.DATA["asset ratings"]
    ratings[asset_id] = ratings.get(asset_id, {})
    ratings[asset_id][type] = value


def get_rating_local(asset_id, rating_type):
    """Get the rating locally from global_vars."""
    r = global_vars.DATA["asset ratings"].get(asset_id, {})
    return r.get(rating_type)


def ensure_rating(asset_id):
    """Ensure rating is available. First check locally.
    If not available then download from server.
    """
    r = global_vars.DATA["asset ratings"].get(asset_id, {})
    if "quality" not in r.keys() or "working_hours " not in r.keys():
        daemon_lib.get_rating(asset_id)


def update_ratings_quality(self, context):
    if not (hasattr(self, "rating_quality")):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset["asset_data"]["id"]
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    store_rating_local(asset_id, type="quality", value=bkit_ratings.rating_quality)
    if self.rating_quality_lock is False:
        args = (asset_id, "quality", bkit_ratings.rating_quality)
        tasks_queue.add_task((daemon_lib.send_rating, args), wait=0.5, only_last=True)


def update_ratings_work_hours(self, context):
    if not (hasattr(self, "rating_work_hours")):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset["asset_data"]["id"]
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    store_rating_local(
        asset_id, type="working_hours", value=bkit_ratings.rating_work_hours
    )
    if self.rating_work_hours_lock is False:
        args = (asset_id, "working_hours", bkit_ratings.rating_work_hours)
        tasks_queue.add_task((daemon_lib.send_rating, args), wait=0.5, only_last=True)


def update_quality_ui(self, context):
    """Converts the _ui the enum into actual quality number."""
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    # we need to check for matching value not to update twice/call the popup twice.
    if user_preferences.api_key == "" and self.rating_quality != int(
        self.rating_quality_ui
    ):
        bpy.ops.wm.blenderkit_login(
            "INVOKE_DEFAULT",
            message="Please login/signup to rate assets. Clicking OK takes you to web login.",
        )
        return

    self.rating_quality = int(self.rating_quality_ui)


def update_ratings_work_hours_ui(self, context):
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    if user_preferences.api_key == "" and self.rating_work_hours != float(
        self.rating_work_hours_ui
    ):
        bpy.ops.wm.blenderkit_login(
            "INVOKE_DEFAULT",
            message="Please login/signup to rate assets. Clicking OK takes you to web login.",
        )
        return
    self.rating_work_hours = float(self.rating_work_hours_ui)


def stars_enum_callback(self, context):
    """regenerates the enum property used to display rating stars, so that there are filled/empty stars correctly."""
    items = []
    for a in range(0, 11):
        if a == 0:
            icon = "REMOVE"

        elif self.rating_quality < a:
            icon = "SOLO_OFF"
        else:
            icon = "SOLO_ON"
        # has to have something before the number in the value, otherwise fails on registration.

        items.append((f"{a}", f"  ", "", icon, a))
    return items


def wh_enum_callback(self, context):
    """Regenerates working hours enum."""
    if self.asset_type in ("model", "scene"):
        possible_wh_values = [
            0,
            0.5,
            1,
            2,
            3,
            4,
            5,
            6,
            8,
            10,
            15,
            20,
            30,
            50,
            100,
            150,
            200,
            250,
        ]
    elif self.asset_type == "hdr":
        possible_wh_values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    else:
        # for material, brush assets
        possible_wh_values = [0, 0.2, 0.5, 1, 2, 3, 4, 5]

    items = []
    items.append(("0", " ", "", "REMOVE", 0))
    pcoll = icons.icon_collections["main"]

    for w in possible_wh_values:
        if w > 0:
            if w < 1:
                icon_name = f"BK{int(w*10)/10}"
            else:
                icon_name = f"BK{int(w)}"
            icon = pcoll[icon_name]
            # index of the item(last value) is multiplied by 10 to get always integer values that aren't zero
            items.append((f"{w}", f"  ", "", icon.icon_id, int(w * 10)))

    return items


class RatingProperties(PropertyGroup):
    message: StringProperty(
        name="message",
        description="message",
        default="Rating asset",
        options={"SKIP_SAVE"},
    )

    asset_id: StringProperty(
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    asset_name: StringProperty(
        name="Asset Name",
        description="Name of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    asset_type: StringProperty(
        name="Asset type", description="asset type", default="", options={"SKIP_SAVE"}
    )

    ### QUALITY RATING
    rating_quality_lock: BoolProperty(
        name="Quality Lock",
        description="Quality is locked -> rating is not sent online",
        default=False,
        options={"SKIP_SAVE"},
    )

    rating_quality: IntProperty(
        name="Quality",
        description="quality of the material",
        default=0,
        min=-1,
        max=10,
        update=update_ratings_quality,
        options={"SKIP_SAVE"},
    )

    # the following enum is only to ease interaction - enums support 'drag over' and enable to draw the stars easily.
    rating_quality_ui: EnumProperty(
        name="rating_quality_ui",
        items=stars_enum_callback,
        description="Rating stars 0 - 10",
        default=0,
        update=update_quality_ui,
        options={"SKIP_SAVE"},
    )

    ### WORK HOURS RATING
    rating_work_hours_lock: BoolProperty(
        name="Work Hours Lock",
        description="Work hours are locked -> rating is not sent online",
        default=False,
        options={"SKIP_SAVE"},
    )
    rating_work_hours: FloatProperty(
        name="Work Hours",
        description="How many hours did this work take?",
        default=0.00,
        min=0.0,
        max=300,
        update=update_ratings_work_hours,
        options={"SKIP_SAVE"},
    )

    rating_work_hours_ui: EnumProperty(
        name="Work Hours",
        description="How many hours did this work take?",
        items=wh_enum_callback,
        default=0,
        update=update_ratings_work_hours_ui,
        options={"SKIP_SAVE"},
    )

    def prefill_ratings(self):
        """Pre-fill the quality and work hours ratings if available.
        Locks the ratings locks so that the update function is not called and ratings are not sent online.
        """
        if not utils.user_logged_in():
            return
        rating_quality = get_rating_local(self.asset_id, "quality")
        rating_work_hours = get_rating_local(self.asset_id, "working_hours")
        if rating_quality is None and rating_work_hours is None:
            return
        if self.rating_quality != 0:
            return  # return if the rating was already filled
        if self.rating_work_hours != 0:
            return

        if rating_quality is not None:
            self.rating_quality_lock = True
            self.rating_quality = int(rating_quality)
            self.rating_quality_lock = False

        if rating_work_hours is not None:
            if rating_work_hours >= 1:
                wh = int(rating_work_hours)
            else:
                wh = round(rating_work_hours, 1)
            whs = str(wh)
            self.rating_work_hours_lock = True
            self.rating_work_hours_ui = whs
            self.rating_work_hours_lock = False

        bpy.context.area.tag_redraw()


# class RatingPropsCollection(PropertyGroup):
#   ratings = CollectionProperty(type = RatingProperties)
