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

from . import paths, ratings, utils, search, upload, ui_bgl, download, bg_blender, colors, tasks_queue, \
    ui_panels, icons, ratings_utils, reports, global_vars

import bpy

import math, random

from bpy.props import (
    BoolProperty,
    StringProperty,
    IntProperty,
    FloatVectorProperty
)

from bpy_extras import view3d_utils
import mathutils
from mathutils import Vector
import time
import datetime
import os

import logging

draw_time = 0
eval_time = 0

bk_logger = logging.getLogger('blenderkit')

handler_2d = None
handler_3d = None
active_area_pointer = None
active_window_pointer = None
active_region_pointer = None

mappingdict = {
    'MODEL': 'model',
    'SCENE': 'scene',
    'HDR': 'hdr',
    'MATERIAL': 'material',
    'TEXTURE': 'texture',
    'BRUSH': 'brush'
}

verification_icons = {
    'ready': 'vs_ready.png',
    'deleted': 'vs_deleted.png',
    'uploaded': 'vs_uploaded.png',
    'uploading': 'vs_uploading.png',
    'on_hold': 'vs_on_hold.png',
    'validated': None,
    'rejected': 'vs_rejected.png'

}


def get_approximate_text_width(st):
    size = 10
    for s in st:
        if s in 'i|':
            size += 2
        elif s in ' ':
            size += 4
        elif s in 'sfrt':
            size += 5
        elif s in 'ceghkou':
            size += 6
        elif s in 'PadnBCST3E':
            size += 7
        elif s in 'GMODVXYZ':
            size += 8
        elif s in 'w':
            size += 9
        elif s in 'm':
            size += 10
        else:
            size += 7
    return size  # Convert to picas


def draw_bbox(location, rotation, bbox_min, bbox_max, progress=None, color=(0, 1, 0, 1)):
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

    lines = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5],
             [2, 6], [3, 7], [0, 8], [1, 8]]
    ui_bgl.draw_lines(vertices, lines, color)
    if progress != None:
        color = (color[0], color[1], color[2], .2)
        progress = progress * .01
        vz0 = (v4 - v0) * progress + v0
        vz1 = (v5 - v1) * progress + v1
        vz2 = (v6 - v2) * progress + v2
        vz3 = (v7 - v3) * progress + v3
        rects = (
            (v0, v1, vz1, vz0),
            (v1, v2, vz2, vz1),
            (v2, v3, vz3, vz2),
            (v3, v0, vz0, vz3))
        for r in rects:
            ui_bgl.draw_rect_3d(r, color)



def draw_ratings_bgl():
    # return;
    ui = bpy.context.window_manager.blenderkitUI

    rating_possible, rated, asset, asset_data = is_rating_possible()
    if rating_possible:  # (not rated or ui_props.rating_menu_on):
        # print('rating is pssible', asset_data['name'])
        bkit_ratings = asset.bkit_ratings

        if ui.rating_button_on:
            # print('should draw button')
            img = utils.get_thumbnail('star_white.png')

            ui_bgl.draw_image(ui.rating_x,
                              ui.rating_y - ui.rating_button_width,
                              ui.rating_button_width,
                              ui.rating_button_width,
                              img, 1)

            # if ui_props.asset_type != 'BRUSH':
            #     thumbnail_image = props.thumbnail
            # else:
            #     b = utils.get_active_brush()
            #     thumbnail_image = b.icon_filepath

            directory = paths.get_temp_dir('%s_search' % asset_data['assetType'])
            tpath = os.path.join(directory, asset_data['thumbnail_small'])
            img = utils.get_hidden_image(tpath, 'rating_preview')
            ui_bgl.draw_image(ui.rating_x + ui.rating_button_width,
                              ui.rating_y - ui.rating_button_width,
                              ui.rating_button_width,
                              ui.rating_button_width,
                              img, 1)
            return


def draw_text_block(x=0, y=0, width=40, font_size=10, line_height=15, text='', color=colors.TEXT):
    lines = text.split('\n')
    nlines = []
    for l in lines:
        nlines.extend(search.split_subs(l, ))

    column_lines = 0
    for l in nlines:
        ytext = y - column_lines * line_height
        column_lines += 1
        ui_bgl.draw_text(l, x, ytext, font_size, color)


def draw_tooltip(x, y, name='', author='', quality='-', img=None, gravatar=None):
    region = bpy.context.region
    scale = bpy.context.preferences.view.ui_scale
    t = time.time()

    if not img or max(img.size[0], img.size[1]) == 0:
        return;

    x += 20
    y -= 20
    # first get image size scaled
    isizex = int(512 * scale * img.size[0] / min(img.size[0], img.size[1]))
    isizey = int(512 * scale * img.size[1] / min(img.size[0], img.size[1]))

    ttipmargin = 5 * scale
    # then do recurrent re-scaling, to know where to fit the tooltip
    estimated_height = 2 * ttipmargin + isizey
    if estimated_height > y:
        scaledown = y / (estimated_height)
        scale *= scaledown

        isizex = int(512 * scale * img.size[0] / min(img.size[0], img.size[1]))
        isizey = int(512 * scale * img.size[1] / min(img.size[0], img.size[1]))

    ttipmargin = 5 * scale
    textmargin = 12 * scale

    if gravatar is not None:
        overlay_height_base = 90
    else:
        overlay_height_base = 70

    overlay_height = overlay_height_base * scale
    name_height = int(20 * scale)

    width = isizex + 2 * ttipmargin

    properties_width = 0
    for r in bpy.context.area.regions:
        if r.type == 'UI':
            properties_width = r.width

    # limit to area borders
    x = min(x + width, region.width - properties_width) - width

    # define_colors
    background_color = bpy.context.preferences.themes[0].user_interface.wcol_tooltip.inner
    background_overlay = (background_color[0], background_color[1], background_color[2], .8)
    textcol = bpy.context.preferences.themes[0].user_interface.wcol_tooltip.text
    textcol = (textcol[0], textcol[1], textcol[2], 1)

    # background
    ui_bgl.draw_rect(x - ttipmargin,
                     y - 2 * ttipmargin - isizey,
                     isizex + ttipmargin * 2,
                     2 * ttipmargin + isizey,
                     background_color)

    # main preview image
    ui_bgl.draw_image(x, y - isizey - ttipmargin, isizex, isizey, img, 1)

    # text overlay background
    ui_bgl.draw_rect(x - ttipmargin,
                     y - 2 * ttipmargin - isizey,
                     isizex + ttipmargin * 2,
                     ttipmargin + overlay_height,
                     background_overlay)

    # draw name
    name_x = x + textmargin
    name_y = y - isizey + overlay_height - textmargin - name_height
    ui_bgl.draw_text(name, name_x, name_y, name_height, textcol)

    # draw gravatar
    author_x_text = x + isizex - textmargin
    gravatar_size = overlay_height - 2 * textmargin
    gravatar_y = y - isizey - ttipmargin + textmargin
    if gravatar is not None:
        author_x_text -= gravatar_size + textmargin
        ui_bgl.draw_image(x + isizex - gravatar_size - textmargin,
                          gravatar_y,  # + textmargin,
                          gravatar_size, gravatar_size, gravatar, 1)

    # draw author's name
    author_text_size = int(name_height * .7)
    ui_bgl.draw_text(author, author_x_text, gravatar_y, author_text_size, textcol, halign='RIGHT')

    # draw quality
    quality_text_size = int(name_height * 1)
    img = utils.get_thumbnail('star_grey.png')
    ui_bgl.draw_image(name_x, gravatar_y, quality_text_size, quality_text_size, img, .6)
    ui_bgl.draw_text(str(quality), name_x + quality_text_size + 5, gravatar_y, quality_text_size, textcol)


