# Blenderkit addon

BlenderKit add-on is the official addon of the BlenderKit service for Blender 3d.
It enables users to upload, search, download, and rate different assets for blender.
It works together with BlenderKit server.

## Development

### Building

Blenderkit addon requires few external modules - mostly `aiohttp` and its dependencies.
To make the start of the addon faster those dependencies are bundled into the addon in the `vendor` directory.
Versions of dependencies are saved in `requirements.txt` file.

To bundle the dependencies into the addon, we use: `build.py` script.
This script cleans the `vendor` and then downloads the dependencies into 3 different directories (`Windows`, `Darwin`, `Linux`) in the `vendor` directory.


Once dependencies are bundled, you can zip the `blenderkit` directory and use it or release it.

To make release do:
1. check you set correct version
2. `python build.py`
3. remove `.git` directory
4. remove `.github` directory
5. remove `__pycache__` from root and other directories
6. zip the `blenderkit` directory - the zip is the release of addon
