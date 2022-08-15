import logging

from . import global_vars


def configure_bk_logger():
  bk_log_formatter = logging.Formatter(fmt='blenderkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]',datefmt='%H:%M:%S')
  
  logging.basicConfig(level=global_vars.LOGGING_LEVEL_BLENDERKIT)
  bk_logger = logging.getLogger("blenderkit")
  bk_logger.propagate = False

  bk_log_handler = logging.StreamHandler()
  bk_log_handler.setFormatter(bk_log_formatter)
  bk_logger.addHandler(bk_log_handler)

def configure_imported_loggers():
  urllib3_formatter = logging.Formatter(fmt='blenderkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]',datefmt='%H:%M:%S')

  urllib3_logger = logging.getLogger("urllib3")
  urllib3_logger.propagate = False
  urllib3_handler = logging.StreamHandler()
  urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
  urllib3_handler.setFormatter(urllib3_formatter)
  urllib3_logger.addHandler(urllib3_handler)

def configure_loggers():
  configure_bk_logger()
  configure_imported_loggers()
