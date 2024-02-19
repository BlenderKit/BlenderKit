# Blenderkit add-on
BlenderKit add-on is the official add-on of the [BlenderKit](https://www.blenderkit.com/) service for Blender 3D.
It enables users to upload, search, download, and rate different assets for Blender 3D.
It works together with BlenderKit online database of models.

## Architecture
For faster task processing the add-on spawns a separate background process BlenderKit-client.
It is a local server that acts as a bridge between BlenderKit add-on and BlenderKit server, it also spawns Blender processes for Packing/Unpacking without taking processing power from user's Blender window.
For more information about BlenderKit-client, see [BlenderKit-client](https://github.com/blenderkit/blenderkit/blob/main/client/README.md).

## How to contribute
We gladly welcome bug reports, feature requests and code contribution.
If you want to contribute code, please check information for developers which are available at [CONTRIBUTING.md](https://github.com/BlenderKit/blenderkit/blob/main/CONTRIBUTING.md).
