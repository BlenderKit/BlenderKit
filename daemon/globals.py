"""Holds global variables used by modules of daemon server."""

import time

import tasks as tsks


tasks: list[tsks.Task] = []
"""Server-wide variable holding all running tasks on the daemon-server."""


TIMEOUT: int = 300
PORT: int = -1
OAUTH_CLIENT_ID: str = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
DNS_SERVERS = [
    "8.8.8.8", "8.8.4.4", # Google
    "1.1.1.1", "1.0.0.1", # CloudFlare
    "9.9.9.9", "149.112.112.112", #Quad9
    ]

active_apps=[]
last_report_time: float = time.time()
servers_statuses = {
    "https://www.blenderkit.com": None,
    "https://www.google.com": None,
}
