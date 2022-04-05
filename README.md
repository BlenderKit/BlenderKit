# Blenderkit addon

BlenderKit add-on is the official addon of the BlenderKit service for Blender 3D.
It enables users to upload, search, download, and rate different assets for Blender.
It works together with BlenderKit server.

## Development

### Release

To release do:
1. run `python build.py` - this downloads dependencies for Mac, Win and Linux into: dependencies/Darwin, dependencies/Windows, dependencies/Linux.
2. remove any files/dirs which are not needed as: `.git`, `.gitignore`, `__pycache__`, `daemon/__pycache__` etc.
3. zip the directory.
