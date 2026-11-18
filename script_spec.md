# Script Specification

## Comparison of manually drawn object silhouettes against the reference (ground truth)

Version 1.0

---

## 1. Purpose and scope

The script compares two annotation files (JSON metadata) for the same photo: the reference
annotation (`ground_truth`) and the manual annotation (`annotated`). Both files describe object
silhouettes as polygons in image coordinates.

The script reports:

1. `width` / `height` comparison — `CONFIRMED` or `WARNING`.
2. `weather` comparison — `CONFIRMED` or `WARNING`.
3. Per-pair metrics for each matched reference/manual figure — `I` (intersection area),
   `U` (union area), `score = I / U`.
4. The overall `score` for the file: `sum(I) / sum(U)`.

Output is written to the console only. The script does not create report files, does not read
the image itself and does not modify the input JSON files.

### Non-goals

- Reading or comparing image pixels (`road.jpg`, `road.png`).
- Reading ZIP archives or PNG masks (`road.jpg.zip`, `road.jpg.images/`).
- Batch processing of directories (exactly one file pair per run).
- Automatic fixing of annotations.

---

## 2. Input data

### 2.1 File pairing

The user passes both files explicitly on the command line. File names are not matched
automatically; nothing is inferred from directories.

### 2.2 JSON structure

Each file is a JSON array of exactly two elements.

**Element 0 — file metadata:**

| Field | Type | Description |
|---|---|---|
| `width`, `height` | number | Image size; compared between the two files |
| `attributes.weather` | string | Detected weather; compared between the two files |
| `objects` | array | Object list with general information |

Each entry of `objects`:

| Field | Type | Description |
|---|---|---|
| `nm` | string | Object identifier, unique within the file |
| `type` | string | Object class (`car`, `road sign`, `road_barrier`, ...) |
| `shape` | string | Geometry kind: `bBox` (rectangle) or `poly` (polygon) |

**Element 1 — object geometry:**

| Field | Type | Description |
|---|---|---|
| `nm` | string | Identifier, must exist in element 0 `objects` |
| `x1`, `y1`, `x2`, `y2` | number | Bounding box of the object |
| `path` | array | Optional; `path[0]` is the perimeter ring as `[[x, y], ...]` |

Additional fields (`key`, `attr_key`, `attributes`, `color`, `version`, `file`, `part`,
`original_frame`, `frame_skip`, `status`, `stage`, `model`, `camera`) are ignored by the
comparison and are preserved untouched.

### 2.3 Reference vs manual: known asymmetry

In the available reference file (`ground_truth/road.jpg.json`) **no `poly` object has a
`path`** — only `x1..y2`. In the manual file (`annotated/road.jpg.json`) every `poly` object has
a `path`.

Consequence, accepted by the customer: a reference `poly` is compared as its bounding
rectangle, which makes the reference figure larger than the real object. Therefore for this
reference an overall score of about `0.23` is the expected result and must not be read as a
sign of poor manual annotation. The script marks this situation with a `NOTE`.

---

## 3. Geometry rules

### 3.1 Building a silhouette from one object

The silhouette is built in this priority order:

| Case | Silhouette |
|---|---|
| `shape == "bBox"` | Rectangle `(x1, y1) → (x2, y2)`; corners ordered `(x1,y1), (x2,y1), (x2,y2), (x1,y2)` |
| `shape == "poly"` and `path[0]` present | Polygon of `path[0]`, vertices used in file order |
| `shape == "poly"`, no `path` | Rectangle `x1..y2` + `NOTE: GT poly without path -> compared as bbox` |
| `shape` missing or unknown | Rectangle `x1..y2` + `NOTE: unknown shape -> compared as bbox` |

Rules:

- Coordinates are absolute image pixels, floats are expected.
- `path[0]` is a single continuous ring; the ring is implicitly closed (the first vertex must
  not be repeated at the end).
- If `path` contains more than one ring, only `path[0]` is used and
  `NOTE: extra rings ignored (nm ...)` is printed.
- If `x1 > x2` or `y1 > y2`, coordinates are normalized with `min`/`max`.
- Coordinates outside `[0, width] × [0, height]` produce
  `NOTE: coordinates outside image bounds (nm ...)`; the object is still compared.
- If the object has no geometry record in element 1, or a geometry record has no matching `nm`
  in element 0, the object is skipped with `NOTE: object without geometry (nm ...)` or
  `NOTE: geometry without object description (nm ...)`.
