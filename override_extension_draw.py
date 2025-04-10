"""
This is a separate library that overrides the extension_draw_item method from Blender extensions list display.
The original code is in the bl_extension_ui.py file in the Blender source code.
The override library can be placed in multiple addons, and the override should happen only once.
The override is done by replacing the original method with the new one, and backing up the original method.
The original method is then called from the new method, with the same arguments, but with the new code added.
"""

import json
import os
import bpy
import bl_pkg.bl_extension_ui as exui
from . import icons
from bl_ui.space_userpref import (
    USERPREF_PT_addons,
    USERPREF_PT_extensions,
    USERPREF_MT_extensions_active_repo,
)
from bpy.props import EnumProperty
from bpy.props import StringProperty, IntProperty
from bpy.types import Operator
import time

EXTENSIONS_API_URL = "https://www.blenderkit.com/api/v1/extensions/"


# --- New Modal Operator ---
class BK_OT_buy_extension_and_watch(Operator):
    """Opens URL to buy extension and starts a modal timer to refresh repo periodically."""

    bl_idname = "bk.buy_extension_and_watch"
    bl_label = "Buy Extension Online and Watch"
    bl_options = {"REGISTER", "UNDO"}

    url: StringProperty(
        name="URL",
        description="Website URL to open",
    )
    repo_index: IntProperty(
        name="Repository Index",
        description="Index of the repository to refresh",
        default=-1,
    )

    _timer = None
    _last_refresh_time = 0
    _start_time = 0
    _refresh_interval = 60  # seconds
    _max_duration = 300  # seconds (5 minutes timeout)

    def execute(self, context):
        if not self.url:
            self.report({"ERROR"}, "No URL specified.")
            return {"CANCELLED"}
        if self.repo_index == -1:
            self.report({"ERROR"}, "No repository index specified.")
            return {"CANCELLED"}

        # Open the URL
        try:
            bpy.ops.wm.url_open(url=self.url)
            print(f"BlenderKit: Opening buy URL: {self.url}")
        except Exception as e:
            self.report({"ERROR"}, f"Could not open URL: {e}")
            # Don't cancel, maybe the user still wants the refresh?
            # Decide if you want modal to continue even if URL fails

        # Add modal handler and timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(
            1.0, window=context.window
        )  # Check every second
        wm.modal_handler_add(self)
        self._start_time = time.time()
        self._last_refresh_time = (
            self._start_time
        )  # Initialize to avoid immediate refresh
        print(
            f"BlenderKit: Started watching repository index {self.repo_index} for updates."
        )
        context.area.tag_redraw()  # Update UI to show operator is running if needed
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        current_time = time.time()

        # --- Exit Conditions ---
        # 1. User closed Preferences or changed area
        if context.area is None or context.area.type != "PREFERENCES":
            print("BlenderKit: Preferences window closed or changed, stopping watcher.")
            self.cancel(context)
            return {"CANCELLED"}

        # 2. Timeout
        if current_time - self._start_time > self._max_duration:
            print("BlenderKit: Watcher timed out, stopping.")
            self.cancel(context)
            return {"CANCELLED"}

        # 3. User cancellation
        if event.type in {"RIGHTMOUSE", "ESC"}:
            print("BlenderKit: Watcher cancelled by user.")
            self.cancel(context)
            return {"CANCELLED"}

        # --- Timer Logic ---
        if event.type == "TIMER":
            # Check if refresh interval has passed
            if current_time - self._last_refresh_time >= self._refresh_interval:
                print(
                    f"BlenderKit: Refresh interval reached, attempting sync for repo index {self.repo_index}..."
                )
                try:
                    # Check if repo still exists at that index
                    if self.repo_index < len(context.preferences.extensions.repos):
                        bpy.ops.extensions.repo_sync(repo_index=self.repo_index)
                        print(
                            f"BlenderKit: repo_sync called for index {self.repo_index}."
                        )
                    else:
                        print(
                            f"BlenderKit: Repository index {self.repo_index} no longer valid."
                        )
                        # Optionally cancel here if repo is gone
                except Exception as e:
                    # This might fail if another operation is in progress
                    print(f"BlenderKit: extensions.repo_sync failed: {e}")
                finally:
                    self._last_refresh_time = (
                        current_time  # Reset timer regardless of success
                    )

        return {"PASS_THROUGH"}  # Pass other events through

    def cancel(self, context):
        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            self._timer = None
            print("BlenderKit: Watcher timer removed.")
        context.area.tag_redraw()  # Update UI


