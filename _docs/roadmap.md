# pycarto roadmap

## Final scope decisions

| Decision            | Choice                                                                                       |
|---------------------|----------------------------------------------------------------------------------------------|
| Suggestion signals  | (a) enclaves + (b) shared-border ratio                                                       |
| Suggestion UX       | dry-run flag (`suggest_only=True`) + library return value                                    |
| Surface             | library only — no CLI, no console-script entry point                                         |
| Layout              | modular package: `data.py`, `geom.py`, `borders.py`, `svg.py`, `__init__.py`                 |
| Out of scope for v1 | multi-resolution, subunits, style theming, Liquipedia id-convention verification, PNG export |

## Status

| Milestone                            | Status              |
|--------------------------------------|---------------------|
| M0 — Project plumbing                 | Complete 2026-05-07 |
| M1 — Data layer (`data.py`)           | Complete 2026-05-08 |
| M2 — Geometry pipeline (`geom.py`)    | Complete 2026-05-08 |
| M2.5 — Overseas-territories centering | Pending             |
| M3 — SVG emission (`svg.py`)          | Pending             |
| M4 — `build_map` orchestration        | Pending             |
| M5 — Border suggester (`borders.py`)  | Pending             |
| M6 — Polish                           | Pending             |

## Target package structure

```
pycarto/
  __init__.py     # public API: build_map, suggest_neighbors, REGION_PROJECTIONS
  py.typed        # PEP 561 typed-library marker
  data.py         # Natural Earth fetch + cache + column normalization
  geom.py         # projection presets, reprojection, topological simplification
  borders.py      # adjacency graph, enclave detection, shared-border scoring
  svg.py          # affine world→SVG, path emission, viewBox/style assembly
_tests/
  __init__.py
  conftest.py              # synthetic GeoDataFrame fixtures
  test_init.py             # smoke tests on package metadata
  test_data.py
  test_geom.py
  test_borders.py
  test_svg.py
  test_build_map.py        # end-to-end on a small region (Benelux)
  fixtures/
    benelux_expected.svg   # golden snapshot
```

No `pycarto/main.py` entrypoint stub — lib-only means the package has no top-level script.

## Milestones

### M0 — Project plumbing (~1 day) — Complete (2026-05-07)

- [x] Rewrite `pyproject.toml` with `[build-system]` + hatchling, full `[project]` metadata (classifiers, keywords,
  authors, urls), `[dependency-groups]` (`dev` + `test`), and tool configs: `[tool.ruff]` (line 120, broad ruleset,
  google docstrings, isort known-first-party), `[tool.mypy]` (strict), `[tool.pytest.ini_options]` (testpaths, `network`
  marker), `[tool.coverage.*]`
- [x] Create `pycarto/__init__.py` with `__version__`, `__author__`, comment-grouped `__all__` placeholder
- [x] Create empty `pycarto/py.typed` (PEP 561 typed marker) and `_tests/__init__.py`
- [x] Create empty module skeletons: `pycarto/data.py`, `pycarto/geom.py`, `pycarto/borders.py`, `pycarto/svg.py`
- [x] Add `.github/workflows/lint-and-test.yml` (lint + type-check + test, on push/PR to `main`; uploads coverage to
  DeepSource)
- [x] Add `.github/workflows/codeql.yml` (Python security analysis on push/PR + monthly cron)
- [x] Add `.github/workflows/license_workflow.yml` (annual LICENSE copyright bump on Jan 1; needs `secrets.PAT`)
- [x] Add `.github/dependabot.yml` (monthly grouped uv + github-actions updates targeting `main`)
- [x] Add `.deepsource.toml` (Python analyzer + test-coverage; needs `secrets.DEEPSOURCE_DSN` once the repo is enrolled)
- [x] Polish `.gitignore` (trailing slashes on private-resource directories, add `_data/` for the NE cache)

**Gate:**
`uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy pycarto && uv run pytest` green on an
empty test suite.

### M1 — Data layer (`data.py`) (½ day) — Complete (2026-05-08)

- [x] `ensure_natural_earth(resolution="50m") -> Path` — downloads + extracts to `./_data/` if missing, from
  `naciscdn.org` (Natural Earth's canonical rolling-latest endpoint). Non-`50m` resolutions raise
  `NotImplementedError` (forward-compat signature, narrow v1 behavior). Reproducibility deferred — see risks.
- [x] `load_countries(shp_path: Path | None = None) -> GeoDataFrame` — reads, uppercases columns (via private
  `_normalize_columns` helper), returns the raw frame.
- [x] `select(gdf, iso_codes, *, filter_field="ISO_A3_EH") -> GeoDataFrame` — filters with `_EH` → non-`_EH` fallback;
  emits both a `UserWarning` and a `pycarto.data` logger warning on missing codes; raises `ValueError` on empty result
  or when neither `filter_field` nor its `_EH`-stripped fallback exists.
- [x] Tests use synthetic `GeoDataFrame` fixtures (`_tests/conftest.py`) — fast, deterministic, no network or fixture
  commit. Real-shapefile coverage deferred to a `network`-marked end-to-end test in M4/M6.

**Gate:** ✔ `select(load_countries(), ["BEL","NLD","LUX"])` returns 3 rows.

### M2 — Geometry pipeline (`geom.py`) (½ day) — Complete (2026-05-08)

- [x] `REGION_PROJECTIONS` dict (verbatim from intro doc)
- [x] `auto_center_laea(gdf) -> str` — builds a PROJ string from the selection's WGS84 bbox center (simpler /
  deterministic than geometry centroid; warns on bbox spans > 180° per the antimeridian gotcha)
