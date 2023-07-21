import logging
import re
import sys

from . import global_vars


bk_logger = logging.getLogger(__name__)


class SensitiveFormatter(logging.Formatter):
    """Formatter that masks API key tokens. Replace temporary tokens with *** and permanent tokens with *****."""

    def format(self, record):
        msg = logging.Formatter.format(self, record)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{30}\b(?=["\'\s])', r"***", msg)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{40}\b(?=["\'\s])', r"*****", msg)
        return msg


def get_sensitive_formatter():
    """Get default sensitive formatter for BlenderKit loggers."""
    return SensitiveFormatter(
        fmt="blenderkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
        datefmt="%H:%M:%S",
    )


def configure_bk_logger():
    """Configure 'blenderkit' logger to which all other logs defined as `bk_logger = logging.getLogger(__name__)` writes.
    Sets it logging level to `global_vars.LOGGING_LEVEL_BLENDERKIT`.
    """
    bk_logger = logging.getLogger("blenderkit")
    bk_logger.setLevel(global_vars.LOGGING_LEVEL_BLENDERKIT)
    bk_logger.propagate = False
    bk_logger.handlers = []

    stream_handler = logging.StreamHandler()
    stream_handler.stream = sys.stdout  # 517
    stream_handler.setFormatter(get_sensitive_formatter())
    bk_logger.addHandler(stream_handler)


def configure_imported_loggers():
    """Configure loggers for imported modules so they can have different logging level `global_vars.LOGGING_LEVEL_IMPORTED` than main blenderkit logger."""
    urllib3_logger = logging.getLogger("urllib3")
    urllib3_logger.propagate = False
    urllib3_logger.handlers = []

    urllib3_handler = logging.StreamHandler()
    urllib3_handler.stream = sys.stdout  # 517
    urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
    urllib3_handler.setFormatter(get_sensitive_formatter())
    urllib3_logger.addHandler(urllib3_handler)


def configure_loggers():
    """Configure all loggers for BlenderKit addon. See called functions for details."""
    configure_bk_logger()
    configure_imported_loggers()
