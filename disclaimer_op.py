import logging
import random
import time

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import global_vars, paths, reports, tasks_queue, utils
from .bl_ui_widgets.bl_ui_button import *
from .bl_ui_widgets.bl_ui_drag_panel import *
from .bl_ui_widgets.bl_ui_draw_op import *
from .bl_ui_widgets.bl_ui_image import *
from .daemon import daemon_tasks


bk_logger = logging.getLogger("blenderkit")

disclaimer_counter = 0


class BlenderKitDisclaimerOperator(BL_UI_OT_draw_operator):
    bl_idname = "view3d.blenderkit_disclaimer_widget"
    bl_label = "BlenderKit disclaimer"
    bl_description = "BlenderKit disclaimer"
    bl_options = {"REGISTER"}

    message: StringProperty(
        name="message",
        description="message",
        default="Welcome to BlenderKit!",
        options={"SKIP_SAVE"},
    )

    url: StringProperty(
        name="url",
        description="ULR",
        default="www.blenderkit.com",
        options={"SKIP_SAVE"},
    )

    fadeout_time: IntProperty(
        name="Fadout time",
        description="after how many seconds do fadout",
        default=5,
        min=1,
        max=50,
        options={"SKIP_SAVE"},
    )
    tip: BoolProperty(
        name="Tip",
        description="Message is a tip, not from server",
        default=True,
        options={"SKIP_SAVE"},
    )

    def cancel_press(self, widget):
        self.finish()

    def open_link(self, widget):
        if self.url == "":
            return
        server_url = global_vars.SERVER
        if self.url[:4] != "http":
            self.url = server_url + self.url

        bpy.ops.wm.url_open(url=self.url)

    def __init__(self):
        super().__init__()
        ui_scale = bpy.context.preferences.view.ui_scale

        text_size = int(14 * ui_scale)
        margin = int(10 * ui_scale)
        area_margin = int(50 * ui_scale)
        if self.tip:
            self.bg_color = (0.05, 0.05, 0.05, 0.5)
            self.hover_bg_color = (0.05, 0.05, 0.05, 1.0)
        else:
            self.bg_color = (0.127, 0.034, 1, 0.1)
            self.hover_bg_color = (0.127, 0.034, 1, 1.0)
        self.text_color = (0.9, 0.9, 0.9, 1)

        pix_size = ui_bgl.get_text_size(
            font_id=1,
            text=self.message,
            text_size=text_size,
            dpi=int(bpy.context.preferences.system.dpi / ui_scale),
        )
        self.height = pix_size[1] + 2 * margin
        self.button_size = int(self.height)
        self.width = (
            pix_size[0] + 2 * margin + 2 * self.button_size
        )  # adding logo and cancel button to width

        a = bpy.context.area
        self.panel = BL_UI_Drag_Panel(
            area_margin, a.height - self.height - area_margin, self.width, self.height
        )
        self.panel.bg_color = (0.2, 0.2, 0.2, 0.02)

        self.logo = BL_UI_Image(0, 0, self.button_size, self.button_size)

        self.label = BL_UI_Button(
            self.button_size, 0, pix_size[0] + 2 * margin, self.height
        )
        self.label.text = self.message
        self.label.text_size = text_size
        self.label.text_color = self.text_color

        self.label.bg_color = self.bg_color
        self.label.hover_bg_color = self.hover_bg_color
        self.label.set_mouse_down(self.open_link)

        self.button_close = BL_UI_Button(
            self.width - self.button_size, 0, self.button_size, self.button_size
        )
        self.button_close.bg_color = self.bg_color
        self.button_close.hover_bg_color = self.hover_bg_color
        self.button_close.text = ""
        self.button_close.set_mouse_down(self.cancel_press)

    def on_invoke(self, context, event):
        # Add new widgets here (TODO: perhaps a better, more automated solution?)
        widgets_panel = [self.label, self.button_close, self.logo]
        widgets = [self.panel]

        widgets += widgets_panel

        # assign image to the cancel button
        img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
        img_size = int(self.button_size / 2)
        img_pos = int(img_size / 2)

        self.button_close.set_image(img_fp)
        self.button_close.set_image_size((img_size, img_size))
        self.button_close.set_image_position((img_pos, img_pos))

        img_fp = paths.get_addon_thumbnail_path("blenderkit_logo.png")
        self.logo.set_image(img_fp)
        self.logo.set_image_size((img_size, img_size))
        self.logo.set_image_position((img_pos, img_pos))

        # self.logo.set_image_position(0,0)
        self.init_widgets(context, widgets)
        self.panel.add_widgets(widgets_panel)
        self.start_time = time.time()

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}

        if not context.area:
            # end if area disappears
            self.finish()

        if self.handle_widget_events(event):
            self.start_time = time.time()
            self.reset_colours()
            return {"RUNNING_MODAL"}

        if event.type in {"ESC"}:
            self.finish()

        if event.type == "TIMER":
            run_time = time.time() - self.start_time
            if run_time > self.fadeout_time:
                self.fadeout()

        return {"PASS_THROUGH"}

    def reset_colours(self):
        for widget in self.widgets:
            widget.bg_color = self.bg_color
            widget.hover_bg_color = self.hover_bg_color
            if hasattr(widget, "text_color"):
                widget.text_color = self.text_color

    def fadeout(self):
        """Fade out widget after some time"""
        m = 0.08
        all_zero = True
        for widget in self.widgets:
            # background color
            bc = widget.bg_color
            widget.bg_color = (bc[0], bc[1], bc[2], max(0, bc[3] - m))
            if widget.bg_color[3] > 0:
                # wait for the last to fade out
                all_zero = False
            # text color
            if hasattr(widget, "text_color"):
                tc = widget.text_color
                widget.text_color = (tc[0], tc[1], tc[2], max(0, tc[3] - m))
                if widget.text_color[3] > 0:
                    # wait for the last to fade out
                    all_zero = False

        if all_zero:
            self.finish()

    # Button press handlers
    def button1_press(self, widget):
        print("Button '{0}' is pressed".format(widget.text))


