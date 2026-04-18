"""Minimal PRX file format reader/writer for Proxor Lite."""

from __future__ import annotations

import base64
import gzip
import logging
import random
from collections.abc import Sequence
from typing import Optional

LOG = logging.getLogger(__name__)

VECTOR_SIZE = 3
RGB_SIZE = VECTOR_SIZE
RGBA_SIZE = 4
BOUND_SIZE = 6
LINE_MIN_POINTS = 2
EPSILON = 1e-9
MIN_VERSION_TOKENS = 2
PROXOR_VERSION_TAG = "PROXOR_VERSION"
PROXOR_VERSION_STRING = "1.0.0"
PRX_VERSION_LINE = f"# {PROXOR_VERSION_TAG} {PROXOR_VERSION_STRING}"

DEFAULT_FACE_NORMAL = (0.0, 1.0, 0.0)
DEFAULT_OBJECT_COLOR = (0.3, 0.3, 0.3)

# -- Normalisation helpers --


def random_color(in_string: str) -> list[float]:
    """Generate a stable random color seeded by *in_string*."""
    random.seed(in_string)
    col = [random.uniform(0.0, 1.0) for _ in range(RGB_SIZE)]  # noqa: S311
    try:
        random.seed(a=None, version=2)
    except Exception:  # noqa: BLE001
        random.seed(a=None)
    return col


def _safe_float_list(values: Sequence[str]) -> list[float]:
    converted: list[float] = []
    for value in values:
        try:
            converted.append(float(value))
        except ValueError:  # noqa: PERF203
            converted.append(0.0)
    return converted


def _bbox_spans(bbox: Sequence[float]) -> list[float]:
    return [
        max(bbox[1] - bbox[0], EPSILON),
        max(bbox[3] - bbox[2], EPSILON),
        max(bbox[5] - bbox[4], EPSILON),
    ]


def _denormalize_points(
    points: Sequence[Sequence[float]],
    bbox: Sequence[float],
    spans: Sequence[float],
) -> list[list[float]]:
    denormalized: list[list[float]] = []
    for point in points:
        if len(point) < VECTOR_SIZE:
            continue
        denormalized.append(
            [
                bbox[0] + point[0] * spans[0],
                bbox[2] + point[1] * spans[1],
                bbox[4] + point[2] * spans[2],
            ]
        )
    return denormalized


def _denormalize_normals(normals: Sequence[Sequence[float]]) -> list[list[float]]:
    return [
        [(c * 2.0) - 1.0 for c in n[:VECTOR_SIZE]]
        for n in normals
        if len(n) >= VECTOR_SIZE
    ]


def _normalize_points(
    points: Sequence[Sequence[float]],
    bbox: Sequence[float],
    spans: Sequence[float],
) -> list[list[float]]:
    normalized: list[list[float]] = []
    for point in points:
        if len(point) < VECTOR_SIZE:
            continue
        normalized.append(
            [
                (point[0] - bbox[0]) / spans[0],
                (point[1] - bbox[2]) / spans[1],
                (point[2] - bbox[4]) / spans[2],
            ]
        )
    return normalized


def _normalize_normals(normals: Sequence[Sequence[float]]) -> list[list[float]]:
    return [
        [(c * 0.5) + 0.5 for c in n[:VECTOR_SIZE]]
        for n in normals
        if len(n) >= VECTOR_SIZE
    ]


def _limit_components(
    values: Sequence[Sequence[float]], *, count: int
) -> list[list[float]]:
    limited: list[list[float]] = []
    for item in values:
        if not item:
            continue
        trimmed = list(item[:count])
        if len(trimmed) < count:
            trimmed.extend([trimmed[-1] if trimmed else 0.0] * (count - len(trimmed)))
        limited.append(trimmed)
    return limited


def _flatten_sections(
    sections: Sequence[Sequence[Sequence[float]]],
) -> list[Sequence[float]]:
    flattened: list[Sequence[float]] = []
    for section in sections or []:
        flattened.extend(section)
    return flattened


# -- Reading --


def _load_prx_lines(file_path: str) -> list[str]:
    if file_path.lower().endswith(".prxc"):
        with open(file_path, "rb") as handle:
            payload = handle.read()
        decoded = base64.b64decode(payload)
        decompressed = gzip.decompress(decoded)
        text = decompressed.decode("utf-8")
        return [line for line in text.splitlines() if line.strip()]
    with open(file_path, encoding="utf-8") as handle:
        return [line for line in handle if line.strip()]


