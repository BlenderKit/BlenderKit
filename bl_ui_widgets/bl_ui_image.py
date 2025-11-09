import os
import logging

import gpu

from .. import image_utils, ui_bgl
from .bl_ui_widget import BL_UI_Widget

bk_logger = logging.getLogger(__name__)


class BL_UI_Image(BL_UI_Widget):
    """A simple image widget.

    Used to display bigger thumbnail with additional info,
    while hover over a button.
    """

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)

        self.__state = 0
        self.__image = None
        self.__image_size = (24, 24)
        self.__image_position = (4, 2)

    def set_image_size(self, image_size):
        self.__image_size = image_size

    def set_image_position(self, image_position):
        self.__image_position = image_position

    def check_image_exists(self):
        # it's possible image was removed and doesn't exist.
        try:
            self.__image
            self.__image.filepath
        except Exception as e:
            self.__image = None
        return None

    def set_image(self, rel_filepath):
        # first try to access the image, for cases where it can get removed
        self.check_image_exists()
        try:
            if self.__image is None or self.__image.filepath != rel_filepath:
                imgname = f".{os.path.basename(rel_filepath)}"
                self.__image = image_utils.IMG(name=imgname, filepath=rel_filepath)
        except Exception as e:
            bk_logger.exception("BL_UI_BUTTON: exception in set_image(): %s", e)
            self.__image = None

    def set_image_colorspace(self, colorspace: str = ""):
        image_utils.set_colorspace(self.__image, colorspace)

    def get_image_path(self):
        self.check_image_exists()
        if self.__image is None:
            return None
        return self.__image.filepath

    def update(self, x, y):
        super().update(x, y)

    def draw(self):
        if not self._is_visible:
            return
        gpu.state.blend_set("ALPHA")

        self.shader.bind()
        self.batch_panel.draw(self.shader)

        self.draw_image()

    def draw_image(self):
        if self.__image is not None:
            y_screen_flip = self.get_area_height() - self.y_screen
            off_x, off_y = self.__image_position
            sx, sy = self.__image_size
            ui_bgl.draw_image_runtime(
                self.x_screen + off_x,
                y_screen_flip - off_y - sy,
                sx,
                sy,
                self.__image,
                1.0,
                crop=(0, 0, 1, 1),
                batch=None,
            )
            return True

        return False

    def set_mouse_down(self, mouse_down_func):
        self.mouse_down_func = mouse_down_func

    def mouse_down(self, x, y):
        return False

    def mouse_move(self, x, y):
        return

    def mouse_up(self, x, y):
        return
