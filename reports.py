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

from inspect import getframeinfo, stack
from logging import getLogger
from os.path import basename
from time import time

import bpy

from . import asset_bar_op, colors, ui_bgl, utils


bk_logger = getLogger(__name__)
reports = []


# check for same reports and just make them longer by the timeout.
def add_report(text='', timeout=5, type='INFO', details=''):
    """Add text report to GUI. Function checks for same reports and make them longer by the timeout.
    Also log the text and details into the console with levels: ERROR=RED, INFO=GREEN.
    """
    global reports
    text = text.strip()
    full_message = text
    details = details.strip()
    if details != '': 
        full_message = f'{text} {details}'

    if type == 'ERROR':
        caller = getframeinfo(stack()[1][0])
        text = f'{text} [{basename(caller.filename)}:{caller.lineno}]'
        bk_logger.error(full_message, stacklevel=2)
        color = colors.RED
    elif type == 'INFO':
        bk_logger.info(full_message, stacklevel=2)
        color = colors.GREEN

    # check for same reports and just make them longer by the timeout.
    for old_report in reports:
        if old_report.text == text:
            old_report.timeout = old_report.age + timeout
            return
    report = Report(text=text, timeout=timeout, color=color)
    reports.append(report)


class Report():
    def __init__(self, text='', timeout=5, color=(.5, 1, .5, 1)):
        self.text = text
        self.timeout = timeout
        self.start_time = time()
        self.color = color
        self.draw_color = color
        self.age = 0

        self.active_area_pointer = asset_bar_op.active_area_pointer
        if asset_bar_op.active_area_pointer == 0:
            w, a, r = utils.get_largest_area(area_type='VIEW_3D')
            if a is not None:
                self.active_area_pointer = a.as_pointer()

    def fade(self):
        fade_time = 1
        self.age = time() - self.start_time
        if self.age + fade_time > self.timeout:
            alpha_multiplier = (self.timeout - self.age) / fade_time
            self.draw_color = (self.color[0], self.color[1], self.color[2], self.color[3] * alpha_multiplier)
            if self.age > self.timeout:
                global reports
                try:
                    reports.remove(self)
                except Exception as e:
                    bk_logger.warning(f'exception in fading: {e}')

    def draw(self, x, y):
        if (bpy.context.area is not None and bpy.context.area.as_pointer() == self.active_area_pointer):
            ui_bgl.draw_text(self.text, x, y + 8, 16, self.draw_color)
