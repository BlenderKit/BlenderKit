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

from ... import ui_bgl
from ...image_utils import IMG
from ..bl_ui_widget import BL_UI_Widget
from .video_decoder import VideoDecoder, get_video_decoder

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

        # GPU texture cache: frame_index → gpu.types.GPUTexture.
        # Textures are created once from raw RGBA bytes on the main (draw)
        # thread and reused on every subsequent draw and loop iteration.
        self._texture_cache: dict = {}
        self._texture_cache_decoder: Optional[VideoDecoder] = None

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

        # Scrubbing: _scrub_frame is set externally (by the asset bar operator) to
        # override the playback position.  None means normal timed playback.
        self._scrub_frame: Optional[int] = None

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
        import os
        bk_logger.info(
            "BK video: set_video(%s) exists=%s", filepath, os.path.exists(filepath)
        )
        new_decoder = get_video_decoder(filepath)
        if new_decoder is not self._decoder:
            self._decoder = new_decoder
            self._play_start = time.time()
            self._batch = None
        bk_logger.info(
            "BK video: decoder status=%s frames=%d",
            new_decoder.status, len(new_decoder.frame_bytes),
        )
        self._ensure_timer()

    def clear_video(self) -> None:
        """Stop video playback; the widget falls back to its static image."""
        self._decoder = None
        self._texture_cache.clear()
        self._texture_cache_decoder = None
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

    def _current_frame_index(self) -> Optional[int]:
        """Return the frame index that should be displayed right now."""
        if self._decoder is None or not self._decoder.is_ready:
            return None
        total = len(self._decoder.frame_bytes) or len(self._decoder.frame_files)
        if not total:
            return None
        if self._scrub_frame is not None:
            return max(0, min(self._scrub_frame, total - 1))
        fps = max(self._decoder.fps, 1.0)
        elapsed = time.time() - self._play_start
        idx = int(elapsed * fps)
        return idx % total if self._loop else min(idx, total - 1)

    def _get_or_create_texture(self, frame_idx: int) -> Optional[gpu.types.GPUTexture]:
        """Return the cached GPU texture for *frame_idx*, creating it if needed.

        Must be called from the main (draw) thread.  The texture is built once
        from the decoder's raw RGBA bytes and cached forever — zero GPU
        allocation cost on subsequent draws and loop iterations.
        """
        # Clear the cache when the active decoder changes.
        if self._texture_cache_decoder is not self._decoder:
            self._texture_cache.clear()
            self._texture_cache_decoder = self._decoder

        if frame_idx in self._texture_cache:
            return self._texture_cache[frame_idx]

        dec = self._decoder
        if dec is None or not dec.frame_bytes or frame_idx >= len(dec.frame_bytes):
            return None

        w, h = dec.frame_width, dec.frame_height
        if w <= 0 or h <= 0:
            bk_logger.warning("BK video: invalid frame dimensions %dx%d", w, h)
            return None
        raw = dec.frame_bytes[frame_idx]
        try:
            import numpy as np
            # gpu.types.GPUTexture(data=) requires a FLOAT buffer; convert UBYTE→float32.
            float_arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 255.0
            buf = gpu.types.Buffer("FLOAT", w * h * 4, float_arr)
            tex = gpu.types.GPUTexture((w, h), format="RGBA32F", data=buf)
            self._texture_cache[frame_idx] = tex
            if len(self._texture_cache) == 1:
                bk_logger.info("BK video: first GPU texture created ok (%dx%d)", w, h)
            return tex
        except Exception:
            bk_logger.warning(
                "BK video: GPU texture creation failed frame=%d (%dx%d)",
                frame_idx, w, h,
                exc_info=True,
            )
            return None

    def _draw_video(self) -> bool:
        """Draw the current video frame.  Returns *True* on success."""
        frame_idx = self._current_frame_index()
        if frame_idx is None:
            if self._decoder is not None:
                bk_logger.debug(
                    "BK video: frame_idx None, decoder status=%s ready=%s",
                    self._decoder.status, self._decoder.is_ready,
                )
            return False

        dec = self._decoder
        if dec is None:
            return False

        # In-memory path: create/reuse a GPU texture from raw RGBA bytes.
        if dec.frame_bytes:
            texture = self._get_or_create_texture(frame_idx)
        else:
            # Disk fallback: load JPEG and let ui_bgl cache the GPU texture.
            if frame_idx >= len(dec.frame_files):
                return False
            texture = ui_bgl.path_to_gpu_texture(dec.frame_files[frame_idx])

        if texture is None:
            return False

        img_x, img_y, sx, sy = self._screen_coords()
        corner_radius = self._corner_radius()

        # Reuse the geometry batch as long as layout hasn't changed.
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
            # Tag all 3D view areas for redraw.  bpy.context.area is None inside
            # timer callbacks, so we iterate window_manager.windows instead.
            try:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "VIEW_3D":
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
            bk_logger.info("BK video: redraw timer registered (interval=%.3fs)", interval)
        except Exception:
            bk_logger.warning("BK video: could not register redraw timer", exc_info=True)
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
    # Mouse handlers
    # ------------------------------------------------------------------

    def mouse_down(self, x, y):
        return False

    def mouse_down_right(self, x, y):
        return False

    def mouse_move(self, x, y):
        return

    def mouse_exit(self, event, x, y):
        return

    def mouse_up(self, x, y):
        return
