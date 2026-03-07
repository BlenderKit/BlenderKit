"""BL_UI_Video – animated video preview widget.

This widget is a drop-in replacement for :class:`bl_ui_image.BL_UI_Image`.
It exposes the full ``BL_UI_Image`` API (``set_image``, ``set_image_size``,
``set_image_position``, ``get_image_path``, …) so callers can switch to it
transparently, and adds a ``set_video`` / ``set_video_from_url`` pair that
triggers asynchronous frame extraction and starts looped playback.

Playback timing
---------------
The current frame is computed from wall-clock elapsed time so that the
animation advances even when Blender only delivers sparse draw events.
A ``bpy.app.timers`` callback is registered whenever the widget is visible
and a video is ready; this forces the active area to redraw at approximately
the video's native frame rate.

Fallback behaviour
------------------
If no video is set, if ffmpeg cannot be found, or while frames are still
being extracted, the widget renders the static fallback image exactly like
``BL_UI_Image`` would.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import bpy
import gpu

from .. import ui_bgl
from ..image_utils import IMG
from ..bl_ui_widget import BL_UI_Widget
from .video_decoder import VideoDecoder, get_video_decoder, request_video

bk_logger = logging.getLogger(__name__)


class BL_UI_Video(BL_UI_Widget):
    """Animated video preview widget compatible with BL_UI_Image's API."""

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.bg_color = (1.0, 1.0, 1.0, 1.0)

        # Video state
        self._decoder: Optional[VideoDecoder] = None
        self._play_start: float = 0.0
        self._loop: bool = True

        # Static fallback image (same as BL_UI_Image)
        self._static_image: Optional[IMG] = None

        # Layout – mirrors BL_UI_Image
        self._image_size: tuple = (24, 24)
        self._image_position: tuple = (0, 0)

        # Cached geometry batch (invalidated when size/position changes)
        self._batch = None
        self._batch_geom_key: tuple = ()

        # bpy.app.timers callback reference (stored to allow un-registration)
        self._timer_fn = None

    # ------------------------------------------------------------------
    # BL_UI_Image-compatible API
    # ------------------------------------------------------------------

    def set_image_size(self, image_size: tuple) -> None:
        if self._image_size != image_size:
            self._batch = None  # geometry changed → rebuild
        self._image_size = image_size

    def set_image_position(self, image_position: tuple) -> None:
        self._image_position = image_position

    def set_image(self, rel_filepath: str) -> None:
        """Set (or replace) the static fallback image."""
        import os
        self.check_image_exists()
        try:
            if (
                self._static_image is None
                or self._static_image.filepath != rel_filepath
            ):
                imgname = f".{os.path.basename(rel_filepath)}"
                self._static_image = IMG(name=imgname, filepath=rel_filepath)
        except Exception:
            bk_logger.exception("BL_UI_Video.set_image error")
            self._static_image = None

    def set_image_colorspace(self, colorspace: str = "") -> None:
        """No-op – kept for API compatibility."""

    def get_image_path(self) -> Optional[str]:
        self.check_image_exists()
        if self._static_image is None:
            return None
        return self._static_image.filepath

    def check_image_exists(self) -> None:
        """Validate the cached static image; clear if stale."""
        try:
            if self._static_image is not None:
                _ = self._static_image.filepath
        except Exception:
            self._static_image = None

    def update(self, x, y):
        super().update(x, y)
        self._batch = None  # position changed → rebuild batch

    # ------------------------------------------------------------------
    # Video API
    # ------------------------------------------------------------------

    def set_video(self, filepath: str) -> None:
        """Start decoding *filepath* and begin looped playback."""
        new_decoder = get_video_decoder(filepath)
        if new_decoder is not self._decoder:
            self._decoder = new_decoder
            self._play_start = time.time()
            self._batch = None
        self._ensure_timer()

    def set_video_from_url(
        self, url: str, save_dir: str, filename: str
    ) -> None:
        """Download *url* → *save_dir/filename*, then start playback."""
        new_decoder = request_video(url, save_dir, filename)
        if new_decoder is not self._decoder:
            self._decoder = new_decoder
            self._play_start = time.time()
            self._batch = None
        self._ensure_timer()

    def clear_video(self) -> None:
        """Stop video playback; the widget falls back to its static image."""
        self._decoder = None
        self._stop_timer()

    def reset_playback(self) -> None:
        """Restart animation from the first frame."""
        self._play_start = time.time()

    def has_video(self) -> bool:
        """Return *True* while a video decoder is attached (any state)."""
        return self._decoder is not None

    def video_is_ready(self) -> bool:
        """Return *True* once frames are available for playback."""
        return self._decoder is not None and self._decoder.is_ready

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self) -> None:
        if not self._is_visible:
            return

        gpu.state.blend_set("ALPHA")

        if self._draw_video():
            return
        if self._draw_static_image():
            return

        # Nothing to draw → plain background
        if self.use_rounded_background:
            area_height = self.get_area_height()
            rect_y = area_height - self.y_screen - self.height
            self.draw_background_rect(
                self.x_screen,
                rect_y,
                self.width,
                self.height,
                self._bg_color,
                force=True,
                fill_color_override=self._bg_color,
            )

    # ------------------------------------------------------------------
    # Internal draw helpers
    # ------------------------------------------------------------------

    def _screen_coords(self) -> tuple:
        """Return (img_x, img_y, sx, sy) in screen-space pixels."""
        area_height = self.get_area_height()
        off_x, off_y = self._image_position
        sx, sy = self._image_size
        img_x = self.x_screen + off_x
        img_y = area_height - self.y_screen - off_y - sy
        return img_x, img_y, sx, sy

    def _corner_radius(self):
        if self.has_background_corner_radius_override():
            return self.background_corner_radius
        return None

    def _current_frame_path(self) -> Optional[str]:
        """Compute which frame file should be displayed right now."""
        if self._decoder is None or not self._decoder.is_ready:
            return None
        frames = self._decoder.frame_files
        if not frames:
            return None
        fps = max(self._decoder.fps, 1.0)
        elapsed = time.time() - self._play_start
        frame_idx = int(elapsed * fps)
        if self._loop:
            frame_idx %= len(frames)
        else:
            frame_idx = min(frame_idx, len(frames) - 1)
        return frames[frame_idx]

    def _draw_video(self) -> bool:
        """Draw the current video frame.  Returns *True* on success."""
        frame_path = self._current_frame_path()
        if frame_path is None:
            return False

        texture = ui_bgl.path_to_gpu_texture(frame_path)
        if texture is None:
            return False

        img_x, img_y, sx, sy = self._screen_coords()
        corner_radius = self._corner_radius()

        # Reuse the batch as long as the geometry hasn't changed.
        geom_key = (img_x, img_y, sx, sy, repr(corner_radius))
        if geom_key != self._batch_geom_key:
            self._batch = None
            self._batch_geom_key = geom_key

        self._batch = ui_bgl.draw_texture_at(
            img_x, img_y, sx, sy,
            texture,
            corner_radius=corner_radius,
            corner_segments=12,
            batch=self._batch,
        )
        return self._batch is not None

    def _draw_static_image(self) -> bool:
        """Draw the static fallback image.  Returns *True* on success."""
        if self._static_image is None:
            return False

        img_x, img_y, sx, sy = self._screen_coords()

        if self.use_rounded_background:
            fill_color = self.bg_color or (1.0, 1.0, 1.0, 1.0)
            self.draw_background_rect(
                img_x, img_y, sx, sy,
                fill_color,
                force=True,
                fill_color_override=fill_color,
            )

        ui_bgl.draw_image_runtime(
            img_x, img_y, sx, sy,
            self._static_image,
            1.0,
            crop=(0, 0, 1, 1),
            batch=None,
            corner_radius=self._corner_radius(),
            corner_segments=12,
        )
        return True

    # ------------------------------------------------------------------
    # Redraw timer
    # ------------------------------------------------------------------

    def _ensure_timer(self) -> None:
        """Register a bpy.app.timers callback to keep the animation smooth."""
        if self._timer_fn is not None:
            return  # already running
        # Use a closure so that the reference stays alive as long as the
        # widget is alive and the timer is registered.
        widget_ref = self  # captured in closure (avoid ref cycle via weak)

        def _callback():
            w = widget_ref
            if not w._is_visible or w._decoder is None:
                w._timer_fn = None
                return None  # unregister
            # Tag the active region for redraw.
            try:
                area = bpy.context.area
                if area is not None:
                    area.tag_redraw()
            except Exception:
                pass
            fps = getattr(w._decoder, "fps", 10.0) if w._decoder else 10.0
            return max(1.0 / max(fps, 1.0), 0.033)  # ≥ 30 ms

        self._timer_fn = _callback
        try:
            interval = 1.0 / max(
                getattr(self._decoder, "fps", 10.0) if self._decoder else 10.0,
                1.0,
            )
            bpy.app.timers.register(self._timer_fn, first_interval=interval)
        except Exception:
            bk_logger.debug("Could not register video redraw timer", exc_info=True)
            self._timer_fn = None

    def _stop_timer(self) -> None:
        if self._timer_fn is None:
            return
        try:
            if bpy.app.timers.is_registered(self._timer_fn):
                bpy.app.timers.unregister(self._timer_fn)
        except Exception:
            pass
        self._timer_fn = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __del__(self):
        self._stop_timer()

    # ------------------------------------------------------------------
    # Mouse handlers (passthrough – same as BL_UI_Image)
    # ------------------------------------------------------------------

    def mouse_down(self, x, y):
        return False

    def mouse_move(self, x, y):
        return

    def mouse_up(self, x, y):
        return
