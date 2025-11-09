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
            continue

        print(f"Failed to set up addon for Blender {version}. See errors above.")
    except Exception as e:
        print(f"Failed to link for Blender {version}: {e}")
