# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
# type: ignore

import argparse
import os
import shutil
import subprocess


def blenderkit_client_build(abs_build_dir: str):
    """Build blenderkit-client for all platforms in parallel."""
    with open("client/VERSION", "r") as f:
        client_version = f.read().strip()
    build_dir = os.path.join(abs_build_dir, "client")
    builds = [
        {
            "env": {"GOOS": "windows", "GOARCH": "amd64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", "blenderkit-client-windows-x86_64.exe"
            ),
        },
        {
            "env": {"GOOS": "windows", "GOARCH": "arm64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-windows-arm64.exe"
            ),
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "amd64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-macos-x86_64"
            ),
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "arm64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-macos-arm64"
            ),
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-linux-x86_64"
            ),
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "arm64", "CGO_ENABLED": "0"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-linux-arm64"
            ),
        },
    ]
    ldflags = f"-X main.ClientVersion={client_version}"
    for build in builds:
        build_path = os.path.join(build_dir, build["output"])
        env = {**build["env"], **os.environ}
        process = subprocess.Popen(
            ["go", "build", "-o", build_path, "-ldflags", ldflags, "."],
            env=env,
            cwd="./client",
        )
        build["process"] = process

    print(
        f"BlenderKit-Client v{client_version} build started for {len(builds)} platforms."
    )
    builds_ok = True
    for build in builds:
        build["process"].wait()
        if build["process"].returncode != 0:
            print(f"Client build ({build['env']}) failed")
            builds_ok = False

    if not builds_ok:
        exit(1)
    print(f"BlenderKit-Client v{client_version} builds completed.")


