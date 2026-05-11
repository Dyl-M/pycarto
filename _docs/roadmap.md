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

| Milestone                                  | Status              |
|--------------------------------------------|---------------------|
| M0 — Project plumbing                      | Complete 2026-05-07 |
| M1 — Data layer (`data.py`)                | Complete 2026-05-08 |
| M2 — Geometry pipeline (`geom.py`)         | Complete 2026-05-08 |
| M2.5 — Overseas-territories centering      | Complete 2026-05-10 |
| M3 — SVG emission (`svg.py`)               | Complete 2026-05-10 |
| M3.5 — Overseas-territories canvas         | Complete 2026-05-10 |
| M4 — `build_map` orchestration             | Complete 2026-05-10 |
| M5 — Border suggester + region unification | Complete 2026-05-10 |
| M6 — Polish                                | Pending             |

## Target package structure

```
pycarto/
  __init__.py     # build_map orchestration + public API: build_map, suggest_neighbors, Suggestion
  py.typed        # PEP 561 typed-library marker
  data.py         # Natural Earth fetch + cache + column normalization
  geom.py         # projection presets, reprojection, topological simplification
  borders.py      # Suggestion + suggest_neighbors (M4 forward-decl, M5 fills the body)
  svg.py          # affine world→SVG, path emission, viewBox/style assembly
_tests/
  __init__.py
  conftest.py              # synthetic GeoDataFrame fixtures
  test_init.py             # package metadata + public-API surface
  test_data.py
  test_geom.py
  test_borders.py
  test_svg.py
  test_build_map.py        # end-to-end on a small region (Benelux)
  test_svg/                # pytest-regressions data dir (per-test-file convention)
    test_render_svg_benelux_golden_snapshot.svg
```

No `pycarto/main.py` entrypoint stub — lib-only means the package has no top-level script.

`_data/` (Natural Earth cache) and `_img/` (default `build_map` output folder) are populated at runtime under
`Path.cwd()`. Both are gitignored.

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

### M2.5 — Overseas-territories centering fix (~¼ day) — Complete (2026-05-10)

`auto_center_laea` currently derives its center from `gdf.total_bounds`, which is fooled by Natural Earth's
aggregation of overseas dependencies into the parent country polygon (Caribbean NL inside `NLD`, French Guiana
inside `FRA`, Hawaii / Alaska inside `USA`). For a Benelux selection the auto-derived center comes out near
`(-30.6°W, 32.8°N)` — middle of the Atlantic — making the function unusable as a default. **Strategy: aggregate
the bbox of each row's largest sub-polygon by area, instead of taking `gdf.total_bounds` over all polygons.**
Tiny overseas territories disappear from the bbox by virtue of being orders of magnitude smaller than the
metropolitan polygon. Bbox-center semantics from M2 are preserved; no new dep, no centroid warnings, no second
shapefile.

- [x] Add a private helper `_main_polygon_bounds(geom) -> tuple[float, float, float, float]` in `pycarto/geom.py`:
  returns the bbox of the largest sub-polygon by area for a `MultiPolygon`, or `geom.bounds` for a single
  `Polygon`. Defensive fall-back for `GeometryCollection` and empty geometries.
- [x] Rework `auto_center_laea` to aggregate `_main_polygon_bounds` row-wise instead of calling `gdf.total_bounds`.
  The CRS guard and antimeridian check (`maxx - minx > 180`) stay verbatim — they apply to the new aggregated
  bbox just the same.
- [x] Add a new fixture `country_with_overseas` to `_tests/conftest.py` — a one-row gdf with a `MultiPolygon`
  built from a metropolitan box (e.g. `box(2, 49, 7, 52)`) plus a small Caribbean box (e.g. `box(-70, 12, -67,
  13)`). The metropolitan polygon must dominate by area so `_main_polygon_bounds` picks it.
- [x] Add `test_auto_center_laea_ignores_overseas_dependencies` — asserts the auto-derived center lon/lat sits
  inside the metropolitan bbox (not in the mid-Atlantic). Plus `test_auto_center_laea_tiebreak_picks_first_by_index`
  on an `overseas_tied_areas` fixture (two equal-area sub-polygons) to lock in the deterministic tie-break.
