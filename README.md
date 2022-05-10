# Blenderkit addon

BlenderKit add-on is the official add-on of the [BlenderKit](https://www.blenderkit.com/) service for Blender 3D.
It enables users to upload, search, download, and rate different assets for Blender 3D.
It works together with BlenderKit online database of models.

## Development

### Building the addon

Use `dev.py` script to build the add-on.
This script will copy relevant files to `out/blenderkit` directory (ignoring all files which are not needed in the add-on).
From this source the script will then create a zip file at `out/blenderkit.zip`.
This zip then can be used as a release of BlenderKit.

To build run:
```
python dev.py build
```

#### Development build: build and copy to Blender for quick testing

Script `dev.py` provides handy option `--install-at` to copy the `out/blenderkit` directly to Blender so you can quickly test the build just by starting the Blender without any further steps.
Just specify path to addons directory in `--install-at` flag.
Script will then remove old `blenderkit` directory in addons location and replace it with current build.

To build and copy to Blender addons directory run:

```
python dev.py build --install-at /path/to/blender/3.1/scripts/addons
```

### Release

To release do:
1. make sure code is OK: version is set, dependencies are updated
2. run `python dev.py build` to build the zip file in `out/blenderkit.zip`
3. double check the zip is OK
4. that's all, upload to Github!
