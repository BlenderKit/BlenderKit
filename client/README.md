# BlenderKit-Client

This is a Client for BlenderKit (previously daemon).
It's a local server that listens for requests from BlenderKit add-on and processes them.
Written in Go.

## How is it run
For now, the Client is built for Windows, MacOS and Linux for both x86_64 and arm64.
BlenderKit-Client binaries are shipped in the blenderkit.zip file, in /client directory where in repo source code is placed.
On add-on start, the Client binary is copied into global_dir/client/bin/vX.Y.Z directory, and started.
