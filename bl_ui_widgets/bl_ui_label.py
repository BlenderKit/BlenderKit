import blf
import bpy

from .bl_ui_widget import BL_UI_Widget


class BL_UI_Label(BL_UI_Widget):
    """A simple text label widget."""

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

    @property
    def text_color(self):
        return self._text_color

    @text_color.setter
    def text_color(self, value):
        if value != self._text_color:
            bpy.context.region.tag_redraw()
        self._text_color = value

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        if value != self._text:
            bpy.context.region.tag_redraw()
        self._text = value

    @property
    def text_size(self):
        return self._text_size

    @text_size.setter
    def text_size(self, value):
        if value != self._text_size:
            bpy.context.region.tag_redraw()
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
        if not self.multiline:
            blf.position(font_id, x, y, 0)

            blf.color(font_id, r, g, b, a)

            blf.draw(font_id, self._text)
        else:
            lines = self._text.split("\n")
            for line in lines:
                blf.position(font_id, x, y, 0)
                blf.color(font_id, r, g, b, a)
                blf.draw(font_id, line)
                y -= self.row_height


class BL_UI_DuoLabel(BL_UI_Widget):
    """A label with two text fields, A and B."""

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)

        self._text_a_color = (1.0, 1.0, 1.0, 1.0)
        self._text_a = "Label"

        self._text_b_color = (1.0, 1.0, 1.0, 1.0)
        self._text_b = ""

        self._text_size = 16
        self._halign = "LEFT"
        self._valign = "TOP"
        # multiline
        self.multiline = False
        self.row_height = 20
        # strikethrough
        self.strikethrough = False

    @property
    def text_a_color(self):
        return self._text_a_color

    @text_a_color.setter
    def text_a_color(self, value):
        if value != self._text_a_color:
            bpy.context.region.tag_redraw()
        self._text_a_color = value

    @property
    def text_a(self):
        return self._text_a

    @text_a.setter
    def text_a(self, value):
        if value != self._text_a:
            bpy.context.region.tag_redraw()
        self._text_a = value

    @property
    def text_b_color(self):
        return self._text_b_color

    @text_b_color.setter
    def text_b_color(self, value):
        if value != self._text_b_color:
            bpy.context.region.tag_redraw()
        self._text_b_color = value

    @property
    def text_b(self):
        return self._text_b

    @text_b.setter
    def text_b(self, value):
        if value != self._text_b:
            bpy.context.region.tag_redraw()
        self._text_b = value

    @property
    def text_size(self):
        return self._text_size

    @text_size.setter
    def text_size(self, value):
        if value != self._text_size:
            bpy.context.region.tag_redraw()
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

        textpos_y = area_height - self.y_screen - self.height

        # draw texts
        cursor_x = self.x_screen
        blocks = [
            (self._text_a, self._text_a_color),
            (self._text_b, self._text_b_color),
        ]
        for text, color in blocks:
            if not text:
                continue
            r, g, b, a = color

            x = cursor_x if self._halign == "LEFT" else self.x_screen
            y = textpos_y
            width, height = blf.dimensions(font_id, text)
            if self._halign != "LEFT":
                if self._halign == "RIGHT":
                    x -= width
                elif self._halign == "CENTER":
                    x -= width // 2
            if self._valign == "CENTER":
                y -= height // 2
            # bottom could be here but there's no reason for it
            if not self.multiline:
                blf.position(font_id, x, y, 0)

                blf.color(font_id, r, g, b, a)

                blf.draw(font_id, text)
            else:
                lines = text.split("\n")
                for line in lines:
                    blf.position(font_id, x, y, 0)
                    blf.color(font_id, r, g, b, a)
                    blf.draw(font_id, line)
                    y -= self.row_height

            if self._halign == "LEFT" and not self.multiline:
                cursor_x = x + width + 4  # small gap between parts
