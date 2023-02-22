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
from bpy.props import EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup

from . import daemon_lib, global_vars, utils
from .daemon import tasks


bk_logger = logging.getLogger(__name__)


def handle_get_rating_task(task: tasks.Task):
    """Handle incomming get_rating task by saving the results into global_vars."""
    if task.status == 'created':
        return
    if task.status == 'error':
        return bk_logger.warning(f'{task.task_type} task failed: {task.message}')

    asset_id = task.data['asset_id']
    ratings = task.result['results']
    if len(ratings) == 0:
        return store_rating_local_empty(asset_id)
        
    for rating in ratings:
        store_rating_local(asset_id, rating['ratingType'], rating['score'])


def store_rating_local_empty(asset_id):
    """Store the empty rating results to the global_vars so add-on does not search it again."""
    ratings = global_vars.DATA['asset ratings']
    ratings[asset_id] = ratings.get(asset_id, {})


def store_rating_local(asset_id, type='quality', value=0):
    """Store the rating locally in the global_vars."""
    ratings = global_vars.DATA['asset ratings']
    ratings[asset_id] = ratings.get(asset_id, {})
    ratings[asset_id][type] = value


def get_rating_local(asset_id):
    """Get the rating locally from global_vars."""
    return global_vars.DATA['asset ratings'].get(asset_id)


def ensure_rating(asset_id):
    """Ensure rating is available. First check locally, if not available then download from server."""
    rating = get_rating_local(asset_id)
    if rating is None:
        daemon_lib.get_rating(asset_id)


def update_ratings_quality(self, context):
    if not (hasattr(self, 'rating_quality')):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset['asset_data']['id']
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    if bkit_ratings.rating_quality <= 0.1:
        return

    store_rating_local(asset_id, type='quality', value=bkit_ratings.rating_quality)
    daemon_lib.send_rating(asset_id, 'quality', bkit_ratings.rating_quality)


def update_ratings_work_hours(self, context):
    if not (hasattr(self, 'rating_work_hours')):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset['asset_data']['id']
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    if bkit_ratings.rating_work_hours <= 0.45:
        return

    store_rating_local(asset_id, type='working_hours', value=bkit_ratings.rating_work_hours)
    daemon_lib.send_rating(asset_id, 'working_hours', bkit_ratings.rating_work_hours)


def update_quality_ui(self, context):
    '''Converts the _ui the enum into actual quality number.'''
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    #we need to check for matching value not to update twice/call the popup twice.
    if user_preferences.api_key == '' and self.rating_quality != int(self.rating_quality_ui):
        # return
        bpy.ops.wm.blenderkit_login('INVOKE_DEFAULT',
                                    message='Please login/signup to rate assets. Clicking OK takes you to web login.')
    else:
      self.rating_quality = int(self.rating_quality_ui)


def update_ratings_work_hours_ui(self, context):
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    if user_preferences.api_key == ''and self.rating_work_hours != float(self.rating_work_hours_ui):
        # ui_panels.draw_not_logged_in(self, message='Please login/signup to rate assets.')
        # bpy.ops.wm.call_menu(name='OBJECT_MT_blenderkit_login_menu')
        # return
        bpy.ops.wm.blenderkit_login('INVOKE_DEFAULT',
                                    message='Please login/signup to rate assets. Clicking OK takes you to web login.')
        # self.rating_work_hours_ui = '0'
    self.rating_work_hours = float(self.rating_work_hours_ui)


def update_ratings_work_hours_ui_1_5(self, context):
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    if user_preferences.api_key == '':
        # ui_panels.draw_not_logged_in(self, message='Please login/signup to rate assets.')
        # bpy.ops.wm.call_menu(name='OBJECT_MT_blenderkit_login_menu')
        # return
        bpy.ops.wm.blenderkit_login('INVOKE_DEFAULT',
                                    message='Please login/signup to rate assets. Clicking OK takes you to web login.')
        # self.rating_work_hours_ui_1_5 = '0'
    self.rating_work_hours = float(self.rating_work_hours_ui_1_5)


def update_ratings_work_hours_ui_1_10(self, context):
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    if user_preferences.api_key == '':
        # ui_panels.draw_not_logged_in(self, message='Please login/signup to rate assets.')
        # bpy.ops.wm.call_menu(name='OBJECT_MT_blenderkit_login_menu')
        # return
        bpy.ops.wm.blenderkit_login('INVOKE_DEFAULT',
                                    message='Please login/signup to rate assets. Clicking OK takes you to web login.')
        # self.rating_work_hours_ui_1_5 = '0'
    self.rating_work_hours = float(self.rating_work_hours_ui_1_10)


def stars_enum_callback(self, context):
    '''regenerates the enum property used to display rating stars, so that there are filled/empty stars correctly.'''
    items = []
    for a in range(0, 10):
        if self.rating_quality < a + 1:
            icon = 'SOLO_OFF'
        else:
            icon = 'SOLO_ON'
        # has to have something before the number in the value, otherwise fails on registration.
        items.append((f'{a + 1}', f'{a + 1}', '', icon, a + 1))
    return items


