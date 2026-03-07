"""Video frame extraction for bl_ui_video.

Architecture
------------
Primary path (in-memory, no disk I/O):
  ``imageio_ffmpeg.read_frames()`` decodes video frames into raw RGBA bytes
  stored in ``VideoDecoder.frame_bytes``.  Each frame is center-cropped to a
  square and scaled to ``FRAME_SIZE × FRAME_SIZE`` by ffmpeg during decode.
  ``BL_UI_Video`` turns these bytes into ``gpu.types.GPUTexture`` objects on
  the first draw and caches them for every subsequent frame/loop — no rebuild
  cost at all after the first pass.

Disk fallback:
  If ``imageio_ffmpeg`` is unavailable (rare, since it auto-installs via pip)
  the decoder falls back to extracting JPEG files into a temp directory.  The
  draw side then uses ``ui_bgl.path_to_gpu_texture()`` which has its own cache.

Binary discovery order (``find_ffmpeg``):
  1. ``imageio_ffmpeg.get_ffmpeg_exe()`` — signed/notarized for all platforms.
  2. System PATH.
  3. Blender's own ``bin/`` (Windows bundled ffmpeg).
  4. Homebrew prefixes (macOS).

Thread safety
-------------
``frame_bytes``, ``frame_files``, and ``status`` are written once by the
worker thread and read from the draw thread.  CPython's GIL makes these
single-attribute assignments atomic.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from typing import Dict, List, Optional

bk_logger = logging.getLogger(__name__)

# Module-level cache: video path → VideoDecoder instance.
_decoders: Dict[str, "VideoDecoder"] = {}
_decoders_lock = threading.Lock()

# Maximum frames to keep in memory / on disk.
MAX_FRAMES = 300
# Output FPS cap.  The source video is never up-sampled above this value.
TARGET_FPS = 24.0


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_video_decoder(filepath: str) -> "VideoDecoder":
    """Return (and lazily start) a :class:`VideoDecoder` for a local file."""
    with _decoders_lock:
        if filepath not in _decoders:
            bk_logger.info("BK video: starting decoder for %s", filepath)
            dec = VideoDecoder(filepath)
            dec.start()
            _decoders[filepath] = dec
        return _decoders[filepath]


def _ensure_imageio_ffmpeg() -> bool:
    """Install imageio-ffmpeg via pip if not already available. Returns True on success."""
    import importlib
    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        return True
    try:
        import sys
        import subprocess as _sp
        bk_logger.info("imageio-ffmpeg not found – installing via pip …")
        _sp.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"],
            check=True,
            capture_output=True,
            timeout=120,
        )
        importlib.invalidate_caches()
        bk_logger.info("imageio-ffmpeg installed successfully.")
        return importlib.util.find_spec("imageio_ffmpeg") is not None
    except Exception as exc:
        bk_logger.warning("Could not install imageio-ffmpeg: %s", exc)
        return False


def find_ffmpeg() -> Optional[str]:
    """Return the path to the ffmpeg binary or *None* if not found.

    Discovery order:
    1. ``imageio_ffmpeg`` – ships signed/notarized binaries for every platform.
       Auto-installed via pip if missing.
    2. System PATH.
    3. Next to the Blender/Python executable (Windows bundled ffmpeg).
    4. Common macOS Homebrew prefixes.
    """
    import sys

    # 1. imageio_ffmpeg bundles signed, notarized binaries – best option on macOS.
    _ensure_imageio_ffmpeg()
    try:
        import imageio_ffmpeg  # type: ignore
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg and os.path.isfile(ffmpeg):
            return ffmpeg
    except Exception:
        pass

    # 2. System PATH.
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    # 3. Next to the Python/Blender executable (Windows ships ffmpeg.exe
    #    alongside blender.exe inside the installation directory).
    blender_bin = os.path.dirname(sys.executable)
    for name in ("ffmpeg", "ffmpeg.exe"):
        candidate = os.path.join(blender_bin, name)
        if os.path.isfile(candidate):
            return candidate

    # 4. Common macOS Homebrew locations.
    for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path):
            return path

    return None


# ---------------------------------------------------------------------------
# VideoDecoder
# ---------------------------------------------------------------------------


class VideoDecoder:
    """Asynchronously extract frames from a local video file.

    Attributes set once by the worker thread, read from the draw thread:

    ``frame_bytes``  – list of raw RGBA bytes per frame (in-memory path).
    ``frame_width``  – frame width in pixels (in-memory path).
    ``frame_height`` – frame height in pixels (in-memory path).
    ``frame_files``  – list of JPEG file paths (disk-fallback path).
    ``fps``          – playback frame rate.
    ``status``       – one of the STATUS_* constants.
    """

    STATUS_PENDING = "pending"
    STATUS_EXTRACTING = "extracting"
    STATUS_READY = "ready"
    STATUS_ERROR = "error"
    STATUS_NO_FFMPEG = "no_ffmpeg"

    def __init__(self, filepath: str):
        self.filepath = filepath

        # In-memory path (primary).
        self.frame_bytes: List[bytes] = []
        self.frame_width: int = 0
        self.frame_height: int = 0

        # Disk fallback path.
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
        return self.status == self.STATUS_READY and bool(
            self.frame_bytes or self.frame_files
        )

    @property
    def has_error(self) -> bool:
        return self.status in (self.STATUS_ERROR, self.STATUS_NO_FFMPEG)

    def start(self) -> None:
        """Kick off the background worker thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="bk_video_decoder"
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            self.status = self.STATUS_EXTRACTING
            bk_logger.info("BK video: extracting frames from %s", self.filepath)

            # Primary: decode into memory via imageio_ffmpeg (fast, no disk I/O).
            if _ensure_imageio_ffmpeg():
                try:
                    self._extract_frames_memory()
                    return
                except Exception as exc:
                    bk_logger.warning(
                        "BK video: in-memory extraction failed for %s (%s), falling back to disk.",
                        self.filepath, exc,
                    )

            # Fallback: write JPEG files and keep file paths.
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                bk_logger.warning(
                    "BK video: ffmpeg not found. "
                    "Install imageio-ffmpeg (pip install imageio-ffmpeg) "
                    "or system ffmpeg to enable animated thumbnails."
                )
                self.status = self.STATUS_NO_FFMPEG
                return
            self._extract_frames_disk(ffmpeg)

        except Exception:
            bk_logger.exception("BK video: worker error for %s", self.filepath)
            self.status = self.STATUS_ERROR

    def _probe_source(self, ffmpeg: str) -> tuple:
        """Return (width, height, fps) from ffmpeg -i stderr probe."""
        import re
        try:
            r = subprocess.run(
                [ffmpeg, "-i", self.filepath],
                capture_output=True, timeout=10,
            )
            text = r.stderr.decode("utf-8", errors="replace")
            # Match e.g. "640x360" or "1920x1080"
            m_size = re.search(r"(\d{2,5})x(\d{2,5})", text)
            # Match e.g. "29.97 fps" or "24 tbr"
            m_fps = re.search(r"([\d.]+)\s+(?:fps|tbr)", text)
            w = int(m_size.group(1)) if m_size else 0
            h = int(m_size.group(2)) if m_size else 0
            fps = float(m_fps.group(1)) if m_fps else TARGET_FPS
            return w, h, fps
        except Exception:
            return 0, 0, TARGET_FPS

    def _extract_frames_memory(self) -> None:
        """Decode frames into raw RGBA bytes via rawvideo pipe (no disk I/O).

        Uses ``imageio_ffmpeg.get_ffmpeg_exe()`` for the binary path, probes
        source dimensions, center-crops to the natural square
        (``min(w, h) × min(w, h)``), and streams raw RGBA frames through
        stdout. No intermediate files are written.
        """
        import imageio_ffmpeg  # type: ignore

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if not ffmpeg or not os.path.isfile(ffmpeg):
            raise RuntimeError("imageio_ffmpeg binary not found")

        src_w, src_h, src_fps = self._probe_source(ffmpeg)
        if src_w <= 0 or src_h <= 0:
            raise RuntimeError(f"Could not probe dimensions of {self.filepath}")

        sq = min(src_w, src_h)
        self.frame_width = sq
        self.frame_height = sq
        self.fps = min(src_fps, TARGET_FPS)

        # Center-crop to square, cap fps, flip for OpenGL's bottom-left origin.
        # \\, is ffmpeg's escaped comma inside a filter expression.
        vf = f"crop=min(iw\\,ih):min(iw\\,ih),fps={self.fps},vflip"
        cmd = [
            ffmpeg,
            "-i", self.filepath,
            "-vf", vf,
            "-frames:v", str(MAX_FRAMES),
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-loglevel", "error",
            "pipe:1",
        ]
        bk_logger.debug("Extracting video frames (memory pipe): %s", " ".join(cmd))

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        frame_size = sq * sq * 4
        frames: List[bytes] = []
        try:
            while len(frames) < MAX_FRAMES:
                chunk = proc.stdout.read(frame_size)
                if len(chunk) < frame_size:
                    break
                frames.append(bytes(chunk))
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            proc.wait(timeout=5)

        if not frames:
            stderr_text = b""
            try:
                stderr_text = proc.stderr.read(500)
            except Exception:
                pass
            raise RuntimeError(
                f"No frames decoded from {self.filepath}: "
                + stderr_text.decode("utf-8", errors="replace")
            )

        self.frame_bytes = frames
        self.status = self.STATUS_READY
        bk_logger.info(
            "BK video: ready – %d frames @ %.1f fps (%dx%d) from %s",
            len(frames), self.fps, sq, sq, self.filepath,
        )

    def _extract_frames_disk(self, ffmpeg: str) -> None:
        """Fallback: extract JPEG frames to a temp directory via subprocess."""
        import re

        # Probe source fps from ffmpeg -i stderr.
        source_fps = TARGET_FPS
        try:
            r = subprocess.run(
                [ffmpeg, "-i", self.filepath],
                capture_output=True, timeout=5,
            )
            m = re.search(
                r"(\d+(?:\.\d+)?)\s+(?:fps|tbr)",
                r.stderr.decode("utf-8", errors="replace"),
            )
            if m:
                source_fps = float(m.group(1))
        except Exception:
            pass
        extract_fps = min(source_fps, TARGET_FPS)

        base = os.path.splitext(os.path.basename(self.filepath))[0]
        frames_dir = os.path.join(
            tempfile.gettempdir(),
            f"bk_video_{base}_{os.getpid()}",
        )
        os.makedirs(frames_dir, exist_ok=True)
        frame_pattern = os.path.join(frames_dir, "frame_%06d.jpg")

        # Center-crop to square (natural square from source dimensions).
        vf = f"crop=min(iw\\,ih):min(iw\\,ih),fps={extract_fps}"
        cmd = [
            ffmpeg, "-i", self.filepath,
            "-vf", vf,
            "-frames:v", str(MAX_FRAMES),
            "-q:v", "2",
            "-loglevel", "error",
            frame_pattern,
        ]
        bk_logger.debug("Extracting video frames (disk): %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            bk_logger.warning("ffmpeg timed out for %s", self.filepath)
            self.status = self.STATUS_ERROR
            return

        if result.returncode != 0:
            bk_logger.warning(
                "ffmpeg failed (exit %d) for %s: %s",
                result.returncode, self.filepath,
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
            "Extracted %d frames @ %.1f fps from %s (disk fallback)",
            len(frames), extract_fps, self.filepath,
        )
