import logging

from . import global_vars


def configure_bk_logger():
  logging.basicConfig(level=global_vars.LOGGING_LEVEL_BLENDERKIT)
  bk_logger = logging.getLogger("blenderkit")
  bk_logger.propagate = False
  bk_log_handler = logging.StreamHandler()
  bk_log_handler.setLevel(global_vars.LOGGING_LEVEL_BLENDERKIT)
  bk_logger.addHandler(bk_log_handler)

def configure_imported_loggers():
  urllib3_logger = logging.getLogger("urllib3")
  urllib3_logger.propagate = False
  urllib3_handler = logging.StreamHandler()
  urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
  urllib3_logger.addHandler(urllib3_handler)

def configure_loggers():
  configure_bk_logger()
  configure_imported_loggers()
