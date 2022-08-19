import collections
import logging


DATA = {
  'images available': {} ,
  'search history': collections.deque(maxlen=20),
}
LOGGING_LEVEL_BLENDERKIT = logging.INFO
LOGGING_LEVEL_IMPORTED = logging.WARN
PREFS = {}

DAEMON_ACCESSIBLE = False
DAEMON_ONLINE = False
