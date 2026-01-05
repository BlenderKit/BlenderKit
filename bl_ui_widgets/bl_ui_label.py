import blf
import bpy
import gpu

from typing import Tuple, Union

from gpu_extras.batch import batch_for_shader

from .bl_ui_widget import BL_UI_Widget, region_redraw


class BL_UI_Label(BL_UI_Widget):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)

        self._text_color = (1.0, 1.0, 1.0, 1.0)
        self._text = "Label"
        self._text_size = 16
        self._halign = "LEFT"
        self._valign = "TOP"
        # multiline
        self.multiline = False
        self.row_height = 20

        self.padding: Union[Tuple[float, float], float] = 0
        self.background = False

    @property
    def text_color(self):
        return self._text_color

    @text_color.setter
    def text_color(self, value):
        if value != self._text_color:
            region_redraw()
        self._text_color = value

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        if value != self._text:
            region_redraw()
        self._text = value

    @property
    def text_size(self):
        return self._text_size

    @text_size.setter
    def text_size(self, value):
        if value != self._text_size:
            region_redraw()
        self._text_size = value

    def is_in_rect(self, x, y):
        return False

    def draw(self):
        if not self._is_visible:
            return

        area_height = self.get_area_height()

        font_id = 1
        if bpy.app.version < (4, 0, 0):
            blf.size(font_id, self._text_size, 72)
        else:
            blf.size(font_id, self._text_size)
        lines = self._text.split("\n") if self.multiline else [self._text]
        if not lines:
            return

        default_line_height = self.row_height if self.multiline else self._text_size
        line_metrics = []
        max_line_width = 0.0
        total_height = 0.0

        for line in lines:
            width, height = blf.dimensions(font_id, line)
            if height == 0:
                height = default_line_height
            line_height = (
                self.row_height if self.multiline else max(height, self._text_size)
            )
            if line_height == 0:
                line_height = default_line_height
            line_metrics.append((line, width, line_height))
            max_line_width = max(max_line_width, width)
            total_height += line_height

        if not line_metrics:
            return

        textpos_y = area_height - self.y_screen - self.height

        r, g, b, a = self._text_color
        x = self.x_screen
        y = textpos_y
        if self._halign != "LEFT":
            width, height = blf.dimensions(font_id, self._text)
            if self._halign == "RIGHT":
                x -= width
            elif self._halign == "CENTER":
                x -= width // 2
            if self._valign == "CENTER":
                y -= height // 2
            # bottom could be here but there's no reason for it

        first_line_height = line_metrics[0][2]

        if self.background and (max_line_width > 0 or total_height > 0):
            pad_x, pad_y = self._padding_tuple()
            text_top = y + first_line_height
            text_bottom = text_top - total_height
            left = x - pad_x
            right = x + max_line_width + pad_x
            top = text_top + pad_y
            bottom = text_bottom - pad_y
            self._draw_background_rect(left, right, bottom, top)

        current_y = y
        if not self.multiline:
            blf.position(font_id, x, current_y, 0)
            blf.color(font_id, r, g, b, a)
            blf.draw(font_id, self._text)
        else:
            for line, _, line_height in line_metrics:
                blf.position(font_id, x, current_y, 0)
                blf.color(font_id, r, g, b, a)
                blf.draw(font_id, line)
                current_y -= line_height

    def _padding_tuple(self) -> Tuple[float, float]:
        pad = self.padding
        if isinstance(pad, (list, tuple)):
            if len(pad) == 0:
                return (0.0, 0.0)
            if len(pad) == 1:
                value = float(pad[0])
                return (value, value)
            return (float(pad[0]), float(pad[1]))
        value = float(pad)
        return (value, value)

    def _draw_background_rect(self, left, right, bottom, top):
        vertices = (
            (left, top),
            (left, bottom),
            (right, bottom),
            (right, top),
        )
        indices = ((0, 1, 2), (0, 2, 3))
        gpu.state.blend_set("ALPHA")
        self.shader.bind()
        self.shader.uniform_float("color", self._bg_color)
        batch = batch_for_shader(
            self.shader, "TRIS", {"pos": vertices}, indices=indices
        )
        batch.draw(self.shader)