# --- End New Modal Operator ---


def extension_draw_item_blenderkit(
    layout,
    *,
    pkg_id,  # `str`
    item_local,  # `PkgManifest_Normalized | None`
    item_remote,  # `PkgManifest_Normalized | None`
    is_enabled,  # `bool`
    is_outdated,  # `bool`
    show,  # `bool`.
    mark,  # `bool | None`.
    # General vars.
    repo_index,  # `int`
    repo_item,  # `RepoItem`
    operation_in_progress,  # `bool`
    extensions_warnings,  # `dict[str, list[str]]`
    show_developer_ui,  # `bool`
):
    ### BlenderKit cache code
    # Ensure cache is up-to-date before drawing
    cache_reloaded = ensure_repo_cache()
    if cache_reloaded:
        # If cache was just reloaded, tag UI for redraw
        layout.tag_redraw()
        print("BlenderKit: Cache reloaded, tagging layout for redraw.")

    # check if the cache is already in the window manager
    if "blenderkit_extensions_repo_cache" not in bpy.context.window_manager:
        # Log if cache is missing after trying to ensure it
        print(
            "BlenderKit: Extension cache not available in window_manager after ensure_repo_cache call."
        )
        # Optionally draw a minimal representation or return early to avoid errors
        # For now, just return to avoid potential errors accessing bk_ext_cache
        return

    bk_ext_cache = bpy.context.window_manager["blenderkit_extensions_repo_cache"]
    bk_cache_pkg = bk_ext_cache.get(pkg_id[:32], None)
    ### end of BlenderKit cache code
    item = item_local or item_remote
    is_installed = item_local is not None
    has_remote = repo_item.remote_url != ""

    if item_remote is not None:
        pkg_block = item_remote.block
    else:
        pkg_block = None

    if is_enabled:
        item_warnings = extensions_warnings.get(
            exui.pkg_repo_module_prefix(repo_item) + pkg_id, []
        )
    else:
        item_warnings = []

    # Left align so the operator text isn't centered.
    colsub = layout.column()
    row = colsub.row(align=True)

    if show:
        props = row.operator(
            "extensions.package_show_clear", text="", icon="DOWNARROW_HLT", emboss=False
        )
    else:
        props = row.operator(
            "extensions.package_show_set", text="", icon="RIGHTARROW", emboss=False
        )
    props.pkg_id = pkg_id
    props.repo_index = repo_index

    if mark is not None:
        if mark:
            props = row.operator(
                "extensions.package_mark_clear",
                text="",
                icon="RADIOBUT_ON",
                emboss=False,
            )
        else:
            props = row.operator(
                "extensions.package_mark_set",
                text="",
                icon="RADIOBUT_OFF",
                emboss=False,
            )
        props.pkg_id = pkg_id
        props.repo_index = repo_index

    sub = row.row()
    sub.active = is_enabled
    # Without checking `is_enabled` here, there is no way for the user to know if an extension
    # is enabled or not, which is useful to show - when they may be considering removing/updating
    # extensions based on them being used or not.
    if pkg_block or item_warnings:
        sub.label(text=item.name, icon="ERROR", translate=False)
    else:
        sub.label(text=item.name, translate=False)

    # Add a top-level row so `row_right` can have a grayed out button/label
    # without graying out the menu item since# that is functional.
    row_right_toplevel = row.row(align=True)
    if operation_in_progress:
        row_right_toplevel.enabled = False
    row_right_toplevel.alignment = "RIGHT"
    row_right = row_right_toplevel.row()
    row_right.alignment = "RIGHT"

    if has_remote and (item_remote is not None):
        if pkg_block is not None:
            row_right.label(text="Blocked   ")
        elif is_installed:
            if is_outdated:
                props = row_right.operator("extensions.package_install", text="Update")
                props.repo_index = repo_index
                props.pkg_id = pkg_id
                props.enable_on_install = is_enabled
        else:
            ### BlenderKit specific code
            # blenderkit logo icon
            pcoll = icons.icon_collections["main"]
            icon_value = pcoll["logo"].icon_id
            # row.label(text="", icon_value=icon_value)
            # only enable install for those for whom it's available
            if bk_cache_pkg is not None:
                # Free , purchased and subscribed add-ons, probably also private add-ons
                if bk_cache_pkg.get("can_download") is True:
                    # if the addon is also for sale, it means the user purchased it and we write "install purchased"
                    if bk_cache_pkg.get("is_for_sale") is True:
                        props = row_right.operator(
                            "extensions.package_install",
                            text="Install purchased",
                            icon_value=icon_value,
                        )
                    else:
                        props = row_right.operator(
                            "extensions.package_install",
                            text="Install",
                            icon_value=icon_value,
                        )
                    props.repo_index = repo_index
                    props.pkg_id = pkg_id

                # Full plan addons
                elif not bk_cache_pkg.get("is_free") and not bk_cache_pkg.get(
                    "is_for_sale"
                ):
                    # open website to subscribe
                    props = row_right.operator(
                        "wm.url_open",
                        text="Subscribe to Full Plan",
                        icon_value=icon_value,
                    )
                    props.url = "https://www.blenderkit.com/plans/pricing/"

                # Paid addons get a buy button and lead to their website link
                else:
                    # Use the new modal operator
                    props = row_right.operator(
                        BK_OT_buy_extension_and_watch.bl_idname,  # Use bl_idname
                        text=f"Buy online ${bk_cache_pkg.get('base_price')}",
                        icon_value=icon_value,
                    )
                    props.url = bk_cache_pkg.get("website", "")  # Pass URL
                    props.repo_index = repo_index  # Pass repo index
            ### end of BlenderKit specific code
    else:
        # Right space for alignment with the button.
        if has_remote and (item_remote is None):
            # There is a local item with no remote
            row_right.label(text="Orphan   ")

        row_right.active = False

    row_right = row_right_toplevel.row(align=True)
    row_right.alignment = "RIGHT"
    row_right.separator()

    # NOTE: Keep space between any buttons and this menu to prevent stray clicks accidentally running install.
    # The separator is around together with the align to give some space while keeping the button and the menu
    # still close-by. Used `extension_path` so the menu can access "this" extension.
    row_right.context_string_set(
        "extension_path", "{:s}.{:s}".format(repo_item.module, pkg_id)
    )
    row_right.menu("USERPREF_MT_extensions_item", text="", icon="DOWNARROW_HLT")

    if show:
        import os
        from bpy.app.translations import pgettext_iface as iface_

        col = layout.column()

        row = col.row()
        row.active = is_enabled

        # The full tagline may be multiple lines (not yet supported by Blender's UI).
        row.label(text=" {:s}.".format(item.tagline), translate=False)

        col.separator(type="LINE")

        col_info = layout.column()
        col_info.active = is_enabled
        split = col_info.split(factor=0.15)
        col_a = split.column()
        col_b = split.column()
        col_a.alignment = "RIGHT"

        if pkg_block is not None:
            col_a.label(text="Blocked")
            col_b.label(text=pkg_block.reason, translate=False)

        if item_warnings:
            col_a.label(text="Warning")
            col_b.label(text=item_warnings[0])
            if len(item_warnings) > 1:
                for value in item_warnings[1:]:
                    col_a.label(text="")
                    col_b.label(text=value)
                # pylint: disable-next=undefined-loop-variable

        if value := (item_remote or item_local).website:
            col_a.label(text="Website")
            col_b.split(factor=0.5).operator(
                "wm.url_open",
                text=exui.domain_extract_from_url(value),
                icon="URL",
            ).url = value
        del value

        if item.type == "add-on":
            col_a.label(text="Permissions")
            # WARNING: while this is documented to be a dict, old packages may contain a list of strings.
            # As it happens dictionary keys & list values both iterate over string,
            # however we will want to show the dictionary values eventually.
            if value := item.permissions:
                col_b.label(
                    text=", ".join([iface_(x).title() for x in value]), translate=False
                )
            else:
                col_b.label(text="No permissions specified")
            del value

        col_a.label(text="Maintainer")
        col_b.label(text=item.maintainer, translate=False)

        col_a.label(text="Version")
        if is_outdated:
            col_b.label(
                text=iface_("{:s} ({:s} available)").format(
                    item.version, item_remote.version
                ),
                translate=False,
            )
        else:
            col_b.label(text=item.version, translate=False)

        if has_remote and (item_remote is not None):
            col_a.label(text="Size")
            col_b.label(
                text=exui.size_as_fmt_string(item_remote.archive_size), translate=False
            )

        col_a.label(text="License")
        col_b.label(text=item.license, translate=False)

        col_a.label(text="Repository")
        col_b.label(text=repo_item.name, translate=False)

        if is_installed:
            col_a.label(text="Path")
            col_b.label(text=os.path.join(repo_item.directory, pkg_id), translate=False)