def run_disclaimer_task(message: str, url: str, tip: bool):
    fake_context = utils.get_fake_context(bpy.context)
    bpy.ops.view3d.blenderkit_disclaimer_widget(
        fake_context,
        "INVOKE_DEFAULT",
        message=message,
        url=url,
        fadeout_time=8,
        tip=tip,
    )


def handle_disclaimer_task(task: daemon_tasks.Task):
    """Handles incoming disclaimer task. If there are any results, it shows them in disclaimer popup.
    If the results are empty, it shows random tip in the disclaimer popup.
    """
    global disclaimer_counter
    disclaimer_counter = -1
    if task.status == "finished":
        if task.result == {}:
            return show_random_tip()

        disclaimer = task.result["results"][0]
        preferences = bpy.context.preferences.addons["blenderkit"].preferences
        if preferences.announcements_on_start is False:
            bk_logger.warning(
                f"Online announcements are disabled! Message hidden from GUI: {disclaimer['message']}"
            )
            return show_random_tip()

        tasks_queue.add_task(
            (run_disclaimer_task, (disclaimer["message"], disclaimer["url"], False)),
            wait=0,
        )
        return

    if task.status == "error":
        reports.add_report(
            f"Error downloading disclaimer info: {task.message}", 2, "ERROR"
        )
        return show_random_tip()


def show_random_tip():
    """Shows random tip in the disclaimer popup if tips_on_start are enabled."""
    preferences = bpy.context.preferences.addons["blenderkit"].preferences
    if preferences.tips_on_start is False:
        return
    tip = random.choice(global_vars.TIPS)
    tasks_queue.add_task((run_disclaimer_task, (tip[0], tip[1], True)), wait=0)


def register():
    bpy.utils.register_class(BlenderKitDisclaimerOperator)


def unregister():
    bpy.utils.unregister_class(BlenderKitDisclaimerOperator)


@bpy.app.handlers.persistent
def show_disclaimer_timer():
    """Timer responsible for showing the tip disclaimer after the startup once.
    It waits for daemon to be online, then prompts daemon to get the disclaimers and ends.
    If daemon does not go online in few seconds, it shows the tips instead and ends.
    """
    global disclaimer_counter
    if disclaimer_counter == -1:
        return

    if disclaimer_counter > 2:
        show_random_tip()
        return

    disclaimer_counter = disclaimer_counter + 1
    return disclaimer_counter
