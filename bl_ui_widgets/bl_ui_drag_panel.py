from .bl_ui_widget import BL_UI_Widget


class BL_UI_Drag_Panel(BL_UI_Widget):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.is_drag = False
        self.drag_enabled = True
        self.resize_enabled = False
        self.resize_edges = set()
        self.resize_handle_size = 0
        self.resize_threshold_px = 0
        self.is_resize = False
        self.resize_press_active = False
        self.resize_hover_edge = None
        self.active_resize_edge = None
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.on_resize_begin = None
        self.on_resize_update = None
        self.on_resize_end = None
        self.on_resize_click = None
        self.on_resize_hover = None
        self.widgets = []

    def set_location(self, x, y):
        super().set_location(x, y)
        self.layout_widgets()

    def add_widget(self, widget):
        self.widgets.append(widget)

    def add_widgets(self, widgets):
        self.widgets = widgets
        self.layout_widgets()

    def remove_widgets(self):
        self.widgets = []
        self.update(self.x_screen, self.y_screen)

    def remove_widget(self, widget):
        if widget in self.widgets:
            self.widgets.remove(widget)
        self.layout_widgets()

    def layout_widgets(self):
        for widget in self.widgets:
            widget.update(self.x_screen + widget.x, self.y_screen + widget.y)

    def update(self, x, y):
        super().update(x - self.drag_offset_x, y + self.drag_offset_y)

    def child_widget_focused(self, x, y):
        for widget in self.widgets:
            if widget.is_in_rect(x, y):
                return True
        return False

    def _call_resize_callback(self, callback_name, *args):
        callback = getattr(self, callback_name, None)
        if callable(callback):
            callback(self, *args)

    def _resize_threshold_reached(self, x, y):
        return (
            abs(x - self.resize_start_x) >= self.resize_threshold_px
            or abs(y - self.resize_start_y) >= self.resize_threshold_px
        )

    def _edge_hit_test(self, x, y):
        if (
            not self.resize_enabled
            or self.resize_handle_size <= 0
            or self.child_widget_focused(x, y)
        ):
            return None

        area_height = self.get_area_height()
        top = area_height - self.y_screen
        bottom = top - self.height
        left = self.x_screen
        right = left + self.width
        handle_size = self.resize_handle_size

        if "bottom" in self.resize_edges:
            if left <= x <= right and bottom >= y >= bottom - handle_size:
                return "bottom"
        if "top" in self.resize_edges:
            if left <= x <= right and top + handle_size >= y >= top:
                return "top"
        if "left" in self.resize_edges:
            if left >= x >= left - handle_size and top >= y >= bottom:
                return "left"
        if "right" in self.resize_edges:
            if right <= x <= right + handle_size and top >= y >= bottom:
                return "right"
        return None

    def _update_resize_hover(self, x, y):
        if self.resize_press_active or self.is_resize:
            return

        hover_edge = self._edge_hit_test(x, y)
        if hover_edge == self.resize_hover_edge:
            return

        if self.resize_hover_edge is not None:
            self._call_resize_callback("on_resize_hover", self.resize_hover_edge, False)
        self.resize_hover_edge = hover_edge
        if hover_edge is not None:
            self._call_resize_callback("on_resize_hover", hover_edge, True)

    def mouse_down(self, x, y):
        resize_edge = self._edge_hit_test(x, y)
        if resize_edge is not None:
            self.resize_press_active = True
            self.active_resize_edge = resize_edge
            self.resize_start_x = x
            self.resize_start_y = y
            return True

        if not self.drag_enabled:
            return False
        if self.child_widget_focused(x, y):
            return False

        if self.is_in_rect(x, y):
            height = self.get_area_height()
            self.is_drag = True
            self.drag_offset_x = x - self.x_screen
            self.drag_offset_y = y - (height - self.y_screen)
            return True

        return False

    def mouse_move(self, x, y):
        self._update_resize_hover(x, y)

        if self.resize_press_active and not self.is_resize:
            if self._resize_threshold_reached(x, y):
                self.is_resize = True
                self._call_resize_callback(
                    "on_resize_begin",
                    self.active_resize_edge,
                    self.resize_start_x,
                    self.resize_start_y,
                )
                self._call_resize_callback(
                    "on_resize_update", self.active_resize_edge, x, y
                )
            return

        if self.is_resize:
            self._call_resize_callback(
                "on_resize_update", self.active_resize_edge, x, y
            )
            return

        if self.drag_enabled and self.is_drag:
            height = self.get_area_height()
            self.update(x, height - y)
            self.layout_widgets()

    def mouse_up(self, x, y):
        if self.resize_press_active or self.is_resize:
            active_edge = self.active_resize_edge
            hovering = self._edge_hit_test(x, y) == active_edge
            if self.is_resize:
                self._call_resize_callback("on_resize_end", active_edge, x, y, hovering)
            elif hovering:
                self._call_resize_callback("on_resize_click", active_edge, x, y)

            self.resize_press_active = False
            self.is_resize = False
            self.active_resize_edge = None
            self.resize_hover_edge = active_edge if hovering else None

        self.is_drag = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
