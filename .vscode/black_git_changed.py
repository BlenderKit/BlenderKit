#!/usr/bin/env python3
"""
Platform-independent script to run Black on git-changed Python files.
Works on Windows, macOS, and Linux.
"""
import subprocess
import sys
from pathlib import Path


def get_git_changed_files():
    """Get list of changed Python files from git."""
    try:
        # Get changed files (staged + unstaged)
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        changed_files = (
            result.stdout.strip().split("\n") if result.stdout.strip() else []
        )

        # Also get staged files
        staged_result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )

        staged_files = (
            staged_result.stdout.strip().split("\n")
            if staged_result.stdout.strip()
            else []
        )

        # Combine and filter for Python files
        all_files = set(changed_files + staged_files)
        python_files = [f for f in all_files if f.endswith(".py") and f != ""]

        return python_files

    except subprocess.CalledProcessError as e:
        print(f"Error getting git changed files: {e}")
        return []
    except FileNotFoundError:
        print("Git not found in PATH")
        return []


def main():
    """Run Black on git-changed Python files."""
    # Get workspace root (parent of .vscode)
    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent

    print(f"Workspace root: {workspace_root}")

    # Change to workspace directory
    import os

    os.chdir(workspace_root)

    # Get changed Python files
    changed_files = get_git_changed_files()

    if not changed_files:
        print("No changed Python files found.")
        return 0

    print(f"Found {len(changed_files)} changed Python files:")
    for file in changed_files:
        print(f"  - {file}")

    # Run Black on changed files
    black_args = ["black", "--check", "--diff"] + changed_files

    print(f"\nRunning: {' '.join(black_args)}")

    try:
        result = subprocess.run(black_args, check=False)
        return result.returncode
    except FileNotFoundError:
        print("Black not found. Make sure it's installed and in PATH.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
