import random

rtips_string = """You can disable tips in the add-on preferences.
Ratings help us distribute funds to creators.
Creators also gain credits for free assets from subscribers.
Click or drag model or material in scene to link/append 
Right click in the asset bar for a detailed asset card
Use Append in import settings if you want to edit downloaded objects. 
Please rate responsively and plentifully. This helps us distribute rewards to the authors.
All materials are free.
Storage for public assets is unlimited.
Locked models are available if you subscribe to Full plan.
Login to upload your own models, materials or brushes.
Use 'A' key over the asset bar to search assets by the same author.
Use semicolon - ; to hide or show the AssetBar.
Support the authors by subscribing to Full plan.
Use the W key over the asset bar to open the Author's webpage.
Use the R key for fast rating of assets.
Use the X key to delete the asset from your hard drive.
"""
rtips = rtips_string.splitlines()


def get_random_tip():
  t = random.choice(rtips)
  t.replace('\n','')
  return t
