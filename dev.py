import argparse
import os
import shutil
import subprocess
import sys

import global_vars


PACKAGES = [
    "multidict==6.0.4",
    "yarl==1.9.4",
    "aiohttp==3.9.1",
    "aiosignal==1.3.1",
    "async-timeout==4.0.3",
    "attrs==23.1.0",
    "certifi==2023.11.17",
    "charset-normalizer==3.3.2",
    "frozenlist==1.4.1",
    "idna==3.6",
]


def blenderkit_client_build(abs_build_dir: str):
    """Build blenderkit client for all platforms in parallel."""
    build_dir = os.path.join(abs_build_dir, "client")
    builds = [
        {
            "env": {"GOOS": "windows", "GOARCH": "amd64"},
            "output": "blenderkit-client-windows-x86_64.exe",
        },
        {
            "env": {"GOOS": "windows", "GOARCH": "arm64"},
            "output": "blenderkit-client-windows-arm64.exe",
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "amd64"},
            "output": "blenderkit-client-macos-x86_64",
        },
        {
            "env": {"GOOS": "darwin", "GOARCH": "arm64"},
            "output": "blenderkit-client-macos-arm64",
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "amd64"},
            "output": "blenderkit-client-linux-x86_64",
        },
        {
            "env": {"GOOS": "linux", "GOARCH": "arm64"},
            "output": "blenderkit-client-linux-arm64",
        },
    ]

    processes = []
    for build in builds:
        build_path = os.path.join(build_dir, build["output"])
        env = {**build["env"], **os.environ}
        process = subprocess.Popen(
            ["go", "build", "-o", build_path, "."],
            env=env,
            cwd="./client",
        )
        processes.append(process)

    print(f"Client build started for {len(builds)} platforms.")
    for process in processes:
        process.wait()
    print("Client builds completed.")


def do_build(install_at=None, include_tests=False):
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
    shutil.copytree(
        "daemon",
        f"{addon_build_dir}/daemon",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree("data", f"{addon_build_dir}/data")
    shutil.copytree(
        "dependencies", f"{addon_build_dir}/dependencies"
    )  # TODO: remove this when client is implemented
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
    shutil.make_archive("out/blenderkit", "zip", "out", "blenderkit")

    if install_at is not None:
        shutil.rmtree(f"{install_at}/blenderkit", ignore_errors=True)
        shutil.copytree("out/blenderkit", f"{install_at}/blenderkit")


def compile_daemon():
    """Compile daemon for current platform."""
    subprocess.check_call(["pipenv", "install", "-r", "requirements.txt"])
    subprocess.check_call(["pipenv", "install", "pyinstaller"])
    print("PLATFORM:", sys.platform)
    if sys.platform == "darwin":
        subprocess.check_call(
            [
                "pipenv",
                "run",
                "pyinstaller",
                "--add-data",
                "daemon:.",
                "--onefile",
                "daemon/daemon.py",
            ],
        )
        print("Macos build done")
    if sys.platform == "win32":
        subprocess.check_call(
            [
                "pipenv",
                "run",
                "pyinstaller",
                "--add-data",
                "daemon;.",
                "--onefile",
                "daemon/daemon.py",
            ],
        )
        print("Windows build done")
    if sys.platform == "linux":
        subprocess.check_call(
            [
                "pipenv",
                "run",
                "pyinstaller",
                "--add-data",
                "daemon:.",
                "--onefile",
                "daemon/daemon.py",
            ],
        )
        print("Linux build done")
    shutil.move("dist", "out-daemon/dist")
    shutil.move("build", "out-daemon/build")
    shutil.move("daemon.spec", "out-daemon/daemon.spec")
    os.remove("Pipfile")
    os.remove("Pipfile.lock")
    print("daemon binary available at: out-daemon/dist/daemon")


def run_tests():
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


def format_code():
    """Sort, format and lint the code."""
    print("***** SORTING IMPORTS on ALL files *****")
    subprocess.call(["isort", "."])

    print("\n***** FORMATTING CODE on ALL files *****")
    subprocess.call(["black", "."])

    # print("\n***** LINTING with RUFF in ./daemon *****")
    # subprocess.call(["ruff", "daemon"])
    # print()


def bundle_dependencies():
    """Bundle dependencies specified in PACKAGES variable into ./dependencies directory."""
    MACOS = {
        "name": "Darwin",
        "platforms": {
            #'macosx_10_9_x86_64': packages,
            "macosx_10_9_universal2": PACKAGES,
        },
    }

    LINUX = {
        "name": "Linux",
        "platforms": {
            "manylinux_2_17_x86_64": PACKAGES[0:3],
            "manylinux1_x86_64": PACKAGES[3:],
        },
    }

    WINDOWS = {
        "name": "Windows",
        "platforms": {
            "win_amd64": PACKAGES,
        },
    }

    shutil.rmtree("dependencies", True)
    print("***** VENDORING DEPENDENCIES *****")
    for OS in [MACOS, WINDOWS, LINUX]:
        print(f'\n===== {OS["name"]} =====')
        for platform in OS["platforms"]:
            for module in OS["platforms"][platform]:
                cmd = [
                    "pip3",
                    "install",
                    "--only-binary=:all:",
                    f"--platform={platform}",
                    f"--python-version={global_vars.BUNDLED_FOR_PYTHON}",
                    f'--target=dependencies/{OS["name"]}',
                    "--no-deps",
                    module,
                ]
                exit_code = subprocess.call(cmd)
                if exit_code != 0:
                    sys.exit(1)


### COMMAND LINE INTERFACE

parser = argparse.ArgumentParser()
parser.add_argument(
    "command",
    default="build",
    choices=["format", "build", "bundle", "compile", "test"],
    help="""
  FORMAT = isort imports, format code with Black and lint it with Ruff.
  TEST = build with test files and run tests
  BUILD = copy relevant files into ./out/blenderkit.
  BUNDLE = bundle dependencies into ./dependencies
  COMPILE = compile daemon for current platform
  """,
)
parser.add_argument(
    "--install-at",
    type=str,
    default=None,
    help="If path is specified, then builded addon will be copied to that location.",
)
args = parser.parse_args()

if args.command == "build":
    do_build(args.install_at)
elif args.command == "test":
    do_build(args.install_at, include_tests=True)
    run_tests()
elif args.command == "bundle":
    bundle_dependencies()
elif args.command == "compile":
    compile_daemon()
elif args.command == "format":
    format_code()
else:
    parser.print_help()
