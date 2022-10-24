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

BLENDERKIT_LOCAL = 'http://localhost:8001'
BLENDERKIT_MAIN = 'https://www.blenderkit.com'
BLENDERKIT_DEVEL = 'https://devel.blenderkit.com'
BLENDERKIT_STAGING = 'https://staging.blenderkit.com'
SERVER = BLENDERKIT_MAIN

TIPS = [
  ('You can disable tips in the add-on preferences.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#preferences'),
  ('Ratings help us distribute funds to creators.', 'https://www.blenderkit.com/docs/rating/'),
  ('Creators also gain credits for free assets from subscribers.', 'https://www.blenderkit.com/docs/fair-share/'),
  ('Click or drag model or material in scene to link/append.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#basic-usage'),
  ('Right click in the asset bar for a detailed asset card.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#'),
  ('Use Append in import settings if you want to edit downloaded objects.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#import-method'),
  ('Go to import settings to set default texture resolution.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#import-method'),
  ('Please rate responsively and plentifully. This helps us distribute rewards to the authors.', 'https://www.blenderkit.com/docs/rating/'),
  ('All materials are free.', 'https://www.blenderkit.com/asset-gallery?query=category_subtree:material%20order:-created'),
  ('Storage for public assets is unlimited.', 'https://www.blenderkit.com/become-creator/'),
  ('Locked models are available if you subscribe to Full plan.', 'https://www.blenderkit.com/plans/pricing/'),
  ('Login to upload your own models, materials or brushes.', 'https://www.blenderkit.com/'),
  ('Use \'A\' key over the asset bar to search assets by the same author.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#basic-usage'),
  ('Use semicolon - ; to hide or show the AssetBar.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#assetbar'),
  ('Support the authors by subscribing to Full plan.', 'https://www.blenderkit.com/plans/pricing/'),
  ('Use the W key over the asset bar to open the Author\'s webpage.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#assetbar'),
  ('Use the R key over the asset bar for fast rating of assets.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#assetbar'),
  ('Use the X key over the asset bar to delete the asset from your hard drive.', 'https://docs.blender.org/manual/en/3.1/addons/3d_view/blenderkit.html#assetbar'),
  ]
VERSION = None #filled in register()

code_verifier = None
daemon_process = None