- [x] Verify all existing M2 tests pass without modification — they all use single-Polygon fixtures, where the
  largest-polygon bbox equals the polygon's own bbox, so the result is unchanged.
- [x] Remove the `TODO(pre-v1)` block in `pycarto/geom.py` (between `REGION_PROJECTIONS` and `auto_center_laea`).
  Rewrite the docstring "Caveat" paragraph to describe the strategy (`bbox of each row's largest sub-polygon`)
  rather than the historical pitfall.
- [x] Update `CLAUDE.md` (Projection bullet) and this file's "Risks / gotchas" entry: swap "Tracked as pre-v1
  fix" / "Pre-v1 fix needed" for "Fixed in M2.5". Move the entry to a "Resolved" sub-list or strike-through
  rather than deleting — the rationale is still useful context for future contributors.
- [x] Bump the M2.5 status row to `Complete <date>` and tick all checkboxes once the gate is green.

**Gate:** ✔ `auto_center_laea` on the `country_with_overseas` fixture returns a center inside the metropolitan
bbox; the M2 topology-preservation gate stays green; `uv run ruff check . && uv run mypy pycarto && uv run
pytest -m "not network"` all clean; coverage on `pycarto/geom.py` stays at 100%.

### M3 — SVG emission (`svg.py`) (½ day) — Complete (2026-05-10)

- [x] `geom_to_path(geom) -> str` — (Multi)Polygon → SVG `d` string. Returns `""` for `None`, empty geometry, or
  non-(Multi)Polygon input (silently dropped by `render_svg`). Coordinates round to 1 decimal place — 0.1 px at the
  default 1000 px width, ~3-4× smaller than full float repr.
- [x] `affine_world_to_svg(gdf, *, width=1000, padding=10) -> tuple[GeoDataFrame, tuple[int, int, int, int], int]` —
  isotropic Y-flip + scale via `shapely.affinity.affine_transform`. Returns a defensive copy (mirroring
  `simplify_topological`), the SVG viewbox `(0, 0, width, height)`, and `height` separately. CRS is not validated —
  caller is expected to feed projected data from `geom.reproject`.
- [x] `render_svg(gdf, *, id_field="ISO_A2_EH", id_lower=True, width=1000, padding=10) -> str` — `affine_world_to_svg`
  → sort by post-lowercase id (stable diffs) → emit one `<path>` per surviving row → wrap in an `<svg>` document with
  a `<g id="countries">` group. Drops rows whose id is in `{"", "-99", "nan"}` after stripping (NE uses `-99` for
  un-coded territories) or whose geometry produces an empty `d`. Uses `xml.sax.saxutils.escape` (stdlib) on the id.
  Styling is emitted as SVG **presentation attributes** on each `<path>` (`fill="#d8d8d8" stroke="#555" …`) rather
  than via an embedded `<style>` block — see M5 for the renderer-compatibility rationale. (Originally M3 used a
  `<style>` block; this was migrated in M5 alongside the region-outline work.)
- [x] No new runtime deps — reuses `shapely.affinity.affine_transform` (already pulled by M2.5) and stdlib
  `xml.sax.saxutils`.
- [x] `_tests/conftest.py` adds a `benelux_projected` fixture (BEL/NLD/LUX subset of `fake_world`, reprojected to
  `REGION_PROJECTIONS["europe"]`). Synthetic-only per "Status" / M1 philosophy — real-shapefile coverage deferred
  to a `network`-marked test in M6.

**Gate:** ✔ `test_render_svg_benelux_golden_snapshot` (`_tests/test_svg.py`) — Benelux selection round-trips through
`select → reproject → render_svg` to a stable SVG snapshot at
`_tests/test_svg/test_render_svg_benelux_golden_snapshot.svg`. Plus 20 unit tests covering each function's contract
(ring walking, Y-flip, padding, id sorting, sentinel/empty-geom skipping, XML escaping, document shape).

### M3.5 — Overseas-territories canvas-bounds fix (~¼ day) — Complete (2026-05-10)

