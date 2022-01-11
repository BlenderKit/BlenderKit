# Asyncio proof of concept

This branch adds DOWNLOAD button to addon which will start 5 async downloads of 155MB Blender releases.
Downloads are non-blocking and Blender seems to run just fine with them.
There is not any visible lag.

## Installation

You need to install `aiohttp` package to Blender.

1. In terminal navigate to location where is stored Blender's Python binary.
2. `python -m ensurepip`
3. `python -m pip install --upgrade pip`
4. `python -m pip install aiohttp` or specify directly the location via `python -m pip install --target <where-blender-python-modules-are> aiohttp`
  
## Problems 

We need to figure out how to automatize installation of aiohttp
or how to bundle it into addon.










BlenderKit add-on is the official addon of the BlenderKit service for Blender 3d.
It enables users to upload, search, download, and rate different assets for blender.
It works together with BlenderKit server.