import dataclasses
from typing import Optional


def asdict(data_class) -> dict:
    return dataclasses.asdict(data_class)


@dataclasses.dataclass
class Prefs:
    debug_value: int
    binary_path: str
    addon_dir: str
    addon_module_name: str
    app_id: int
    download_counter: int
    asset_popup_counter: int
    welcome_operator_counter: int
    api_key: str
    api_key_refresh: str
    api_key_timeout: int
    experimental_features: bool
    keep_preferences: bool
    directory_behaviour: str
    global_dir: str
    project_subdir: str
    unpack_files: bool
    show_on_start: bool
    thumb_size: int
    max_assetbar_rows: int
    search_field_width: int
    search_in_header: bool
    tips_on_start: bool
    announcements_on_start: bool
    client_port: str
    ip_version: str
    ssl_context: str
    proxy_which: str
    proxy_address: str
    trusted_ca_certs: str
    auto_check_update: bool
    enable_prereleases: bool
    updater_interval_months: int
    updater_interval_days: int
    resolution: str
    material_import_automap: bool


@dataclasses.dataclass
class SearchData:
    """Data needed to make a Search request."""

    PREFS: Prefs
    tempdir: str
    urlquery: str
    asset_type: str
    scene_uuid: str
    get_next: bool
    page_size: int
    blender_version: str
    addon_version: str = ""
    platform_version: str = ""
    api_key: str = ""
    app_id: int = 0
    is_validator: bool = (
        False  # Client makes some extra stuff for validators - like fetching all the ratings right away
    )
    history_id: str = ""


@dataclasses.dataclass
class SocialNetwork:
    url: str
    icon: str
    name: str
    order: int


def parse_social_networks(networks: list[dict]) -> list[SocialNetwork]:
    social_networks = []
    for network in networks:
        url = network.get("url", "")
        n = network.get("socialNetwork", {})
        social_network = SocialNetwork(
            url=url,
            icon=n.get("icon", ""),
            name=n.get("name", ""),
            order=n.get("order", -1),
        )
        social_networks.append(social_network)
    return social_networks


@dataclasses.dataclass
class UserProfile:
    """This is public information about profiles of others."""

    aboutMe: str
    aboutMeUrl: str
    avatar128: str
    firstName: str
    fullName: str
    gravatarHash: str
    id: int
    lastName: str
    socialNetworks: list[SocialNetwork] = dataclasses.field(default_factory=list)
    avatar256: str = ""
    gravatarImg: str = ""  # filled later from getGravatar task
    tooltip: str = ""  # generated later from Name and AboutMe etc.


@dataclasses.dataclass
class MineProfile:
    """
    This is private information about current user's profile. Fields can be also None.
    Because API can just return null just for fun (https://github.com/BlenderKit/BlenderKit/issues/1545#event-17220997340).
    None/null is not 0 or "" however, so we keep the None to distinguish both states.
    As result the Nones has to be catched later in code, types are just hints in here!
    """

    aboutMe: str = ""
    aboutMeUrl: str = ""
    avatar128: str = ""
    avatar256: str = ""
    avatar512: str = ""
    currentPlanName: str = ""
    email: str = ""
    firstName: str = ""
    fullName: str = ""
    gravatarHash: str = ""
    hasFreePlan: bool = True
    id: int = -1
    lastName: str = ""
    remainingPrivateQuota: int = 0
    sumAssetFilesSize: int = 0
    sumPrivateAssetFilesSize: int = 0
    username: str = ""
    socialNetworks: list[SocialNetwork] = dataclasses.field(default_factory=list)
    gravatarImg: str = ""  # filled later from getGravatar task
    tooltip: str = ""  # generated later from Name and AboutMe etc.
    canEditAllAssets: bool = False  # whether User is validator

    def __bool__(self):
        return self.id != -1


@dataclasses.dataclass
class AssetRating:
    bookmarks: Optional[int] = None  # name kept as comes from API
    quality: Optional[int] = None
    quality_fetched: bool = False
    working_hours: Optional[float] = None  # name kept as comes from API
    working_hours_fetched: bool = False
    # TODO: Add last time ratings checked to improve caching
