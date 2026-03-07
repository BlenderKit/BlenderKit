"""Video frame extraction for bl_ui_video.

Architecture
------------
* ``VideoDecoder`` runs entirely in a daemon thread so it never blocks
  the Blender UI thread.
* Frames are extracted to a per-video temporary directory as JPEG files
  and sorted by frame number.  The draw side just picks the right filename
  at render time based on wall-clock elapsed time.
* ffmpeg is the only external dependency.  It is looked up in the system
  PATH and in Blender's own ``bin/`` directory so it works on all three
  platforms without bundling anything extra.
* When no ffmpeg is found the decoder enters the ``STATUS_NO_FFMPEG``
  state; the video widget gracefully falls back to a static thumbnail.

Thread safety
-------------
``VideoDecoder.frame_files`` and ``VideoDecoder.status`` are written once
(by the worker thread) and read from the draw thread.  CPython's GIL makes
single-attribute reads/writes atomic for these simple types, so no extra
locking is needed.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from typing import Dict, List, Optional

bk_logger = logging.getLogger(__name__)

# Module-level cache: video path/url → VideoDecoder instance.
_decoders: Dict[str, "VideoDecoder"] = {}
_decoders_lock = threading.Lock()

# Maximum frames to extract (keeps memory and disk usage bounded).
MAX_FRAMES = 200
# Target playback FPS for extracted frames.  The source video may run
# faster; we down-sample to keep extraction quick.
TARGET_FPS = 10.0


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_video_decoder(filepath: str) -> "VideoDecoder":
    """Return (and lazily start) a :class:`VideoDecoder` for a local file."""
    with _decoders_lock:
        if filepath not in _decoders:
            dec = VideoDecoder(filepath)
            dec.start()
            _decoders[filepath] = dec
        return _decoders[filepath]


def request_video(url: str, save_dir: str, filename: str) -> "VideoDecoder":
    """Download *url* to *save_dir/filename* and start decoding it.

    If the file already exists on disk the download step is skipped.
    The decoder is cached by URL so repeated calls return the same object.
    """
    filepath = os.path.join(save_dir, filename)
    with _decoders_lock:
        # Prefer lookup by URL so we don't start two downloads for the same
        # file when the filepath decoder hasn't been registered yet.
        if url in _decoders:
            return _decoders[url]
        if filepath in _decoders:
            dec = _decoders[filepath]
            _decoders[url] = dec
            return dec
        dec = VideoDecoder(filepath, download_url=url)
        dec.start()
        _decoders[url] = dec
        _decoders[filepath] = dec
        return dec


def find_ffmpeg() -> Optional[str]:
    """Return the path to the ffmpeg binary or *None* if not found."""
    import sys

    # 1. System PATH (covers Linux, most macOS/Windows setups).
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    # 2. Next to the Python/Blender executable (Windows ships ffmpeg.exe
    #    alongside blender.exe inside the installation directory).
    blender_bin = os.path.dirname(sys.executable)
    for name in ("ffmpeg", "ffmpeg.exe"):
        candidate = os.path.join(blender_bin, name)
        if os.path.isfile(candidate):
            return candidate

    # 3. Common macOS Homebrew locations.
    for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path):
            return path

    return None


# ---------------------------------------------------------------------------
# VideoDecoder
# ---------------------------------------------------------------------------

class VideoDecoder:
    """Asynchronously download (optional) and extract frames from a video.

    States
    ------
    ``STATUS_PENDING``
        Thread not started yet.
    ``STATUS_DOWNLOADING``
        Fetching the video file from the network.
    ``STATUS_EXTRACTING``
        Running ffmpeg to extract JPEG frames.
    ``STATUS_READY``
        ``frame_files`` is populated; the widget can start animating.
    ``STATUS_ERROR``
        Something went wrong (download failed, ffmpeg crashed, …).
    ``STATUS_NO_FFMPEG``
        ffmpeg binary not found; video playback is unavailable.
    """

    STATUS_PENDING = "pending"
    STATUS_DOWNLOADING = "downloading"
    STATUS_EXTRACTING = "extracting"
    STATUS_READY = "ready"
    STATUS_ERROR = "error"
    STATUS_NO_FFMPEG = "no_ffmpeg"

    def __init__(self, filepath: str, download_url: Optional[str] = None):
        self.filepath = filepath
        self.download_url = download_url

        # Populated once extraction completes.
        self.frames_dir: Optional[str] = None
        self.frame_files: List[str] = []
        self.fps: float = TARGET_FPS

        self.status: str = self.STATUS_PENDING
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self.status == self.STATUS_READY and bool(self.frame_files)

    @property
    def has_error(self) -> bool:
        return self.status in (self.STATUS_ERROR, self.STATUS_NO_FFMPEG)

    def start(self) -> None:
        """Kick off the background worker thread."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="bk_video_decoder")
        self._thread.start()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            # --- optional download ---
            if self.download_url and not os.path.isfile(self.filepath):
                self.status = self.STATUS_DOWNLOADING
                self._download()
                if not os.path.isfile(self.filepath):
                    self.status = self.STATUS_ERROR
                    return

            # --- locate ffmpeg ---
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                bk_logger.warning(
                    "BlenderKit video preview: ffmpeg not found. "
                    "Install ffmpeg and make sure it is on PATH to enable animated thumbnails."
                )
                self.status = self.STATUS_NO_FFMPEG
                return

            # --- extract frames ---
            self.status = self.STATUS_EXTRACTING
            self._extract_frames(ffmpeg)

        except Exception:
            bk_logger.exception("VideoDecoder worker error for %s", self.filepath)
            self.status = self.STATUS_ERROR

    def _download(self) -> None:
        """Download *self.download_url* to *self.filepath*."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        bk_logger.debug("Downloading animated thumbnail: %s", self.download_url)
        try:
            urllib.request.urlretrieve(self.download_url, self.filepath)
        except Exception as exc:
            bk_logger.warning(
                "Failed to download animated thumbnail %s: %s",
                self.download_url,
                exc,
            )
            raise

    def _probe_fps(self, ffprobe: str) -> float:
        """Return the video frame rate using ffprobe, defaulting to TARGET_FPS."""
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    self.filepath,
                ],
                capture_output=True,
                timeout=5,
            )
            output = result.stdout.decode("utf-8", errors="replace").strip()
            if "/" in output:
                num, den = output.split("/", 1)
                fps = float(num) / max(float(den), 1e-6)
                return max(1.0, fps)
        except Exception:
            pass
        return TARGET_FPS

    def _extract_frames(self, ffmpeg: str) -> None:
        """Run ffmpeg to write JPEG frames into a temp directory."""
        # ffprobe is usually shipped alongside ffmpeg.
        ffprobe = shutil.which("ffprobe") or os.path.join(
            os.path.dirname(ffmpeg),
            "ffprobe" if os.name != "nt" else "ffprobe.exe",
        )
        source_fps = self._probe_fps(ffprobe) if os.path.isfile(ffprobe) else TARGET_FPS
        extract_fps = min(source_fps, TARGET_FPS)

        base = os.path.splitext(os.path.basename(self.filepath))[0]
        # Include the PID so parallel Blender sessions don't collide.
        frames_dir = os.path.join(
            tempfile.gettempdir(),
            f"bk_video_{base}_{os.getpid()}",
        )
        os.makedirs(frames_dir, exist_ok=True)

        frame_pattern = os.path.join(frames_dir, "frame_%06d.jpg")

        cmd = [
            ffmpeg,
            "-i", self.filepath,
            "-vf", f"fps={extract_fps}",
            "-frames:v", str(MAX_FRAMES),
            "-q:v", "3",        # JPEG quality (2=best, 31=worst)
            "-loglevel", "error",
            frame_pattern,
        ]

        bk_logger.debug("Extracting video frames: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            bk_logger.warning("ffmpeg timed out for %s", self.filepath)
            self.status = self.STATUS_ERROR
            return

        if result.returncode != 0:
            bk_logger.warning(
                "ffmpeg failed (exit %d) for %s: %s",
                result.returncode,
                self.filepath,
                result.stderr.decode("utf-8", errors="replace")[:200],
            )
            self.status = self.STATUS_ERROR
            return

        frames = sorted(
            os.path.join(frames_dir, f)
            for f in os.listdir(frames_dir)
            if f.startswith("frame_") and f.endswith(".jpg")
        )

        if not frames:
            bk_logger.warning("No frames extracted from %s", self.filepath)
            self.status = self.STATUS_ERROR
            return

        self.frames_dir = frames_dir
        self.frame_files = frames
        self.fps = extract_fps
        self.status = self.STATUS_READY
        bk_logger.debug(
            "Extracted %d frames @ %.1f fps from %s",
            len(frames),
            extract_fps,
            self.filepath,
        )
