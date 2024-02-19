# BlenderKit-client

This a client for BlenderKit (previously daemon).
It's a local server that listens for requests from BlenderKit add-on and processes them.
Written in Go.

## How is it run
For now, the client is built for Windows, MacOS and Linux for both x86_64 and arm64.
BlenderKit-client binaries are shipped in the blenderkit.zip file, in /client directory where in repo source code is placed.
On add-on start, the client is copied into global_dir/client/vX.Y.Z.YYMMDD directory, and started.