`affine_world_to_svg` shipped with M3 still derived its canvas bbox from `gdf.total_bounds`, so for any
selection containing `NLD` / `FRA` / `USA` / `GBR` (countries whose Natural Earth `admin_0_countries`
geometry aggregates overseas dependencies), the bbox stretched across an ocean and the canvas aspect ratio
deformed badly. The first manual end-to-end run on real NE 1:50m (Benelux + `auto_center_laea`) produced
**viewBox `0 0 1000 146`** (~7:1 horizontal stretch) instead of the expected **`0 0 1000 1384`** —
Caribbean Netherlands projecting far west of metropolitan NL pulled the bbox sideways. **Strategy: mirror
M2.5 for the affine pass — aggregate per-row largest-sub-polygon bbox via the now-public
`main_polygon_bounds` helper instead of `gdf.total_bounds`.** Bounds-only fix; off-canvas overseas `<path>`
data stays in the SVG (renderers clip to viewBox), opt-in dropping deferred to M5/M6.

- [x] Promote `pycarto.geom._main_polygon_bounds` → public `main_polygon_bounds`. Update its docstring to
  describe its general purpose (used by `auto_center_laea` and `affine_world_to_svg`). Update the call site
  in `auto_center_laea`. No test rename — the helper is referenced indirectly via the M2.5 tests.
- [x] Rework `affine_world_to_svg` in `pycarto/svg.py` to aggregate per-row `main_polygon_bounds` instead
  of `gdf.total_bounds`, mirroring `auto_center_laea`'s pattern verbatim. Strengthen the existing
  degenerate-bbox guard from `if map_w == 0 or map_h == 0` to `if not (map_w > 0 and map_h > 0)` — same
  test coverage of zero/zero, plus catches NaN (all-empty frames) and negatives. Add a new `# Local`
  import section to `svg.py` for `from pycarto.geom import main_polygon_bounds`; this is the first
  cross-module dependency in pycarto, one-way (svg → geom).
- [x] Refresh the `affine_world_to_svg` docstring to describe the new bounds semantics, reference M3.5,
  and acknowledge the off-canvas-`<path>`-data trade-off.
- [x] Add `test_affine_world_to_svg_ignores_overseas_dependencies` to `_tests/test_svg.py` reusing the
  existing `country_with_overseas` fixture (no new fixture; CRS unvalidated, math unit-agnostic). Asserts
  `height == 608` (metropolitan-only bounds) instead of 529 (metropolitan + Caribbean span).
- [x] Add `test_affine_world_to_svg_rejects_all_empty_geometry_frame` to cover the new fallback branch
  (all-empty `Polygon()` rows → NaN bounds → ValueError via the strengthened guard).
- [x] Verify all M3 tests pass without modification — including the synthetic Benelux golden snapshot
  (`fake_world` has no MultiPolygons, so `main_polygon_bounds(Polygon) = Polygon.bounds` exactly and the
  per-row aggregation yields the same result as `gdf.total_bounds` for all-Polygon frames).
- [x] Drop the workaround `filter_overseas` helper from `_drafts/render_benelux.py` and re-run as
  end-to-end smoke verification. Output viewBox should now be `0 0 1000 ~1384` (correct Benelux aspect
  ratio) without the manual filter.
- [x] Update the "Risks / gotchas" overseas-territories entry below to note that the bounds half is now
  also fixed; only the off-canvas `<path>` data remains as a documented trade-off pending an opt-in
  `drop_overseas` helper.
- [x] Bump the M3.5 status row to `Complete <date>` and tick all checkboxes once the gate is green.

**Gate:** ✔ `test_affine_world_to_svg_ignores_overseas_dependencies` — projected canvas height for the
overseas fixture is 608 (metropolitan-only) not 529 (metropolitan + Caribbean span). The M3 Benelux
golden snapshot stays bit-identical. `uv run ruff check . && uv run mypy pycarto && uv run pytest -m "not
network"` all clean; coverage on `pycarto/geom.py` and `pycarto/svg.py` stays at 100%.

### M4 — `build_map` orchestration (`__init__.py`) (¼ day) — Complete (2026-05-10)

