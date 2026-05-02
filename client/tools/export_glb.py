"""tools/export_glb.py - bundled BlenderKit-client recipe.

Re-exports the active scene to .glb. Invoked via
POST /run_blender_script with `script_id="export_glb"`.

Recipe ABI (every script in tools/ follows this):
    sys.argv = [..., "--", <params.json>]
    params.json keys (this script):
        output_path : str   (required) - destination .glb
        yup         : bool  (default True)
        draco       : bool  (default False)
        export_apply: bool  (default True)
"""
import json
import sys

import bpy

argv = sys.argv
if "--" not in argv:
    print("export_glb: missing -- separator", file=sys.stderr)
    sys.exit(2)
argv = argv[argv.index("--") + 1:]
if not argv:
    print("export_glb: no params.json path given after --", file=sys.stderr)
    sys.exit(2)

with open(argv[-1], "r", encoding="utf-8") as fh:
    params = json.load(fh)

out_glb = params["output_path"]
print("export_glb: writing", out_glb)

bpy.ops.export_scene.gltf(
    filepath=out_glb,
    export_format="GLB",
    export_draco_mesh_compression_enable=bool(params.get("draco", False)),
    export_yup=bool(params.get("yup", True)),
    use_visible=False,
    use_active_collection=False,
    export_apply=bool(params.get("export_apply", True)),
)

print("export_glb: done")
