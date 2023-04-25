"""Holds global variables used by modules of daemon server."""

from logging import INFO, WARN
from time import time

import daemon_tasks


tasks: list[daemon_tasks.Task] = []
"""Server-wide variable holding all running tasks on the daemon-server."""


LOGGING_LEVEL_DAEMON = INFO
LOGGING_LEVEL_IMPORTED = WARN
TIMEOUT: int = 300
PORT: int = -1
OAUTH_CLIENT_ID: str = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
SERVER = None
IP_VERSION = None
SSL_CONTEXT = None
SYSTEM_ID = None
VERSION = None

code_verifier = None
active_apps = []
last_report_time: float = time()
