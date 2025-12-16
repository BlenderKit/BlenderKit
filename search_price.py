from typing import Iterable, List, Optional, Tuple

from . import client_lib, paths, utils


def _normalize_version_uuid_list(values: Optional[Iterable[str]]) -> List[str]:
    if values is None:
        return []

    normalized: List[str] = []
    for value in values:
        if not value:
            continue
        as_str = str(value)
        if as_str not in normalized:
            normalized.append(as_str)
    return normalized


def query_user_price(
    version_uuids: list[str] = [],
    page_size: int = 15,
    timeout: Tuple[float, float] = (1, 30),
) -> dict:
    """Return results for price lookup of multiple asset versions.

    The server endpoint now expects a POST body with `version_uuids`, so we keep
    the helper focused on returning the correct URL alongside the JSON payload
    that should be sent in the request.
    """

    if isinstance(version_uuids, str):
        version_uuids = [version_uuids]

    version_uuid_list = _normalize_version_uuid_list(version_uuids)
    if page_size > 0:
        version_uuid_list = version_uuid_list[:page_size]

    payload: dict = {"version_uuids": version_uuid_list}

    url = f"{paths.BLENDERKIT_API}/cart/request-price-bulk/"

    if not payload["version_uuids"]:
        raise ValueError("No version UUIDs provided for price lookup.")

    headers = utils.get_simple_headers()
    headers.setdefault("Content-Type", "application/json")

    response = client_lib.blocking_request(
        url,
        "POST",
        headers,
        json_data=payload,
        timeout=timeout,
    )
    search_results = response.json()
    return search_results