def _parse_prx_lines(lines: Sequence[str]) -> tuple[list[dict], Optional[str]]:
    known_blocks = {"F", "FC", "FN", "P", "PC", "L", "LC", "BB", "O", "C"}
    block_headers = {"F", "FC", "FN", "P", "PC", "L", "LC"}

    objects: list[dict] = []
    current: Optional[dict] = None
    current_block: Optional[str] = None
    file_version: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if file_version is None:
                body = line[1:].strip().upper()
                if body.startswith(PROXOR_VERSION_TAG):
                    parts = line[1:].strip().split()
                    if len(parts) >= MIN_VERSION_TOKENS:
                        file_version = parts[1]
            continue
        if line.startswith("@"):
            if current:
                objects.append(current)
            current = {
                "name": line[1:].strip() or "object",
                "bounding_box": None,
                "origin": None,
                "color": None,
                "blocks": {},
            }
            current_block = None
            continue
        if current is None:
            continue
        head = line.split()[0]
        if head not in known_blocks and current_block is None:
            continue
        if head in {"BB", "O", "C"}:
            values = _safe_float_list(line.split()[1:])
            if head == "BB":
                current["bounding_box"] = values
            elif head == "O":
                current["origin"] = values
            else:
                current["color"] = values
            current_block = None
            continue
        if head in block_headers and len(line.split()) == 1:
            current_block = head
            buckets = current.setdefault("blocks", {})
            sections = buckets.setdefault(head, [])
            sections.append([])
            continue
        if current_block:
            values = _safe_float_list(line.split())
            if values:
                buckets = current.setdefault("blocks", {})
                sections = buckets.setdefault(current_block, [])
                if not sections:
                    sections.append([])
                sections[-1].append(values)
    if current:
        objects.append(current)
    return objects, file_version


def _build_output_data(
    objects: Sequence[dict],
    default_color: tuple[float, float, float] = DEFAULT_OBJECT_COLOR,
) -> dict:
    """Build a legacy payload dict from parsed PRX objects."""
    mesh_positions: list[list[float]] = []
    mesh_colors: list[list[float]] = []
    mesh_normals: list[list[float]] = []
    line_positions: list[list[float]] = []
    line_colors: list[list[float]] = []
    point_positions: list[list[float]] = []
    point_colors: list[list[float]] = []

    for obj in objects:
        bbox = obj.get("bounding_box")
        if not bbox or len(bbox) < BOUND_SIZE:
            continue
        spans = _bbox_spans(bbox)
        blocks = obj.get("blocks", {})

        # Mesh faces
        face_pts = _denormalize_points(
            _flatten_sections(blocks.get("F", [])), bbox, spans
        )
        face_nrm = _denormalize_normals(_flatten_sections(blocks.get("FN", [])))
        face_col = _limit_components(
            _flatten_sections(blocks.get("FC", [])), count=RGB_SIZE
        )
        if face_pts:
            mesh_positions.extend(face_pts)
            if len(face_col) != len(face_pts):
                face_col = face_col or [list(default_color)] * len(face_pts)
                repeats = (len(face_pts) + len(face_col) - 1) // len(face_col)
                face_col = (face_col * repeats)[: len(face_pts)]
            mesh_colors.extend(face_col)
            if len(face_nrm) != len(face_pts):
                face_nrm = [list(DEFAULT_FACE_NORMAL)] * len(face_pts)
            mesh_normals.extend(face_nrm)

        # Points
        point_secs = blocks.get("P", [])
        if point_secs:
            pts = _denormalize_points(_flatten_sections(point_secs), bbox, spans)
            if pts:
                point_positions.extend(pts)
                pc = _limit_components(
                    _flatten_sections(blocks.get("PC", []) or []), count=RGBA_SIZE
                )
                if not pc:
                    base = obj.get("color") or list(default_color)
                    if len(base) < RGBA_SIZE:
                        base = [*base[:RGB_SIZE], 1.0][:RGBA_SIZE]
                    pc = [list(base[:RGBA_SIZE])] * len(pts)
                elif len(pc) != len(pts):
                    repeats = (len(pts) + len(pc) - 1) // len(pc)
                    pc = (pc * repeats)[: len(pts)]
                point_colors.extend(pc)

        # Lines
        for idx, section in enumerate(blocks.get("L", []) or []):
            den = _denormalize_points(section, bbox, spans)
            if len(den) < LINE_MIN_POINTS:
                continue
            lc_sections = blocks.get("LC", []) or []
            lc_sec = lc_sections[idx] if idx < len(lc_sections) else []
            for seg in range(len(den) - 1):
                line_positions.extend([den[seg], den[seg + 1]])
                if lc_sec and seg < len(lc_sec):
                    col = (
                        list(lc_sec[seg][:RGB_SIZE])
                        if len(lc_sec[seg]) >= RGB_SIZE
                        else list(default_color)
                    )
                else:
                    col = list(default_color)
                line_colors.extend([col, col])

    return {
        "mesh": {"pos": mesh_positions, "col": mesh_colors, "nrm": mesh_normals},
        "line": {"pos": line_positions, "col": line_colors},
        "points": {"pos": point_positions, "col": point_colors},
        "text": {"pos": [], "col": [], "str": []},
    }


