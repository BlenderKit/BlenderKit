"""Video playback sub-package for bl_ui_widgets.

Provides lightweight, ffmpeg-backed video playback suitable for use in
Blender's modal operators and BGL/GPU draw callbacks.

Main entry points
-----------------
``BL_UI_Video``
    Drop-in replacement for :class:`bl_ui_widgets.bl_ui_image.BL_UI_Image`
    that can additionally display animated video previews (WebM, MP4, …).

``get_video_decoder(filepath)``
    Low-level function that returns the :class:`VideoDecoder` for a given
    local video file, starting frame extraction the first time it is called.
"""

from .bl_ui_video import BL_UI_Video
from .video_decoder import get_video_decoder

__all__ = ["BL_UI_Video", "get_video_decoder"]
