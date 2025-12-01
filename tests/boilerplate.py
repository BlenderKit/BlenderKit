"""Boilerplate to set values for testing.

Sets __package__ and module variables for use in tests.py files.
Dynamically set the package context for the BlenderKit add-on
by inspecting the currently enabled add-ons in Blender.

This allows the test files to import the correct modules
from the add-on regardless of whether it's installed as a regular add-on or hard-linked.
"""

import importlib

import bpy

__package__ = None
for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
    # allow hard-linked version
    elif "blenderkit_dev_hl" in addon.module:
        __package__ = addon.module
        break

module = importlib.import_module(__package__, package=None)