def draw_tooltip_with_author(asset_data, x, y):
    # TODO move this lazy loading into a function and don't duplicate through the code

    img = get_large_thumbnail_image(asset_data)
    gimg = None
    tooltip_data = asset_data.get('tooltip_data')
    if tooltip_data is None:
        author_text = ''

        if global_vars.DATA.get('bkit authors') is not None:
            a = global_vars.DATA['bkit authors'].get(asset_data['author']['id'])
            if a is not None and a != '':
                if a.get('gravatarImg') is not None:
                    gimg = utils.get_hidden_image(a['gravatarImg'], a['gravatarHash']).name

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
            quality = round(asset_data['ratingsAverage'].get('quality'))
        tooltip_data = {
            'aname': aname,
            'author_text': author_text,
            'quality': quality,
            'gimg': gimg
        }
        asset_data['tooltip_data'] = tooltip_data
    gimg = tooltip_data['gimg']
    if gimg is not None:
        gimg = bpy.data.images[gimg]

    draw_tooltip(x, y, name=tooltip_data['aname'],
                 author=tooltip_data['author_text'],
                 quality=tooltip_data['quality'],
                 img=img,
                 gravatar=gimg)


def draw_callback_2d(self, context):
    if not utils.guard_from_crash():
        return

    a = context.area
    w = context.window
    try:
        # self.area might throw error just by itself.
        a1 = self.area
        w1 = self.window
        go = True
        if len(a.spaces[0].region_quadviews) > 0:
            # print(dir(bpy.context.region_data))
            # print('quad', a.spaces[0].region_3d, a.spaces[0].region_quadviews[0])
            if a.spaces[0].region_3d != context.region_data:
                go = False
    except:
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d, 'WINDOW')
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')
        go = False
    if go and a == a1 and w == w1:

        props = context.window_manager.blenderkitUI
        if props.down_up == 'SEARCH':
            draw_ratings_bgl()
            draw_asset_bar(self, context)
        elif props.down_up == 'UPLOAD':
            draw_callback_2d_upload_preview(self, context)


def draw_downloader(x, y, percent=0, img=None, text=''):
    if img is not None:
        ui_bgl.draw_image(x, y, 50, 50, img, .5)

    ui_bgl.draw_rect(x, y, 50, int(0.5 * percent), (.2, 1, .2, .3))
    ui_bgl.draw_rect(x - 3, y - 3, 6, 6, (1, 0, 0, .3))
    # if asset_data is not None:
    #     ui_bgl.draw_text(asset_data['name'], x, y, colors.TEXT)
    #     ui_bgl.draw_text(asset_data['filesSize'])
    if text:
        ui_bgl.draw_text(text, x, y - 15, 12, colors.TEXT)


def draw_progress(x, y, text='', percent=None, color=colors.GREEN):
    ui_bgl.draw_rect(x, y, percent, 5, color)
    ui_bgl.draw_text(text, x, y + 8, 16, color)


def draw_callback_3d_progress(self, context):
    # 'star trek' mode is here

    if not utils.guard_from_crash():
        return
    for key,task in download.download_tasks.items():
        asset_data = task['asset_data']
        if task.get('downloaders'):
            for d in task['downloaders']:
                if asset_data['assetType'] == 'model':
                    draw_bbox(d['location'], d['rotation'], asset_data['bbox_min'], asset_data['bbox_max'],
                              progress=task['progress'])


def draw_callback_2d_progress(self, context):
    if not utils.guard_from_crash():
        return

    green = (.2, 1, .2, .3)
    offset = 0
    row_height = 35

    ui = bpy.context.window_manager.blenderkitUI

    x = ui.reports_x
    y = ui.reports_y
    index = 0
    for key,task in download.download_tasks.items():
        asset_data = task['asset_data']

        directory = paths.get_temp_dir('%s_search' % asset_data['assetType'])
        tpath = os.path.join(directory, asset_data['thumbnail_small'])
        img = utils.get_hidden_image(tpath, asset_data['id'])

        if task.get('downloaders'):
            for d in task['downloaders']:

                loc = view3d_utils.location_3d_to_region_2d(bpy.context.region, bpy.context.space_data.region_3d,
                                                            d['location'])
                # print('drawing downloader')
                if loc is not None:
                    if asset_data['assetType'] == 'model':
                        # models now draw with star trek mode, no need to draw percent for the image.
                        draw_downloader(loc[0], loc[1], percent=task['progress'], img=img, text=task['text'])
                    else:
                        draw_downloader(loc[0], loc[1], percent=task['progress'], img=img, text=task['text'])
                # utils.p('end drawing downlaoders  downloader')
        else:
            draw_progress(x, y - index * 30, text='downloading %s' % asset_data['name'],
                          percent=task['progress'])
            index += 1

    for process in bg_blender.bg_processes:
        tcom = process[1]
        n = ''
        if tcom.name is not None:
            n = tcom.name + ': '
        draw_progress(x, y - index * 30, '%s' % n + tcom.lasttext,
                      tcom.progress)
        index += 1
    for report in reports.reports:
        # print('drawing reports', x, y, report.text)
        report.draw(x, y - index * 30)
        index += 1
        report.fade()


