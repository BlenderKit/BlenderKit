# This script compares append_link.py between two BlenderKit versions
import difflib
import sys

# Paths to the two files to compare
old_path = (
    r"C:\Users\mikih\Downloads\blenderkit-v3.18.1.251219\blenderkit\append_link.py"
)
new_path = r"C:\_blenderkit_dev\blenderkit_addon\append_link.py"

with open(old_path, encoding="utf-8") as f:
    old_lines = f.readlines()
with open(new_path, encoding="utf-8") as f:
    new_lines = f.readlines()

diff = difflib.unified_diff(
    old_lines,
    new_lines,
    fromfile="blenderkit-v3.18.1.251219/append_link.py",
    tofile="_blenderkit_dev/append_link.py",
    lineterm="",
)

for line in diff:
    print(line)
