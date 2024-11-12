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

from collections import deque
from logging import INFO, WARN
from os import environ

CLIENT_VERSION = "v1.2.1"
CLIENT_ACCESSIBLE = False
CLIENT_FAILED_REPORTS = 0
"""Number of failed requests to get reports from the BlenderKit-Client. If too many, something is wrong."""

CLIENT_PORTS = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
"""Ports are ordered during the start, and later after malfunction."""

CLIENT_RUNNING = False
DATA = {
    "images available": {},
    "search history": deque(maxlen=20),
    "bkit notifications": None,
    "bkit authors": {},
    "asset comments": {},
    "asset ratings": {},
}
LOGGING_LEVEL_BLENDERKIT = INFO
LOGGING_LEVEL_IMPORTED = WARN
PREFS = {}

SERVER = environ.get("BLENDERKIT_SERVER", "https://www.blenderkit.com")
DISCORD_INVITE_URL = "https://discord.gg/tCKyjFMRar"

TIPS = [
    (
        "You can disable tips in the add-on preferences.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#preferences",
    ),
    ("Ratings help us distribute funds to creators.", f"{SERVER}/docs/rating/"),
    (
        "Creators also gain credits for free assets from subscribers.",
        f"{SERVER}/docs/fair-share/",
    ),
    (
        "Click on or drag a model or material into the scene to link or append it.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage",
    ),
    (
        "Press ESC while dragging a model or material to cancel the action and avoid any download.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#cancel-drag-and-drop",
    ),
    (
        "During drag-and-drop, rotate the dragged asset's outline box by 90 degrees using the mouse wheel.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#rotate-asset",
    ),
    (
        "Right click in the asset bar for a detailed asset card.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation",
    ),
    (
        "Use Append in import settings if you want to edit downloaded objects.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings",
    ),
    (
        "Go to import settings to set default texture resolution.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings",
    ),
    (
        "Please rate responsively and plentifully. This helps us distribute rewards to the authors.",
        f"{SERVER}/docs/rating/",
    ),
    (
        "All materials are free.",
        f"{SERVER}/asset-gallery?query=category_subtree:material%20order:-created",
    ),
    ("Storage for public assets is unlimited.", f"{SERVER}/become-creator/"),
    (
        "Locked models are available if you subscribe to Full plan.",
        f"{SERVER}/plans/pricing/",
    ),
    ("Login to upload your own models, materials or brushes.", f"{SERVER}/"),
    (
        "Use 'A' key over the asset bar to search assets by the same author.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage",
    ),
    (
        "Use semicolon - ; to hide or show the AssetBar.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    ("Support the authors by subscribing to Full plan.", f"{SERVER}/plans/pricing/"),
    (
        "Use the 'P' key over the asset bar to open the Author's profile on BlenderKit.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'W' key over the asset bar to open Author's personal webpage.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'R' key over the asset bar for fast rating of assets.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'X' key over the asset bar to delete the asset from your hard drive.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'S' key over the asset bar to search similar assets.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'C' key over the asset bar to search assets in same subcategory.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'B' key over the asset bar to bookmark the asset.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Get latest experimental versions of add-on by enabling prerelases in preferences.",
        "",
    ),
    (
        "On Discord? Jump into assets & add-on talks.",
        DISCORD_INVITE_URL,
    ),
    (
        "Right-click on the downloaded asset to rate, bookmark and more in the 'Selected Model' submenu.",
        "",
    ),
]
VERSION = None  # filled in register()

client_process = None
"""Holds return value of subprocess.Popen() which starts the BlenderKit-Client."""
