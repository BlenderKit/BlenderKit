import logging
import sys
import os


from . import global_vars


def get_formatter():
  return logging.Formatter(fmt='blenderkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]',datefmt='%H:%M:%S')


def configure_terminal_logger():
  terminal_logger = logging.getLogger("bk_terminal_logger")
  terminal_logger.propagate = False
  stream_handler = logging.StreamHandler()
  terminal_logger.addHandler(stream_handler)


def configure_bk_logger():
  logging.basicConfig(level=global_vars.LOGGING_LEVEL_BLENDERKIT)
  bk_logger = logging.getLogger("blenderkit")
  bk_logger.propagate = False

  stream_handler = logging.StreamHandler()
  stream_handler.setFormatter(get_formatter())
  bk_logger.addHandler(stream_handler)


def configure_imported_loggers():
  urllib3_logger = logging.getLogger("urllib3")
  urllib3_logger.propagate = False

  urllib3_handler = logging.StreamHandler()
  urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
  urllib3_handler.setFormatter(get_formatter())
  urllib3_logger.addHandler(urllib3_handler)


def add_file_logger(global_dir: str):
  log_path = os.path.join(global_dir, 'blenderkit.log')

  bk_logger = logging.getLogger('blenderkit')
  file_handler = logging.FileHandler(log_path)
  file_handler.setFormatter(get_formatter())
  bk_logger.addHandler(file_handler)

  sys.stdout = LogFile('stdout', log_path)
  sys.stderr = LogFile('stderr', log_path)
  return


class LogFile(object):
  """File-like object to log text using the `logging` module."""

  def __init__(self, name, log_path):
    handler = logging.FileHandler(log_path, mode='w')
    formatter = logging.Formatter(fmt='%(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]', datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    
    self.logger = logging.getLogger(name)
    self.logger.propagate = False
    self.logger.addHandler(handler)

  def write(self, msg, level = logging.INFO):
    if msg.strip() == "":
      return
    self.logger.log(level, msg.rstrip())
    #logging.getLogger("bk_terminal_logger").log(level, msg)

  def flush(self):
    for handler in self.logger.handlers:
      handler.flush()


def configure_loggers():
  configure_bk_logger()
  configure_imported_loggers()
  configure_terminal_logger()
