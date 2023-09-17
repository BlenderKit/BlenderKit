import json
import logging
import os

import bpy

from . import paths, utils


bk_logger = logging.getLogger(__name__)


def keep_preferences_property_updated(user_preferences, context):
    """Delete persistent JSON preferences file if keep_preferences was set to False. Call save_prefs() in all cases."""
    if user_preferences.keep_preferences is True:
        return utils.save_prefs(user_preferences, context)

    settings_path = paths.BLENDERKIT_SETTINGS_FILENAME
    if os.path.exists(settings_path) is False:
        return utils.save_prefs(user_preferences, context)

    try:
        os.remove(settings_path)
        bk_logger.info(f"Deleted preferences file {settings_path}")
    except Exception as e:
        bk_logger.error(f"Failed to delete preferences file {settings_path}: {e}")
    utils.save_prefs(user_preferences, context)


def write_preferences_to_JSON(preferences: dict):
    if not os.path.exists(paths._presets):
        os.makedirs(paths._presets)

    try:
        settings_path = paths.BLENDERKIT_SETTINGS_FILENAME
        with open(settings_path, "w", encoding="utf-8") as s:
            json.dump(preferences, s, ensure_ascii=False, indent=4)
        bk_logger.info(f"Saved preferences to {settings_path}")
    except Exception as e:
        bk_logger.warning(f"Failed to save preferences: {e}")


def asset_counter_property_updated(user_preferences, context):
    """Update asset counter in persistent JSON preferences file."""
    print(
        "asset_counter_property_updated, writting to json:",
        user_preferences.asset_counter,
    )
    prefs = utils.get_preferences_as_dict()
    write_preferences_to_JSON(prefs)  # TODO: WRITE TO SOME OTHER FILE
    # SO THAT ASSETS ARE COUNTED ALSO FOR USERS WHO DO NOT HAVE KEEP_PREFERENCES ENABLED
    print("wrote asset_counter:", prefs.get("asset_counter"))


def load_preferences_from_JSON():
    """Load preferences from JSON file and update the user preferences accordingly."""
    user_preferences = bpy.context.preferences.addons["blenderkit"].preferences
    # wm = bpy.context.window_manager

    fpath = paths.BLENDERKIT_SETTINGS_FILENAME
    if os.path.exists(fpath) is not True:
        return utils.get_preferences_as_dict()

    try:
        with open(fpath, "r", encoding="utf-8") as s:
            prefs = json.load(s)
    except Exception as e:
        bk_logger.warning("Failed to read preferences from JSON: {e}")
        os.remove(fpath)
        return utils.get_preferences_as_dict()

    user_preferences.preferences_lock = True

    # SYSTEM STUFF
    user_preferences.asset_counter = prefs.get(
        "asset_counter", user_preferences.asset_counter
    )
    bk_logger.info(f"Asset counter is: {user_preferences.asset_counter}")

    # MAIN PREFERENCES
    user_preferences.api_key = prefs.get("api_key", user_preferences.api_key)
    user_preferences.api_key_refresh = prefs.get(
        "api_key_refresh", user_preferences.api_key_refresh
    )
    user_preferences.api_key_timeout = prefs.get(
        "api_key_timeout", user_preferences.api_key_timeout
    )
    user_preferences.experimental_features = prefs.get(
        "experimental_features", user_preferences.experimental_features
    )
    user_preferences.keep_preferences = prefs.get(
        "keep_preferences", user_preferences.keep_preferences
    )

    # FILE PATHS
    user_preferences.directory_behaviour = prefs.get(
        "directory_behaviour", user_preferences.directory_behaviour
    )
    user_preferences.global_dir = prefs.get("global_dir", user_preferences.global_dir)
    user_preferences.project_subdir = prefs.get(
        "project_subdir", user_preferences.project_subdir
    )
    user_preferences.unpack_files = prefs.get(
        "unpack_files", user_preferences.unpack_files
    )

    # GUI
    user_preferences.show_on_start = prefs.get(
        "show_on_start", user_preferences.show_on_start
    )
    user_preferences.thumb_size = prefs.get("thumb_size", user_preferences.thumb_size)
    user_preferences.max_assetbar_rows = prefs.get(
        "max_assetbar_rows", user_preferences.max_assetbar_rows
    )
    user_preferences.search_field_width = prefs.get(
        "search_field_width", user_preferences.search_field_width
    )
    user_preferences.search_in_header = prefs.get(
        "search_in_header", user_preferences.search_in_header
    )
    user_preferences.tips_on_start = prefs.get(
        "tips_on_start", user_preferences.tips_on_start
    )
    user_preferences.announcements_on_start = prefs.get(
        "announcements_on_start", user_preferences.announcements_on_start
    )

    # NETWORK
    user_preferences.daemon_port = prefs.get(
        "daemon_port", user_preferences.daemon_port
    )
    user_preferences.ip_version = prefs.get("ip_version", user_preferences.ip_version)
    user_preferences.ssl_context = prefs.get(
        "ssl_context", user_preferences.ssl_context
    )
    user_preferences.proxy_which = prefs.get(
        "proxy_which", user_preferences.proxy_which
    )
    user_preferences.proxy_address = prefs.get(
        "proxy_address", user_preferences.proxy_address
    )
    user_preferences.trusted_ca_certs = prefs.get(
        "trusted_ca_certs", user_preferences.trusted_ca_certs
    )

    # UPDATES
    user_preferences.auto_check_update = prefs.get(
        "auto_check_update", user_preferences.auto_check_update
    )
    user_preferences.enable_prereleases = prefs.get(
        "enable_prereleases", user_preferences.enable_prereleases
    )
    user_preferences.updater_interval_months = prefs.get(
        "updater_interval_months", user_preferences.updater_interval_months
    )
    user_preferences.updater_interval_days = prefs.get(
        "updater_interval_days", user_preferences.updater_interval_days
    )

    # IMPORT SETTINGS
    user_preferences.resolution = prefs.get("resolution", user_preferences.resolution)

    # wm.blenderkit_models.resolution = prefs.get("models_resolution")
    # wm.blenderkit_mat.resolution = prefs.get("materials_resolution")
    # wm.blenderkit_HDR.resolution = prefs.get("hdrs_resolution")
    bk_logger.info(f"Successfully loaded preferences from {fpath}")
    user_preferences.preferences_lock = False
    return prefs
