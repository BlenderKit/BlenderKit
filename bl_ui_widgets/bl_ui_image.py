import os

import bpy

from .. import ui_bgl
from .bl_ui_widget import *


class BL_UI_Image(BL_UI_Widget):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)

        self.__state = 0
        self.__image = None
        self.__image_size = (24, 24)
        self.__image_position = (4, 2)

    def set_image_size(self, imgage_size):
        self.__image_size = imgage_size

    def set_image_position(self, image_position):
        self.__image_position = image_position

    def check_image_exists(self):
        # it's possible image was removed and doesn't exist.
        try:
            self.__image
            self.__image.filepath
            # self.__image.pixels
        except:
            self.__image = None

    def set_image(self, rel_filepath):
        # first try to access the image, for cases where it can get removed
        self.check_image_exists()
        try:
            if self.__image is None or self.__image.filepath != rel_filepath:
                imgname = f".{os.path.basename(rel_filepath)}"
                img = bpy.data.images.get(imgname)
                if img is not None:
                    self.__image = img
                else:
                    self.__image = bpy.data.images.load(
                        rel_filepath, check_existing=True
                    )
                    self.__image.name = imgname

                self.__image.gl_load()

            if self.__image and len(self.__image.pixels) == 0:
                self.__image.reload()
                self.__image.gl_load()
        except Exception as e:
            print(e)
            self.__image = None

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

        area_height = self.get_area_height()

        self.shader.bind()

        self.batch_panel.draw(self.shader)

        self.draw_image()

    def draw_image(self):
        if self.__image is not None:
            y_screen_flip = self.get_area_height() - self.y_screen
            off_x, off_y = self.__image_position
            sx, sy = self.__image_size
            ui_bgl.draw_image(
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
