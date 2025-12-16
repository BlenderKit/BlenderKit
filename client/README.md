# BlenderKit-Client

This is a Client for BlenderKit (previously daemon).
It's a local server that listens for requests from BlenderKit add-ons and processes them.
Written in Go.

## How is it run
The Client is built for Windows, MacOS and Linux for both x86_64 and arm64.
BlenderKit-Client binaries are shipped in the blenderkit.zip file, in /client directory where normally in the repo Client's source code is placed.
On add-on start, the Client binary is copied into global_dir/client/bin/vX.Y.Z directory, and started.

### Client start
Client can be started from the add-on automatically, but it can be also started manually.
When Client is started from the add-on, the add-on automatically fills some flags:
- `--version` informing about the version of the add-on which starts Client
- `--software` in which software starting add-on runs - for now it is just Blender
- `--pid` the process number of the software whose add-on starts the Client

For manual start these flags are empty (if the user does not specify those from CLI).
In the future Client could behave differently when started manually - e.g. does not shutdown automatically after a while.
