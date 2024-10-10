# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import uuid
from typing import Optional


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
        result: Optional[dict] = None,
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
        if result is None:
            self.result = {}
        else:
            self.result = result.copy()

    def __str__(self):
        return f"ID={self.task_id}, APP_ID={self.app_id}"
