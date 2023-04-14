import logging
import math
import time

import bpy
from bpy.props import BoolProperty, StringProperty

from . import comments_utils, global_vars, paths, ratings_utils, search, ui, utils
from .bl_ui_widgets.bl_ui_button import *
from .bl_ui_widgets.bl_ui_drag_panel import *
from .bl_ui_widgets.bl_ui_draw_op import *
from .bl_ui_widgets.bl_ui_image import *
from .bl_ui_widgets.bl_ui_label import *


# from .bl_ui_widgets.bl_ui_checkbox import *
# from .bl_ui_widgets.bl_ui_slider import *
# from .bl_ui_widgets.bl_ui_up_down import *
# from .bl_ui_widgets.bl_ui_textbox import *


bk_logger = logging.getLogger(__name__)

active_area_pointer = 0

def get_area_height(self):
    if type(self.context) != dict:
        if self.context is None:
            self.context = bpy.context
        self.context = self.context.copy()
    if self.context.get('area') is not None:
        return self.context['area'].height
    # else:
    #     maxw, maxa, region = utils.get_largest_area()
    #     if maxa:
    #         self.context['area'] = maxa
    #         self.context['window'] = maxw
    #         self.context['region'] = region
    #         self.update(self.x,self.y)
    #
    #         return self.context['area'].height
    return 100


BL_UI_Widget.get_area_height = get_area_height


def modal_inside(self, context, event):
    try:
        ui_props = bpy.context.window_manager.blenderkitUI
        user_preferences = bpy.context.preferences.addons['blenderkit'].preferences

        if ui_props.turn_off:
            ui_props.turn_off = False
            self.finish()

        if self._finished:
            return {'FINISHED'}

        if not context.area:
            self.finish()
            w,a,r = utils.get_largest_area(area_type='VIEW_3D')
            if a is not None:
                bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
            return {'FINISHED'}

        # sr = bpy.context.window_manager.get('search results')
        sr = global_vars.DATA.get('search results')
        if sr is not None:
            # this check runs more search, usefull especially for first search. Could be moved to a better place where the check
            # doesn't run that often.
            if len(sr) - ui_props.scroll_offset < (ui_props.wcount * user_preferences.max_assetbar_rows) + 15:
                self.search_more()

        time_diff = time.time() - self.update_timer_start
        if time_diff > self.update_timer_limit:
            self.update_timer_start = time.time()
            # self.update_buttons()

            # progress bar
            # change - let's try to optimize and redraw only when needed
            change = False
            ui_scale = bpy.context.preferences.view.ui_scale
            for asset_button in self.asset_buttons:
                if not asset_button.visible:
                    continue
                if sr is not None and len(sr) > asset_button.asset_index:
                    asset_data = sr[asset_button.asset_index]
                    self.update_progress_bar(asset_button, asset_data)
            if change:
                context.region.tag_redraw()

        #ANY EVENT ACTIVATED = DON'T LET EVENTS THROUGH
        if self.handle_widget_events(event):
            return {'RUNNING_MODAL'}

        if event.type in {"ESC"}:
            self.finish()

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        #TRACKPAD SCROLL
        if event.type == 'TRACKPADPAN' and self.panel.is_in_rect(self.mouse_x, self.mouse_y):
            # accumulate trackpad inputs
            self.trackpad_x_accum -= event.mouse_x - event.mouse_prev_x
            self.trackpad_y_accum += event.mouse_y - event.mouse_prev_y

            step=0
            multiplier = 30
            if abs(self.trackpad_x_accum)>abs(self.trackpad_y_accum) or self.hcount <2:
                step = math.floor(self.trackpad_x_accum/multiplier)
                self.trackpad_x_accum -= step*multiplier
                # reset the other axis not to accidentally scroll it
                if step!=0:
                    self.trackpad_y_accum = 0
            if abs(self.trackpad_y_accum)>0 and self.hcount >1:
                step = self.wcount * math.floor(self.trackpad_x_accum/multiplier)
                self.trackpad_y_accum -= step * multiplier
                # reset the other axis not to accidentally scroll it
                if step!=0:
                    self.trackpad_x_accum = 0
            if step!=0:
                self.scroll_offset += step
                self.scroll_update()
            return {'RUNNING_MODAL'}

        #MOUSEWHEEL SCROLL
        if event.type == 'WHEELUPMOUSE' and self.panel.is_in_rect(self.mouse_x, self.mouse_y):
            if self.hcount>1:
                self.scroll_offset -= self.wcount
            else:
                self.scroll_offset -= 2
            self.scroll_update()
            return {'RUNNING_MODAL'}

        elif event.type == 'WHEELDOWNMOUSE' and self.panel.is_in_rect(self.mouse_x, self.mouse_y):
            if self.hcount>1:
                self.scroll_offset += self.wcount
            else:
                self.scroll_offset += 2

            self.scroll_update()
            return {'RUNNING_MODAL'}
        if self.check_ui_resized(context) or self.check_new_search_results(context):
            self.update_ui_size(context)
            self.update_layout(context, event)
            self.scroll_update(always=True) # one extra update for scroll for correct redraw, updates all buttons


        # this was here to check if sculpt stroke is running, but obviously that didn't help,
        #  since the RELEASE event is cought by operator and thus there is no way to detect a stroke has ended...
        if bpy.context.mode in ('SCULPT', 'PAINT_TEXTURE'):
            if event.type == 'MOUSEMOVE':  # ASSUME THAT SCULPT OPERATOR ACTUALLY STEALS THESE EVENTS,
                # SO WHEN THERE ARE SOME WE CAN APPEND BRUSH...
                bpy.context.window_manager['appendable'] = True
            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    bpy.context.window_manager['appendable'] = False
        return {"PASS_THROUGH"}
    except Exception as e:
        bk_logger.warning(f'{e}')
        self.finish()
        return {'FINISHED'}


def asset_bar_modal(self, context, event):
    return modal_inside(self, context, event)


