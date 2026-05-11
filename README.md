# PYCARTO | Region SVG maps from a list of country codes

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![License](https://img.shields.io/github/license/Dyl-M/pycarto)

![Status](https://img.shields.io/badge/status-pre--alpha-yellow?style=flat-square)
[![Lint & Test](https://img.shields.io/github/actions/workflow/status/Dyl-M/pycarto/lint-and-test.yml?label=Lint%20%26%20Test&style=flat-square&logo=github-actions&logoColor=white)](https://github.com/Dyl-M/pycarto/actions/workflows/lint-and-test.yml)
[![DeepSource](https://app.deepsource.com/gh/Dyl-M/pycarto.svg/?label=active+issues&show_trend=true&token=TOKEN)](https://app.deepsource.com/gh/Dyl-M/pycarto/)
[![DeepSource](https://app.deepsource.com/gh/Dyl-M/pycarto.svg/?label=code+coverage&show_trend=true&token=TOKEN)](https://app.deepsource.com/gh/Dyl-M/pycarto/)

## About

`pycarto` generates region SVG maps from a list of country ISO codes. A border-aware suggester proposes additional
countries (full enclaves and high shared-border ratio neighbors) for visually cleaner regional maps.

Built on [`geopandas`](https://geopandas.org/) (with [`pyogrio`](https://pyogrio.readthedocs.io/) +
[`httpxyz`](https://codeberg.org/httpxyz/httpxyz) for I/O), [`topojson`](https://github.com/mattijn/topojson) for
topology-preserving simplification, and [`shapely`](https://shapely.readthedocs.io/) for geometry typing. Source
geometry is [Natural Earth](https://www.naturalearthdata.com/) 1:50m (public domain).

The project was started as a side project to help fill out
[Liquipedia's region maps category](https://liquipedia.net/commons/Category:Region_Maps), but the outputs are
general-purpose — they work in any context where a clean SVG region map is needed.

> **Status:** Pre-alpha — environment scaffolding (M0), the data layer (M1), the geometry pipeline (M2 + M2.5
> overseas-territories centering fix), SVG emission (M3 + M3.5 overseas-territories canvas-bounds fix),
> `build_map` orchestration (M4), and the border-suggester + region-unification module (M5) are complete;
> only polish (M6) is pending. See the [Roadmap](_docs/roadmap.md) for milestone progress.

## Project Structure

```
pycarto/
├── __init__.py    # public API: build_map (with unify_region), suggest_neighbors, Suggestion (M4 + M5)
├── data.py        # Natural Earth fetch, cache, column normalization (M1)
├── geom.py        # projection presets, reprojection, topological simplification (M2 + M2.5)
├── borders.py     # adjacency graph + neighbor suggester (M5)
├── svg.py         # affine world→SVG, path emission, fill-only unified mode (M3 + M3.5 + M5)
└── py.typed       # PEP 561 typed-library marker
```

## Quick Start

```python
from pycarto import build_map, suggest_neighbors
from pycarto.geom import REGION_PROJECTIONS

# Generate a map directly from a list of ISO alpha-3 codes.
# A bare filename lands in `./_img/` (gitignored); pass an explicit directory or absolute path to override.
build_map(
    iso_codes=["BRN", "KHM", "IDN", "LAO", "MYS", "MMR", "PHL", "SGP", "THA", "TLS", "VNM"],
    output_path="Map_of_Southeast_Asia.svg",
    projection=REGION_PROJECTIONS["se_asia"],
    simplify_tolerance=4000,
)

# Ask for neighbor suggestions to clean up the selection first.
# Returns a list[Suggestion] sorted (enclaves first, then by descending score, then by iso).
suggestions = suggest_neighbors(["UKR", "POL", "LTU", "LVA", "RUS"])
# -> [Suggestion(iso="BLR", reason="enclave", score=1.0,
#                neighbors_in_selection=("LTU", "LVA", "POL", "RUS", "UKR"))]
```

`build_map` also exposes a dry-run mode that returns suggestions without writing the SVG:

```python
suggestions = build_map(
    iso_codes=["UKR", "POL", "LTU", "LVA", "RUS"],
    output_path="ignored.svg",
    suggest_only=True,
)
```

Add `unify_region=True` for a borderless rendering — every country `<path>` emits `stroke="none"` so adjacent
countries with the same fill visually merge into a single region:

```python
build_map(
    iso_codes=["BEL", "NLD", "LUX"],
    output_path="benelux_unified.svg",
    unify_region=True,
)
```

Per-country `<path id="…">` elements stay intact (just borderless), so they remain queryable for downstream
theming or selection.

## Development

```bash
# Clone the repository
git clone https://github.com/Dyl-M/pycarto.git
cd pycarto

# Install dev dependencies (requires uv)
uv sync --group dev

# Lint & format
uv run ruff check .
uv run ruff format --check .

# Type check
uv run mypy pycarto

# Tests (network-tagged tests are opt-in: drop the marker filter to include them)
uv run pytest -m "not network"
```

## License

Code is licensed under the [MIT License](LICENSE).

## Data License

Geometry sourced from [Natural Earth](https://www.naturalearthdata.com/) is **public domain**. SVG outputs inherit
that public-domain status — no attribution is required to use, redistribute, or relicense them in any context, though
crediting Natural Earth is good practice.

This makes outputs explicitly compatible with restrictive content licenses such as
[CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), used by Wikimedia Commons, Liquipedia, and others.

Avoid these alternative geodata sources — they cannot be redistributed under the same terms: amCharts (CC-BY-NC) and
GADM (no redistribution).
