# Implementation Plan

## Console tool for comparing manual annotation against the reference

Companion document: `script_spec.md` (requirements). This plan describes how the script is
built, in which order, and how each stage is verified.

---

## 1. Deliverables

| File | Purpose |
|---|---|
| `main.py` | CLI entry point: argument parsing, JSON loading, figure building, matching, console report, exit codes |
| `geometry.py` | Pure geometry: shoelace area, rectangle/polygon construction, intersection/union areas, pair score |
| `requirements.txt` | `shapely>=2.0,<3` |
| `script_spec.md` | Approved specification (already written) |
| `implementation_plan.md` | This document |

Out of scope: report files (JSON/CSV), batch mode, unit tests, image or ZIP processing. The
existing `main.py` (currently only `import json`) is replaced. `spec.md` stays untouched.

---

## 2. Environment

- Python 3.12.3, project virtual environment `.venv` (already present in the project root).
- `shapely` 2.2.0 is already installed in `.venv` (verified).
- Install command to document in the README section of `main.py` docstring and in the spec:
  `.venv\Scripts\pip install -r requirements.txt`.

---

## 3. Module design

### 3.1 `geometry.py`

Knows nothing about JSON, `nm` or file names.

```python
def shoelace_area(points: Sequence[tuple[float, float]]) -> float
    """Absolute area of a ring by the Gauss shoelace formula."""

def polygon_from_points(points: Sequence[tuple[float, float]]) -> Polygon | None
    """Polygon from path[0]; None if fewer than 3 distinct vertices."""

def polygon_from_bbox(x1: float, y1: float, x2: float, y2: float) -> Polygon
    """Axis-aligned rectangle, coordinates normalized with min/max."""

def intersection_area(a: Polygon, b: Polygon) -> float
def union_area(a: Polygon, b: Polygon) -> float

def pair_score(a: Polygon, b: Polygon) -> tuple[float, float, float]
    """(score, I, U); score is 0.0 when U == 0."""

def is_valid(polygon: Polygon) -> tuple[bool, str]
    """(is_valid, shapely reason or empty string)."""
```

Notes:

- `shoelace_area` is the only place where the figure area is computed and it is used for the
  area of a single figure (matched and unmatched alike). `shapely` is used for `I` and `U`
  only. For simple polygons the two agree; keeping the separated function satisfies the
  requirement that the area function is implemented independently.
- `pair_score` returns areas before rounding; formatting is the report layer's job.

### 3.2 `main.py`

```python
@dataclass
class Figure:
    nm: str
    type: str
    shape: str
    polygon: Polygon | None
    area: float
    note: str | None

@dataclass
class Side:
    path: Path
    width: float
    height: float
    weather: str | None
    figures: list[Figure]
    notes: list[str]

@dataclass
class Pair:
    ref: Figure
    manual: Figure
    i: float
    u: float
    score: float

def parse_args(argv: list[str]) -> tuple[Path, Path]              # (manual, reference)
def load_side(path: Path, role: str) -> Side                      # role: "manual" | "reference"
def build_figures(meta: dict, geometry: dict, role: str) -> tuple[list[Figure], list[str]]
def find_pairs(ref: list[Figure], manual: list[Figure]) -> tuple[list[Pair], list[Figure], list[Figure]]
def compare_meta(ref: Side, manual: Side) -> list[str]            # pre-formatted metadata lines
def render_report(...) -> str
def main(argv: list[str]) -> int
```

Internal rules:

- `natural_key(nm)` — split on `.` and convert numeric parts to `int` for sorting.
- `load_side` validates: JSON parses, top-level is a list of length 2, element 0 has `width`,
  `height`, `objects`, element 1 has `objects`. Any violation raises `DataError`, caught in
  `main`, printed to `stderr`, exit code `2`.
- `build_figures` implements the silhouette priority table from spec §3.1 and collects notes
  (`GT poly without path`, `extra rings ignored`, `degenerate polygon`, `invalid polygon`,
  `coordinates outside image bounds`, `object without geometry`, `geometry without object
  description`). Invalid polygons get `polygon = None` and are dropped from matching but their
  `nm` is kept for the note.
- `find_pairs` is the greedy 1-to-1 algorithm from spec §4, including the four-level sort key
  and pairing only among figures with `polygon is not None`.
- `render_report` produces the exact layout of spec §7; grouping of identical notes happens here.
- Exit code `0` on success regardless of warnings; `2` only for `DataError` / wrong argument
  count.

---

## 4. Stages

### Stage 1 — Skeleton and dependency

Actions: create `requirements.txt`, replace `main.py` with the CLI skeleton (`parse_args`,
`main`, exit codes `0`/`2`), add the docstring with the install command.

Checkpoint: `python main.py` with no arguments prints the usage line to `stderr` and exits with
`2`; `python -c "import shapely; print(shapely.__version__)"` inside `.venv` prints `2.2.0`.