- [x] Compose `data → geom → svg` in `pycarto/__init__.py`. Signature matches the intro-doc draft minus what was
  already promoted to defaults in M1–M3 (`filter_field`, `id_field`, `id_lower`, `width`, `padding`,
  `simplify_tolerance=4_000.0`).
- [x] `projection: str | None = None` — `None` derives a LAEA via :func:`pycarto.geom.auto_center_laea` from the
  selection's WGS84 bbox (idiomatic for regional maps; reuses the M2.5 helper). Selections spanning the
  antimeridian still surface the M2 `UserWarning` from `auto_center_laea`.
- [x] `suggest_only: bool = False` and `suggestions: Iterable[str] | None = None`. `suggestions` extends
  `iso_codes` (curate-and-rebuild flow) — caller runs `suggest_neighbors`, reviews, passes accepted codes back.
  Codes are upper-cased + de-duped before `data.select`.
- [x] Forward-declare the M5 public surface: `pycarto/borders.py` ships a frozen `Suggestion` dataclass (schema
  locked per the roadmap §M5 spec) and a `suggest_neighbors` stub that raises `NotImplementedError("lands in
  M5")`. `build_map(..., suggest_only=True)` short-circuits before any I/O and delegates to that stub. M5 just
  fills the body — no signature churn.
- [x] Public API: `from pycarto import Suggestion, build_map, suggest_neighbors`. `REGION_PROJECTIONS` stays in
  `pycarto.geom` (canonical home) — `from pycarto.geom import REGION_PROJECTIONS` is the documented import path.
  `__all__` rebuilt with comment-grouped Metadata / Public API sections.
- [x] Default SVG output folder: a bare filename (no directory component) is resolved under
  `Path.cwd() / "_img"` — mirrors `pycarto.data.ensure_natural_earth`'s `_data/` cache resolution. Missing
  parent directories are created with `mkdir(parents=True, exist_ok=True)`. `_img/` is gitignored alongside
  `_data/`. Explicit directories or absolute paths bypass the default and are still honored verbatim.
- [x] Tests are synthetic-only (`_tests/test_build_map.py` writes `fake_world` to a temp shapefile via `tmp_path`
  and passes it as `shp_path`) — mirrors M3's pattern. Real-NE SE Asia / South America counts stay deferred to
  M6's `network`-marked end-to-end test.

**Gate:** ✔ Synthetic Benelux end-to-end (`select → auto_center_laea → reproject → simplify_topological →
render_svg`) writes a 3-path SVG with stable lowercase ids `be` / `lu` / `nl`. `suggest_only=True` raises
`NotImplementedError` without touching the filesystem. `uv run ruff check . && uv run ruff format --check . &&
uv run mypy pycarto && uv run pytest -m "not network"` all clean; coverage stays at 100%. Real-NE SE Asia / South
America (intro-doc) deferred to the M6 `network`-marked test.

### M5 — Border suggester + region unification (1½–2 days) — Complete (2026-05-10)

The suggester (`borders.py`) is the only piece without a draft. Region unification is an additive SVG-rendering
deliverable that lands in the same milestone because it's the second half of "make regional maps look clean" alongside
the suggester. Two building blocks for the suggester:

**Adjacency graph**

- [x] Build on the **raw, unsimplified** NE frame — simplification can erode shared boundaries below numerical noise.
- [x] For each selected country, candidate neighbors = countries whose bbox intersects (selection bbox buffered by ~1°).
  Avoids quadratic blowup on the full 250-row frame.
- [x] Pair adjacency = `geom_a.intersection(geom_b).length > epsilon`. Don't use exact `touches()` — it's brittle on
  Natural Earth's vertex-snapped polygons. Drop pairs that meet at a single point (length ≈ 0).

**Two scorers**

- [x] Enclave scorer: candidate country `c` is an enclave if it has at least one neighbor and **every** neighbor is in
  `selection`. Score = 1.0. Inlined into `suggest_neighbors` rather than extracted as `_find_enclaves` — the body is
  small enough that an extra function would obscure rather than clarify; an explicit `if not nbrs: continue` guard
  blocks vacuous-`all([])` false positives on isolated islands.
