import asyncio
import json
import uuid
from inspect import getframeinfo, stack
from os.path import basename


class Task:
    """Holds all information needed for a task."""

    def __init__(
        self,
        data: dict,
        app_id: str,
        task_type: str,
        task_id: str = "",
        message: str = "",
        message_detailed: str = "",
        progress: int = 0,
        status: str = "created",
        result: dict = {},
    ):
        if task_id == "":
            task_id = str(uuid.uuid4())

        self.data = data
        self.task_id = task_id
        self.app_id = app_id  # TODO: implement solution for report to "all" Blenders
        self.task_type = task_type

        self.message = message
        self.message_detailed = message_detailed
        self.progress = progress
        self.status = status  # created / finished / error
        self.result = result.copy()

        self.async_task: asyncio.Task | None = None

    def change_progress(self, progress: int, message: str = "", status: str = ""):
        self.progress = progress
        if message != "":
            self.message = message
        if status != "":
            self.status = status

    def error(self, message: str, message_detailed: str = "", progress: int = -1):
        """End the task with error."""
        self.status = "error"
        caller = getframeinfo(stack()[1][0])
        self.message = f"{message} [{basename(caller.filename)}:{caller.lineno}]"
        if message_detailed != "":
            self.message_detailed = message_detailed
        if progress != -1:
            self.progress = progress

    def finished(self, message: str):
        """End the task successfuly."""
        self.message = message
        self.status = "finished"
        self.progress = 100

    def cancel(self):
        if type(self.async_task) == asyncio.Task:
            self.async_task.cancel()

    def __str__(self):
        return f"ID={self.task_id}, APP_ID={self.app_id}"

    def to_JSON(self) -> str:
        async_task = self.async_task
        del self.async_task
        result = json.dumps(self, default=lambda x: x.__dict__)
        self.async_task = async_task
        return result

    def to_seriazable_object(self):
        return json.loads(self.to_JSON())


def handle_async_errors(atask: asyncio.Task):
    stack = atask.get_stack()
    exception = atask.exception()
    if exception is None and stack == []:
        return

    atask.print_stack()
    import daemon_globals  # ugly but we cannot import on start as this is also imported from add-on directly

    for task in daemon_globals.tasks:
        if atask is not task.async_task:
            continue
        task.error(str(exception))
