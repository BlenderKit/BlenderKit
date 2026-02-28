# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import bpy
import rna_keymap_ui


bk_logger = logging.getLogger(__name__)


@dataclass
class KeyMapItemDef:
    """Description of a keymap item we want to register."""

    idname: str
    type: str
    value: str
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    oskey: bool = False
    key_modifier: str = "NONE"
    properties: Dict[str, object] = field(default_factory=dict)


@dataclass
class KeyMapDef:
    """Description of a keymap with its items."""

    name: str
    space_type: str
    region_type: str = "WINDOW"
    items: List[KeyMapItemDef] = field(default_factory=list)


# Default bindings we ship. Users can edit these in Preferences.
DEFAULT_KEYMAP_ITEMS: List[KeyMapItemDef] = [
    KeyMapItemDef(
        idname="view3d.run_assetbar_fix_context",
        type="SEMI_COLON",
        value="PRESS",
        properties={"keep_running": False, "do_search": False},
    ),
    KeyMapItemDef(
        idname="wm.blenderkit_menu_rating_upload",
        type="R",
        value="PRESS",
    ),
]

DEFAULT_KEYMAPS: List[KeyMapDef] = [
    # Register into the standard "Window" keymap so Blender shows it in the main tree.
    KeyMapDef(
        name="Window",  # must be windows otherwise blender will not show it in the default keymap
        space_type="EMPTY",
        region_type="WINDOW",
        items=DEFAULT_KEYMAP_ITEMS,
    ),
]

# Store only the keymap items we create so we can clean them up without touching user overrides.
_registered_keymaps: List[
    Tuple[bpy.types.KeyConfig, bpy.types.KeyMap, bpy.types.KeyMapItem]
] = []


def _keymap_has_item(
    km: bpy.types.KeyMap, idname: str
) -> Optional[bpy.types.KeyMapItem]:
    for item in km.keymap_items:
        if item.idname == idname:
            return item
    return None


def _find_in_keyconfig(
    keyconfig: bpy.types.KeyConfig, idname: str
) -> Optional[bpy.types.KeyMapItem]:
    for km in keyconfig.keymaps:
        kmi = _keymap_has_item(km, idname)
        if kmi:
            return kmi
    return None


def _get_target_keyconfigs() -> List[bpy.types.KeyConfig]:
    """Return keyconfigs to register into, ordered by preference.

    We register into both the user keyconfig (shows in main tree/search) and the
    add-on keyconfig (visible under Preferences → Keymap → Add-ons) when available.
    """

    wm = bpy.context.window_manager
    if not wm:
        return []

    targets: List[bpy.types.KeyConfig] = []
    if wm.keyconfigs.user:
        targets.append(wm.keyconfigs.user)
    if wm.keyconfigs.addon and wm.keyconfigs.addon not in targets:
        targets.append(wm.keyconfigs.addon)
    if not targets and wm.keyconfigs.active:
        targets.append(wm.keyconfigs.active)
    return targets


