import collections
import logging


DAEMON_ACCESSIBLE = False
DAEMON_ONLINE = False
DATA = {
  'images available': {} ,
  'search history': collections.deque(maxlen=20),
}
LOGGING_LEVEL_BLENDERKIT = logging.INFO
LOGGING_LEVEL_IMPORTED = logging.WARN
PREFS = {}
SERVER = 'https://www.blenderkit.com'
TIPS = [
  'You can disable tips in the add-on preferences.',
  'Ratings help us distribute funds to creators.',
  'Creators also gain credits for free assets from subscribers.',
  'Click or drag model or material in scene to link/append.', 
  'Right click in the asset bar for a detailed asset card.',
  'Use Append in import settings if you want to edit downloaded objects.',
  'Go to import settings to set default texture resolution.',
  'Please rate responsively and plentifully. This helps us distribute rewards to the authors.',
  'All materials are free.',
  'Storage for public assets is unlimited.',
  'Locked models are available if you subscribe to Full plan.',
  'Login to upload your own models, materials or brushes.',
  "Use 'A' key over the asset bar to search assets by the same author.",
  'Use semicolon - ; to hide or show the AssetBar.',
  'Support the authors by subscribing to Full plan.',
  "Use the W key over the asset bar to open the Author's webpage.",
  'Use the R key over the asset bar for fast rating of assets.',
  'Use the X key over the asset bar to delete the asset from your hard drive.',
  ]