- [x] Shared-border scorer: `sum(shared_boundary_length(candidate, s) for s in selection ∩ neighbors(candidate)) /
  candidate.boundary.length`. Range [0, 1], threshold-gated. Skipped when the enclave scorer already fired for the
  candidate.

**Public API**

```python
@dataclass(frozen=True)
class Suggestion:
    iso: str  # ISO_A3_EH of the suggested country
    reason: Literal["enclave", "shared_border"]
    score: float  # 1.0 for enclave; ratio in [0,1] for shared_border
    neighbors_in_selection: tuple[str, ...]


def suggest_neighbors(
    iso_codes: Iterable[str],
    *,
    enclaves: bool = True,
    shared_border_threshold: float = 0.5,
    shp_path: Path | None = None,
) -> list[Suggestion]: ...
```

`iso_codes` widened from M4's `list[str]` to `Iterable[str]` so the public API matches `build_map`'s
`Iterable[str]` parameter without a manual `list(...)` cast at the wiring point. Returned list is sorted by
`(reason_rank, -score, iso)` — enclaves first, then descending score within each reason, ISO breaks ties.

**Wire `suggest_only=True` in `build_map`**: returns the `list[Suggestion]` and skips geom + svg work entirely
(unchanged from M4 — only the body it delegates to changed).

**Region unification** (borderless fills — opt-in, orthogonal to the suggester):

- [x] New `unify_region: bool = False` kwarg on `build_map`. When `True`, each country `<path>` element renders
  with ``stroke="none"`` (fill-only) so adjacent countries with the same fill color visually merge into a single
  region. No internal borders, no outline overlay, no geometric dissolve — purely a styling switch. Default
  `False` keeps the per-country border stroke (M3 / M4 output bit-for-bit unchanged).
- [x] New `country_borders: bool = True` kwarg on `svg.render_svg`. ``True`` → each country path carries
  ``fill="#d8d8d8" stroke="#555" stroke-width="0.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"``.
  ``False`` → ``fill="#d8d8d8" stroke="none"``. `build_map` passes `country_borders=not unify_region` through.
- [x] **Styling switched from `<style>` block to SVG presentation attributes** (`fill="…"` / `stroke="…"` /
  `stroke-width="…"` / `stroke-linejoin="round"` / `vector-effect="non-scaling-stroke"` written directly on each
  `<path>`). The original `_DEFAULT_STYLE` constant was dropped — embedded `<style>` isn't reliably parsed by
  every SVG renderer (some IDE preview panes and image-processing tools silently skip it, leaving country
  `<path>` strokes defaulting to a visible border). Presentation attributes render identically across every
  spec-compliant viewer. Module constants `_COUNTRY_FILL`, `_BORDER_STROKE`, `_BORDER_STROKE_WIDTH` carry the
  color/width values; `render_svg` builds the attribute strings inline. Both M3 and M5 golden snapshots
  regenerated to reflect the new format.
- [x] `suggest_only=True` short-circuits before `render_svg` is called, so `unify_region` is a no-op when both
  are set — covered by `test_build_map_suggest_only_overrides_unify_region`.
- **Design pivot during M5:** the original spec called for `unify_region=True` to dissolve the frame via
  `shapely.ops.unary_union`, filter with a `_largest_sub_polygon` helper, and emit a stroked
  `<path id="region">` overlay. That landed and worked, but produced a visual asymmetry — the dissolve filter
  dropped offshore islands from the overlay, so the mainland received a dark stroke while offshore islands
  rendered as borderless gray silhouettes. User feedback during the first DACH/Benelux real-NE run flagged
  this as inconsistent. The simpler current design (just toggle country strokes off, no overlay) avoids the
  asymmetry entirely. The `_largest_sub_polygon` helper, `_compute_affine_matrix` helper,
  `shapely.ops.unary_union` import in `__init__.py`, and the `region_outline: BaseGeometry | None` parameter
  on `render_svg` were all dropped in the simplification.

**Tests** (split between fast synthetic-fixture algorithm tests and `@pytest.mark.network` real-NE cases):

