"""Small utility script to link this addon repo into Blender's addons folder for easier dev on Windows.

What it does per detected Blender version under the user's AppData scripts/addons:
- Try creating an NTFS directory junction.

Notes:
- Junctions typically work without Developer Mode, but can still be restricted by policy.
"""

import os
import sys
import shutil
import subprocess
import re

# for windows only currently --- sorry linux / mac users.
if sys.platform != "win32":
    raise RuntimeError("This script only works on Windows currently.")

import re
import glob

THIS_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace(
    "\\", "/"
)

BLENDER_VERSIONS_PATH = os.path.expanduser(
    "~/AppData/Roaming/Blender Foundation/Blender"
).replace("\\", "/")

RESULTING_ADDON_NAME = "blenderkit_dev_hl"

# \scripts\addons

all_versions = [
    p.replace("\\", "/") for p in glob.glob(BLENDER_VERSIONS_PATH + "/*/scripts/addons")
]
pattern = re.compile(r".*\/(\d+\.\d+)\/scripts\/addons")


def _remove_existing(path: str) -> None:
    """Remove existing file/dir/link at path safely."""
    if not os.path.lexists(path):
        return
    # Symlink to dir or file
    if os.path.islink(path):
        os.unlink(path)
        return
    # Directory (including junction)
    if os.path.isdir(path):
        try:
            # rmdir works for empty dirs and junctions; fallback to rmtree
            os.rmdir(path)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
        return
    # Plain file
    os.remove(path)


def _try_junction(src: str, dst: str) -> bool:
    # Use mklink /J to create directory junctions (works on NTFS)
    try:
        cmd = f'cmd /c mklink /J "{dst}" "{src}"'
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode == 0:
            return True
        print(f"  Junction failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return False
    except Exception as e:
        print(f"  Junction failed: {e}")
        return False


was_linked = False
for version_path in all_versions:
    match = pattern.match(version_path)
    if not match:
        print("Could not parse Blender version from path:", version_path)
        continue
    version = match.group(1)
    target_addon_path = os.path.join(version_path, RESULTING_ADDON_NAME).replace(
        "\\", "/"
    )
    print(f"Setting up link for Blender {version} -> {target_addon_path}")
    try:
        _remove_existing(target_addon_path)

        if _try_junction(THIS_REPO, target_addon_path):
            print(
                f"Linked (junction) blenderkit addon to Blender {version} addons folder."
            )
            was_linked = True
            continue

        print(f"Failed to set up addon for Blender {version}. See errors above.")
    except Exception as e:
        print(f"Failed to link for Blender {version}: {e}")

# make sure we have the latest build and move it to client/
if not was_linked:
    print("No Blender versions were linked. Exiting.")
    sys.exit(1)

# build the client if needed
was_built = False
build_script = os.path.join(THIS_REPO, "dev.py").replace("\\", "/")
build_cmds = [sys.executable, build_script, "build"]
# run and wait
subprocess.run(build_cmds, check=True)

# copy source to client/
# this folder is ingored and will not be synced to blenderkit addon repo
# but will be used by the addon to run the client
build_output_master_dir = os.path.join(
    THIS_REPO, "out", "blenderkit", "client"
).replace("\\", "/")
was_built = False

client_dir = os.path.join(THIS_REPO, "client").replace("\\", "/")
# find the latest build using regex
for f in os.listdir(build_output_master_dir):
    print(f)
    if re.match(r"v\d+\.\d+\.\d+", f):
        latest_build_dir = os.path.join(build_output_master_dir, f).replace("\\", "/")
        print(f"Copying latest client build from {latest_build_dir} to client/ folder.")
        if os.path.exists(os.path.join(THIS_REPO, "client", f)):
            shutil.rmtree(os.path.join(THIS_REPO, "client", f))
        shutil.copytree(latest_build_dir, os.path.join(THIS_REPO, "client", f))
        was_built = True
        break
