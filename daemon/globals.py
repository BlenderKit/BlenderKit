"""Holds global variables used by modules of daemon server."""

import json



class Task():
  """Holds all information needed for a task.
  
  Constructor automatically adds the instance of Task into list globals.new_tasks.
  """

  def __init__(self, data: dict, task_id: str):
    self.data = data
    self.task_id = task_id
    self.progress = 0
    self.type = None
    self.text = None
    self.app_id = None

    global new_tasks
    new_tasks.append(self)

  def __str__(self):
    return self.task_id

  def change_progress(self, progress: int, text: str):
    self.progress = progress
    self.text = text

  def to_JSON(self):
    return json.dumps(self, default=lambda x: x.__dict__)

new_tasks: list[Task] = []

tasks = dict()
"""Server-wide variable holding all running tasks on the daemon-server."""

# JUST FOR TESTING
if __name__ == "__main__":
  
  Task("data", "1")
  Task("data", "2")
  Task("data", "3")
  
  print(new_tasks)
