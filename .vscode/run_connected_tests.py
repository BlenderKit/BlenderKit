"""Helper script to start Blender from VS Code.

Reads configuration from environment variables so launch.json can stay simple.

Relevant variables:
- BLENDER_EXECUTABLE (required): absolute path to blender(.exe).
- BLENDER_ADDON_MODULE (optional): passed to --addons to auto-enable a module.
- BLENDER_FILE (optional): .blend file to open.
- BLENDER_BOOTSTRAP_SCRIPT (optional): extra Python script to run via --python.
- BLENDER_EXTRA_ARGS (optional): additional CLI flags, parsed with shlex.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def _path_from_env(value: str | None) -> Path | None:
    if not value:
        return None
    expanded = Path(value).expanduser().resolve()
    return expanded


def _build_cli(executable: Path) -> list[str]:
    cmd = [str(executable)]

    # we assume hardlinked addon package name here
    addon_package_name = "blenderkit_dev_hl"
    cmd += [
        "--background",
        "-noaudio",
        "--python-exit-code",
        "1",
        "--python",
        "./tests/test.py",
        "--",
        addon_package_name,
    ]

    return cmd


def _format_command(cmd: list[str]) -> str:
    parts = []
    for token in cmd:
        if " " in token:
            parts.append(f'"{token}"')
        else:
            parts.append(token)
    return " ".join(parts)


def main() -> int:
    executable_value = os.environ.get("BLENDER_EXECUTABLE")
    if not executable_value:
        print(
            "[blender-runner] BLENDER_EXECUTABLE is not set. Add it to your .env file.",
            file=sys.stderr,
        )
        return 1

    executable_path = _path_from_env(executable_value)
    if not executable_path or not executable_path.exists():
        print(
            f"[blender-runner] Blender executable not found at: {executable_path}",
            file=sys.stderr,
        )
        return 1

    if not executable_path.is_file():
        print(
            f"[blender-runner] BLENDER_EXECUTABLE must point to a file, got: {executable_path}",
            file=sys.stderr,
        )
        return 1

    cmd = _build_cli(executable_path)
    print(f"[blender-runner] Launching: {_format_command(cmd)}")

    try:
        process = subprocess.Popen(cmd)
    except OSError as exc:
        print(f"[blender-runner] Failed to start Blender: {exc}", file=sys.stderr)
        return 1

    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()


if __name__ == "__main__":
    sys.exit(main())
