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
# Per version, link to EXACTLY ONE target:
#   - Blender 4.2+ -> extensions/user_default/
#   - Blender < 4.2 -> scripts/addons/
all_versions = []
seen_versions = set()
for p in sorted(glob.glob(BLENDER_VERSIONS_PATH + "/*/")):
    p = p.replace("\\", "/").rstrip("/")
    version_dir = os.path.basename(p)
    if not re.match(r"\d+\.\d+", version_dir):
        continue
    if version_dir in seen_versions:
        continue
    seen_versions.add(version_dir)
    major, minor = map(int, version_dir.split("."))
    if major > 4 or (major == 4 and minor >= 2):
        addon_dir = os.path.join(p, "extensions", "user_default")
    else:
        addon_dir = os.path.join(p, "scripts", "addons")
    all_versions.append(addon_dir.replace("\\", "/"))

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


def _has_dependent_addon(addons_dir: str) -> str:
    """Return the name of a sibling addon that likely depends on the legacy
    `blenderkit_dev_hl` import path (e.g. blenderkit_validator_dev_hl), or "".

    Such addons must stay together with the main addon in `scripts/addons/`
    because in `extensions/user_default/` the import name becomes
    `bl_ext.user_default.blenderkit_dev_hl` and `import blenderkit_dev_hl`
    would fail.
    """
    if not os.path.isdir(addons_dir):
        return ""
    for name in os.listdir(addons_dir):
        if name == RESULTING_ADDON_NAME:
            continue
        # Match dev-hardlinked siblings like blenderkit_validator_dev_hl
        if name.startswith("blenderkit_") and name.endswith("_dev_hl"):
            return name
    return ""


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

    # Remove any stale link in the *other* location (extensions vs addons)
    # so we never end up with the addon registered in both places — UNLESS a
    # sibling dev addon there depends on the legacy import path.
    version_root = os.path.dirname(os.path.dirname(version_path))
    legacy_addons_dir = os.path.join(version_root, "scripts", "addons").replace(
        "\\", "/"
    )
    extensions_dir = os.path.join(version_root, "extensions", "user_default").replace(
        "\\", "/"
    )
    other_candidates = [
        os.path.join(legacy_addons_dir, RESULTING_ADDON_NAME).replace("\\", "/"),
        os.path.join(extensions_dir, RESULTING_ADDON_NAME).replace("\\", "/"),
    ]
    # Always check for dependent addon — independent of whether a stale link exists.
    dependent_addon = _has_dependent_addon(legacy_addons_dir)
    legacy_target = os.path.join(legacy_addons_dir, RESULTING_ADDON_NAME).replace(
        "\\", "/"
    )
    keep_legacy_link = bool(dependent_addon) and legacy_target != target_addon_path
    if keep_legacy_link:
        print(
            f"  Dependent addon '{dependent_addon}' found in scripts/addons; "
            f"will keep legacy link at {legacy_target}."
        )

    for other in other_candidates:
        if other == target_addon_path or not os.path.lexists(other):
            continue
        # If a dependent dev addon lives in scripts/addons, keep that link.
        if keep_legacy_link and other == legacy_target:
            continue
        print(f"  Removing stale link at {other}")
        _remove_existing(other)

    # Create parent directories if they don't exist (e.g. scripts/addons)
    os.makedirs(version_path, exist_ok=True)
    print(f"Setting up link for Blender {version} -> {target_addon_path}")
    try:
        _remove_existing(target_addon_path)

        if _try_link(THIS_REPO, target_addon_path):
            print(f"Linked blenderkit addon to Blender {version} addons folder.")
            was_linked = True
        else:
            print(f"Failed to set up addon for Blender {version}. See errors above.")
            continue
    except Exception as e:
        print(f"Failed to link for Blender {version}: {e}")
        continue

    # Also (re)create the legacy link if a dependent addon needs it.
    if keep_legacy_link and not os.path.lexists(legacy_target):
        os.makedirs(legacy_addons_dir, exist_ok=True)
        if _try_link(THIS_REPO, legacy_target):
            print(f"  Also linked at {legacy_target} for legacy importers.")
        else:
            print(f"  WARNING: could not create legacy link at {legacy_target}.")

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