def register_keymaps(custom_keymaps: Optional[Iterable[KeyMapDef]] = None) -> None:
    """Register keymaps for the add-on.

    Args:
        custom_keymaps: Optional iterable of KeyMapDef if callers want to override defaults.
    """

    wm = bpy.context.window_manager
    if not wm:
        bk_logger.warning("Unable to register keymaps: no window manager available")
        return
    kc_addon = wm.keyconfigs.addon
    kc_user = wm.keyconfigs.user
    if not kc_addon:
        bk_logger.warning("Unable to register keymaps: no add-on keyconfig available")
        return
    bk_logger.debug("Registering keymaps for BlenderKit add-on")

    keymaps = list(custom_keymaps) if custom_keymaps is not None else DEFAULT_KEYMAPS

    for km_def in keymaps:
        # If the user already has a custom binding in their keyconfig, don't recreate it.
        if kc_user and _find_in_keyconfig(kc_user, km_def.items[0].idname):
            bk_logger.debug(
                f"User keyconfig already has binding for {km_def.items[0].idname}; leaving user override intact"
            )
            continue

        km = kc_addon.keymaps.find(
            km_def.name, space_type=km_def.space_type, region_type=km_def.region_type
        )
        if km is None:
            bk_logger.debug(
                f"Keymap {km_def.name} not found in {kc_addon.name}, creating new one"
            )
            km = kc_addon.keymaps.new(
                name=km_def.name,
                space_type=km_def.space_type,
                region_type=km_def.region_type,
            )

        for item_def in km_def.items:
            if _keymap_has_item(km, item_def.idname):
                bk_logger.debug(
                    f"Keymap {km_def.name} in {kc_addon.name} already has item {item_def.idname}, skipping"
                )
                continue
            bk_logger.debug(
                f"Adding keymap item {item_def.idname} to keymap {km_def.name} in {kc_addon.name}"
            )
            kmi = km.keymap_items.new(
                idname=item_def.idname,
                type=item_def.type,
                value=item_def.value,
                shift=item_def.shift,
                ctrl=item_def.ctrl,
                alt=item_def.alt,
                oskey=item_def.oskey,
                key_modifier=item_def.key_modifier,
            )
            for prop_name, prop_value in item_def.properties.items():
                bk_logger.debug(
                    f"Setting property {prop_name}={prop_value} on keymap item {item_def.idname} in {kc_addon.name}"
                )
                setattr(kmi.properties, prop_name, prop_value)
            _registered_keymaps.append((kc_addon, km, kmi))
    wm.keyconfigs.update(keep_properties=True)


def unregister_keymaps() -> None:
    if not _registered_keymaps:
        return

    for kc, km, kmi in _registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except RuntimeError:
            # Already removed by user; ignore.
            pass
    _registered_keymaps.clear()


def get_keymap_item(idname: str) -> Optional[bpy.types.KeyMapItem]:
    """Return the current keymap item for the given operator.

    Prefers the user's key configuration (where edits are stored) and falls back to the
    add-on keyconfig defaults.
    """

    wm = bpy.context.window_manager
    if not wm:
        return None

    for cfg in (wm.keyconfigs.user, wm.keyconfigs.addon):
        if cfg:
            kmi = _find_in_keyconfig(cfg, idname)
            if kmi:
                return kmi
    return None


def format_keymap_item(kmi: bpy.types.KeyMapItem) -> str:
    """Return a human readable shortcut label for a KeyMapItem."""

    parts = []
    if kmi.ctrl:
        parts.append("Ctrl")
    if kmi.alt:
        parts.append("Alt")
    if kmi.shift:
        parts.append("Shift")
    if kmi.oskey:
        parts.append("Cmd")
    if kmi.key_modifier and kmi.key_modifier != "NONE":
        parts.append(kmi.key_modifier.replace("_", " ").title())
    parts.append(kmi.type.replace("_", " ").title())
    return "+".join(parts)


def get_shortcut_label(idname: str, fallback: str = "") -> str:
    """Return a formatted shortcut string for the operator if available."""

    kmi = get_keymap_item(idname)
    if not kmi:
        return fallback
    return format_keymap_item(kmi)


def _find_km_and_kmi(
    keyconfig: bpy.types.KeyConfig, idname: str
) -> Optional[Tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]]:
    if not keyconfig:
        return None
    for km in keyconfig.keymaps:
        kmi = _keymap_has_item(km, idname)
        if kmi:
            return km, kmi
    return None


def draw_keymap(self, context):
    layout = self.layout
    wm = context.window_manager
    kc_addon = wm.keyconfigs.addon
    kc_user = wm.keyconfigs.user
    if not kc_addon:
        return

    box = layout.box()
    box.label(text="BlenderKit Keymaps")

    for item_def in DEFAULT_KEYMAP_ITEMS:
        # Prefer user override if available, otherwise show addon default.
        entry = _find_km_and_kmi(kc_user, item_def.idname) if kc_user else None
        source_kc = kc_user if entry else kc_addon
        km, kmi = (
            entry
            if entry
            else _find_km_and_kmi(kc_addon, item_def.idname) or (None, None)
        )
        if not km or not kmi:
            continue
        rna_keymap_ui.draw_kmi([], source_kc, km, kmi, box, 0)
