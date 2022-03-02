# Blenderkit addon

## Development

### Building

Blenderkit addon requires few external modules - mostly aiohttp and its dependencies.
To make the start of the addon faster those dependencies are bundled to the addon.
To bundle them into the addon, run: `python build.py`.
This script will download the dependencies into 3 different directories (`Windows`, `Darwin`, `Linux`) in the `vendor` directory.

Once dependencies are bundled, you can zip the `blenderkit` directory and use it or release it.








BlenderKit add-on is the official addon of the BlenderKit service for Blender 3d.
It enables users to upload, search, download, and rate different assets for blender.
It works together with BlenderKit server.