def verify_client_binaries(binaries_path: str):
    """Verify client binaries tha they were signed correctly.
    - osslsigncode needs to be on PATH (https://github.com/mtrojnar/osslsigncode)
    -
    """
    print("===== VERIFYING CLIENT BINARIES =====")
    signatures_ok = True
    files = os.listdir(binaries_path)
    client_files = [f for f in files if f.startswith("blenderkit-client")]
    for file_name in client_files:
        print(f"\n\n==={file_name}")
        file_path = os.path.join(binaries_path, file_name)

        # WINDOWS
        if file_path.endswith(".exe"):
            process = subprocess.Popen(
                ["osslsigncode", "verify", "-in", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            # print(f"out:{output}, err:{error}")
            stdout = str(output)
            if (
                "CN=Blender Kit s.r.o." in stdout
                and "O=Blender Kit s.r.o." in stdout
                and "L=Prague" in stdout
                and "ST=Prague" in stdout
                and "C=CZ" in stdout
            ):
                print(f">>> OK!")
            elif expected in str(error):
                print(f">>> WARNING")
            else:
                print(f">>> ERROR")
                signatures_ok = False
            continue

        # MACOS
        if "macos" in file_path:
            # validate codesigning
            process = subprocess.Popen(
                ["codesign", "--verify", "-vvvv", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            print(f"out:{output}, err:{error}")
            expected = "satisfies its Designated Requirement"
            if expected in str(output) or expected in str(error):
                print(">>> OK on codesigning")
            else:
                print(f">>> ERROR on codesigning")
                signatures_ok = False

            # validate notarization
            process = subprocess.Popen(
                ["spctl", "--assess", "-vvv", "--ignore-cache", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            print(f"out:{output}, err:{error}")
            expected = "origin=Developer ID Application: BlenderKit s.r.o. (A839AY9877)"
            if expected in str(output):
                print(f">>> OK notarization!")
            elif expected in str(error):
                print(f">>> WARNING notarization")
            else:
                print(f">>> ERROR notarization")
                signatures_ok = False

            continue

    if signatures_ok == False:
        print("\n>>>>> Verification failed for one or more files, exiting.")
        exit(1)

    print("\n>>>>> Verification OK for all files!\n\n")


def copy_client_binaries(binaries_path: str, addon_build_dir: str):
    if not os.path.exists(binaries_path):
        print(f"Client binaries path {binaries_path} does not exist, exiting.")
        exit(1)
    if not os.path.isdir(binaries_path):
        print(f"Client binaries path {binaries_path} is not a directory, exiting.")
        exit(1)

    with open("client/VERSION", "r") as f:
        expected_client_version = f"v{f.read().strip()}"

    client_version = os.path.basename(os.path.normpath(binaries_path))
    if client_version != expected_client_version:
        print(
            f"Client binaries version {client_version} does not match expected version {expected_client_version}, exiting."
        )
        exit(1)

    target_dir = os.path.join(addon_build_dir, "client", expected_client_version)
    os.makedirs(target_dir)

    files = os.listdir(binaries_path)
    client_files = [f for f in files if f.startswith("blenderkit-client")]
    for file_name in client_files:
        source_file = os.path.join(binaries_path, file_name)
        target_file = os.path.join(target_dir, file_name)
        shutil.copy2(source_file, target_file)
        print(f"Copied {source_file} to {target_file}")

    print(f"BlenderKit-Client binaries copied from {binaries_path} to {target_dir}")


def do_build(
    install_at=None, include_tests=False, clean_dir=None, client_binaries_path=None
):
    """Build addon by copying relevant addon directories and files to ./out/blenderkit directory.
    Create zip in ./out/blenderkit.zip.
    - install_at: string or list of paths where to install the addon, e.g. ["/path1/addons", "/path2/addons"]
    - include_tests: include test files into .zip file, so tests can be run with this .zip
    - clean_dir: if specified, clean that directory before building the add-on, e.g. clean client bin in blenderkit_data: "/Users/username/blenderkit_data/client/bin"
    - client_binaries_path: if specified, use client (signed) binaries from that path instead of building new ones, e.g. "./client_builds/v1.0.0" containing client binaries for different platforms
    """
    out_dir = os.path.abspath("out")
    addon_build_dir = os.path.join(out_dir, "blenderkit")
    shutil.rmtree(out_dir, True)

    if client_binaries_path == None:
        blenderkit_client_build(addon_build_dir)
    else:
        copy_client_binaries(client_binaries_path, addon_build_dir)

    ignore_files = [
        ".gitignore",
        "dev.py",
        "README.md",
        "CONTRIBUTING.md",
        "setup.cfg",
        ".DS_Store",
    ]

    shutil.copytree(
        "bl_ui_widgets",
        f"{addon_build_dir}/bl_ui_widgets",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )
    shutil.copytree(
        "blendfiles",
        f"{addon_build_dir}/blendfiles",
        ignore=shutil.ignore_patterns(".DS_Store"),
    )
    shutil.copytree(
        "data", f"{addon_build_dir}/data", ignore=shutil.ignore_patterns(".DS_Store")
    )
    shutil.copytree(
        "thumbnails",
        f"{addon_build_dir}/thumbnails",
        ignore=shutil.ignore_patterns(".DS_Store"),
    )

    for item in os.listdir():
        if os.path.isdir(item):
            continue  # we copied directories above
        if item in ignore_files:
            continue
        if include_tests is False and item == "test.py":
            continue
        if include_tests is False and item.startswith("test_"):
            continue  # we do not include test files
        shutil.copy(item, f"{addon_build_dir}/{item}")

    # CREATE ZIP
    print("Creating ZIP archive.")
    shutil.make_archive("out/blenderkit", "zip", "out", "blenderkit")

    # Handle multiple install locations
    if install_at is not None:

        for location in install_at:
            print(f"Copying to {location}/blenderkit")
            shutil.rmtree(f"{location}/blenderkit", ignore_errors=True)
            shutil.copytree("out/blenderkit", f"{location}/blenderkit")

    if clean_dir is not None:
        print(f"Cleaning directory {clean_dir}")
        shutil.rmtree(clean_dir, ignore_errors=True)

    print("Build done!")


def run_tests(args):
    do_build(
        args.install_at,
        include_tests=True,
        clean_dir=args.clean_dir,
        client_binaries_path=args.client_build,
    )
    # Best effort here to keep it simple and detect automatically, other option would be to add it as a flag
    if "extensions/user_default" in args.install_at:
        extensions_format = True
    else:
        extensions_format = False
    run_go_tests()
    run_python_tests(extensions_format, fast=args.fast)


def run_python_tests(extension_format: bool, fast: bool):
    print("=== Running add-on integration tests in Blender ===")
    if extension_format:  # Here we expect default settings
        addon_package_name = "bl_ext.user_default.blenderkit"
    else:  # legacy format
        addon_package_name = "blenderkit"
    env = os.environ.copy()
    if fast:
        env["TESTS_TYPE"] = "FAST"
    test = subprocess.Popen(
        [
            "blender",
            "--background",
            "-noaudio",
            "--python-exit-code",
            "1",
            "--python",
            "test.py",
            "--",
            addon_package_name,
        ],
        env=env,
    )
    test.wait()
    if test.returncode == 1:
        exit(1)
    print("=== Blender integration tests passed ===")


def run_go_tests():
    print("\n=== Running Client Go unit tests ===")
    gotest = subprocess.Popen(["go", "test"], cwd="client")
    gotest.wait()
    if gotest.returncode != 0:
        exit(1)
    print("=== Go tests passed.\n")


def format_code():
    """Sort, format and lint the code."""
    print("***** SORTING IMPORTS on ALL files *****")
    subprocess.call(["isort", "."])

    print("\n***** FORMATTING CODE on ALL files *****")
    subprocess.call(["black", "."])


### COMMAND LINE INTERFACE

parser = argparse.ArgumentParser()
parser.add_argument(
    "command",
    default="build",
    choices=["format", "build", "test", "release"],
    help="""
  FORMAT = isort imports, format code with Black and lint it with Ruff.
  TEST = build with test files and run tests
  BUILD = copy relevant files into ./out/blenderkit.
  RELEASE = build the add-on .zip with already built client binaries.
  """,
)
parser.add_argument(
    "--install-at",
    type=str,
    action="append",  # This allows multiple --install-at arguments
    default=None,
    help="Specify path where the add-on should be installed. Flag can be used multiple times.",
)
parser.add_argument(
    "--clean-dir",
    type=str,
    default=None,
    help="Specify path to global_dir/client/bin or other dir which should be cleaned.",
)
parser.add_argument(
    "--client-build",
    type=str,
    default=None,
    help="Specify path client_builds/vX.Y.Z. Binaries in this directory will be used instead of building new ones.",
)
parser.add_argument(
    "--fast",
    type=bool,
    default=False,
    help="Run just fast tests. These are Go unittests and Python fast tests (skips those which do requests).",
)
args = parser.parse_args()

if args.command == "build":
    do_build(
        args.install_at,
        clean_dir=args.clean_dir,
        client_binaries_path=args.client_build,
    )
elif args.command == "release":
    if args.client_build is None:
        print(
            "Error: Client binaries path (containing signed binaries) is required for release"
        )
        exit(1)
    verify_client_binaries(args.client_build)
    do_build(
        args.install_at,
        clean_dir=args.clean_dir,
        client_binaries_path=args.client_build,
    )
elif args.command == "test":
    run_tests(args)
elif args.command == "format":
    format_code()
else:
    parser.print_help()