def draw_callback_2d_upload_preview(self, context):
    ui_props = context.window_manager.blenderkitUI

    props = utils.get_upload_props()

    # assets which don't need asset preview
    if ui_props.asset_type == 'HDR':
        return

    if props != None and ui_props.draw_tooltip:

        if ui_props.asset_type != 'BRUSH':
            ui_props.thumbnail_image = props.thumbnail
        else:
            b = utils.get_active_brush()
            ui_props.thumbnail_image = b.icon_filepath

        img = utils.get_hidden_image(ui_props.thumbnail_image, 'upload_preview')

        draw_tooltip(ui_props.bar_x, ui_props.bar_y, name=props.name, img=img)



def get_large_thumbnail_image(asset_data):
    '''Get thumbnail image from asset data'''
    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI
    iname = utils.previmg_name(ui_props.active_index, fullsize=True)
    directory = paths.get_temp_dir('%s_search' % mappingdict[ui_props.asset_type])
    tpath = os.path.join(directory, asset_data['thumbnail'])
    # if asset_data['assetType'] == 'hdr':
    #     tpath = os.path.join(directory, asset_data['thumbnail'])
    if not asset_data['thumbnail']:
        tpath = paths.get_addon_thumbnail_path('thumbnail_not_available.jpg')

    if asset_data['assetType'] == 'hdr':
        colorspace = 'Non-Color'
    else:
        colorspace = 'sRGB'
    img = utils.get_hidden_image(tpath, iname, colorspace=colorspace)
    return img


