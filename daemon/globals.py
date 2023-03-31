"""Holds global variables used by modules of daemon server."""

from logging import INFO, WARN
from time import time

import tasks as tsks


tasks: list[tsks.Task] = []
"""Server-wide variable holding all running tasks on the daemon-server."""


LOGGING_LEVEL_DAEMON = INFO
LOGGING_LEVEL_IMPORTED = WARN
TIMEOUT: int = 300
PORT: int = -1
OAUTH_CLIENT_ID: str = 'IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F'
SERVER = None
IP_VERSION = None
SSL_CONTEXT = None
SYSTEM_ID = None
VERSION = None
DNS_HOSTS = [
    "8.8.8.8", #Google
    "8.8.4.4",
    "76.76.2.0", #Control D
    "76.76.10.0",
    "9.9.9.9", #Quad9
    "149.112.112.112",
    "208.67.222.222", #OpenDNS Home
    "208.67.220.220",
    "1.1.1.1", #Cloudflare 
    "1.0.0.1",
    "185.228.168.9", #CleanBrowsing
    "185.228.169.9",
    "76.76.19.19", #Alternate DNS
    "76.223.122.150",
    "94.140.14.14", #AdGuard DNS
    "94.140.15.15"
]

code_verifier = None
active_apps=[]
last_report_time: float = time()
online_status = None
