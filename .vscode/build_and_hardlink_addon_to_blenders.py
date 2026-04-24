"""Small utility script to link this addon repo into Blender's addons folder for easier dev.

What it does per detected Blender version under the user's addons directory:
- On Windows: Try creating an NTFS directory junction.
- On macOS/Linux: Create a symlink.

Notes:
- Junctions typically work without Developer Mode, but can still be restricted by policy.
- On macOS, Blender stores user data in ~/Library/Application Support/Blender/
- On Linux, Blender stores user data in ~/.config/blender/
"""

import glob
import os
import re
import shutil
import subprocess
import sys

THIS_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace(
    "\\", "/"
)

RESULTING_ADDON_NAME = "blenderkit_dev_hl"

if sys.platform == "win32":
    BLENDER_VERSIONS_PATH = os.path.expanduser(
        "~/AppData/Roaming/Blender Foundation/Blender"
    ).replace("\\", "/")
elif sys.platform == "darwin":
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/Library/Application Support/Blender")
else:
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/.config/blender")

# Discover addon directories for each Blender version.
# Blender 4.2+ supports extensions -> link only into extensions/user_default/.
# Older Blender versions -> link only into scripts/addons/.
all_versions = []
for p in glob.glob(BLENDER_VERSIONS_PATH + "/*/"):
    p = p.replace("\\", "/").rstrip("/")
    version_dir = os.path.basename(p)
    if not re.match(r"\d+\.\d+", version_dir):
        continue
    major, minor = map(int, version_dir.split("."))
    supports_extensions = major > 4 or (major == 4 and minor >= 2)
    if supports_extensions:
        addon_dir = os.path.join(p, "extensions", "user_default")
    else:
        addon_dir = os.path.join(p, "scripts", "addons")
    addon_dir = addon_dir.replace("\\", "/")
    if addon_dir not in all_versions:
        all_versions.append(addon_dir)

pattern = re.compile(
    r".*[/\\](\d+\.\d+)[/\\](?:scripts[/\\]addons|extensions[/\\]user_default)"
)


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


def _try_link(src: str, dst: str) -> bool:
    """Create a directory junction (Windows) or symlink (macOS/Linux)."""
    if sys.platform == "win32":
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
    else:
        try:
            os.symlink(src, dst)
            return True
        except Exception as e:
            print(f"  Symlink failed: {e}")
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
    # Create parent directories if they don't exist (e.g. scripts/addons)
    os.makedirs(version_path, exist_ok=True)
    print(f"Setting up link for Blender {version} -> {target_addon_path}")
    try:
        _remove_existing(target_addon_path)

        if _try_link(THIS_REPO, target_addon_path):
            print(f"Linked blenderkit addon to Blender {version} addons folder.")
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


# find the latest build using regex
highest_version = None
for f in os.listdir(build_output_master_dir):
    if re.match(r"v\d+\.\d+\.\d+", f):
        # is the version the highest?
        version_numbers = list(map(int, f[1:].split(".")))
        if highest_version is None:
            highest_version = version_numbers
        else:
            for i in range(3):
                if version_numbers[i] > highest_version[i]:
                    highest_version = version_numbers
                    break
                elif version_numbers[i] < highest_version[i]:
                    break


if highest_version is None:
    print("No client build found.")
    sys.exit(1)

# prepare the highest version folder name
highest_version_str = "v" + ".".join(map(str, highest_version))

build_output_master_dir = os.path.join(
    build_output_master_dir, highest_version_str
).replace("\\", "/")

client_dir = os.path.join(THIS_REPO, "client", highest_version_str).replace("\\", "/")
# local user client bin
local_client_bin = os.path.join(
    os.path.expanduser("~"), "blenderkit_data", "client", "bin", highest_version_str
).replace("\\", "/")

print(f"Copying built client from {build_output_master_dir} to {client_dir}")

# remove existing client build folder
_remove_existing(client_dir)
if os.path.exists(local_client_bin):
    _remove_existing(local_client_bin)

# copy the build
shutil.copytree(build_output_master_dir, client_dir)
shutil.copytree(build_output_master_dir, local_client_bin)

print("Client build copied successfully.")