def extension_draw_item_override(
    layout,
    *,
    pkg_id,  # `str`
    item_local,  # `PkgManifest_Normalized | None`
    item_remote,  # `PkgManifest_Normalized | None`
    is_enabled,  # `bool`
    is_outdated,  # `bool`
    show,  # `bool`.
    mark,  # `bool | None`.
    # General vars.
    repo_index,  # `int`
    repo_item,  # `RepoItem`
    operation_in_progress,  # `bool`
    extensions_warnings,  # `dict[str, list[str]]`
    show_developer_ui=False,  # `bool`
):
    print("BlenderKit Debug: ENTERING extension_draw_item_override")
    # filter by verification state, only for blenderkit repository
    if repo_item.remote_url == EXTENSIONS_API_URL:
        extension_draw_item_blenderkit(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
            show_developer_ui=show_developer_ui,
        )
        return True

    # show developer ui only needs to be passed since blender 4.4
    if bpy.app.version >= (4, 4):
        exui.extension_draw_item_original(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
            show_developer_ui=show_developer_ui,
        )
    else:
        exui.extension_draw_item_original(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
        )

    return True


def override_draw_function():
    if hasattr(exui, "extension_draw_item_original"):
        return False
    exui.extension_draw_item_original = exui.extension_draw_item
    exui.extension_draw_item = extension_draw_item_override
    return True


