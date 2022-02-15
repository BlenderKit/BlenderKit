"""Holds global variables used by modules of daemon server."""

import json
import time


class Task():
  """Holds all information needed for a task."""

  def __init__(self, data: dict, task_id: str, app_id: str, task_type: str, message: str = ""):
    self.data = data
    self.task_id = task_id
    self.app_id = app_id
    self.task_type = task_type
    self.message = message

    self.progress = 0
    self.status = "created" # created / finished / error
    self.result = None

  def change_progress(self, progress: int, message: str, status: str = ""):
    self.progress = progress
    self.message = message
    if status != "":
      self.status = status

  def error(self, message: str, progress: int = -1):
    self.message = message
    self.status = "error"
    if progress != -1:
      self.progress = progress

  def finished(self, message: str):
    self.message = message
    self.status = "finished"

  def __str__(self):
    return f'ID={self.task_id}, APP_ID={self.app_id}'

  def to_JSON(self) -> str:
    return json.dumps(self, default=lambda x: x.__dict__)

  def to_seriazable_object(self):
    return json.loads(self.to_JSON())


tasks: list[Task] = []
"""Server-wide variable holding all running tasks on the daemon-server."""

last_report_time: float = time.time()
TIMEOUT: int = 300