def draw_asset_bar(self, context):
    s = bpy.context.scene
    ui_props = context.window_manager.blenderkitUI
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    is_validator = utils.profile_is_validator()
    r = self.region
    # hc = bpy.context.preferences.themes[0].view_3d.space.header
    # hc = bpy.context.preferences.themes[0].user_interface.wcol_menu_back.inner
    # hc = (hc[0], hc[1], hc[2], .2)
    hc = (1, 1, 1, .07)
    # grey1 = (hc.r * .55, hc.g * .55, hc.b * .55, 1)
    grey2 = (hc[0] * .8, hc[1] * .8, hc[2] * .8, .5)
    # grey1 = (hc.r, hc.g, hc.b, 1)
    white = (1, 1, 1, 0.2)
    green = (.2, 1, .2, .7)
    highlight = bpy.context.preferences.themes[0].user_interface.wcol_menu_item.inner_sel
    highlight = (1, 1, 1, .2)
    # highlight = (1, 1, 1, 0.8)
    # background of asset bar
    # if ui_props.hcount>0:
    #     #this fixes a draw issue introduced in blender 2.91. draws a very small version of the image to avoid problems
    #     # with alpha. Not sure why this works.
    #     img = utils.get_thumbnail('arrow_left.png')
    #     ui_bgl.draw_image(0, 0, 1,
    #                       1,
    #                       img,
    #                       1)
    if ui_props.hcount > 0 and ui_props.wcount > 0:
        search_results = global_vars.DATA.get('search results')
        search_results_orig = global_vars.DATA.get('search results orig')
        if search_results == None:
            return
        h_draw = min(ui_props.hcount, math.ceil(len(search_results) / ui_props.wcount))

        if ui_props.wcount > len(search_results):
            bar_width = len(search_results) * (ui_props.thumb_size + ui_props.margin) + ui_props.margin
        else:
            bar_width = ui_props.bar_width
        row_height = ui_props.thumb_size + ui_props.margin
        ui_bgl.draw_rect(ui_props.bar_x, ui_props.bar_y - ui_props.bar_height, bar_width,
                         ui_props.bar_height, hc)

        if search_results is not None:
            if ui_props.scroll_offset > 0 or ui_props.wcount * ui_props.hcount < len(search_results):
                ui_props.drawoffset = 35
            else:
                ui_props.drawoffset = 0

            if ui_props.wcount * ui_props.hcount < len(search_results):
                # arrows
                arrow_y = ui_props.bar_y - int((ui_props.bar_height + ui_props.thumb_size) / 2) + ui_props.margin
                if ui_props.scroll_offset > 0:

                    if ui_props.active_index == -2:
                        ui_bgl.draw_rect(ui_props.bar_x, ui_props.bar_y - ui_props.bar_height, 25,
                                         ui_props.bar_height, highlight)
                    img = utils.get_thumbnail('arrow_left.png')
                    ui_bgl.draw_image(ui_props.bar_x, arrow_y, 25,
                                      ui_props.thumb_size,
                                      img,
                                      1)

                if search_results_orig['count'] - ui_props.scroll_offset > (ui_props.wcount * ui_props.hcount) + 1:
                    if ui_props.active_index == -1:
                        ui_bgl.draw_rect(ui_props.bar_x + ui_props.bar_width - 25,
                                         ui_props.bar_y - ui_props.bar_height, 25,
                                         ui_props.bar_height,
                                         highlight)
                    img1 = utils.get_thumbnail('arrow_right.png')
                    ui_bgl.draw_image(ui_props.bar_x + ui_props.bar_width - 25,
                                      arrow_y, 25,
                                      ui_props.thumb_size, img1, 1)
            ar = global_vars.DATA.get('asset ratings',{})
            for b in range(0, h_draw):
                w_draw = min(ui_props.wcount, len(search_results) - b * ui_props.wcount - ui_props.scroll_offset)

                y = ui_props.bar_y - (b + 1) * (row_height)
                for a in range(0, w_draw):
                    x = ui_props.bar_x + a * (
                            ui_props.margin + ui_props.thumb_size) + ui_props.margin + ui_props.drawoffset

                    #
                    index = a + ui_props.scroll_offset + b * ui_props.wcount
                    iname = utils.previmg_name(index)
                    img = bpy.data.images.get(iname)
                    if img is not None and img.size[0] > 0 and img.size[1] > 0:
                        w = int(ui_props.thumb_size * img.size[0] / max(img.size[0], img.size[1]))
                        h = int(ui_props.thumb_size * img.size[1] / max(img.size[0], img.size[1]))
                        crop = (0, 0, 1, 1)
                        if img.size[0] > img.size[1]:
                            offset = (1 - img.size[1] / img.size[0]) / 2
                            crop = (offset, 0, 1 - offset, 1)

                        ui_bgl.draw_image(x, y, w, w, img, 1,
                                          crop=crop)
                        if index == ui_props.active_index:
                            ui_bgl.draw_rect(x - ui_props.highlight_margin, y - ui_props.highlight_margin,
                                             w + 2 * ui_props.highlight_margin, w + 2 * ui_props.highlight_margin,
                                             highlight)
                        # if index == ui_props.active_index:
                        #     ui_bgl.draw_rect(x - highlight_margin, y - highlight_margin,
                        #               w + 2*highlight_margin, h + 2*highlight_margin , highlight)

                    else:
                        ui_bgl.draw_rect(x, y, ui_props.thumb_size, ui_props.thumb_size, grey2)
                        ui_bgl.draw_text('loading', x + ui_props.thumb_size // 2, y + ui_props.thumb_size // 2,
                                         ui_props.thumb_size // 6, white, halign='CENTER', valign='CENTER')

                    result = search_results[index]
                    # code to inform validators that the validation is waiting too long and should be done asap
                    if result['verificationStatus'] == 'uploaded':
                        if is_validator:
                            over_limit = utils.is_upload_old(result)
                            if over_limit:
                                redness = min(over_limit * .05, 0.5)
                                red = (1, 0, 0, redness)
                                ui_bgl.draw_rect(x, y, ui_props.thumb_size, ui_props.thumb_size, red)

                    if result['downloaded'] > 0:
                        ui_bgl.draw_rect(x, y, int(ui_props.thumb_size * result['downloaded'] / 100.0), 2, green)
                    # object type icons - just a test..., adds clutter/ not so userfull:
                    # icons = ('type_finished.png', 'type_template.png', 'type_particle_system.png')

                    if (result.get('canDownload', True)) == 0:
                        img = utils.get_thumbnail('locked.png')
                        ui_bgl.draw_image(x + 2, y + 2, 24, 24, img, 1)

                    # pcoll = icons.icon_collections["main"]
                    # v_icon = pcoll['rejected']
                    v_icon = verification_icons[result.get('verificationStatus', 'validated')]

                    if v_icon is None and is_validator:
                        # poke for validators to rate
                        rating = ar.get(result['id'])
                        if rating is not None:
                            rating = rating.to_dict()
                        if rating in (None, {}):
                            v_icon = 'star_grey.png'

                    if v_icon is not None:
                        img = utils.get_thumbnail(v_icon)
                        ui_bgl.draw_image(x + ui_props.thumb_size - 26, y + 2, 24, 24, img, 1)

            # if user_preferences.api_key == '':
            #     report = 'Register on BlenderKit website to upload your own assets.'
            #     ui_bgl.draw_text(report, ui_props.bar_x + ui_props.margin,
            #                      ui_props.bar_y - 25 - ui_props.margin - ui_props.bar_height, 15)
            # elif len(search_results) == 0:
            #     report = 'BlenderKit - No matching results found.'
            #     ui_bgl.draw_text(report, ui_props.bar_x + ui_props.margin,
            #                      ui_props.bar_y - 25 - ui_props.margin, 15)
            if ui_props.draw_tooltip and len(search_results) > ui_props.active_index:
                r = search_results[ui_props.active_index]
                draw_tooltip_with_author(r, ui_props.mouse_x, ui_props.mouse_y)
        s = bpy.context.scene
        props = utils.get_search_props()
        # if props.report != '' and props.is_searching or props.search_error:
        #     ui_bgl.draw_text(props.report, ui_props.bar_x,
        #                      ui_props.bar_y - 15 - ui_props.margin - ui_props.bar_height, 15)


def object_in_particle_collection(o):
    '''checks if an object is in a particle system as instance, to not snap to it and not to try to attach material.'''
    for p in bpy.data.particles:
        if p.render_type == 'COLLECTION':
            if p.instance_collection:
                for o1 in p.instance_collection.objects:
                    if o1 == o:
                        return True
        if p.render_type == 'COLLECTION':
            if p.instance_object == o:
                return True
    return False


def deep_ray_cast(depsgraph, ray_origin, vec):
    # this allows to ignore some objects, like objects with bounding box draw style or particle objects
    object = None
    # while object is None or object.draw
    has_hit, snapped_location, snapped_normal, face_index, object, matrix = bpy.context.scene.ray_cast(
        depsgraph, ray_origin, vec)
    empty_set = False, Vector((0, 0, 0)), Vector((0, 0, 1)), None, None, None
    if not object:
        return empty_set
    try_object = object
    while try_object and (try_object.display_type == 'BOUNDS' or object_in_particle_collection(try_object)):
        ray_origin = snapped_location + vec.normalized() * 0.0003
        try_has_hit, try_snapped_location, try_snapped_normal, try_face_index, try_object, try_matrix = bpy.context.scene.ray_cast(
            depsgraph, ray_origin, vec)
        if try_has_hit:
            # this way only good hits are returned, otherwise
            has_hit, snapped_location, snapped_normal, face_index, object, matrix = try_has_hit, try_snapped_location, try_snapped_normal, try_face_index, try_object, try_matrix
    if not (object.display_type == 'BOUNDS' or object_in_particle_collection(
            try_object)):  # or not object.visible_get()):
        return has_hit, snapped_location, snapped_normal, face_index, object, matrix
    return empty_set


def mouse_raycast(context, mx, my):
    r = context.region
    rv3d = context.region_data
    coord = mx, my
    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(r, rv3d, coord)
    if rv3d.view_perspective == 'CAMERA' and rv3d.is_perspective == False:
        #  ortographic cameras don'w work with region_2d_to_origin_3d
        view_position = rv3d.view_matrix.inverted().translation
        ray_origin = view3d_utils.region_2d_to_location_3d(r, rv3d, coord, depth_location=view_position)
    else:
        ray_origin = view3d_utils.region_2d_to_origin_3d(r, rv3d, coord, clamp=1.0)

    ray_target = ray_origin + (view_vector * 1000000000)

    vec = ray_target - ray_origin

    has_hit, snapped_location, snapped_normal, face_index, object, matrix = deep_ray_cast(
        bpy.context.view_layer.depsgraph, ray_origin, vec)

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

        snapped_rotation = snapped_normal.to_track_quat('Z', 'Y').to_euler()

        if props.randomize_rotation and snapped_normal.angle(up) < math.radians(10.0):
            randoffset = props.offset_rotation_amount + math.pi + (
                    random.random() - 0.5) * props.randomize_rotation_amount
        else:
            randoffset = props.offset_rotation_amount  # we don't rotate this way on walls and ceilings. + math.pi
        # snapped_rotation.z += math.pi + (random.random() - 0.5) * .2

    else:
        snapped_rotation = mathutils.Quaternion((0, 0, 0, 0)).to_euler()

    snapped_rotation.rotate_axis('Z', randoffset)

    return has_hit, snapped_location, snapped_normal, snapped_rotation, face_index, object, matrix


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
    if math.isclose(view_vector.x, 0, abs_tol=1e-4) and math.isclose(view_vector.z, 0, abs_tol=1e-4):
        plane_normal = (0, 1, 0)
    elif math.isclose(view_vector.z, 0, abs_tol=1e-4):
        plane_normal = (1, 0, 0)

    snapped_location = mathutils.geometry.intersect_line_plane(ray_origin, ray_target, (0, 0, 0), plane_normal,
                                                               False)
    if snapped_location != None:
        has_hit = True
        snapped_normal = Vector((0, 0, 1))
        face_index = None
        object = None
        matrix = None
        snapped_rotation = snapped_normal.to_track_quat('Z', 'Y').to_euler()
        props = bpy.context.window_manager.blenderkit_models
        if props.randomize_rotation:
            randoffset = props.offset_rotation_amount + math.pi + (
                    random.random() - 0.5) * props.randomize_rotation_amount
        else:
            randoffset = props.offset_rotation_amount + math.pi
        snapped_rotation.rotate_axis('Z', randoffset)

    return has_hit, snapped_location, snapped_normal, snapped_rotation, face_index, object, matrix


def is_rating_possible():
    ao = bpy.context.active_object
    ui = bpy.context.window_manager.blenderkitUI
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    # first test if user is logged in.
    if preferences.api_key == '':
        return False, False, None, None
    if bpy.context.scene.get('assets rated') is not None and ui.down_up == 'SEARCH':
        if bpy.context.mode in ('SCULPT', 'PAINT_TEXTURE'):
            b = utils.get_active_brush()
            ad = b.get('asset_data')
            if ad is not None:
                rated = bpy.context.scene['assets rated'].get(ad['assetBaseId'])
                return True, rated, b, ad
        if ao is not None:
            ad = None
            # crawl parents to reach active asset. there could have been parenting so we need to find the first onw
            ao_check = ao
            while ad is None or (ad is None and ao_check.parent is not None):
                s = bpy.context.scene
                ad = ao_check.get('asset_data')
                if ad is not None and ad.get('assetBaseId') is not None:

                    s['assets rated'] = s.get('assets rated', {})
                    rated = s['assets rated'].get(ad['assetBaseId'])
                    # originally hidden for already rated assets
                    return True, rated, ao_check, ad
                elif ao_check.parent is not None:
                    ao_check = ao_check.parent
                else:
                    break
            # check also materials
            m = ao.active_material
            if m is not None:
                ad = m.get('asset_data')

                if ad is not None and ad.get('assetBaseId'):
                    rated = bpy.context.scene['assets rated'].get(ad['assetBaseId'])
                    return True, rated, m, ad

        # if t>2 and t<2.5:
        #     ui_props.rating_on = False

    return False, False, None, None




def mouse_in_region(r, mx, my):
    if 0 < my < r.height and 0 < mx < r.width:
        return True
    else:
        return False


def update_ui_size(area, region):
    if bpy.app.background or not area:
        return
    ui = bpy.context.window_manager.blenderkitUI
    user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
    ui_scale = bpy.context.preferences.view.ui_scale

    ui.margin = ui.bl_rna.properties['margin'].default * ui_scale
    ui.thumb_size = user_preferences.thumb_size * ui_scale

    reg_multiplier = 1
    if not bpy.context.preferences.system.use_region_overlap:
        reg_multiplier = 0

    for r in area.regions:
        if r.type == 'TOOLS':
            ui.bar_x = r.width * reg_multiplier + ui.margin + ui.bar_x_offset * ui_scale
        elif r.type == 'UI':
            ui.bar_end = r.width * reg_multiplier + 100 * ui_scale

    ui.bar_width = region.width - ui.bar_x - ui.bar_end
    ui.wcount = math.floor(
        (ui.bar_width - 2 * ui.drawoffset) / (ui.thumb_size + ui.margin))

    search_results = global_vars.DATA.get('search results')
    if search_results != None and ui.wcount > 0:
        ui.hcount = min(user_preferences.max_assetbar_rows, math.ceil(len(search_results) / ui.wcount))
    else:
        ui.hcount = 1
    ui.bar_height = (ui.thumb_size + ui.margin) * ui.hcount + ui.margin
    ui.bar_y = region.height - ui.bar_y_offset * ui_scale
    if ui.down_up == 'UPLOAD':
        ui.reports_y = ui.bar_y - 600
        ui.reports_x = ui.bar_x
    else:
        ui.reports_y = ui.bar_y - ui.bar_height - 100
        ui.reports_x = ui.bar_x

    ui.rating_x = ui.bar_x
    ui.rating_y = ui.bar_y - ui.bar_height


class ParticlesDropDialog(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "object.blenderkit_particles_drop"
    bl_label = "BlenderKit particle plants object drop"
    bl_options = {'REGISTER', 'INTERNAL'}

    asset_search_index: IntProperty(name="Asset index",
                                    description="Index of the asset in asset bar",
                                    default=0,
                                    )

    model_location: FloatVectorProperty(name="Location",
                                        default=(0, 0, 0))

    model_rotation: FloatVectorProperty(name="Rotation",
                                        default=(0, 0, 0),
                                        subtype='QUATERNION')

    target_object: StringProperty(
        name="Target object",
        description="The object to which the particles will get applied",
        default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        message = 'This asset is a particle setup. BlenderKit can apply particles to the active/drag-drop object.' \
                  'The number of particles is caluclated automatically, but if there are 2 many particles,' \
                  ' BlenderKit can do the following steps to make sure Blender continues to run:' \
                  '\n1.Switch to bounding box view of the particles.' \
                  '\n2.Turn down number of particles that are shown in the view.' \
                  '\n3.Hide the particle system completely from the 3D view.' \
                  "as a result of this, it's possible you'll see the particle setup only in render view or " \
                  "rendered images. You should still be careful and test particle systems on smaller objects first."
        utils.label_multiline(layout, text=message, width=400)

    def execute(self, context):
        bpy.ops.scene.blenderkit_download(True,
                                          # asset_type=ui_props.asset_type,
                                          asset_index=self.asset_search_index,
                                          model_location=self.model_rotation,
                                          model_rotation=self.model_rotation,
                                          target_object=self.target_object)
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)


# class MaterialDropDialog(bpy.types.Operator):
#     """Tooltip"""
#     bl_idname = "object.blenderkit_material_drop"
#     bl_label = "BlenderKit material drop on linked objects"
#     bl_options = {'REGISTER', 'INTERNAL'}
#
#     asset_search_index: IntProperty(name="Asset index",
#                                     description="Index of the asset in asset bar",
#                                     default=0,
#                                     )
#
#     model_location: FloatVectorProperty(name="Location",
#                                         default=(0, 0, 0))
#
#     model_rotation: FloatVectorProperty(name="Rotation",
#                                         default=(0, 0, 0),
#                                         subtype='QUATERNION')
#
#     target_object: StringProperty(
#         name="Target object",
#         description="The object to which the particles will get applied",
#         default="", options={'SKIP_SAVE'})
#
#     target_material_slot: IntProperty(name="Target material slot",
#                                     description="Index of the material on the object to be changed",
#                                     default=0,
#                                     )
#
#     @classmethod
#     def poll(cls, context):
#         return True
#
#     def draw(self, context):
#         layout = self.layout
#         message = "This asset is linked to the scene from an external file and cannot have material appended." \
#                   " Do you want to bring it into Blender Scene?"
#         utils.label_multiline(layout, text=message, width=400)
#
#     def execute(self, context):
#         for c in bpy.data.collections:
#             for o in c.objects:
#                 if o.name != self.target_object:
#                     continue;
#                 for empty in bpy.context.visible_objects:
#                     if not(empty.instance_type == 'COLLECTION' and empty.instance_collection == c):
#                         continue;
#                     utils.activate(empty)
#                     break;
#         bpy.ops.object.blenderkit_bring_to_scene()
#         bpy.ops.scene.blenderkit_download(True,
#                                           # asset_type=ui_props.asset_type,
#                                           asset_index=self.asset_search_index,
#                                           model_location=self.model_rotation,
#                                           model_rotation=self.model_rotation,
#                                           target_object=self.target_object,
#                                           material_target_slot = self.target_slot)
#         return {'FINISHED'}
#
#     def invoke(self, context, event):
#         wm = context.window_manager
#         return wm.invoke_props_dialog(self, width=400)


class TransferBlenderkitData(bpy.types.Operator):
    """Regenerate cobweb"""
    bl_idname = "object.blenderkit_data_trasnfer"
    bl_label = "Transfer BlenderKit data"
    bl_description = "Transfer blenderKit metadata from one object to another when fixing uploads with wrong parenting"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        source_ob = bpy.context.active_object
        for target_ob in bpy.context.selected_objects:
            if target_ob != source_ob:
                # target_ob.property_unset('blenderkit')
                for k in source_ob.blenderkit.keys():
                    if k in ('name',):
                        continue
                    target_ob.blenderkit[k] = source_ob.blenderkit[k]
        # source_ob.property_unset('blenderkit')
        return {'FINISHED'}


class UndoWithContext(bpy.types.Operator):
    """Regenerate cobweb"""
    bl_idname = "wm.undo_push_context"
    bl_label = "BlenderKit undo push"
    bl_description = "BlenderKit undo push with fixed context"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # def modal(self, context, event):
    #     return {'RUNNING_MODAL'}

    message: StringProperty('Undo Message', default='BlenderKit operation')

    def execute(self, context):
        # C_dict = utils.get_fake_context(context)
        # w, a, r = get_largest_area(area_type=area_type)
        # wm = bpy.context.window_manager#bpy.data.window_managers[0]
        # w = wm.windows[0]
        #
        # C_dict = {'window': w, 'screen': w.screen}
        # bpy.ops.ed.undo_push(C_dict, 'INVOKE_REGION_WIN', message=self.message)
        bpy.ops.ed.undo_push('INVOKE_REGION_WIN', message=self.message)

        return {'FINISHED'}


def draw_callback_dragging(self, context):
    try:
        img = bpy.data.images.get(self.iname)
    except:
        #  self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_dragging, args, 'WINDOW', 'POST_PIXEL')
        #  self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_3d_dragging, args, 'WINDOW',
        #   bpy.types.SpaceView3D.draw_handler_remove(self._handle,
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')

        return
    linelength = 35
    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_bgl.draw_image(self.mouse_x + linelength, self.mouse_y - linelength - ui_props.thumb_size,
                      ui_props.thumb_size, ui_props.thumb_size, img, 1)
    ui_bgl.draw_line2d(self.mouse_x, self.mouse_y, self.mouse_x + linelength,
                       self.mouse_y - linelength, 2, colors.WHITE)


def draw_callback_3d_dragging(self, context):
    ''' Draw snapped bbox while dragging. '''
    if not utils.guard_from_crash():
        return
    try:
        self.has_hit
    except:
        return
    ui_props = context.window_manager.blenderkitUI
    # print(ui_props.asset_type, self.has_hit, self.snapped_location)
    if ui_props.asset_type == 'MODEL':
        if self.has_hit:
            draw_bbox(self.snapped_location, self.snapped_rotation, self.snapped_bbox_min, self.snapped_bbox_max)


def find_and_activate_instancers(object):
    for ob in bpy.context.visible_objects:
        if ob.instance_type == 'COLLECTION' and ob.instance_collection and object.name in ob.instance_collection.objects:
            utils.activate(ob)
            return ob


class AssetDragOperator(bpy.types.Operator):
    """Drag & drop assets into scene"""
    bl_idname = "view3d.asset_drag_drop"
    bl_label = "BlenderKit asset drag drop"

    asset_search_index: IntProperty(name="Active Index", default=0)
    drag_length: IntProperty(name="Drag_length", default=0)

    object_name = None

    def handlers_remove(self):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')

    def mouse_release(self):
        scene = bpy.context.scene
        ui_props = bpy.context.window_manager.blenderkitUI

        if ui_props.asset_type == 'MODEL':
            if not self.drag:
                self.snapped_location = scene.cursor.location
                self.snapped_rotation = (0, 0, 0)

            target_object = ''
            if self.object_name is not None:
                target_object = self.object_name
                target_slot = ''

            if 'particle_plants' in self.asset_data['tags']:
                bpy.ops.object.blenderkit_particles_drop("INVOKE_DEFAULT",
                                                         asset_search_index=self.asset_search_index,
                                                         model_location=self.snapped_location,
                                                         model_rotation=self.snapped_rotation,
                                                         target_object=target_object)
            else:
                bpy.ops.scene.blenderkit_download(True,
                                                  # asset_type=ui_props.asset_type,
                                                  asset_index=self.asset_search_index,
                                                  model_location=self.snapped_location,
                                                  model_rotation=self.snapped_rotation,
                                                  target_object=target_object)
        if ui_props.asset_type == 'MATERIAL':
            object = None
            target_object = ''
            target_slot = ''
            if not self.drag:
                # click interaction
                object = bpy.context.active_object
                if object is None:
                    ui_panels.ui_message(title='Nothing selected',
                                         message=f"Select something to assign materials by clicking.")
                    return
                target_object = object.name
                target_slot = object.active_material_index
                self.snapped_location = object.location
            elif self.object_name is not None and self.has_hit:

                # first, test if object can have material applied.
                object = bpy.data.objects[self.object_name]
                # this enables to run Bring to scene automatically when dropping on a linked objects.
                # it's however quite a slow operation, that's why not enabled (and finished) now.
                # if object is not None and object.is_library_indirect:
                #     find_and_activate_instancers(object)
                #     bpy.ops.object.blenderkit_bring_to_scene()
                if object is not None and \
                        not object.is_library_indirect and \
                        object.type in utils.supported_material_drag:

                    target_object = object.name
                    # create final mesh to extract correct material slot
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                    object_eval = object.evaluated_get(depsgraph)

                    if object.type == 'MESH':
                        temp_mesh = object_eval.to_mesh()
                        target_slot = temp_mesh.polygons[self.face_index].material_index
                        object_eval.to_mesh_clear()
                    else:
                        ui_props.snapped_location = object.location
                        target_slot = object.active_material_index

            if not object:
                return
            if object.is_library_indirect:
                ui_panels.ui_message(title='This object is linked from outer file',
                                     message="Please select the model,"
                                             "go to the 'Selected Model' panel "
                                             "in BlenderKit and hit 'Bring to Scene' first.")
                return
            if object.type not in utils.supported_material_drag:
                if object.type in utils.supported_material_click:
                    ui_panels.ui_message(title='Unsupported object type',
                                         message=f"Use click interaction for {object.type.lower()} object.")
                    return
                else:
                    ui_panels.ui_message(title='Unsupported object type',
                                         message=f"Can't assign materials to {object.type.lower()} object.")
                    return

            if target_object != '':
                # position is for downloader:
                loc = self.snapped_location
                rotation = (0, 0, 0)

                utils.automap(target_object, target_slot=target_slot,
                              tex_size=self.asset_data.get('texture_size_meters', 1.0))
                bpy.ops.scene.blenderkit_download(True,
                                                  # asset_type=ui_props.asset_type,
                                                  asset_index=self.asset_search_index,
                                                  model_location=loc,
                                                  model_rotation=rotation,
                                                  target_object=target_object,
                                                  material_target_slot=target_slot)

        if ui_props.asset_type == 'HDR':
            bpy.ops.scene.blenderkit_download('INVOKE_DEFAULT',
                                              asset_index=self.asset_search_index,
                                              # replace_resolution=True,
                                              invoke_resolution=True,
                                              max_resolution=self.asset_data.get('max_resolution', 0)
                                              )

        if ui_props.asset_type == 'SCENE':
            bpy.ops.scene.blenderkit_download('INVOKE_DEFAULT',
                                              asset_index=self.asset_search_index,
                                              # replace_resolution=True,
                                              invoke_resolution=False,
                                              invoke_scene_settings=True
                                              )

        if ui_props.asset_type == 'BRUSH':
            bpy.ops.scene.blenderkit_download(  # asset_type=ui_props.asset_type,
                asset_index=self.asset_search_index,
            )

    def modal(self, context, event):
        scene = bpy.context.scene
        ui_props = bpy.context.window_manager.blenderkitUI
        context.area.tag_redraw()

        # if event.type == 'MOUSEMOVE':
        if not hasattr(self, 'start_mouse_x'):
            self.start_mouse_x = event.mouse_region_x
            self.start_mouse_y = event.mouse_region_y

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        # are we dragging already?
        drag_threshold = 10
        if not self.drag and \
                (abs(self.start_mouse_x - self.mouse_x) > drag_threshold or \
                 abs(self.start_mouse_y - self.mouse_y) > drag_threshold):
            self.drag = True

        if self.drag and ui_props.assetbar_on:
            # turn off asset bar here, shout start again after finishing drag drop.
            ui_props.turn_off = True

        if (event.type == 'ESC' or \
            not mouse_in_region(context.region, self.mouse_x, self.mouse_y)) and \
                (not self.drag or self.steps < 5):
            # this case is for canceling from inside popup card when there's an escape attempt to close the window
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'} or \
                not mouse_in_region(context.region, self.mouse_x, self.mouse_y):
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")
            ui_props.dragging = False
            bpy.ops.view3d.blenderkit_asset_bar_widget('INVOKE_REGION_WIN',
                                                       do_search=False)

            return {'CANCELLED'}

        sprops = bpy.context.window_manager.blenderkit_models
        if event.type == 'WHEELUPMOUSE':
            sprops.offset_rotation_amount += sprops.offset_rotation_step
        elif event.type == 'WHEELDOWNMOUSE':
            sprops.offset_rotation_amount -= sprops.offset_rotation_step

        if event.type == 'MOUSEMOVE' or event.type == 'WHEELUPMOUSE' or event.type == 'WHEELDOWNMOUSE':

            #### TODO - this snapping code below is 3x in this file.... refactor it.
            self.has_hit, self.snapped_location, self.snapped_normal, self.snapped_rotation, self.face_index, object, self.matrix = mouse_raycast(
                context, event.mouse_region_x, event.mouse_region_y)
            if object is not None:
                self.object_name = object.name

            # MODELS can be dragged on scene floor
            if not self.has_hit and ui_props.asset_type == 'MODEL':
                self.has_hit, self.snapped_location, self.snapped_normal, self.snapped_rotation, self.face_index, object, self.matrix = floor_raycast(
                    context,
                    event.mouse_region_x, event.mouse_region_y)
                if object is not None:
                    self.object_name = object.name

            if ui_props.asset_type == 'MODEL':
                self.snapped_bbox_min = Vector(self.asset_data['bbox_min'])
                self.snapped_bbox_max = Vector(self.asset_data['bbox_max'])
            #return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.mouse_release()  # does the main job with assets
            self.handlers_remove()
            bpy.context.window.cursor_set("DEFAULT")
            
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
            ui_props.dragging = False
            return {'FINISHED'}

        self.steps += 1

        #pass event to assetbar so it can close itself
        if ui_props.assetbar_on and ui_props.turn_off:
                return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            # the arguments we pass the the callback
            args = (self, context)
            # Add the region OpenGL drawing callback
            # draw in view space with 'POST_VIEW' and 'PRE_VIEW'
            self.iname = utils.previmg_name(self.asset_search_index)

            self.mouse_x = 0
            self.mouse_y = 0
            self.steps = 0

            self.has_hit = False
            self.snapped_location = (0, 0, 0)
            self.snapped_normal = (0, 0, 1)
            self.snapped_rotation = (0, 0, 0)
            self.face_index = 0
            object = None
            self.matrix = None

            sr = global_vars.DATA['search results']
            self.asset_data = sr[self.asset_search_index]

            if not self.asset_data.get('canDownload'):
                message = "Let's support asset creators and Open source."
                link_text = 'Unlock the asset.'
                url = paths.get_bkit_url() + '/get-blenderkit/' + self.asset_data['id'] + '/?from_addon=True'
                bpy.ops.wm.blenderkit_url_dialog('INVOKE_REGION_WIN', url=url, message=message,
                                                 link_text=link_text)

                return {'CANCELLED'}

            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_dragging, args, 'WINDOW', 'POST_PIXEL')
            self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_3d_dragging, args, 'WINDOW',
                                                                     'POST_VIEW')

            bpy.context.window.cursor_set("NONE")
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.dragging = True
            self.drag = False
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}


