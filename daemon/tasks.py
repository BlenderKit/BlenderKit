import asyncio
import json


class Task():
  """Holds all information needed for a task."""

  def __init__(self, data: dict, task_id: str, app_id: str, task_type: str, message: str = "", progress: int = 0, status: str = "created", result: dict = {}):
    self.data = data
    self.task_id = task_id
    self.app_id = app_id
    self.task_type = task_type
    
    self.message = message
    self.progress = progress
    self.status = status # created / finished / error
    self.result = result

    self.async_task: asyncio.Task | None = None

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

  def cancel(self):
    if type(self.async_task) == asyncio.Task:
      self.async_task.cancel()

  def __str__(self):
    return f'ID={self.task_id}, APP_ID={self.app_id}'

  def to_JSON(self) -> str:
    async_task = self.async_task
    del self.async_task
    result = json.dumps(self, default=lambda x: x.__dict__)
    self.async_task = async_task
    return result

  def to_seriazable_object(self):
    return json.loads(self.to_JSON())