def get_repository_by_url(url: str):
    """Get the repository by its remote URL, from registered blenderkit Extension repositories."""
    for r in bpy.context.preferences.extensions.repos:
        if r.remote_url == url:
            return r
    return None


def clear_repo_cache():
    """Clear the repository cache."""
    wm = bpy.context.window_manager
    cache_key = "blenderkit_extensions_repo_cache"
    if cache_key in wm:
        del wm[cache_key]


def ensure_repo_cache():
    """
    Reads the .json file blender stores in \extensions\www_blenderkit_com\.blender_ext
    and parses it to a dict from json, we can use it then for drawing purposes and have the extra data BlenderKit api provides.
    Checks the modification time of the cache file and reloads it if necessary.
    """
    reloaded_flag = False  # Track if we actually reloaded
    wm = bpy.context.window_manager
    cache_key = "blenderkit_extensions_repo_cache"
    mtime_key = "blenderkit_extensions_repo_cache_mtime"

    blenderkit_repository = get_repository_by_url(EXTENSIONS_API_URL)
    if blenderkit_repository is None:
        # If repo doesn't exist, clear cache if it exists in window manager
        if cache_key in wm:
            del wm[cache_key]
            print(f"BlenderKit: Cleared stale extension cache for missing repository.")
        if mtime_key in wm:
            del wm[mtime_key]
        print(f"BlenderKit Debug: Repository not found, exiting check.")
        return False  # No repo, nothing loaded

    # get the path to the cache file which is in repository directory under /.blender_ext/index.json
    cache_file = os.path.join(
        blenderkit_repository.directory, ".blender_ext", "index.json"
    )

    current_mtime = None
    try:
        if os.path.exists(cache_file):
            current_mtime = os.path.getmtime(cache_file)
    except OSError as e:  # Handle potential race condition or permission issue
        print(
            f"BlenderKit: Warning - Could not get modification time for {cache_file}: {e}"
        )
        # Clear cache if we can't verify its freshness? Safer approach.
        if cache_key in wm:
            del wm[cache_key]
            print(f"BlenderKit: Cleared extension cache due to mtime access error.")
        if mtime_key in wm:
            del wm[mtime_key]
        return False  # Error, nothing loaded

    stored_mtime = wm.get(mtime_key, None)

    # --- Determine if reload is needed ---
    should_reload = False
    if cache_key not in wm:
        if current_mtime is not None:  # Only load if file actually exists
            should_reload = True  # Cache doesn't exist, need initial load.
        else:
            # Cache doesn't exist and file doesn't exist/accessible. Fall through to check if we need to clear.
            pass

    elif current_mtime is None:
        # Cache exists in wm, but file is gone/inaccessible. Clear stale cache.
        del wm[cache_key]
        if mtime_key in wm:
            del wm[mtime_key]
        return False  # Cleared stale cache, did not load new data

    elif cache_key not in wm and current_mtime is None:
        # Cache doesn't exist, and file doesn't exist. Nothing to do or load.
        return False

    elif (
        cache_key in wm and (stored_mtime is None or stored_mtime != current_mtime)
    ) or (
        cache_key not in wm and current_mtime is not None
    ):  # Reload if cache exists and is outdated, OR if cache doesn't exist but file does
        should_reload = True  # Cache exists but is outdated or missing mtime.

    if not should_reload:
        # Cache exists and is up-to-date
        return False  # Nothing reloaded

    # --- (Re)Load cache ---
    try:
        with open(cache_file, "r", encoding="utf-8") as f:  # Specify encoding
            data_str = f.read()
        data = json.loads(data_str)

        # store the data as a dict with keys being the package names (first 32 chars)
        new_cache = {}
        for pkg in data.get(
            "data", []
        ):  # Handle case where 'data' key might be missing
            if (
                isinstance(pkg, dict) and "id" in pkg
            ):  # Ensure pkg is a dict and 'id' key exists
                new_cache[pkg["id"][:32]] = pkg
            else:
                print(f"BlenderKit: Skipping invalid package entry in cache: {pkg}")

        wm[cache_key] = new_cache
        wm[mtime_key] = current_mtime  # Update mtime only on successful load

        reloaded_flag = True  # Mark that we reloaded successfully

    except json.JSONDecodeError:
        print(
            f"BlenderKit: Error decoding JSON from {cache_file}. Cache not loaded/updated."
        )
        # Clear potentially corrupt cache? Or leave old one? Clearing is safer.
        if cache_key in wm:
            del wm[cache_key]
            print("BlenderKit: Cleared cache due to JSON error.")
        if mtime_key in wm:
            del wm[mtime_key]
    except Exception as e:
        print(f"BlenderKit: Error reading or processing cache file {cache_file}: {e}")
        # Clear potentially corrupt cache?
        if cache_key in wm:
            del wm[cache_key]
            print("BlenderKit: Cleared cache due to file processing error.")
        if mtime_key in wm:
            del wm[mtime_key]

    return reloaded_flag  # Return whether cache was actually reloaded