def asset_bar_invoke(self, context, event):
    if not self.on_invoke(context, event):
        return {"CANCELLED"}
    if not context.window:
        return {"CANCELLED"}
    if not context.area:
        return {"CANCELLED"}

    args = (self, context)

    self.register_handlers(args, context)

    self.update_timer_limit = .5
    self.update_timer_start = time.time()
    self._timer = context.window_manager.event_timer_add(0.5, window=context.window)

    context.window_manager.modal_handler_add(self)
    global active_area_pointer
    self.active_window_pointer = context.window.as_pointer()
    self.active_area_pointer = context.area.as_pointer()
    active_area_pointer = self.active_area_pointer
    self.active_region_pointer = context.region.as_pointer()

    return {"RUNNING_MODAL"}




def set_mouse_down_right(self, mouse_down_right_func):
    self.mouse_down_right_func = mouse_down_right_func


def mouse_down_right(self, x, y):
    if self.is_in_rect(x, y):
        self.__state = 1
        try:
            self.mouse_down_right_func(self)
        except Exception as e:
            bk_logger.warning(f'{e}')

        return True

    return False


BL_UI_Button.mouse_down_right = mouse_down_right
BL_UI_Button.set_mouse_down_right = set_mouse_down_right

asset_bar_operator = None


# BL_UI_Button.handle_event = handle_event

def get_tooltip_data(asset_data):
    gimg = None
    tooltip_data = asset_data.get('tooltip_data')
    if tooltip_data is None:
        author_text = ''

        if global_vars.DATA.get('bkit authors') is not None:
            a = global_vars.DATA['bkit authors'].get(asset_data['author']['id'])
            if a is not None and a != '':
                # if a.get('gravatarImg') is not None:
                #     gimg = utils.get_hidden_image(a['gravatarImg'], a['gravatarHash']).name

                if len(a['firstName']) > 0 or len(a['lastName']) > 0:
                    author_text = f"by {a['firstName']} {a['lastName']}"

        aname = asset_data['displayName']
        aname = aname[0].upper() + aname[1:]
        if len(aname) > 36:
            aname = f"{aname[:33]}..."

        rc = asset_data.get('ratingsCount')
        show_rating_threshold = 0
        rcount = 0
        quality = '-'
        if rc:
            rcount = min(rc.get('quality', 0), rc.get('workingHours', 0))
        if rcount > show_rating_threshold:
            quality = str(round(asset_data['ratingsAverage'].get('quality')))
        tooltip_data = {
            'aname': aname,
            'author_text': author_text,
            'quality': quality,
            # 'gimg': gimg
        }
        asset_data['tooltip_data'] = tooltip_data


def set_thumb_check(element, asset, thumb_type = 'thumbnail_small'):
    '''sets image in case it is loaded in search results
     - if image doesn't exist, it will be set to 'thumbnail_notready.jpg'

    '''
    directory = paths.get_temp_dir('%s_search' % asset['assetType'])
    if asset[thumb_type] == '': # for thumbnails not present at all
        tpath = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
    else:
        tpath = os.path.join(directory, asset[thumb_type])

    if element.get_image_path() == tpath:
        # no need to update
        return
    # img_name_datablock = f'.{asset["thumbnail_small"]}'

    # if not os.path.exists(tpath):
    #     del global_vars.DATA['images available'][tpath]

    if not global_vars.DATA['images available'].get(tpath):
        tpath = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
        if element.get_image_path() == tpath:
            return
    element.set_image(tpath)
    # if asset['assetType'] == 'hdr':
    #   # to display hdr thumbnails correctly, we use non-color, otherwise looks shifted
    #   image_utils.set_colorspace(img, 'Non-Color')
    # else:
    #   image_utils.set_colorspace(img, 'sRGB')
    # asset['thumb_small_loaded'] = True


