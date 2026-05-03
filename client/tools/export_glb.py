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


def ensure_gltf_addon():
    """Make sure ``bpy.ops.export_scene.gltf`` is callable.

    The glTF I/O addon ships with Blender but isn't always enabled by
    default — when it isn't, ``export_scene.gltf`` raises
    ``AttributeError: ... has no attribute 'gltf'`` and the export
    fails before we get a useful error. Worse, the module name has
    moved over time:

      * Blender 3.x / 4.0 / 4.1: classic addon ``io_scene_gltf2``.
      * Blender 4.2+: bundled extensions repo. Module is
        ``bl_ext.<repo_id>.io_scene_gltf2`` where ``repo_id`` varies
        per install (``system``, ``user_default``, ``blender_org``).

    A hand-maintained list of names will rot, so we discover candidates
    dynamically with ``addon_utils.modules()`` and pick anything whose
    bl_info advertises a glTF importer/exporter — then fall back to a
    short list of known names if the scan didn't find any (e.g. the
    extensions repo wasn't refreshed yet).

    Enabling goes through ``addon_utils.enable(default_set=True)`` so
    the change is persistent (saved into userprefs after we
    ``save_userpref`` — non-fatal if that step can't write to the prefs
    file in a sandboxed background run).
    """
    if hasattr(bpy.ops.export_scene, "gltf"):
        return  # already available — nothing to do

    try:
        import addon_utils
    except Exception as exc:  # noqa: BLE001
        # No addon_utils means we're inside something that's not real
        # Blender — bail with a clear error instead of carrying on.
        raise RuntimeError(
            f"export_glb: addon_utils unavailable ({exc!r}); cannot enable glTF addon."
        )

    # 1) Discover by scanning installed modules. Survives the
    #    addon→extension rename without us tracking module paths.
    candidates = []
    seen = set()
    try:
        for mod in addon_utils.modules(refresh=False):
            modname = getattr(mod, "__name__", None)
            if not modname or modname in seen:
                continue
            try:
                info = addon_utils.module_bl_info(mod) or {}
            except Exception:  # noqa: BLE001
                info = {}
            name = (info.get("name") or "").lower()
            cat = (info.get("category") or "").lower()
            # bl_info names are stable: "glTF 2.0 format" for both the
            # classic addon and the extension. Match on substring so
            # any future rename (eg. "glTF 3.0") still picks it up.
            if "gltf" in name or ("import-export" in cat and "gltf" in modname.lower()):
                candidates.append(modname)
                seen.add(modname)
    except Exception as scan_exc:  # noqa: BLE001
        print(f"export_glb: addon_utils scan failed ({scan_exc!r}); falling back to known names.",
              file=sys.stderr)

    # 2) Always also try well-known module names — covers the case
    #    where the extensions repo index hasn't been built yet on a
    #    fresh Blender install.
    for name in (
        "io_scene_gltf2",
        "bl_ext.system.io_scene_gltf2",
        "bl_ext.user_default.io_scene_gltf2",
        "bl_ext.blender_org.io_scene_gltf2",
    ):
        if name not in seen:
            candidates.append(name)
            seen.add(name)

    last_err = None
    for module in candidates:
        try:
            mod = addon_utils.enable(module, default_set=True, persistent=True)
        except Exception as exc:  # noqa: BLE001 - Blender raises mixed types
            last_err = exc
            continue
        if mod is None:
            # enable() returns None when the module wasn't found.
            continue
        if hasattr(bpy.ops.export_scene, "gltf"):
            print(f"export_glb: enabled glTF addon ({module})")
            try:
                bpy.ops.wm.save_userpref()
            except Exception as save_exc:  # noqa: BLE001
                # Headless / read-only-prefs runs can't persist; the
                # in-process enable is still enough for THIS export.
                print(
                    f"export_glb: enabled but couldn't save prefs ({save_exc!r})",
                    file=sys.stderr,
                )
            return

    raise RuntimeError(
        "export_glb: could not enable glTF addon. "
        f"tried_candidates={candidates} last_err={last_err!r}"
    )


argv = sys.argv
if "--" not in argv:
    print("export_glb: missing -- separator", file=sys.stderr)
    sys.exit(2)
argv = argv[argv.index("--") + 1 :]
if not argv:
    print("export_glb: no params.json path given after --", file=sys.stderr)
    sys.exit(2)

with open(argv[-1], "r", encoding="utf-8") as fh:
    params = json.load(fh)

ensure_gltf_addon()

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