def read_prx(file_path: str) -> dict:
    """Read a PRX / PRXC file and return a payload dict with ``legacy`` key."""
    lines = _load_prx_lines(file_path)
    objects, version = _parse_prx_lines(lines)
    data = _build_output_data(objects)
    return {"legacy": data, "objects": objects, "version": version}


# -- Writing --


def _compute_bounding_box(points: Sequence[Sequence[float]]) -> list[float]:
    xs = [p[0] for p in points if len(p) >= VECTOR_SIZE]
    ys = [p[1] for p in points if len(p) >= VECTOR_SIZE]
    zs = [p[2] for p in points if len(p) >= VECTOR_SIZE]
    if not xs:
        return [0.0] * BOUND_SIZE
    return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]


def _fmt(value: float, precision: int = 4) -> str:
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


def write_prx(
    file_path: str,
    payload: dict,
    *,
    name: str = "object",
    precision: int = 4,
    compress: bool = False,
    include_mesh: bool = True,
    include_lines: bool = True,
    include_points: bool = True,
    include_colors: bool = True,
) -> None:
    """Write a PRX payload to disk.

    Args:
        file_path: Destination path (.prx or .prxc).
        payload: Dict with ``legacy`` key containing mesh/line/points sections.
        name: Object name for the PRX file.
        precision: Float precision for coordinates.
        compress: If True write base64+gzip compressed .prxc format.
        include_mesh: If True include face/mesh data in the output.
        include_lines: If True include line/wireframe data in the output.
        include_points: If True include point cloud data in the output.
        include_colors: If True include colour data in the output.
    """
    legacy = payload.get("legacy", {})
    lines: list[str] = [PRX_VERSION_LINE]
    lines.append(f"@{name}")

    all_pts: list[list[float]] = []
    for section_key in ("mesh", "points", "line"):
        sec = legacy.get(section_key, {})
        all_pts.extend(sec.get("pos", []))

    if not all_pts:
        return

    bbox = _compute_bounding_box(all_pts)
    spans = _bbox_spans(bbox)
    lines.append("BB " + " ".join(_fmt(v, precision) for v in bbox))

    # Mesh faces
    mesh = legacy.get("mesh", {})
    mesh_pos = mesh.get("pos", [])
    if include_mesh and mesh_pos:
        norm_pts = _normalize_points(mesh_pos, bbox, spans)
        lines.append("F")
        lines.extend(" ".join(_fmt(v, precision) for v in pt) for pt in norm_pts)
        mesh_col = mesh.get("col", [])
        if include_colors and mesh_col:
            lines.append("FC")
            lines.extend(
                " ".join(_fmt(v, precision) for v in col[:RGB_SIZE]) for col in mesh_col
            )
        mesh_nrm = mesh.get("nrm", [])
        if mesh_nrm:
            norm_nrm = _normalize_normals(mesh_nrm)
            lines.append("FN")
            lines.extend(" ".join(_fmt(v, precision) for v in nrm) for nrm in norm_nrm)

    # Points
    pts_sec = legacy.get("points", {})
    pts_pos = pts_sec.get("pos", [])
    if include_points and pts_pos:
        norm_pts = _normalize_points(pts_pos, bbox, spans)
        lines.append("P")
        lines.extend(" ".join(_fmt(v, precision) for v in pt) for pt in norm_pts)
        pts_col = pts_sec.get("col", [])
        if include_colors and pts_col:
            lines.append("PC")
            lines.extend(
                " ".join(_fmt(v, precision) for v in col[:RGBA_SIZE]) for col in pts_col
            )

    # Lines — write each segment pair as a separate L block so
    # the reader does not chain unrelated endpoints into a polyline.
    line_sec = legacy.get("line", {})
    line_pos = line_sec.get("pos", [])
    if include_lines and line_pos:
        norm_lp = _normalize_points(line_pos, bbox, spans)
        line_col = line_sec.get("col", [])
        for seg_idx in range(0, len(norm_lp) - 1, 2):
            seg = norm_lp[seg_idx : seg_idx + 2]
            lines.append("L")
            lines.extend(" ".join(_fmt(v, precision) for v in pt) for pt in seg)
            if include_colors and line_col:
                col_idx = min(seg_idx, len(line_col) - 1)
                col = line_col[col_idx]
                lines.append("LC")
                lines.append(" ".join(_fmt(v, precision) for v in col[:RGB_SIZE]))

    text = "\n".join(lines) + "\n"
    if compress or file_path.lower().endswith(".prxc"):
        encoded = base64.b64encode(gzip.compress(text.encode("utf-8")))
        with open(file_path, "wb") as handle:
            handle.write(encoded)
    else:
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(text)


__all__ = [
    "PRX_VERSION_LINE",
    "read_prx",
    "write_prx",
]