class BlenderKitAssetBarOperator(BL_UI_OT_draw_operator):
    bl_idname = "view3d.blenderkit_asset_bar_widget"
    bl_label = "BlenderKit asset bar refresh"
    bl_description = "BlenderKit asset bar refresh"
    bl_options = {'REGISTER'}

    do_search: BoolProperty(name="Run Search", description='', default=True, options={'SKIP_SAVE'})
    keep_running: BoolProperty(name="Keep Running", description='', default=True, options={'SKIP_SAVE'})
    free_only: BoolProperty(name="Free first", description='', default=False, options={'SKIP_SAVE'})

    category: StringProperty(
        name="Category",
        description="search only subtree of this category",
        default="", options={'SKIP_SAVE'})

    tooltip: bpy.props.StringProperty(default='Runs search and displays the asset bar at the same time')

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def new_text(self, text, x, y, width=100, height=15, text_size=None, halign='LEFT'):
        label = BL_UI_Label(x, y, width, height)
        label.text = text
        if text_size is None:
            text_size = 14
        label.text_size = text_size
        label.text_color = self.text_color
        label._halign = halign
        return label

    def init_tooltip(self):
        self.tooltip_widgets = []
        self.tooltip_height = self.tooltip_size
        self.tooltip_width = self.tooltip_size
        ui_props = bpy.context.window_manager.blenderkitUI
        if ui_props.asset_type == 'HDR':
            self.tooltip_width = self.tooltip_size * 2
        # total_size = tooltip# + 2 * self.margin
        self.tooltip_panel = BL_UI_Drag_Panel(0, 0, self.tooltip_width, self.tooltip_height)
        self.tooltip_panel.bg_color = (0.0, 0.0, 0.0, 0.5)
        self.tooltip_panel.visible = False

        tooltip_image = BL_UI_Image(0, 0, 1, 1)
        img_path = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
        tooltip_image.set_image(img_path)
        tooltip_image.set_image_size((self.tooltip_width, self.tooltip_height))
        tooltip_image.set_image_position((0, 0))
        self.tooltip_image = tooltip_image
        self.tooltip_widgets.append(tooltip_image)

        bottom_panel_fraction = 0.15
        labels_start = self.tooltip_height * (1 - bottom_panel_fraction)

        dark_panel = BL_UI_Widget(0, labels_start, self.tooltip_width, self.tooltip_height * bottom_panel_fraction)
        dark_panel.bg_color = (0.0, 0.0, 0.0, 0.7)
        self.tooltip_dark_panel = dark_panel
        self.tooltip_widgets.append(dark_panel)

        name_label = self.new_text('', self.margin, labels_start + self.margin,
                                   height=self.asset_name_text_size,
                                   text_size=self.asset_name_text_size)
        self.asset_name = name_label
        self.tooltip_widgets.append(name_label)

        self.gravatar_size = int(self.tooltip_height * bottom_panel_fraction - self.margin)

        authors_name = self.new_text('author',
                                     self.tooltip_width - self.gravatar_size - self.margin,
                                     self.tooltip_height - self.author_text_size - self.margin,
                                     labels_start,
                                     height = self.author_text_size,
                                     text_size=self.author_text_size, halign='RIGHT')
        self.authors_name = authors_name
        self.tooltip_widgets.append(authors_name)

        gravatar_image = BL_UI_Image(self.tooltip_width - self.gravatar_size, self.tooltip_height - self.gravatar_size,
                                     1, 1)
        img_path = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
        gravatar_image.set_image(img_path)
        gravatar_image.set_image_size((self.gravatar_size - 1 * self.margin, self.gravatar_size - 1 * self.margin))
        gravatar_image.set_image_position((0, 0))
        self.gravatar_image = gravatar_image
        self.tooltip_widgets.append(gravatar_image)

        quality_star = BL_UI_Image(self.margin, self.tooltip_height - self.margin - self.asset_name_text_size,

                                   1, 1)
        img_path = paths.get_addon_thumbnail_path('star_grey.png')
        quality_star.set_image(img_path)
        quality_star.set_image_size((self.asset_name_text_size, self.asset_name_text_size))
        quality_star.set_image_position((0, 0))
        self.quality_star = quality_star
        self.tooltip_widgets.append(quality_star)
        quality_label = self.new_text('', 2 * self.margin + self.asset_name_text_size,
                              self.tooltip_height - int(self.asset_name_text_size + self.margin),
                              height = self.asset_name_text_size,
                              text_size=self.asset_name_text_size)
        self.tooltip_widgets.append(quality_label)
        self.quality_label = quality_label

        user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
        offset = 0
        if user_preferences.asset_popup_counter < 5:
            # this is shown only to users who don't know yet about the popup card.
            label = self.new_text('Right click for menu.', self.margin,
                                  self.tooltip_height + self.margin,
                                  height = self.author_text_size,
                                  text_size=self.author_text_size)
            self.tooltip_widgets.append(label)
            offset += 1
        # version warning
        version_warning = self.new_text('', self.margin,
                                        self.tooltip_height + self.margin + int(self.author_text_size * offset),
                                        height = self.author_text_size,
                                        text_size=self.author_text_size)
        version_warning.text_color = self.warning_color
        self.tooltip_widgets.append(version_warning)
        self.version_warning = version_warning

    def hide_tooltip(self):
        self.tooltip_panel.visible = False
        for w in self.tooltip_widgets:
            w.visible = False

    def show_tooltip(self):
        self.tooltip_panel.visible = True
        self.tooltip_panel.active = False
        for w in self.tooltip_widgets:
            w.visible = True

    def show_notifications(self, widget):
        bpy.ops.wm.show_notifications()
        if comments_utils.check_notifications_read():
            widget.visible = False

    def check_new_search_results(self, context):
        '''checks if results were replaced.
        this can happen from search, but also by switching results.
        We should rather trigger that update from search. maybe let's add a uuid to the results?'''
        sr = global_vars.DATA.get('search results')

        if not hasattr(self, 'search_results_count'):
            if not sr or len(sr)==0:
                self.search_results_count = 0
                self.last_asset_type =''
                return True
            self.search_results_count = len(sr)
            self.last_asset_type = sr[0]['assetType']
        if sr is not None and len(sr) != self.search_results_count:
            self.search_results_count = len(sr)
            return True
        return False

    def get_region_size(self, context):
        # just check the size of region..

        region = context.region
        area = context.area
        ui_width = 0
        tools_width = 0
        for r in area.regions:
            if r.type == 'UI':
                ui_width = r.width
            if r.type == 'TOOLS':
                tools_width = r.width
        total_width = region.width - tools_width - ui_width
        return total_width, region.height

    def check_ui_resized(self, context):
        # TODO this should only check if region was resized, not really care about the UI elements size.
        region_width, region_height = self.get_region_size(context)

        if not hasattr(self, 'total_width'):
            self.total_width = region_width
            self.region_height = region_height

        if region_height != self.region_height or region_width != self.total_width:
            self.region_height = region_height
            self.total_width = region_width
            return True
        return False

    def update_ui_size(self, context):


        region = context.region
        area = context.area

        ui_props = bpy.context.window_manager.blenderkitUI
        user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
        ui_scale = bpy.context.preferences.view.ui_scale

        # self.margin = int(ui_props.bl_rna.properties['margin'].default * ui_scale)
        self.margin = int(9 * ui_scale)
        self.button_margin = int(0 * ui_scale)
        self.asset_name_text_size = int(20 * ui_scale)
        self.author_text_size = int(self.asset_name_text_size * .8)
        self.assetbar_margin = int(2 * ui_scale)
        self.tooltip_size = int(512 * ui_scale)

        if ui_props.asset_type == 'HDR':
            self.tooltip_width = self.tooltip_size * 2
        else:
            self.tooltip_width = self.tooltip_size

        self.thumb_size = int(user_preferences.thumb_size * ui_scale)
        self.button_size = 2 * self.button_margin + self.thumb_size
        self.other_button_size = int(30 * ui_scale)
        self.icon_size = int(24 * ui_scale)
        self.validation_icon_margin = int(3 * ui_scale)
        reg_multiplier = 1
        if not bpy.context.preferences.system.use_region_overlap:
            reg_multiplier = 0

        ui_width = 0
        tools_width = 0
        reg_multiplier = 1
        if not bpy.context.preferences.system.use_region_overlap:
            reg_multiplier = 0
        for r in area.regions:
            if r.type == 'UI':
                ui_width = r.width * reg_multiplier
            if r.type == 'TOOLS':
                tools_width = r.width * reg_multiplier
        self.bar_x = int(tools_width + self.margin + ui_props.bar_x_offset * ui_scale)
        self.bar_end = int(ui_width + 180 * ui_scale + self.other_button_size)
        self.bar_width = int(region.width - self.bar_x - self.bar_end)

        self.wcount = math.floor((self.bar_width) / (self.button_size))

        self.max_hcount = math.floor(max(region.width , context.window.width) / self.button_size)
        self.max_wcount = user_preferences.max_assetbar_rows

        search_results = global_vars.DATA.get('search results')
        # we need to init all possible thumb previews in advance/
        # self.hcount = user_preferences.max_assetbar_rows
        if search_results is not None and self.wcount > 0:
            self.hcount = min(user_preferences.max_assetbar_rows, math.ceil(len(search_results) / self.wcount))
            self.hcount = max(self.hcount, 1)
        else:
            self.hcount = 1

        self.bar_height = (self.button_size) * self.hcount + 2 * self.assetbar_margin
        # self.bar_y = region.height - ui_props.bar_y_offset * ui_scale
        self.bar_y = int(ui_props.bar_y_offset * ui_scale)
        if ui_props.down_up == 'UPLOAD':
            self.reports_y = region.height - self.bar_y - 600
            ui_props.reports_y = region.height - self.bar_y - 600
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x

        else:  # ui.bar_y - ui.bar_height - 100

            self.reports_y = region.height - self.bar_y - self.bar_height - 50
            ui_props.reports_y = region.height - self.bar_y - self.bar_height - 50
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x

    def update_layout(self, context, event):
        # restarting asset_bar completely since the widgets are too hard to get working with updates.

        self.scroll_update(always = True)
        self.position_and_hide_buttons()

        self.button_close.set_location(self.bar_width - self.other_button_size, -self.other_button_size)
        # if hasattr(self, 'button_notifications'):
        #     self.button_notifications.set_location(self.bar_width - self.other_button_size * 2, -self.other_button_size)
        self.button_scroll_up.set_location(self.bar_width, 0)
        self.panel.width = self.bar_width
        self.panel.height = self.bar_height

        self.panel.set_location(self.bar_x, self.panel.y)

        # update Tooltip size
        if self.tooltip_dark_panel.width != self.tooltip_width:
            self.tooltip_dark_panel.width = self.tooltip_width
            self.tooltip_panel.width = self.tooltip_width
            self.tooltip_image.width = self.tooltip_width
            self.tooltip_image.set_image_size((self.tooltip_width, self.tooltip_height))
            self.gravatar_image.set_location(self.tooltip_width - self.gravatar_size,
                                             self.tooltip_height - self.gravatar_size)
            self.authors_name.set_location(self.tooltip_width - self.gravatar_size - self.margin,
                                           self.tooltip_height - self.author_text_size - self.margin)

        # to hide arrows accordingly

    def asset_button_init(self, asset_x, asset_y, button_idx):
        ui_scale = bpy.context.preferences.view.ui_scale

        button_bg_color = (0.2, 0.2, 0.2, .1)
        button_hover_color = (0.8, 0.8, 0.8, .2)
        fully_transparent_color = (0.2,0.2,0.2,0.0)
        new_button = BL_UI_Button(asset_x, asset_y, self.button_size, self.button_size)

        # asset_data = sr[asset_idx]
        # iname = utils.previmg_name(asset_idx)
        # img = bpy.data.images.get(iname)

        new_button.bg_color = button_bg_color
        new_button.hover_bg_color = button_hover_color
        new_button.text = ""  # asset_data['name']
        # if img:
        #     new_button.set_image(img.filepath)

        new_button.set_image_size((self.thumb_size, self.thumb_size))
        new_button.set_image_position((self.button_margin, self.button_margin))
        new_button.button_index = button_idx
        new_button.search_index = button_idx
        new_button.set_mouse_down(self.drag_drop_asset)
        new_button.set_mouse_down_right(self.asset_menu)
        new_button.set_mouse_enter(self.enter_button)
        new_button.set_mouse_exit(self.exit_button)
        new_button.text_input = self.handle_key_input
        # add validation icon to button

        validation_icon = BL_UI_Image(
            asset_x + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin,
            asset_y + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin, 0, 0)

        validation_icon.set_image_size((self.icon_size, self.icon_size))
        validation_icon.set_image_position((0, 0))
        self.validation_icons.append(validation_icon)
        new_button.validation_icon = validation_icon

        bookmark_button =  BL_UI_Button(
            asset_x + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin,
            asset_y  + self.button_margin + self.validation_icon_margin, self.icon_size, self.icon_size)
        bookmark_button.set_image_size((self.icon_size, self.icon_size))
        bookmark_button.set_image_position((0, 0))
        bookmark_button.button_index = button_idx
        bookmark_button.search_index = button_idx
        bookmark_button.text=""
        bookmark_button.set_mouse_down(self.bookmark_asset)

        img_fp = paths.get_addon_thumbnail_path("bookmark_empty.png")
        bookmark_button.set_image(img_fp)
        bookmark_button.bg_color = fully_transparent_color
        bookmark_button.hover_bg_color = button_bg_color
        bookmark_button.select_bg_color = fully_transparent_color
        bookmark_button.visible = False
        new_button.bookmark_button = bookmark_button
        self.bookmark_buttons.append(bookmark_button
                                     )
        progress_bar = BL_UI_Widget(asset_x, asset_y + self.button_size - 3, self.button_size, 3)
        progress_bar.bg_color = (0.0, 1.0, 0.0, 0.3)
        new_button.progress_bar = progress_bar
        self.progress_bars.append(progress_bar)

        if utils.profile_is_validator():
            red_alert = BL_UI_Widget(asset_x-self.validation_icon_margin, asset_y-self.validation_icon_margin,
                                     self.button_size+2*self.validation_icon_margin, self.button_size+2*self.validation_icon_margin)
            red_alert.bg_color = (1.0, 0.0, 0.0, 0.0)
            red_alert.visible = False
            red_alert.active = False
            new_button.red_alert = red_alert
            self.red_alerts.append(red_alert)
        # if result['downloaded'] > 0:
        #     ui_bgl.draw_rect(x, y, int(ui_props.thumb_size * result['downloaded'] / 100.0), 2, green)

        return new_button

    def init_ui(self):
        ui_scale = bpy.context.preferences.view.ui_scale

        button_bg_color = (0.2, 0.2, 0.2, .1)
        button_hover_color = (0.8, 0.8, 0.8, .2)

        self.buttons = []
        self.asset_buttons = []
        self.validation_icons = []
        self.bookmark_buttons = []
        self.progress_bars = []
        self.red_alerts = []
        self.widgets_panel = []

        self.panel = BL_UI_Drag_Panel(0, 0, self.bar_width, self.bar_height)
        self.panel.bg_color = (0.0, 0.0, 0.0, 0.5)

        # sr = global_vars.DATA.get('search results', [])
        # if sr is not None:
        # we init max possible buttons.
        button_idx = 0
        for x in range(0, self.max_wcount):
            for y in range(0, self.max_hcount):
                # asset_x = self.assetbar_margin + a * (self.button_size)
                # asset_y = self.assetbar_margin + b * (self.button_size)
                # button_idx = x + y * self.max_wcount
                asset_idx = button_idx + self.scroll_offset
                # if asset_idx < len(sr):
                new_button = self.asset_button_init(0, 0, button_idx)
                new_button.asset_index = asset_idx
                self.asset_buttons.append(new_button)
                button_idx += 1

        self.button_close = BL_UI_Button(self.bar_width - self.other_button_size, -self.other_button_size,
                                         self.other_button_size,
                                         self.other_button_size)
        self.button_close.bg_color = button_bg_color
        self.button_close.hover_bg_color = button_hover_color
        self.button_close.text = ""
        self.button_close.set_image_position((0,0))
        self.button_close.set_image_size((self.other_button_size,self.other_button_size))
        self.button_close.set_mouse_down(self.cancel_press)

        self.widgets_panel.append(self.button_close)

        self.scroll_width = 30
        self.button_scroll_down = BL_UI_Button(-self.scroll_width, 0, self.scroll_width, self.bar_height)
        self.button_scroll_down.bg_color = button_bg_color
        self.button_scroll_down.hover_bg_color = button_hover_color
        self.button_scroll_down.text = ""
        self.button_scroll_down.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_down.set_image_position((0, int((self.bar_height - self.button_size) / 2)))

        self.button_scroll_down.set_mouse_down(self.scroll_down)

        self.widgets_panel.append(self.button_scroll_down)

        self.button_scroll_up = BL_UI_Button(self.bar_width, 0, self.scroll_width, self.bar_height)
        self.button_scroll_up.bg_color = button_bg_color
        self.button_scroll_up.hover_bg_color = button_hover_color
        self.button_scroll_up.text = ""
        self.button_scroll_up.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_up.set_image_position((0, int((self.bar_height - self.button_size) / 2)))

        self.button_scroll_up.set_mouse_down(self.scroll_up)

        self.widgets_panel.append(self.button_scroll_up)

        # notifications
        # if not comments_utils.check_notifications_read():
        #     self.button_notifications = BL_UI_Button(self.bar_width - self.other_button_size * 2,
        #                                              -self.other_button_size, self.other_button_size,
        #                                              self.other_button_size)
        #     self.button_notifications.bg_color = button_bg_color
        #     self.button_notifications.hover_bg_color = button_hover_color
        #     self.button_notifications.text = ""
        #
        #     self.button_notifications.set_mouse_down(self.show_notifications)
        #     self.widgets_panel.append(self.button_notifications)

        # self.update_buttons()

    def set_element_images(self):
        '''set ui elements images, has to be done after init of UI.'''
        img_fp = paths.get_addon_thumbnail_path('vs_rejected.png')
        self.button_close.set_image(img_fp)
        self.button_scroll_down.set_image(paths.get_addon_thumbnail_path('arrow_left.png'))
        self.button_scroll_up.set_image(paths.get_addon_thumbnail_path('arrow_right.png'))
        # if not comments_utils.check_notifications_read():
        #     img_fp = paths.get_addon_thumbnail_path('bell.png')
        #     self.button_notifications.set_image(img_fp)

    def position_and_hide_buttons(self):
        # position and layout buttons
        sr = global_vars.DATA.get('search results', [])
        if sr is None:
            sr = []

        i = 0
        for y in range(0, self.hcount):
            for x in range(0, self.wcount):
                asset_x = self.assetbar_margin + x * (self.button_size)
                asset_y = self.assetbar_margin + y * (self.button_size)
                button_idx = x + y * self.wcount
                asset_idx = button_idx + self.scroll_offset
                if len(self.asset_buttons) <= button_idx:
                    break
                button = self.asset_buttons[button_idx]
                button.set_location(asset_x, asset_y)
                button.validation_icon.set_location(
                    asset_x + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin,
                    asset_y + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin)
                button.bookmark_button.set_location(
                    asset_x + self.button_size - self.icon_size - self.button_margin - self.validation_icon_margin,
                    asset_y + self.button_margin + self.validation_icon_margin)
                button.progress_bar.set_location(asset_x, asset_y + self.button_size - 3)
                if asset_idx < len(sr):
                    button.visible = True
                    button.validation_icon.visible = True
                    button.bookmark_button.visible = False
                    # button.progress_bar.visible = True
                else:
                    button.visible = False
                    button.validation_icon.visible = False
                    button.bookmark_button.visible = False
                    button.progress_bar.visible = False
                if utils.profile_is_validator():
                    button.red_alert.set_location(asset_x- self.validation_icon_margin, asset_y- self.validation_icon_margin)
                i += 1

        for a in range(i, len(self.asset_buttons)):
            button = self.asset_buttons[a]
            button.visible = False
            button.validation_icon.visible = False
            button.bookmark_button.visible = False
            button.progress_bar.visible = False

        self.button_scroll_down.height = self.bar_height
        self.button_scroll_down.set_image_position((0, int((self.bar_height - self.button_size) / 2)))
        self.button_scroll_up.height = self.bar_height
        self.button_scroll_up.set_image_position((0, int((self.bar_height - self.button_size) / 2)))

    def __init__(self):
        super().__init__()

    def on_init(self, context):

        self.update_ui_size(bpy.context)

        # todo move all this to update UI size
        ui_props = context.window_manager.blenderkitUI

        self.draw_tooltip = False
        # let's take saved scroll offset and use it to keep scroll between operator runs

        self.last_scroll_offset = -10 #set to -10 so it updates on first run
        self.scroll_offset = ui_props.scroll_offset

        self.text_color = (0.9, 0.9, 0.9, 1.0)
        self.warning_color = (0.9, 0.5, 0.5, 1.0)

        self.init_ui()
        self.init_tooltip()
        self.hide_tooltip()

        self.trackpad_x_accum=0
        self.trackpad_y_accum=0

    def setup_widgets(self, context, event):
        widgets_panel = []
        widgets_panel.extend(self.widgets_panel)
        widgets_panel.extend(self.buttons)

        widgets_panel.extend(self.asset_buttons)
        widgets_panel.extend(self.red_alerts)
        widgets_panel.extend(self.bookmark_buttons)#we try to put bookmark_buttons before others, because they're on top
        widgets_panel.extend(self.validation_icons)
        widgets_panel.extend(self.progress_bars)

        widgets = [self.panel]

        widgets += widgets_panel
        widgets.append(self.tooltip_panel)
        widgets += self.tooltip_widgets

        self.init_widgets(context, widgets)
        self.panel.add_widgets(widgets_panel)
        self.tooltip_panel.add_widgets(self.tooltip_widgets)

    def on_invoke(self, context, event):
        if not context.area:
            return{'CANCELLED'}

        self.on_init(context)
        self.context = context

        if self.do_search or global_vars.DATA.get('search results') is None:
            # TODO: move the search behaviour to separate operator, since asset bar can be already woken up from a timer.

            # we erase search keywords for cateogry search now, since these combinations usually return nothing now.
            # when the db gets bigger, this can be deleted.
            # if self.category != '':
            #     sprops = utils.get_search_props()
            #     sprops.search_keywords = ''
            search.search(category=self.category)

        ui_props = context.window_manager.blenderkitUI
        if ui_props.assetbar_on:
            # TODO solve this otehrwise to enable more asset bars?

            # we don't want to run the assetbar many times, that's why it has a switch on/off behaviour,
            # unless being called with 'keep_running' prop.

            if not self.keep_running:
                # this sends message to the originally running operator, so it quits, and then it ends this one too.
                # If it initiated a search, the search will finish in a thread. The switch off procedure is run
                # by the 'original' operator, since if we get here, it means
                # same operator is already running.
                ui_props.turn_off = True
                # if there was an error, we need to turn off these props so we can restart after 2 clicks
                ui_props.assetbar_on = False

            else:
                pass
            return False

        ui_props.assetbar_on = True
        global asset_bar_operator

        asset_bar_operator = self

        self.active_index = -1

        self.check_new_search_results(context)
        self.setup_widgets(context, event)
        self.set_element_images()
        self.position_and_hide_buttons()
        self.hide_tooltip()
        # for b in self.buttons:
        #     b.bookmark_button.visible=False

        self.panel.set_location(self.bar_x,
                                self.bar_y)
        # to hide arrows accordingly

        self.scroll_update(always = True)

        self.window = context.window
        self.area = context.area
        self.scene = bpy.context.scene
        return True

    def on_finish(self, context):
        # redraw all areas, since otherwise it stays to hang for some more time.
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d_tooltip, 'WINDOW')
        # to pass the operator to validation icons
        global asset_bar_operator
        asset_bar_operator = None

        context.window_manager.event_timer_remove(self._timer)

        scene = bpy.context.scene
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.assetbar_on = False
        ui_props.scroll_offset = self.scroll_offset

        wm = bpy.data.window_managers[0]

        # for w in wm.windows:
        #     for a in w.screen.areas:
        #         a.tag_redraw()
        self._finished = True

    def update_tooltip_image(self, asset_id):
        """Update tootlip image when it finishes downloading and the downloaded image matches the active one."""

        search_results = global_vars.DATA.get('search results')
        if search_results is None:
            return

        if self.active_index >= len(search_results):
            return

        asset_data = search_results[self.active_index]
        if asset_data['assetBaseId'] == asset_id:
            set_thumb_check(self.tooltip_image, asset_data, thumb_type='thumbnail')

    # handlers
    def enter_button(self, widget):
        if not hasattr(widget, "button_index"):
            return #click on left/right arrow button gave no attr button_index
            #we should detect on which button_index scroll/left/right happened to refresh shown thumbnail
        bpy.context.window.cursor_set("HAND")
        search_index = widget.button_index + self.scroll_offset
        if search_index < self.search_results_count:
            self.show_tooltip()
        if self.active_index != search_index:
            self.active_index = search_index

            # scene = bpy.context.scene
            # wm = bpy.context.window_manager
            sr = global_vars.DATA['search results']
            asset_data = sr[search_index]  # + self.scroll_offset]

            self.draw_tooltip = True
            # self.tooltip = asset_data['tooltip']
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = search_index  # + self.scroll_offset

            set_thumb_check(self.tooltip_image,asset_data,thumb_type='thumbnail')
            get_tooltip_data(asset_data)
            an = asset_data['displayName']
            max_name_length = 30
            if len(an) > max_name_length + 3:
                an = an[:30] + '...'
            self.asset_name.text = an
            self.authors_name.text = asset_data['tooltip_data']['author_text']
            quality_text = asset_data['tooltip_data']['quality']
            if utils.profile_is_validator():
                quality_text+=f" / {int(asset_data['score'])}"
            self.quality_label.text  = quality_text

            if utils.asset_from_newer_blender_version(asset_data):
                self.version_warning.text = 'Asset from newer Blender version! Use at your own risk.'
            else:
                self.version_warning.text = ''

            authors = global_vars.DATA['bkit authors']
            a_id = asset_data['author']['id']
            if authors.get(a_id) is not None and authors[a_id].get('gravatarImg') is not None:
                self.gravatar_image.set_image(authors[a_id].get('gravatarImg'))
            else:
                img_path = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')

                self.gravatar_image.set_image(img_path)

            properties_width = 0
            for r in bpy.context.area.regions:
                if r.type == 'UI':
                    properties_width = r.width
            tooltip_x = min(int(widget.x_screen),
                            int(bpy.context.region.width - self.tooltip_panel.width - properties_width))
            tooltip_y = int(widget.y_screen + widget.height)
            #need to set image here because of context issues.
            img_path = paths.get_addon_thumbnail_path('star_grey.png')
            self.quality_star.set_image(img_path)
            # self.init_tooltip()
            self.tooltip_panel.set_location(tooltip_x, tooltip_y)
            self.tooltip_panel.layout_widgets()
            #show bookmark button - always on mouse enter
            if utils.experimental_enabled():
                widget.bookmark_button.visible = True

            # bpy.ops.wm.blenderkit_asset_popup('INVOKE_DEFAULT')

    def exit_button(self, widget):
        # this condition checks if there wasn't another button already entered, which can happen with small button gaps
        if self.active_index == widget.button_index + self.scroll_offset:
            scene = bpy.context.scene
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.draw_tooltip = False
            self.draw_tooltip = False
            self.hide_tooltip()
            self.active_index = -1
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = self.active_index
            bpy.context.window.cursor_set("DEFAULT")
        # hide bookmark button - only when Not bookmarked
        self.update_bookmark_icon(widget.bookmark_button)
        # popup asset card on mouse down
        # if utils.experimental_enabled():
        #     h = widget.get_area_height()
        # if utils.experimental_enabled() and self.mouse_y<widget.y_screen:
        #     self.active_index = widget.button_index + self.scroll_offset
        # bpy.ops.wm.blenderkit_asset_popup('INVOKE_DEFAULT')

    def bookmark_asset(self, widget):
        #bookmark the asset linked to this button
        if not utils.user_logged_in():
            bpy.ops.wm.blenderkit_login_dialog("INVOKE_DEFAULT", message="Please login to bookmark your favourite assets.")
            return

        sr = global_vars.DATA['search results']
        asset_data = sr[widget.asset_index]  # + self.scroll_offset]

        bpy.ops.wm.blenderkit_bookmark_asset(asset_id=asset_data['id'])
        self.update_bookmark_icon(widget)

    def drag_drop_asset(self, widget):
        bpy.ops.view3d.asset_drag_drop("INVOKE_DEFAULT", asset_search_index=widget.search_index + self.scroll_offset)

    def cancel_press(self, widget):
        self.finish()

    def asset_menu(self, widget):
        self.hide_tooltip()
        bpy.ops.wm.blenderkit_asset_popup('INVOKE_DEFAULT')
        # bpy.ops.wm.call_menu(name='OBJECT_MT_blenderkit_asset_menu')

    def search_more(self):
        sro = global_vars.DATA.get('search results orig')
        if sro is None:
            return
        if sro.get('next') is None:
            return
        search_props = utils.get_search_props()
        if search_props.is_searching:
            return

        search.search(get_next=True)

    def update_bookmark_icon(self, bookmark_button):
        if not utils.experimental_enabled():
            bookmark_button.visible=False
            return
        asset_data = global_vars.DATA['search results'][bookmark_button.asset_index]
        r = ratings_utils.get_rating_local(asset_data['id'],"bookmarks")
        if r == 1:
            icon = "bookmark_full.png"
            visible=True
        else:
            icon = "bookmark_empty.png"
            if self.active_index == bookmark_button.asset_index:
                visible=True
            else:
                visible=False
        bookmark_button.visible=visible
        img_fp = paths.get_addon_thumbnail_path(icon)
        bookmark_button.set_image(img_fp)

    def update_progress_bar(self, asset_button, asset_data):
        if asset_data['downloaded'] > 0:
            pb = asset_button.progress_bar
            ui_scale = bpy.context.preferences.view.ui_scale
            w = int(self.button_size * ui_scale * asset_data['downloaded'] / 100.0)
            asset_button.progress_bar.width = w
            asset_button.progress_bar.update(pb.x_screen, pb.y_screen)
            asset_button.progress_bar.visible = True
        else:
            asset_button.progress_bar.visible = False


    def update_validation_icon(self, asset_button, asset_data):
        if utils.profile_is_validator():
            ar = global_vars.DATA.get('asset ratings', {})

            rating = ar.get(asset_data['id'])
            # if rating is not None:
            #     rating = rating.to_dict()

            v_icon = ui.verification_icons[asset_data.get('verificationStatus', 'validated')]
            if v_icon is not None:
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            elif rating is None or rating.get('quality') is None:
                v_icon = 'star_grey.png'
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            else:
                asset_button.validation_icon.visible = False
        else:
            if asset_data.get('canDownload', True) == 0:
                img_fp = paths.get_addon_thumbnail_path('locked.png')
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True

            else:
                asset_button.validation_icon.visible = False

    def update_image(self, asset_id):
        '''should be run after thumbs are retrieved so they can be updated '''
        sr = global_vars.DATA.get('search results')
        if not sr:
            return
        for asset_button in self.asset_buttons:
            if asset_button.asset_index < len(sr):
                asset_data = sr[asset_button.asset_index]
                if asset_data['assetBaseId'] == asset_id:
                    set_thumb_check(asset_button, asset_data, thumb_type = 'thumbnail_small')

    def update_buttons(self):
        sr = global_vars.DATA.get('search results')
        if not sr:
            return
        for asset_button in self.asset_buttons:
            if asset_button.visible:
                asset_button.asset_index = asset_button.button_index + self.scroll_offset
                if asset_button.asset_index < len(sr):
                    asset_button.visible = True

                    asset_data = sr[asset_button.asset_index]
                    if asset_data is None:
                        continue


                    # show indices for debug purposes
                    # asset_button.text = str(asset_button.asset_index)


                    set_thumb_check(asset_button, asset_data, thumb_type = 'thumbnail_small')
                    # asset_button.set_image(img_filepath)
                    self.update_validation_icon(asset_button, asset_data)

                    #update bookmark buttons
                    asset_button.bookmark_button.asset_index = asset_button.asset_index

                    self.update_bookmark_icon(asset_button.bookmark_button)

                    self.update_progress_bar(asset_button, asset_data)

                    if utils.profile_is_validator() and asset_data['verificationStatus'] == 'uploaded':
                        over_limit = utils.is_upload_old(asset_data)
                        if over_limit:
                            redness = min(over_limit * .05, 0.7)
                            asset_button.red_alert.bg_color = (1, 0, 0, redness)
                            asset_button.red_alert.visible = True
                        else:
                            asset_button.red_alert.visible = False
                    elif utils.profile_is_validator():
                        asset_button.red_alert.visible = False
            else:
                asset_button.visible = False
                asset_button.validation_icon.visible = False
                asset_button.bookmark_button.visible = False
                asset_button.progress_bar.visible = False
                if utils.profile_is_validator():
                    asset_button.red_alert.visible = False

    def scroll_update(self, always =False):
        sr = global_vars.DATA.get('search results')
        sro = global_vars.DATA.get('search results orig')
        # orig_offset = self.scroll_offset
        # empty results
        if sr is None:
            self.button_scroll_down.visible = False
            self.button_scroll_up.visible = False
            return

        self.scroll_offset = min(self.scroll_offset, len(sr) - (self.wcount * self.hcount))
        self.scroll_offset = max(self.scroll_offset, 0)
        #only update if scroll offset actually changed, otherwise this is unnecessary

        if sro['count'] > len(sr) and len(sr) - self.scroll_offset < (self.wcount * self.hcount) + 15:
            self.search_more()

        if self.scroll_offset == 0:
            self.button_scroll_down.visible = False
        else:
            self.button_scroll_down.visible = True

        if self.scroll_offset >= sro['count'] - (self.wcount * self.hcount):
            self.button_scroll_up.visible = False
        else:
            self.button_scroll_up.visible = True

        # here we save some time by only updating the images if the scroll offset actually changed
        if self.last_scroll_offset == self.scroll_offset and not always:
            return
        self.last_scroll_offset = self.scroll_offset

        self.update_buttons()

    def search_by_author(self, asset_index):
        sr = global_vars.DATA['search results']
        asset_data = sr[asset_index]
        a = asset_data['author']['id']
        if a is not None:
            sprops = utils.get_search_props()
            sprops.search_keywords = ''
            sprops.search_verification_status = 'ALL'
            # utils.p('author:', a)
            search.search(author_id=a)
        return True

    def handle_key_input(self, event):
        if event.type == 'A':
            self.search_by_author(self.active_index)
            return True
        if event.type == 'X' and self.active_index > -1:
            # delete downloaded files for this asset
            sr = global_vars.DATA['search results']
            asset_data = sr[self.active_index]
            bk_logger.info(f'deleting asset from local drive: {asset_data["name"]}')
            paths.delete_asset_debug(asset_data)
            asset_data['downloaded'] = 0
            return True
        if event.type == 'W' and self.active_index > -1:
            sr = global_vars.DATA['search results']
            asset_data = sr[self.active_index]
            a = global_vars.DATA['bkit authors'].get(asset_data['author']['id'])
            if a is not None:
                utils.p('author:', a)
                if a.get('aboutMeUrl') is not None:
                    bpy.ops.wm.url_open(url=a['aboutMeUrl'])
            return True
        # FastRateMenu
        if event.type == 'R' and self.active_index > -1:
            sr = global_vars.DATA['search results']
            asset_data = sr[self.active_index]
            if not utils.user_is_owner(asset_data=asset_data):
                bpy.ops.wm.blenderkit_menu_rating_upload(asset_name=asset_data['name'], asset_id=asset_data['id'],
                                                         asset_type=asset_data['assetType'])
            return True
        return False

    def scroll_up(self, widget):
        self.scroll_offset += self.wcount * self.hcount
        self.scroll_update()
        self.enter_button(widget)

    def scroll_down(self, widget):
        self.scroll_offset -= self.wcount * self.hcount
        self.scroll_update()
        self.enter_button(widget)

BlenderKitAssetBarOperator.modal = asset_bar_modal
BlenderKitAssetBarOperator.invoke = asset_bar_invoke

def register():
    bpy.utils.register_class(BlenderKitAssetBarOperator)


def unregister():
    bpy.utils.unregister_class(BlenderKitAssetBarOperator)