- [x] Synthetic-fixture tests in `_tests/test_borders.py` cover algorithm correctness without network: enclave
  detection on the `enclave_synthetic` fixture, shared-border above/below threshold on `shared_border_synthetic`
  (with different selections to swing the ratio), zero-neighbor-island guard on `island_no_neighbors`, sort-order
  stability, `enclaves=False` suppression, enclave-precedence-over-shared-border, and
  `neighbors_in_selection` ⊆ selection invariant.
- [x] `@pytest.mark.network` cases on real NE 1:50m. Behavior diverges from the original roadmap intuitions in two
  places — the strict definition is the contract, and the test expectations document what NE 1:50m actually
  produces:
  - `["FRA","DEU","ITA","AUT"]` → `CHE` as **`shared_border`** (not enclave). NE 1:50m records a measurable
    LIE-CHE border, so CHE has a neighbor outside the selection and the strict enclave definition doesn't fire.
    Score is still high (>0.5) — the LIE fragment is a tiny part of CHE's perimeter.
  - `["UKR","POL","LTU","LVA","RUS"]` → `BLR` as **`enclave`** (score 1.0, not the originally-anticipated
    shared_border > 0.7). All 5 of Belarus's NE-1:50m neighbors are in the selection.
  - `["BEL","NLD"]` with `shared_border_threshold=0.3` → `LUX` as `shared_border` — matches the original intent
    (LUX isn't enclosed because FRA + DEU are also neighbors but not in selection).
- [x] Synthetic Benelux `unify_region=True` (equivalent: `render_svg(..., country_borders=False)`) → SVG
  contains 3 country paths each with `stroke="none"`, no `<path id="region">` overlay. New golden snapshot at
  `_tests/test_svg/test_render_svg_benelux_unified_golden_snapshot.svg`. The existing M3 golden snapshot for
  the default (`country_borders=True`) path keeps passing — regenerated once at M5 to switch from embedded
  `<style>` to presentation attributes.

**Gate:** ✔ Synthetic suggester tests + region-unification tests pass without network. The three real-NE cases
pass under `pytest -m network`. The M3 Benelux golden snapshot stays bit-identical. `uv run ruff check . && uv
run ruff format --check . && uv run mypy pycarto && uv run pytest -m "not network"` all clean; coverage stays at
100% across the touched modules.

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
- **Overseas territories** — **Resolved in M2.5 + M3.5**: Natural Earth's `admin_0_countries` aggregates
  dependencies into the parent country polygon (Caribbean NL inside `NLD`, French Guiana inside `FRA`,
  Hawaii/Alaska inside `USA`). Two downstream effects, each addressed separately:
  1. `auto_center_laea` returned a center in open water → M2.5 aggregates per-row largest-sub-polygon bbox.
  2. `affine_world_to_svg` deformed the canvas aspect ratio → M3.5 mirrors the same per-row aggregation via
     the public `main_polygon_bounds` helper (promoted from private in M3.5).
  Off-canvas `<path d>` data for overseas parts still emits into the per-country SVG paths (renderers clip
  to viewBox), so the output file is ~30% larger for selections including NLD / FRA / USA / GBR; an opt-in
  `drop_overseas` helper that strips them entirely is deferred to post-v1. Full subunit-level splitting
  (separate `<path>` per dependency) stays post-v1. (M5's `unify_region=True` is unaffected by overseas
  territories — the simplified styling-only design renders them as borderless fill silhouettes consistent
  with the mainland; no overlay is drawn that would single them out.)
- **Singapore / GUF / small islands**: present in 1:50m, drop out at 1:110m. Tests at 1:110m must avoid them or use
  larger countries.
- **`_data/` cache vs reproducibility**: M1 downloads from `naciscdn.org` (rolling-latest); URL-based pinning is not
  viable because `nvkelso/natural-earth-vector` doesn't ship the bundled zip as a release asset or repo path. The
  realistic post-v1 plan is content-hash pinning — record an expected SHA256 of the zip and verify on download.
  Tracked as an inline `TODO(post-v1)` in `pycarto/data.py`.

## Total estimate

~3¾–4¼ working days for v1, with M5 the only milestone where unknowns are real (M2.5 adds ~¼ day).