def ensure_repo_order():
    """Ensure order of repositories in Blender's preferences."""
    # get the blenderkit repository
    blenderkit_repository = get_repository_by_url(EXTENSIONS_API_URL)
    if blenderkit_repository is None:
        return

    # get all repositories
    all_repos = bpy.context.preferences.extensions.repos
    # get all online repositories except blenderkit
    online_repos = []  # need to convert repos to dicts
    remove_online_repos = []
    for r in all_repos:
        if r.remote_url != EXTENSIONS_API_URL and r.remote_url != "":

            repo_dict = {
                "name": r.name,
                "module": r.module,
                "use_remote_url": r.use_remote_url,
                "remote_url": r.remote_url,
                "use_sync_on_startup": r.use_sync_on_startup,
                "use_cache": r.use_cache,
                "use_access_token": r.use_access_token,
                "access_token": r.access_token,
                "use_custom_directory": r.use_custom_directory,
                "custom_directory": r.custom_directory,
                "enabled": r.enabled,
            }
            online_repos.append(repo_dict)
            remove_online_repos.append(r)

    # remove all online repositories except blenderkit
    for r in remove_online_repos:
        all_repos.remove(r)

    # add all other repositories back
    for r in online_repos:
        # complete list of properties of a repository:
        #'access_token', 'custom_directory', 'directory', 'enabled', 'module', 'name', 'remote_url', 'rna_type', 'source', 'use_access_token', 'use_cache', 'use_custom_directory', 'use_remote_url', 'use_sync_on_startup'

        new_repo = all_repos.new()
        new_repo.name = r["name"]
        new_repo.module = r["module"]
        new_repo.use_remote_url = r["use_remote_url"]
        new_repo.remote_url = r["remote_url"]
        new_repo.use_sync_on_startup = r["use_sync_on_startup"]
        new_repo.use_cache = r["use_cache"]
        new_repo.use_access_token = r["use_access_token"]
        new_repo.access_token = r["access_token"]
        new_repo.use_custom_directory = r["use_custom_directory"]
        new_repo.custom_directory = r["custom_directory"]
        new_repo.enabled = r["enabled"]