class View3DExecutor(bpy.types.Operator):
    '''should run anything with correct context, avoiding the need for get fake context tricks in timers'''
    bl_idname = "view3d.run_func_in_operator"
    bl_label = "BlenderKit executor"
    bl_description = "BlenderKit operator to execute various functions in correct context"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    keep_running: StringProperty(name="Run function", description='', default='', options={'SKIP_SAVE'})

    def execute(self,context):
        C_dict = bpy.context.copy()# let's try to get the right context
        bpy.ops.view3d.blenderkit_asset_bar_widget(C_dict, 'INVOKE_REGION_WIN', keep_running=self.keep_running,
                                                   do_search=self.do_search)
        return {'FINISHED'}




class ModalTimerOperator(bpy.types.Operator):
    """Operator which runs its self from a timer"""
    bl_idname = "wm.modal_timer_operator"
    bl_label = "Modal Timer Operator"

    _timer = None

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            # change theme color, silly!
            color = context.preferences.themes[0].view_3d.space.gradients.high_gradient
            color.s = 1.0
            color.h += 0.01

        return {'PASS_THROUGH'}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)

class AssetBarModalStarter(bpy.types.Operator):
    '''Needed for starting asset bar with correct context'''

    bl_idname = "view3d.run_assetbar_start_modal"
    bl_label = "BlenderKit assetbar modal starter"
    bl_description = "Assetbar modal starter"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    keep_running: BoolProperty(name="Keep Running", description='', default=True, options={'SKIP_SAVE'})
    do_search: BoolProperty(name="Run Search", description='', default=False, options={'SKIP_SAVE'})
    _timer = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            # change theme color, silly!
            C_dict = bpy.context.copy()  # let's try to get the right context
            bpy.ops.view3d.blenderkit_asset_bar_widget(C_dict, 'INVOKE_REGION_WIN', keep_running=self.keep_running,
                                                       do_search=self.do_search)
            self.cancel(context)
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


