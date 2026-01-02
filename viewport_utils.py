import bpy


def _unique_window_regions(area):
    if area is None:
        return

    seen = set()

    def _register(region):
        if getattr(region, "type", None) != "WINDOW":
            return None
        try:
            handle = region.as_pointer()
        except ReferenceError:
            return None
        if handle in seen:
            return None
        seen.add(handle)
        return region

    for region in getattr(area, "regions", []):
        candidate = _register(region)
        if candidate is not None:
            yield candidate

    space = None
    try:
        space = area.spaces.active
    except ReferenceError:
        space = None

    if getattr(space, "type", None) != "VIEW_3D":
        return

    quadviews = getattr(space, "region_quadviews", None)
    if not quadviews:
        return

    for quad in quadviews:
        candidate = _register(getattr(quad, "region", None))
        if candidate is not None:
            yield candidate


def iter_view3d_window_regions(area):
    """Yield every VIEW_3D window region for the given area (quad view included)."""
    yield from _unique_window_regions(area)


def region_data_for_view(area, region):
    """Return the RegionView3D that belongs to the given area/region pair."""
    if region is None or getattr(region, "type", None) != "WINDOW":
        return None

    direct_data = getattr(region, "data", None)
    if direct_data is not None:
        return direct_data

    if area is None:
        return None

    try:
        region_ptr = region.as_pointer()
    except ReferenceError:
        return None

    for space in getattr(area, "spaces", []):
        if getattr(space, "type", None) != "VIEW_3D":
            continue

        quadviews = getattr(space, "region_quadviews", None)
        if quadviews:
            for quad in quadviews:
                quad_region = getattr(quad, "region", None)
                if quad_region is None:
                    continue
                try:
                    if quad_region.as_pointer() == region_ptr:
                        return getattr(quad, "region_3d", None)
                except ReferenceError:
                    continue

        region_3d = getattr(space, "region_3d", None)
        if region_3d is not None:
            return region_3d

    return None
