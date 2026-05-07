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

| Milestone                                | Status              |
|------------------------------------------|---------------------|
| M0 — Project plumbing                    | Complete 2026-05-07 |
| M1 — Data layer (`data.py`)              | Pending             |
| M2 — Geometry pipeline (`geom.py`)       | Pending             |
| M3 — SVG emission (`svg.py`)             | Pending             |
| M4 — `build_map` orchestration           | Pending             |
| M5 — Border suggester (`borders.py`)     | Pending             |
| M6 — Polish                              | Pending             |

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

- Rewrite `pyproject.toml` with `[build-system]` + hatchling, full `[project]` metadata (classifiers, keywords, authors,
  urls), `[dependency-groups]` (`dev` + `test`), and tool configs: `[tool.ruff]` (line 120, broad ruleset, google
  docstrings, isort known-first-party), `[tool.mypy]` (strict), `[tool.pytest.ini_options]` (testpaths, `network`
  marker), `[tool.coverage.*]`
- Create `pycarto/__init__.py` with `__version__`, `__author__`, comment-grouped `__all__` placeholder
- Create empty `pycarto/py.typed` (PEP 561 typed marker) and `_tests/__init__.py`
- Create empty module skeletons: `pycarto/data.py`, `pycarto/geom.py`, `pycarto/borders.py`, `pycarto/svg.py`
- Add `.github/workflows/lint-and-test.yml` (lint + type-check + test, on push/PR to `main`; uploads coverage to
  DeepSource)
- Add `.github/workflows/codeql.yml` (Python security analysis on push/PR + monthly cron)
- Add `.github/workflows/license_workflow.yml` (annual LICENSE copyright bump on Jan 1; needs `secrets.PAT`)
- Add `.github/dependabot.yml` (monthly grouped uv + github-actions updates targeting `main`)
- Add `.deepsource.toml` (Python analyzer + test-coverage; needs `secrets.DEEPSOURCE_DSN` once the repo is enrolled)
- Polish `.gitignore` (trailing slashes on private-resource directories, add `data/` for the NE cache)

**Gate:**
`uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy pycarto && uv run pytest` green on an
empty test suite.

### M1 — Data layer (`data.py`) (½ day)

- `ensure_natural_earth(resolution="50m") -> Path` — downloads + extracts to `./data/` if missing. Pin a Natural Earth
  release tag in a constant for reproducibility.
- `load_countries(shp_path: Path | None = None) -> GeoDataFrame` — reads, uppercases columns, returns the raw frame.
- `select(gdf, iso_codes, *, filter_field="ISO_A3_EH") -> GeoDataFrame` — filters with `_EH` → non-`_EH` fallback, warns
  on missing codes.
- Tests use NE 1:110m bundled with `pyogrio` (fast, no network).

**Gate:** load + select(`["BEL","NLD","LUX"]`) returns 3 rows.

### M2 — Geometry pipeline (`geom.py`) (½ day)

- `REGION_PROJECTIONS` dict (verbatim from intro doc)
- `auto_center_laea(gdf) -> str` — builds a PROJ string from the selection's centroid (the "good practice" the intro doc
  flagged as a follow-up)
- `reproject(gdf, projection)` — thin wrapper, kept for testability
- `simplify_topological(gdf, tolerance: float)` — `topojson.Topology(...).toposimplify(...).to_gdf()`

**Gate:** simplification preserves topology — adjacent countries still share boundaries (no gaps).

### M3 — SVG emission (`svg.py`) (½ day)

- `geom_to_path(geom) -> str` — (Multi)Polygon → SVG `d` string
- `affine_world_to_svg(gdf, *, width, padding) -> tuple[GeoDataFrame, viewbox, height]` — Y-flip + scale
- `render_svg(gdf, *, id_field, id_lower, width, padding) -> str` — sorts by id, builds the full SVG document

**Gate:** golden snapshot test passes for Benelux at 1:110m.

### M4 — `build_map` orchestration (`__init__.py`) (¼ day)

- Compose `data → geom → svg`. Same signature as the intro-doc draft, minus what we promote to defaults.
- Add `suggest_only: bool = False` and `suggestions: list[str] | None = None` (forward-declared here; M5 wires the
  body).
- Public API: `from pycarto import build_map, suggest_neighbors, REGION_PROJECTIONS`.

**Gate:** end-to-end test reproduces the intro-doc SE Asia / South America outputs (10 + 12 paths).

### M5 — Border suggester (`borders.py`) — the new feature (1–1½ days)

This is the only piece without a draft. Two building blocks:

**Adjacency graph**

- Build on the **raw, unsimplified** NE frame — simplification can erode shared boundaries below numerical noise.
- For each selected country, candidate neighbors = countries whose bbox intersects (selection bbox buffered by ~1°).
  Avoids quadratic blowup on the full 250-row frame.
- Pair adjacency = `geom_a.intersection(geom_b).length > epsilon`. Don't use exact `touches()` — it's brittle on Natural
  Earth's vertex-snapped polygons. Drop pairs that meet at a single point (length ≈ 0).

**Two scorers**

- `_find_enclaves(graph, selection)`: candidate country `c` is an enclave if every neighbor of `c` in the graph is in
  `selection`. Score = 1.0.
- `_shared_border_ratio(graph, selection, candidate)`:
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

- `["FRA","DEU","ITA","AUT"]` → Suggestion for `CHE` with reason="enclave"
- `["UKR","POL","LTU","LVA","RUS"]` → Suggestion for `BLR` with reason="shared_border", score > 0.7
- `["BEL","NLD"]` → no enclave (LUX isn't enclosed by 2 countries), but LUX appears as `shared_border` if threshold
  lowered

**Gate:** the three fixture cases above pass.

### M6 — Polish (¼ day)

- README usage block: minimal `from pycarto import build_map; build_map([...], "out.svg", projection=...)`
- README "suggestions" block: same with `suggest_only=True`
- One end-to-end happy-path golden SVG checked into `_tests/fixtures/`

**Gate:** `uv run pytest && uv run ruff check` green; README runs as written.

## Risks / gotchas to track during implementation

- **Adjacency must run pre-simplification.** Worth a comment in `borders.py`.
- **Floating-point boundary noise**: use `.intersection(...).length > 1e-6` (in degrees on raw NE data) rather than
  `touches()`.
- **Russia / antimeridian**: not in scope for v1, but flag in `geom.py` to warn if selection bbox spans > 180°
  longitude — projection will distort badly.
- **Singapore / GUF / small islands**: present in 1:50m, drop out at 1:110m. Tests at 1:110m must avoid them or use
  larger countries.
- **`data/` cache vs reproducibility**: a future M-something could pin Natural Earth to a specific release URL with a
  checksum. Worth a TODO comment, not a v1 task.

## Total estimate

~3½–4 working days for v1, with M5 the only milestone where unknowns are real.