class RunAssetBarWithContext(bpy.types.Operator):
    """This operator can run from a timer and assign a context to modal starter"""
    bl_idname = "view3d.run_assetbar_fix_context"
    bl_label = "BlenderKit assetbar with fixed context"
    bl_description = "Run assetbar with fixed context"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    keep_running: BoolProperty(name="Keep Running", description='', default=True, options={'SKIP_SAVE'})
    do_search: BoolProperty(name="Run Search", description='', default=False, options={'SKIP_SAVE'})

    # def modal(self, context, event):
    #     return {'RUNNING_MODAL'}

    def execute(self, context):
        #possibly only since blender 3.0?
        # if check_context(context):
        #     bpy.ops.view3d.blenderkit_asset_bar_widget('INVOKE_REGION_WIN', keep_running=self.keep_running,
        #                                            do_search=self.do_search)

        C_dict = utils.get_fake_context()
        if C_dict.get('window'):  # no 3d view, no asset bar.
            bpy.ops.view3d.run_assetbar_start_modal(C_dict, keep_running=self.keep_running,
                                                   do_search=self.do_search)

        return {'FINISHED'}


classes = (
    AssetDragOperator,
    View3DExecutor,
    AssetBarModalStarter,
    RunAssetBarWithContext,
    TransferBlenderkitData,
    UndoWithContext,
    ParticlesDropDialog
)

