from collections import deque
from logging import INFO, WARN
from os import environ


DAEMON_ACCESSIBLE = False
DAEMON_FAILED_REPORTS = 0

DAEMON_PORTS = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
"""Ports are ordered during the start, and later after malfunction."""

DAEMON_ONLINE = False
DATA = {
  'images available': {},
  'search history': deque(maxlen=20),
  'bkit notifications': None,
  'bkit authors': {},
  'asset comments': {},
  'asset ratings': {},
}
LOGGING_LEVEL_BLENDERKIT = INFO
LOGGING_LEVEL_IMPORTED = WARN
PREFS = {}

SERVER = environ.get('BLENDERKIT_SERVER', 'https://www.blenderkit.com')

TIPS = [
  ('You can disable tips in the add-on preferences.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#preferences'),
  ('Ratings help us distribute funds to creators.', f'{SERVER}/docs/rating/'),
  ('Creators also gain credits for free assets from subscribers.', f'{SERVER}/docs/fair-share/'),
  ('Click or drag model or material in scene to link/append.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage'),
  ('Right click in the asset bar for a detailed asset card.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation'),
  ('Use Append in import settings if you want to edit downloaded objects.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings'),
  ('Go to import settings to set default texture resolution.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings'),
  ('Please rate responsively and plentifully. This helps us distribute rewards to the authors.', f'{SERVER}/docs/rating/'),
  ('All materials are free.', f'{SERVER}/asset-gallery?query=category_subtree:material%20order:-created'),
  ('Storage for public assets is unlimited.', f'{SERVER}/become-creator/'),
  ('Locked models are available if you subscribe to Full plan.', f'{SERVER}/plans/pricing/'),
  ('Login to upload your own models, materials or brushes.', f'{SERVER}/'),
  ('Use \'A\' key over the asset bar to search assets by the same author.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage'),
  ('Use semicolon - ; to hide or show the AssetBar.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar'),
  ('Support the authors by subscribing to Full plan.', f'{SERVER}/plans/pricing/'),
  ('Use the W key over the asset bar to open the Author\'s webpage.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar'),
  ('Use the R key over the asset bar for fast rating of assets.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar'),
  ('Use the X key over the asset bar to delete the asset from your hard drive.', 'https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar'),
  ('Get latest experimental versions of add-on by enabling prerelases in preferences.', ''),
]
VERSION = None  # filled in register()
BUNDLED_FOR_PYTHON = "3.10"

daemon_process = None
