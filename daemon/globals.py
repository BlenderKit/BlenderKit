"""Holds global variables used by modules of daemon server."""

import time

import tasks as tsks


tasks: list[tsks.Task] = []
"""Server-wide variable holding all running tasks on the daemon-server."""

last_report_time: float = time.time()
TIMEOUT: int = 300
PORT: int = -1
OAUTH_CLIENT_ID: str = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
active_apps=[]