- Polygons with fewer than 3 distinct vertices are skipped with
  `NOTE: degenerate polygon, skipped (nm ...)`; their area counts as `0`, so they neither match
  nor add to `sum(U)`.
- Validity is checked with `shapely` (`is_valid`). An invalid polygon (self-intersection,
  duplicated vertices, zero area) is **skipped, not repaired**, with
  `NOTE: invalid polygon, skipped (nm ...): <shapely reason>`. A skipped figure takes part in
  neither matching nor the total score.

### 3.2 Areas

- Area of a single figure — shoelace (Gauss) formula, implemented separately in
  `geometry.shoelace_area(points)` and returned as an absolute value.
- Area of intersection `I` and area of union `U` — computed with `shapely`
  (`a.intersection(b).area`, `a.union(b).area`).
- `U` is the area of the combined figure (`A ∪ B`), **not** the sum of `area(A)` and `area(B)`.
- All areas are in square pixels (px²).

### 3.3 Pair score

```
score = I / U
```

- If `U == 0`, then `score = 0.0`.
- Only pairs with `I > 0` are candidates for matching.

---

## 4. Pairing algorithm (1-to-1)

1. Build the set of candidate pairs: every reference figure against every manual figure where
   `I > 0`. `type` is **not** used as a matching constraint and does not affect ranking.
2. Compute `score = I / U` for every candidate pair.
3. Sort candidates by:
   1. `score` descending;
   2. `abs(area(ref) - area(manual))` ascending;
   3. reference `nm` ascending (natural order);
   4. manual `nm` ascending (natural order).
4. Walk the sorted list; a pair is accepted only if **both** figures are still unmatched.
   Accepted pairs are locked; each figure participates in at most one pair.

The rule "the pair with the highest score is the match" is thus applied under the 1-to-1
constraint: if two reference figures compete for the same manual figure, the pair with the
higher score wins, and the losing reference figure continues looking among the remaining free
manual figures.

### 4.1 Figures without a pair

- Reference figure without a pair: `I = 0`, `score = 0.0`, and its own area is added to
  `sum(U)` (`UNMATCHED (missing in manual)`).
- Manual figure without a pair: `I = 0`, `score = 0.0`, and its own area is added to `sum(U)`
  (`UNMATCHED (extra in manual)`).

### 4.2 Overall score

```
score (total) = sum(I over matched pairs) / ( sum(U over matched pairs) + sum(area of every unmatched figure) )
```

If the denominator is `0`, the total score is `0.0000`.

---

## 5. Metadata comparison

### 5.1 Image size

- Equal `width` and `height` → `CONFIRMED`.
- Different → `WARNING` with both values printed:
  `WARNING: image size 1000x667 (reference) vs 1000x668 (manual)`.

### 5.2 Weather

- Values are compared case-insensitively after `strip()`.
- Equal → `CONFIRMED`.
- Different → `WARNING` with both values.
- `null`, missing key or missing `attributes` → `WARNING: weather is not specified`.

Warnings never block the calculation: matching and scores are always computed.

---

## 6. Command line contract

```
python main.py <annotated.json> <ground_truth.json>
```

- First positional argument — manual annotation (`manual`).
- Second positional argument — reference annotation (`reference`).
- The resolved absolute file paths are printed at the top of the report, so the order of the
  arguments is never ambiguous.
- Relative paths are resolved against the current working directory.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Comparison completed (warnings/notes do not change the code) |
| `2` | Wrong number of arguments, unreadable file, invalid JSON, or structure other than a two-element array with `width`, `height`, `objects` |

On exit code `2` a single explanatory line is printed to `stderr`, no partial report is printed.

### 6.1 Dependencies

- Python 3.12.
- `shapely >= 2.0, < 3` (`requirements.txt`).
- Installation: `.venv\Scripts\pip install -r requirements.txt`.

---

## 7. Output format

Output is plain text in the console. Fixed-width columns, decimal point, no thousands
separators. `score` — 4 decimals, areas — 2 decimals, coordinates — as found in the file.

