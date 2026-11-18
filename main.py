"""Compare a manually annotated JSON file against the reference annotation.

Usage:
    python main.py <annotated.json> <ground_truth.json>

The first positional argument is the manual annotation, the second one is the
reference (ground truth).  Only the console is used for output; no files are
created or modified.

Dependency installation:
    .venv\\Scripts\\pip install -r requirements.txt
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import geometry
from geometry import Polygon

USAGE = "usage: python main.py <annotated.json> <ground_truth.json>"

NOTE_SEP = "\x1f"
NOTE_KEY_GT_POLY = "GT poly without path -> compared as bbox"
NOTE_KEY_UNKNOWN_SHAPE = "unknown shape -> compared as bbox"
NOTE_KEY_EXTRA_RINGS = "extra rings ignored"
NOTE_KEY_DEGENERATE = "degenerate polygon, skipped"
NOTE_KEY_INVALID = "invalid polygon, skipped"
NOTE_KEY_BOUNDS = "coordinates outside image bounds"
NOTE_KEY_NO_GEOMETRY = "object without geometry"
NOTE_KEY_NO_OBJECT = "geometry without object description"


class DataError(Exception):
    """Raised for unreadable input or an invalid JSON structure."""


@dataclass
class Figure:
    nm: str
    type: str
    shape: str
    polygon: Polygon | None
    area: float
    note: str | None = None


@dataclass
class Side:
    path: Path
    width: float | int | None
    height: float | int | None
    weather: str | None
    figures: list[Figure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Pair:
    ref: Figure
    manual: Figure
    i: float
    u: float
    score: float


def natural_key(nm: str) -> tuple[tuple[bool, object], ...]:
    """Sort key splitting on dots so that ``0.2`` comes before ``0.10``."""
    parts: list[tuple[bool, object]] = []
    for part in str(nm).split("."):
        if part.isdigit():
            parts.append((True, int(part)))
        else:
            parts.append((False, part.lower()))
    return tuple(parts)


def make_note(key: str, template: str, nm: str) -> str:
    """Encode one nm-specific note; grouping happens in the report layer."""
    return NOTE_SEP.join((key, template, nm))


def parse_args(argv: list[str]) -> tuple[Path, Path]:
    """Return ``(manual, reference)`` paths from the command line."""
    if len(argv) != 2:
        raise DataError(USAGE)
    return Path(argv[0]), Path(argv[1])


def _single_line(text: str) -> str:
    return " ".join(str(text).splitlines())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_float(value: object) -> float | None:
    if _is_number(value):
        return float(value)
    return None


def _bbox_from_record(record: dict) -> tuple[float, float, float, float] | None:
    values = [record.get(key) for key in ("x1", "y1", "x2", "y2")]
    if not all(_is_number(value) for value in values):
        return None
    x1, y1, x2, y2 = (float(value) for value in values)
    return x1, y1, x2, y2


def _bbox_points(
    bbox: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """Rectangle corners in spec order, with min/max normalization."""
    x1, y1, x2, y2 = bbox
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return [
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
    ]


def _points_from_ring(ring: object) -> list[tuple[float, float]] | None:
    if not isinstance(ring, (list, tuple)):
        return None
    points: list[tuple[float, float]] = []
    for item in ring:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        if not _is_number(item[0]) or not _is_number(item[1]):
            return None
        points.append((float(item[0]), float(item[1])))
    return points


def _outside_bounds(
    points: list[tuple[float, float]],
    width: float | int | None,
    height: float | int | None,
) -> bool:
    width_f = _as_float(width)
    height_f = _as_float(height)
    if width_f is None or height_f is None:
        return False
    for x, y in points:
        if x < 0 or y < 0 or x > width_f or y > height_f:
            return True
    return False


def build_figures(
    meta: dict, geometry_doc: dict, role: str
) -> tuple[list[Figure], list[str]]:
    """Build silhouettes for one file and collect data-quality notes."""
    figures: list[Figure] = []
    notes: list[str] = []

    width = meta.get("width")
    height = meta.get("height")
    objects = meta.get("objects") or []
    records = geometry_doc.get("objects") or []

    records_by_nm: dict[str, dict] = {}
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("nm"), str):
            records_by_nm[record["nm"]] = record

    described: set[str] = set()

    for obj in objects:
        if not isinstance(obj, dict):
            continue
        nm = obj.get("nm")
        if not isinstance(nm, str):
            continue
        described.add(nm)

        record = records_by_nm.get(nm)
        if record is None:
            notes.append(
                make_note(
                    NOTE_KEY_NO_GEOMETRY,
                    NOTE_KEY_NO_GEOMETRY + " (nm: {nm})",
                    nm,
                )
            )
            continue

        shape = obj.get("shape")
        bbox = _bbox_from_record(record)
        points: list[tuple[float, float]] | None = None
        note: str | None = None

        if shape == "poly":
            path = record.get("path")
            ring = path[0] if isinstance(path, (list, tuple)) and path else None
            points = _points_from_ring(ring) if ring is not None else None
            if points is None or not points:
                if bbox is None:
                    notes.append(
                        make_note(
                            NOTE_KEY_NO_GEOMETRY,
                            NOTE_KEY_NO_GEOMETRY + " (nm: {nm})",
                            nm,
                        )
                    )
                    continue
                points = _bbox_points(bbox)
                notes.append(
                    make_note(
                        NOTE_KEY_GT_POLY,
                        NOTE_KEY_GT_POLY + " (nm: {nm})",
                        nm,
                    )
                )
                note = NOTE_KEY_GT_POLY
            else:
                if isinstance(path, (list, tuple)) and len(path) > 1:
                    notes.append(
                        make_note(
                            NOTE_KEY_EXTRA_RINGS,
                            NOTE_KEY_EXTRA_RINGS + " (nm: {nm})",
                            nm,
                        )
                    )
        else:
            if shape != "bBox":
                notes.append(
                    make_note(
                        NOTE_KEY_UNKNOWN_SHAPE,
                        NOTE_KEY_UNKNOWN_SHAPE + " (nm: {nm})",
                        nm,
                    )
                )
                note = NOTE_KEY_UNKNOWN_SHAPE
            if bbox is None:
                notes.append(
                    make_note(
                        NOTE_KEY_NO_GEOMETRY,
                        NOTE_KEY_NO_GEOMETRY + " (nm: {nm})",
                        nm,
                    )
                )
                continue
            points = _bbox_points(bbox)

        if _outside_bounds(points, width, height):
            notes.append(
                make_note(
                    NOTE_KEY_BOUNDS,
                    NOTE_KEY_BOUNDS + " (nm: {nm})",
                    nm,
                )
            )

        polygon = geometry.polygon_from_points(points)
        if polygon is None:
            notes.append(
                make_note(
                    NOTE_KEY_DEGENERATE,
                    NOTE_KEY_DEGENERATE + " (nm: {nm})",
                    nm,
                )
            )
            figures.append(
                Figure(
                    nm=nm,
                    type=str(obj.get("type") or ""),
                    shape=str(shape),
                    polygon=None,
                    area=0.0,
                    note=NOTE_KEY_DEGENERATE,
                )
            )
            continue

        area = geometry.shoelace_area(points)
        valid, reason = geometry.is_valid(polygon)
        if not valid:
            key = f"{NOTE_KEY_INVALID}: {reason}"
            notes.append(
                make_note(
                    key,
                    NOTE_KEY_INVALID + " (nm: {nm}): " + reason,
                    nm,
                )
            )
            figures.append(
                Figure(
                    nm=nm,
                    type=str(obj.get("type") or ""),
                    shape=str(shape),
                    polygon=None,
                    area=0.0,
                    note=NOTE_KEY_INVALID,
                )
            )
            continue

        figures.append(
            Figure(
                nm=nm,
                type=str(obj.get("type") or ""),
                shape=str(shape),
                polygon=polygon,
                area=area,
                note=note,
            )
        )

    for record in records:
        if not isinstance(record, dict):
            continue
        nm = record.get("nm")
        if not isinstance(nm, str) or nm in described:
            continue
        notes.append(
            make_note(
                NOTE_KEY_NO_OBJECT,
                NOTE_KEY_NO_OBJECT + " (nm: {nm})",
                nm,
            )
        )

    return figures, notes


def load_side(path: Path, role: str) -> Side:
    """Read and validate one annotation file, then build its figures."""
    resolved = Path(path).resolve()
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise DataError(f"{resolved}: file not found") from exc
    except IsADirectoryError as exc:
        raise DataError(f"{resolved}: is a directory") from exc
    except PermissionError as exc:
        raise DataError(f"{resolved}: permission denied") from exc
    except OSError as exc:
        raise DataError(f"{resolved}: cannot read file ({exc.strerror or exc})") from exc
    except json.JSONDecodeError as exc:
        raise DataError(
            _single_line(f"{resolved}: invalid JSON ({exc})")
        ) from exc
    except UnicodeDecodeError as exc:
        raise DataError(
            _single_line(f"{resolved}: invalid JSON (not UTF-8: {exc})")
        ) from exc

    if not isinstance(data, list) or len(data) != 2:
        raise DataError(
            f"{resolved}: expected a JSON array of exactly two elements"
        )

    meta, geometry_doc = data
    if not isinstance(meta, dict):
        raise DataError(f"{resolved}: element 0 is not an object")
    for key in ("width", "height", "objects"):
        if key not in meta:
            raise DataError(f"{resolved}: element 0 is missing '{key}'")
    if not isinstance(meta.get("objects"), list):
        raise DataError(f"{resolved}: element 0 'objects' is not an array")
    if not isinstance(geometry_doc, dict):
        raise DataError(f"{resolved}: element 1 is not an object")
    if not isinstance(geometry_doc.get("objects"), list):
        raise DataError(f"{resolved}: element 1 'objects' is not an array")

    attributes = meta.get("attributes")
    weather = attributes.get("weather") if isinstance(attributes, dict) else None
    if not isinstance(weather, str):
        weather = None

    figures, notes = build_figures(meta, geometry_doc, role)
    return Side(
        path=resolved,
        width=meta.get("width"),
        height=meta.get("height"),
        weather=weather,
        figures=figures,
        notes=notes,
    )


def find_pairs(
    ref: list[Figure], manual: list[Figure]
) -> tuple[list[Pair], list[Figure], list[Figure]]:
    """Greedy 1-to-1 matching of reference figures against manual figures."""
    active_ref = [figure for figure in ref if figure.polygon is not None]
    active_manual = [figure for figure in manual if figure.polygon is not None]

    candidates: list[Pair] = []
    for ref_figure in active_ref:
        for manual_figure in active_manual:
            i = geometry.intersection_area(ref_figure.polygon, manual_figure.polygon)
            if i <= 0:
                continue
            u = geometry.union_area(ref_figure.polygon, manual_figure.polygon)
            score = i / u if u != 0 else 0.0
            candidates.append(
                Pair(
                    ref=ref_figure,
                    manual=manual_figure,
                    i=i,
                    u=u,
                    score=score,
                )
            )

    candidates.sort(
        key=lambda pair: (
            -pair.score,
            abs(pair.ref.area - pair.manual.area),
            natural_key(pair.ref.nm),
            natural_key(pair.manual.nm),
        )
    )

    matched_ref: set[str] = set()
    matched_manual: set[str] = set()
    pairs: list[Pair] = []
    for pair in candidates:
        if pair.ref.nm in matched_ref or pair.manual.nm in matched_manual:
            continue
        matched_ref.add(pair.ref.nm)
        matched_manual.add(pair.manual.nm)
        pairs.append(pair)

    unmatched_ref = [
        figure for figure in active_ref if figure.nm not in matched_ref
    ]
    unmatched_manual = [
        figure for figure in active_manual if figure.nm not in matched_manual
    ]
    return pairs, unmatched_ref, unmatched_manual


def _format_dimension(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compare_meta(ref: Side, manual: Side) -> list[str]:
    """Return the pre-formatted ``Image size`` and ``Weather`` lines."""
    lines: list[str] = []

    if ref.width == manual.width and ref.height == manual.height:
        size_value = (
            f"{_format_dimension(ref.width)}x{_format_dimension(ref.height)}"
            " | CONFIRMED"
        )
    else:
        size_value = (
            f"WARNING: image size "
            f"{_format_dimension(ref.width)}x{_format_dimension(ref.height)}"
            f" (reference) vs "
            f"{_format_dimension(manual.width)}x{_format_dimension(manual.height)}"
            f" (manual)"
        )
    lines.append(f"{'Image size':<11}: {size_value}")

    ref_weather = ref.weather.strip() if isinstance(ref.weather, str) else ""
    manual_weather = (
        manual.weather.strip() if isinstance(manual.weather, str) else ""
    )
    if not ref_weather or not manual_weather:
        weather_value = "WARNING: weather is not specified"
    elif ref_weather.casefold() == manual_weather.casefold():
        weather_value = f"{ref_weather} | CONFIRMED"
    else:
        weather_value = f"{ref_weather} | {manual_weather} | WARNING"
    lines.append(f"{'Weather':<11}: {weather_value}")

    return lines


def _group_notes(notes: list[str]) -> list[str]:
    grouped: dict[str, tuple[str, list[str]]] = {}
    for note in notes:
        key, template, nm = note.split(NOTE_SEP, 2)
        if key not in grouped:
            grouped[key] = (template, [])
        grouped[key][1].append(nm)

    lines: list[str] = []
    for template, names in grouped.values():
        names_sorted = sorted(names, key=natural_key)
        lines.append(
            "  - " + template.replace("{nm}", ", ".join(names_sorted))
        )
    return lines


def render_report(ref: Side, manual: Side) -> str:
    """Render the complete console report."""
    pairs, unmatched_ref, unmatched_manual = find_pairs(
        ref.figures, manual.figures
    )

    lines: list[str] = [
        f"{'Reference:':<11}{ref.path}",
        f"{'Manual:':<11}{manual.path}",
        "",
        f"=== {ref.path.name} ===",
    ]
    lines.extend(compare_meta(ref, manual))
    lines.append("")
    lines.append(
        "#    GT nm   ANN nm   Type            I (px^2)    U (px^2)    Score"
    )

    row_number = 1
    matched_pairs = sorted(pairs, key=lambda pair: natural_key(pair.ref.nm))
    sum_i = 0.0
    sum_u = 0.0
    for pair in matched_pairs:
        lines.append(
            f"{row_number:<5}"
            f"{pair.ref.nm:<8}"
            f"{pair.manual.nm:<9}"
            f"{pair.ref.type:<16}"
            f"{pair.i:>9.2f}"
            f"{pair.u:>12.2f}"
            f"{pair.score:>9.4f}"
        )
        sum_i += pair.i
        sum_u += pair.u
        row_number += 1

    for figure in sorted(unmatched_ref, key=lambda item: natural_key(item.nm)):
        lines.append(
            f"{row_number:<5}"
            f"{figure.nm:<8}"
            f"{'-':<9}"
            f"{figure.type:<16}"
            f"{0.0:>9.2f}"
            f"{figure.area:>12.2f}"
            f"{0.0:>9.4f}"
            "   UNMATCHED (missing in manual)"
        )
        sum_u += figure.area
        row_number += 1

    for figure in sorted(unmatched_manual, key=lambda item: natural_key(item.nm)):
        lines.append(
            f"{row_number:<5}"
            f"{'-':<8}"
            f"{figure.nm:<9}"
            f"{figure.type:<16}"
            f"{0.0:>9.2f}"
            f"{figure.area:>12.2f}"
            f"{0.0:>9.4f}"
            "   UNMATCHED (extra in manual)"
        )
        sum_u += figure.area
        row_number += 1

    total_score = sum_i / sum_u if sum_u != 0 else 0.0
    lines.append("")
    lines.append(
        f"TOTAL: sum(I) = {sum_i:.2f}   "
        f"sum(U) = {sum_u:.2f}   "
        f"score = {total_score:.4f}"
    )

    note_lines = _group_notes(list(ref.notes) + list(manual.notes))
    if note_lines:
        lines.append("")
        lines.append("NOTES:")
        lines.extend(note_lines)

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Run the comparison; return the process exit code."""
    try:
        manual_path, reference_path = parse_args(argv)
        manual = load_side(manual_path, "manual")
        reference = load_side(reference_path, "reference")
    except DataError as exc:
        print(_single_line(str(exc)), file=sys.stderr)
        return 2

    sys.stdout.write(render_report(reference, manual))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
