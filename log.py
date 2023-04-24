import logging
import os
import sys

import bpy

from . import global_vars


bk_logger = logging.getLogger(__name__)


def get_formatter():
    """Get default formatter for BlenderKit loggers."""
    return logging.Formatter(
        fmt="blenderkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
        datefmt="%H:%M:%S",
    )


def configure_bk_logger():
    """Configure 'blenderkit' logger to which all other logs defined as `bk_logger = logging.getLogger(__name__)` writes.
    Sets it logging level to `global_vars.LOGGING_LEVEL_BLENDERKIT`.
    """
    logging.basicConfig(level=global_vars.LOGGING_LEVEL_BLENDERKIT)
    bk_logger = logging.getLogger("blenderkit")
    bk_logger.propagate = False
    bk_logger.handlers = []

    stream_handler = logging.StreamHandler()
    stream_handler.stream = sys.stdout  # 517
    stream_handler.setFormatter(get_formatter())
    bk_logger.addHandler(stream_handler)


def configure_imported_loggers():
    """Configure loggers for imported modules so they can have different logging level `global_vars.LOGGING_LEVEL_IMPORTED` than main blenderkit logger."""
    urllib3_logger = logging.getLogger("urllib3")
    urllib3_logger.propagate = False
    urllib3_logger.handlers = []

    urllib3_handler = logging.StreamHandler()
    urllib3_handler.stream = sys.stdout  # 517
    urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
    urllib3_handler.setFormatter(get_formatter())
    urllib3_logger.addHandler(urllib3_handler)


def configure_loggers():
    """Configure all loggers for BlenderKit addon. See called functions for details."""
    configure_bk_logger()
    configure_imported_loggers()


### UNUSED - REMOVE IF FIX IS NOT FOUND
def setup_logging_to_file(global_dir: str):
    """Setup logging to file by redirecting all stdout and stderr into dedicated loggers which logs into file and into stream (back to console), also add file handler to `blenderkit` logger.
    The redirection is done by setting `sys.stdout` and `sys.stderr` to custom `LogFile()` object.
    File output is located at `global_dir/blenderkit.log`.
    If the blender runs in background logging to file is skipped.
    """
    if bpy.app.background:
        return

    log_path = os.path.join(global_dir, "blenderkit.log")
    os.makedirs(global_dir, exist_ok=True)

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(get_formatter())

    # has to be done here as before we do not have access to preferences and global_dir
    logging.getLogger("blenderkit").addHandler(file_handler)

    sys.stdout = LogFile("stdout", log_path)
    sys.stderr = LogFile("stderr", log_path)


class LogFile(object):
    """File-like object to log text using the `logging` module. This is used to replace the default `sys.stdout` and `sys.stderr`."""

    def __init__(self, name, log_path):
        formatter = logging.Formatter(
            fmt="%(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
            datefmt="%H:%M:%S",
        )

        file_handler = logging.FileHandler(log_path, mode="w")
        file_handler.setFormatter(formatter)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        self.logger = logging.getLogger(name)
        self.logger.propagate = False
        self.logger.addHandler(file_handler)
        self.logger.addHandler(stream_handler)

    def write(self, msg, level=logging.INFO):
        if msg.strip() == "":
            return
        self.logger.log(level, msg.rstrip(), stacklevel=2)

    def flush(self):
        for handler in self.logger.handlers:
            handler.flush()