- [x] `reproject(gdf, projection)` — thin wrapper, kept for testability
- [x] `simplify_topological(gdf, tolerance: float)` — `topojson.Topology(...).toposimplify(...).to_gdf()`;
  `tolerance <= 0` is a pass-through so M4 doesn't have to special-case the no-simplify path
- [x] `topojson` promoted from "lands with M2" to a runtime dep (`>=1.10,<2`); `[[tool.mypy.overrides]]` updated

**Gate:** ✔ `test_simplify_topological_preserves_topology` — adjacent polygons still share a non-zero boundary
post-simplify (`_tests/test_geom.py`).

### M2.5 — Overseas-territories centering fix (~¼ day)

`auto_center_laea` currently derives its center from `gdf.total_bounds`, which is fooled by Natural Earth's
aggregation of overseas dependencies into the parent country polygon (Caribbean NL inside `NLD`, French Guiana
inside `FRA`, Hawaii / Alaska inside `USA`). For a Benelux selection the auto-derived center comes out near
`(-30.6°W, 32.8°N)` — middle of the Atlantic — making the function unusable as a default. **Strategy: aggregate
the bbox of each row's largest sub-polygon by area, instead of taking `gdf.total_bounds` over all polygons.**
Tiny overseas territories disappear from the bbox by virtue of being orders of magnitude smaller than the
metropolitan polygon. Bbox-center semantics from M2 are preserved; no new dep, no centroid warnings, no second
shapefile.

- [ ] Add a private helper `_main_polygon_bounds(geom) -> tuple[float, float, float, float]` in `pycarto/geom.py`:
  returns the bbox of the largest sub-polygon by area for a `MultiPolygon`, or `geom.bounds` for a single
  `Polygon`. Defensive fall-back for `GeometryCollection` and empty geometries.
- [ ] Rework `auto_center_laea` to aggregate `_main_polygon_bounds` row-wise instead of calling `gdf.total_bounds`.
  The CRS guard and antimeridian check (`maxx - minx > 180`) stay verbatim — they apply to the new aggregated
  bbox just the same.
- [ ] Add a new fixture `country_with_overseas` to `_tests/conftest.py` — a one-row gdf with a `MultiPolygon`
  built from a metropolitan box (e.g. `box(2, 49, 7, 52)`) plus a small Caribbean box (e.g. `box(-70, 12, -67,
  13)`). The metropolitan polygon must dominate by area so `_main_polygon_bounds` picks it.
- [ ] Add `test_auto_center_laea_ignores_overseas_dependencies` — asserts the auto-derived center lon/lat sits
  inside the metropolitan bbox (not in the mid-Atlantic). Optionally a second test on a `MultiPolygon` with two
  near-equal polygons to lock in the deterministic tie-break (first by index).
- [ ] Verify all existing M2 tests pass without modification — they all use single-Polygon fixtures, where the
  largest-polygon bbox equals the polygon's own bbox, so the result is unchanged.
- [ ] Remove the `TODO(pre-v1)` block in `pycarto/geom.py` (between `REGION_PROJECTIONS` and `auto_center_laea`).
  Rewrite the docstring "Caveat" paragraph to describe the strategy (`bbox of each row's largest sub-polygon`)
  rather than the historical pitfall.
- [ ] Update `CLAUDE.md` (Projection bullet) and this file's "Risks / gotchas" entry: swap "Tracked as pre-v1
  fix" / "Pre-v1 fix needed" for "Fixed in M2.5". Move the entry to a "Resolved" sub-list or strike-through
  rather than deleting — the rationale is still useful context for future contributors.
- [ ] Bump the M2.5 status row to `Complete <date>` and tick all checkboxes once the gate is green.

**Gate:** ✔ `auto_center_laea` on the `country_with_overseas` fixture returns a center inside the metropolitan
bbox; the M2 topology-preservation gate stays green; `uv run ruff check . && uv run mypy pycarto && uv run
pytest -m "not network"` all clean; coverage on `pycarto/geom.py` stays at 100%.

### M3 — SVG emission (`svg.py`) (½ day)

- [ ] `geom_to_path(geom) -> str` — (Multi)Polygon → SVG `d` string
- [ ] `affine_world_to_svg(gdf, *, width, padding) -> tuple[GeoDataFrame, viewbox, height]` — Y-flip + scale
- [ ] `render_svg(gdf, *, id_field, id_lower, width, padding) -> str` — sorts by id, builds the full SVG document

**Gate:** golden snapshot test passes for Benelux at 1:110m.