# store keymap items here to access after registration
addon_keymapitems = []


# @persistent
def pre_load(context):
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.assetbar_on = False
    ui_props.turn_off = True
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    preferences.login_attempt = False


def register_ui():
    global handler_2d, handler_3d

    for c in classes:
        bpy.utils.register_class(c)

    args = (None, bpy.context)

    handler_2d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_2d_progress, args, 'WINDOW', 'POST_PIXEL')
    handler_3d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_3d_progress, args, 'WINDOW', 'POST_VIEW')

    wm = bpy.context.window_manager

    # spaces solved by registering shortcut to Window. Couldn't register object mode before somehow.
    if not wm.keyconfigs.addon:
        return
    km = wm.keyconfigs.addon.keymaps.new(name="Window", space_type='EMPTY')
    # asset bar shortcut
    kmi = km.keymap_items.new("view3d.run_assetbar_fix_context", 'SEMI_COLON', 'PRESS', ctrl=False, shift=False)
    kmi.properties.keep_running = False
    kmi.properties.do_search = False
    addon_keymapitems.append(kmi)
    # fast rating shortcut
    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps['Window']
    # kmi = km.keymap_items.new(ratings.FastRateMenu.bl_idname, 'R', 'PRESS', ctrl=False, shift=False)
    # addon_keymapitems.append(kmi)
    # kmi = km.keymap_items.new(upload.FastMetadata.bl_idname, 'F', 'PRESS', ctrl=True, shift=False)
    # addon_keymapitems.append(kmi)


def unregister_ui():
    global handler_2d, handler_3d
    pre_load(bpy.context)

    bpy.types.SpaceView3D.draw_handler_remove(handler_2d, 'WINDOW')
    bpy.types.SpaceView3D.draw_handler_remove(handler_3d, 'WINDOW')

    for c in classes:
        bpy.utils.unregister_class(c)

    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        return

    km = wm.keyconfigs.addon.keymaps.get('Window')
    if km:
        for kmi in addon_keymapitems:
            km.keymap_items.remove(kmi)
    del addon_keymapitems[:]
