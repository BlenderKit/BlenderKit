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
            "env": {"GOOS": "windows", "GOARCH": "amd64"},
            "output": os.path.join(
                f"v{client_version}", "blenderkit-client-windows-x86_64.exe"
            ),
        },
        {
            "env": {"GOOS": "windows", "GOARCH": "arm64"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-windows-arm64.exe"
            ),
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "amd64"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-macos-x86_64"
            ),
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "arm64"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-macos-arm64"
            ),
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "amd64"},
            "output": os.path.join(
                f"v{client_version}", f"blenderkit-client-linux-x86_64"
            ),
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "arm64"},
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
        f"BlenderKit-client v{client_version} build started for {len(builds)} platforms."
    )
    builds_ok = True
    for build in builds:
        build["process"].wait()
        if build["process"].returncode != 0:
            print(f"Client build ({build['env']}) failed")
            builds_ok = False

    if not builds_ok:
        exit(1)
    print(f"BlenderKit-client v{client_version} builds completed.")


def do_build(install_at=None, include_tests=False, clean_dir=None):
    """Build addon by copying relevant addon directories and files to ./out/blenderkit directory.
    Create zip in ./out/blenderkit.zip.
    """
    out_dir = os.path.abspath("out")
    addon_build_dir = os.path.join(out_dir, "blenderkit")
    shutil.rmtree(out_dir, True)

    blenderkit_client_build(addon_build_dir)

    ignore_files = [".gitignore", "dev.py", "README.md", "CONTRIBUTING.md", "setup.cfg"]

    shutil.copytree(
        "bl_ui_widgets",
        f"{addon_build_dir}/bl_ui_widgets",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree("blendfiles", f"{addon_build_dir}/blendfiles")
    shutil.copytree("data", f"{addon_build_dir}/data")
    shutil.copytree("thumbnails", f"{addon_build_dir}/thumbnails")

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

    if install_at is not None:
        print(f"Copying to {install_at}/blenderkit")
        shutil.rmtree(f"{install_at}/blenderkit", ignore_errors=True)
        shutil.copytree("out/blenderkit", f"{install_at}/blenderkit")
    if clean_dir is not None:
        print(f"Cleaning directory {clean_dir}")
        shutil.rmtree(clean_dir, ignore_errors=True)

    print("Build done!")


def run_tests():
    print("\n=== Running Client Go unit tests ===")
    gotest = subprocess.Popen(["go", "test"], cwd="client")
    gotest.wait()
    if gotest.returncode != 0:
        exit(1)
    print("Go tests passed.\n")

    print("=== Running add-on integration tests in Blender tests ===")
    test = subprocess.Popen(
        [
            "blender",
            "--background",
            "-noaudio",
            "--python-exit-code",
            "1",
            "--python",
            "test.py",
        ]
    )
    test.wait()
    if test.returncode == 1:
        exit(1)
    print("=== Blender integration tests passed ===")


def format_code():
    """Sort, format and lint the code."""
    print("***** SORTING IMPORTS on ALL files *****")
    subprocess.call(["isort", "."])

    print("\n***** FORMATTING CODE on ALL files *****")
    subprocess.call(["black", "."])

    # print("\n***** LINTING with RUFF in ./daemon *****")
    # subprocess.call(["ruff", "daemon"])
    # print()


### COMMAND LINE INTERFACE

parser = argparse.ArgumentParser()
parser.add_argument(
    "command",
    default="build",
    choices=["format", "build", "test"],
    help="""
  FORMAT = isort imports, format code with Black and lint it with Ruff.
  TEST = build with test files and run tests
  BUILD = copy relevant files into ./out/blenderkit.
  """,
)
parser.add_argument(
    "--install-at",
    type=str,
    default=None,
    help="If path is specified, then builded addon will be copied to that location.",
)
parser.add_argument(
    "--clean-dir",
    type=str,
    default=None,
    help="Specify path to global_dir or other dir to be cleaned.",
)
args = parser.parse_args()

if args.command == "build":
    do_build(args.install_at, clean_dir=args.clean_dir)
elif args.command == "test":
    do_build(args.install_at, include_tests=True)
    run_tests()
elif args.command == "format":
    format_code()
else:
    parser.print_help()
