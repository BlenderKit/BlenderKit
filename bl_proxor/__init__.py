"""bl_proxor - lightweight PRX viewer and generator, integrated into BlenderKit.

Generates, saves, loads, and displays PRX/PRXC proxor data in the viewport
via GPU drawing.  Used as a preview proxy during model drag-and-drop instead
of the default green bounding box when a .prxc file is available for the asset.

All submodules (draw, generate, prx_format) are imported lazily where needed.
"""