### Stage 2 — `geometry.py`

Actions: implement `shoelace_area`, `polygon_from_bbox`, `polygon_from_points`,
`intersection_area`, `union_area`, `pair_score`, `is_valid`.

Checkpoint (interactive, no test files): a unit square `10×10` gives area `100`; two squares
offset by `5` on one axis give `I = 50`, `U = 150`, `score = 0.3333`; identical squares give
`score = 1.0`; disjoint squares give `I = 0` and `score = 0.0`; a bow-tie polygon is reported
invalid.

### Stage 3 — Loading and figure building

Actions: implement `load_side`, `build_figures`, all data-quality notes.

Checkpoint: on `annotated/road.jpg.json` and `ground_truth/road.jpg.json` the loaded figures
match spec §9.2 areas (`GT 0.7 = 24584.28`, `GT 0.8 = 29825.68`, manual `0.8 = 4511.90`,
manual `0.1 = 7814.35`, `GT 0.4 = 115.09`, manual `0.5 = 155.89`); six bbox-fallback notes are
collected for the reference.

### Stage 4 — Matching

Actions: implement `find_pairs` with the greedy ordering and unmatched classification.

Checkpoint: on `road.jpg` the pairs must be exactly
`0.1↔0.3, 0.2↔0.9, 0.3↔0.2, 0.5↔0.7, 0.6↔0.6, 0.7↔0.8, 0.8↔0.1`, with `GT 0.4` reported as
missing and manual `0.5` as extra.

### Stage 5 — Report

Actions: implement metadata comparison, fixed-width table, `TOTAL`, grouped `NOTES` block,
absolute-path header.

Checkpoint: the console output equals the sample in spec §7 character-for-character apart from
the absolute paths.

### Stage 6 — Verification against acceptance criteria

Actions: run the reference command, walk through spec §9.1 and §9.3 manually.

Checkpoint:

- `.venv\Scripts\python.exe main.py annotated/road.jpg.json ground_truth/road.jpg.json` →
  exit `0`, `score = 0.2327`, `sum(I) = 14373.34`, `sum(U) = 61760.34`.
- Reversed order `ground_truth road.jpg.json annotated/road.jpg.json` → exit `0`, identical
  total score.
- Negative checks, each exits `2` with one line on `stderr`: no arguments, one argument, three
  arguments, non-existent path, a JSON object instead of an array, an array of one element.

### Stage 7 — Edge-case pass

Actions: temporary throwaway copies of the JSON in the temp directory (not in the project) to
exercise: manual `poly` without `path`; a self-intersecting manual polygon (bow-tie); a manual
object present in element 1 but absent in element 0; `weather` absent; coordinates outside the
image; `width`/`height` mismatch.

Checkpoint: every case prints the expected `NOTE`/`WARNING`, the process still exits `0`, and
the remaining figures are still scored. Thrown-away files are deleted afterwards.

---

## 5. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Reference `poly` are bboxes → dominant scoring error | Overall score stays low (~0.23) and can be misread | Explicit bbox `NOTE` in every report; expectation documented in spec §2.3 |
| Greedy matching differs from globally optimal assignment | Total score may be slightly lower than theoretical maximum | Accepted by the customer; deterministic ordering documented and reproducible |
| Float rounding in `score` | Mismatch of the 4th decimal on another machine | Rounding only at formatting; tolerance `0.0001` documented in acceptance criteria |
| `shapely` invalid geometries (self-intersections in manual paths) | Wrong areas or exceptions | Validity check before matching, figure skipped with `NOTE` |
| `nm` numbering differs between files | Wrong pairing if `nm` is trusted | Pairing is purely geometric, `nm` used for display and sorting only |
| Non-ASCII console output (Windows code page) | Garbled report | Output is ASCII-only; paths are printed as returned by `Path.resolve()` |
| Only one data sample available | Unverified behaviour on multi-object edge cases | Edge-case pass in Stage 7 with temporary synthetic files |

---

## 6. Definition of done

1. `main.py`, `geometry.py`, `requirements.txt` exist; `python main.py` without arguments exits
   with `2` and prints usage.
2. The reference run reproduces spec §7 and §9.2 numbers within the stated tolerances.
3. All `NOTE`/`WARNING` cases from spec §9.3 behave as described.
4. No files other than the three above are created by the script; `annotated`, `ground_truth`,
   `spec.md`, `road.jpg` are untouched.
5. Code is organised as specified (no geometry maths in `main.py`, no JSON/naming logic in
   `geometry.py`).

---

## 7. Effort estimate

| Stage | Effort |
|---|---|
| 1. Skeleton + dependency | ~15 min |
| 2. `geometry.py` | ~45 min |
| 3. Loading / figure building | ~45 min |
| 4. Matching | ~30 min |
| 5. Report | ~40 min |
| 6. Verification | ~30 min |
| 7. Edge-case pass | ~30 min |
| **Total** | **~3.5–4 h** |