```
Reference: D:\fug\testtest\ground_truth\road.jpg.json
Manual:    D:\fug\testtest\annotated\road.jpg.json

=== road.jpg.json ===
Image size : 1000x667 | CONFIRMED
Weather    : clear | fog | WARNING

#    GT nm   ANN nm   Type            I (px^2)    U (px^2)    Score
1    0.1     0.3      car               1906.08     2420.50   0.7875
2    0.2     0.9      car                385.71      675.60   0.5709
3    0.3     0.2      car                544.72      624.23   0.8726
4    0.5     0.7      road sign          688.30    1733.07   0.3972
5    0.6     0.6      road sign           63.55       84.74   0.7500
6    0.7     0.8      road_barrier      4206.49    24889.69   0.1690
7    0.8     0.1      road_barrier      6578.49    31061.53   0.2118
8    0.4     -        car                  0.00      115.09   0.0000   UNMATCHED (missing in manual)
9    -       0.5      road sign            0.00      155.89   0.0000   UNMATCHED (extra in manual)

TOTAL: sum(I) = 14373.34   sum(U) = 61760.34   score = 0.2327

NOTES:
  - GT poly without path -> compared as bbox (nm: 0.1, 0.2, 0.3, 0.4, 0.7, 0.8)
```

Rules:

- Matched rows are ordered by reference `nm` in natural order (`0.2` before `0.10`).
- Unmatched rows follow: first missing reference figures (ordered by `nm`), then extra manual
  figures (ordered by `nm`).
- `nm` of the absent side is printed as `-`.
- `Type` is informational only; it is taken from the reference figure (for extra manual figures —
  from the manual figure) and never affects pairing.
- `NOTES:` block is printed only if at least one note exists; identical notes are grouped into
  one line with the list of `nm` values.
- No `OVERALL` line: exactly one file pair is processed per run.

---

## 8. Message vocabulary

| Kind | Meaning |
|---|---|
| `CONFIRMED` | The compared metadata field is identical |
| `WARNING` | The compared metadata field differs (or is missing) — calculation continues |
| `UNMATCHED` | The figure has no pair; `score = 0.0000` |
| `NOTE` | Data-quality remark affecting interpretation (bbox fallback, skipped figure, out-of-bounds coordinates) |

---

## 9. Acceptance criteria

### 9.1 Functional

1. `python main.py annotated/road.jpg.json ground_truth/road.jpg.json` exits with code `0`.
2. `Image size` shows `1000x667 | CONFIRMED`.
3. `Weather` shows `clear | fog | WARNING`.
4. The per-pair table matches section 7 exactly, including the pairing of `nm` values.
5. `TOTAL` shows `sum(I) = 14373.34`, `sum(U) = 61760.34`, `score = 0.2327`
   (tolerance `0.0001` for the score, `0.01` for areas).
6. The `NOTES` block contains the bbox-fallback note with reference `nm`
   `0.1, 0.2, 0.3, 0.4, 0.7, 0.8`.
7. Swapping the arguments changes the roles of the files but produces the same scores.

### 9.2 Numeric reference values (file `road.jpg`)

| Reference nm | Manual nm | Type | I | U | Score |
|---|---|---|---|---|---|
| 0.1 | 0.3 | car | 1906.08 | 2420.50 | 0.7875 |
| 0.2 | 0.9 | car | 385.71 | 675.60 | 0.5709 |
| 0.3 | 0.2 | car | 544.72 | 624.23 | 0.8726 |
| 0.5 | 0.7 | road sign | 688.30 | 1733.07 | 0.3972 |
| 0.6 | 0.6 | road sign | 63.55 | 84.74 | 0.7500 |
| 0.7 | 0.8 | road_barrier | 4206.49 | 24889.69 | 0.1690 |
| 0.8 | 0.1 | road_barrier | 6578.49 | 31061.53 | 0.2118 |
| 0.4 | — | car | 0.00 | 115.09 | 0.0000 |
| — | 0.5 | road sign | 0.00 | 155.89 | 0.0000 |
| **total** | | | **14373.34** | **61760.34** | **0.2327** |

### 9.3 Robustness

1. A file with `width` = `0` or a figure with `U = 0` must not raise an exception.
2. An invalid (self-intersecting) polygon produces a `NOTE` and is excluded, the rest of the
   file is still compared.
3. Missing `path` for a manual `poly` produces a `NOTE` and a bbox comparison.
4. Wrong argument count, missing file, malformed JSON and a JSON array of length ≠ 2 each exit
   with code `2` and a single explanatory line on `stderr`.

---

## 10. Constraints and assumptions

- The comparison is purely geometric; object identity is established by geometry, not by `nm`
  (the two files use different `nm` numbering — verified on `road.jpg`: reference `0.1` is a
  `car`, manual `0.1` is a `road_barrier`).
- `type` mismatch is reported implicitly (both `Type` values are visible per row) but does not
  affect matching.
- Figures are simple polygons in a single image coordinate system; both files relate to the same
  photo, so no scaling, rotation or offset compensation is applied.
- Floating-point arithmetic is IEEE-754 double precision; `shapely` performs the geometry
  predicates.