### M4 — `build_map` orchestration (`__init__.py`) (¼ day)

- [ ] Compose `data → geom → svg`. Same signature as the intro-doc draft, minus what we promote to defaults.
- [ ] Add `suggest_only: bool = False` and `suggestions: list[str] | None = None` (forward-declared here; M5 wires the
  body).
- [ ] Public API: `from pycarto import build_map, suggest_neighbors, REGION_PROJECTIONS`.

**Gate:** end-to-end test reproduces the intro-doc SE Asia / South America outputs (10 + 12 paths).

### M5 — Border suggester (`borders.py`) — the new feature (1–1½ days)

This is the only piece without a draft. Two building blocks:

**Adjacency graph**

- [ ] Build on the **raw, unsimplified** NE frame — simplification can erode shared boundaries below numerical noise.
- [ ] For each selected country, candidate neighbors = countries whose bbox intersects (selection bbox buffered by ~1°).
  Avoids quadratic blowup on the full 250-row frame.
- [ ] Pair adjacency = `geom_a.intersection(geom_b).length > epsilon`. Don't use exact `touches()` — it's brittle on
  Natural Earth's vertex-snapped polygons. Drop pairs that meet at a single point (length ≈ 0).

**Two scorers**

- [ ] `_find_enclaves(graph, selection)`: candidate country `c` is an enclave if every neighbor of `c` in the graph is
  in `selection`. Score = 1.0.
- [ ] `_shared_border_ratio(graph, selection, candidate)`:
  `sum(shared_boundary_length(candidate, s) for s in selection ∩ neighbors(candidate)) / candidate.boundary.length`.
  Range [0, 1].

**Public API**

```python
@dataclass(frozen=True)
class Suggestion:
    iso: str  # ISO_A3_EH of the suggested country
    reason: Literal["enclave", "shared_border"]
    score: float  # 1.0 for enclave; ratio in [0,1] for shared_border
    neighbors_in_selection: tuple[str, ...]


def suggest_neighbors(
    iso_codes: list[str],
    *,
    enclaves: bool = True,
    shared_border_threshold: float = 0.5,
    shp_path: Path | None = None,
) -> list[Suggestion]: ...
```

**Wire `suggest_only=True` in `build_map`**: when set, returns the `list[Suggestion]` and skips geom + svg work
entirely.

**Tests** (fixture-based, deterministic):

- [ ] `["FRA","DEU","ITA","AUT"]` → Suggestion for `CHE` with reason="enclave"
- [ ] `["UKR","POL","LTU","LVA","RUS"]` → Suggestion for `BLR` with reason="shared_border", score > 0.7
- [ ] `["BEL","NLD"]` → no enclave (LUX isn't enclosed by 2 countries), but LUX appears as `shared_border` if threshold
  lowered

**Gate:** the three fixture cases above pass.

### M6 — Polish (¼ day)

- [ ] README usage block: minimal `from pycarto import build_map; build_map([...], "out.svg", projection=...)`
- [ ] README "suggestions" block: same with `suggest_only=True`
- [ ] One end-to-end happy-path golden SVG checked into `_tests/fixtures/`

**Gate:** `uv run pytest && uv run ruff check` green; README runs as written.

## Risks / gotchas to track during implementation

- **Adjacency must run pre-simplification.** Worth a comment in `borders.py`.
- **Floating-point boundary noise**: use `.intersection(...).length > 1e-6` (in degrees on raw NE data) rather than
  `touches()`.
- **Russia / antimeridian**: not in scope for v1, but flag in `geom.py` to warn if selection bbox spans > 180°
  longitude — projection will distort badly. Implemented in `auto_center_laea` (dual `UserWarning` + logger).
- **Overseas territories**: Natural Earth's `admin_0_countries` aggregates dependencies into the parent country
  polygon (Caribbean NL inside `NLD`, French Guiana inside `FRA`, Hawaii/Alaska inside `USA`). Selections that
  include those countries get a bbox spanning oceans and `auto_center_laea` returns a center in open water.
  **Pre-v1 fix needed** — current workaround is `REGION_PROJECTIONS` presets; long-term options are largest-polygon
  bbox per row, area-weighted centroid, or sourcing centers from `ne_50m_admin_0_map_subunits`. Full subunit-level
  splitting (separate `<path>` per dependency) can stay post-v1. Tracked as `TODO(pre-v1)` in `pycarto/geom.py`.
- **Singapore / GUF / small islands**: present in 1:50m, drop out at 1:110m. Tests at 1:110m must avoid them or use
  larger countries.
- **`_data/` cache vs reproducibility**: M1 downloads from `naciscdn.org` (rolling-latest); URL-based pinning is not
  viable because `nvkelso/natural-earth-vector` doesn't ship the bundled zip as a release asset or repo path. The
  realistic post-v1 plan is content-hash pinning — record an expected SHA256 of the zip and verify on download.
  Tracked as an inline `TODO(post-v1)` in `pycarto/data.py`.

## Total estimate

~3¾–4¼ working days for v1, with M5 the only milestone where unknowns are real (M2.5 adds ~¼ day).