class RatingProperties(PropertyGroup):
    message: StringProperty(
        name="message",
        description="message",
        default="Rating asset",
        options={'SKIP_SAVE'})

    asset_id: StringProperty(
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={'SKIP_SAVE'})

    asset_name: StringProperty(
        name="Asset Name",
        description="Name of the asset (hidden)",
        default="",
        options={'SKIP_SAVE'})

    asset_type: StringProperty(
        name="Asset type",
        description="asset type",
        default="",
        options={'SKIP_SAVE'})

    rating_quality: IntProperty(name="Quality",
                                description="quality of the material",
                                default=0,
                                min=-1, max=10,
                                update=update_ratings_quality,
                                options={'SKIP_SAVE'})

    # the following enum is only to ease interaction - enums support 'drag over' and enable to draw the stars easily.
    rating_quality_ui: EnumProperty(name='rating_quality_ui',
                                    items=stars_enum_callback,
                                    description='Rating stars 0 - 10',
                                    default=0,
                                    update=update_quality_ui,
                                    options={'SKIP_SAVE'})

    rating_work_hours: FloatProperty(name="Work Hours",
                                     description="How many hours did this work take?",
                                     default=0.00,
                                     min=0.0, max=300,
                                     update=update_ratings_work_hours,
                                     options={'SKIP_SAVE'}
                                     )

    high_rating_warning = "This is a high rating, please be sure to give such rating only to amazing assets"

    possible_wh_values = [0,.5,1,2,3,4,5,6,8,10,15,20,30,50,100,150,200,250]
    items_models = [('0', '0', ''),
                    ('.5', '0.5', ''),
                    ('1', '1', ''),
                    ('2', '2', ''),
                    ('3', '3', ''),
                    ('4', '4', ''),
                    ('5', '5', ''),
                    ('6', '6', ''),
                    ('8', '8', ''),
                    ('10', '10', ''),
                    ('15', '15', ''),
                    ('20', '20', ''),
                    ('30', '30', high_rating_warning),
                    ('50', '50', high_rating_warning),
                    ('100', '100', high_rating_warning),
                    ('150', '150', high_rating_warning),
                    ('200', '200', high_rating_warning),
                    ('250', '250', high_rating_warning),
                    ]
    rating_work_hours_ui: EnumProperty(name="Work Hours",
                                       description="How many hours did this work take?",
                                       items=items_models,
                                       default='0', update=update_ratings_work_hours_ui,
                                       options={'SKIP_SAVE'}
                                       )
    possible_wh_values_1_5 = [0,.2, .5,1,2,3,4,5]

    items_1_5 = [('0', '0', ''),
                 ('.2', '0.2', ''),
                 ('.5', '0.5', ''),
                 ('1', '1', ''),
                 ('2', '2', ''),
                 ('3', '3', ''),
                 ('4', '4', ''),
                 ('5', '5', '')
                 ]
    rating_work_hours_ui_1_5: EnumProperty(name="Work Hours",
                                           description="How many hours did this work take?",
                                           items=items_1_5,
                                           default='0',
                                           update=update_ratings_work_hours_ui_1_5,
                                           options={'SKIP_SAVE'}
                                           )
    possible_wh_values_1_10 = [0,1,2,3,4,5,6,7,8,9,10]

    items_1_10= [('0', '0', ''),
       ('1', '1', ''),
       ('2', '2', ''),
       ('3', '3', ''),
       ('4', '4', ''),
       ('5', '5', ''),
       ('6', '6', ''),
       ('7', '7', ''),
       ('8', '8', ''),
       ('9', '9', ''),
       ('10', '10', '')
       ]
    rating_work_hours_ui_1_10: EnumProperty(name="Work Hours",
                                            description="How many hours did this work take?",
                                            items= items_1_10,
                                            default='0',
                                            update=update_ratings_work_hours_ui_1_10,
                                            options={'SKIP_SAVE'}
                                            )

    def prefill_ratings(self):
        # pre-fill ratings
        if not utils.user_logged_in():
          return
        ratings = get_rating_local(self.asset_id)
        if ratings in (None, {}):
          return
        if not self.rating_quality ==0:
          #return if the rating was already filled
          return
        if ratings and ratings.get('quality'):
            self.rating_quality = int(ratings['quality'])
        if ratings and ratings.get('working_hours'):
            wh = int(ratings['working_hours'])
            whs = str(wh)
            if wh in self.possible_wh_values:
                self.rating_work_hours_ui = whs
            if wh < 6 and wh in self.possible_wh_values_1_5:
                self.rating_work_hours_ui_1_5 = whs
            if wh < 11 and wh in self.possible_wh_values_1_10:
                self.rating_work_hours_ui_1_10 = whs
        bpy.context.area.tag_redraw()
# class RatingPropsCollection(PropertyGroup):
#   ratings = CollectionProperty(type = RatingProperties)