def ensure_repository(api_key: str = ""):
    """Ensure that the blenderkit extensions repository is correctly added in Blender's preferences.
    If the repository is not present, it is added. If the repository is present, but the API key is not set, it is set.
    """

    blenderkit_repository = get_repository_by_url(EXTENSIONS_API_URL)

    if blenderkit_repository is None:

        blenderkit_repository = bpy.context.preferences.extensions.repos.new()
        blenderkit_repository.name = "www.blenderkit.com"
        blenderkit_repository.module = "www_blenderkit_com"
        blenderkit_repository.use_remote_url = True
        blenderkit_repository.remote_url = EXTENSIONS_API_URL
        blenderkit_repository.use_sync_on_startup = True

    if api_key != "":
        blenderkit_repository.use_access_token = True
        blenderkit_repository.access_token = api_key
    else:
        # let's try to import blenderkit preferences and get the api key
        # try:
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        api_key = user_preferences.api_key
        if api_key != "":
            blenderkit_repository.use_access_token = True
            blenderkit_repository.access_token = api_key
        else:
            # clear after logout
            blenderkit_repository.use_access_token = False
            blenderkit_repository.access_token = ""
        # pass
    # ensure_repo_order()
    ensure_repo_cache()


def register():

    ensure_repository()
    override_draw_function()
    bpy.utils.register_class(BK_OT_buy_extension_and_watch)  # Register new operator


def unregister():
    exui.extension_draw_item = exui.extension_draw_item_original
    del exui.extension_draw_item_original
    bpy.utils.unregister_class(BK_OT_buy_extension_and_watch)  # Unregister new operator
