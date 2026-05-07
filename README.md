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

Built with [`geopandas`](https://geopandas.org/), [`topojson`](https://github.com/mattijn/topojson), and
[`shapely`](https://shapely.readthedocs.io/). Source geometry is [Natural Earth](https://www.naturalearthdata.com/)
1:50m (public domain).

The project was started as a side project to help fill out
[Liquipedia's region maps category](https://liquipedia.net/commons/Category:Region_Maps), but the outputs are
general-purpose — they work in any context where a clean SVG region map is needed.

> **Status:** Pre-alpha — environment scaffolding (M0) is complete; the data, geometry, SVG, and border-suggester
> modules are pending. See the [Roadmap](_docs/roadmap.md) for milestone progress.

## Project Structure

```
pycarto/
├── __init__.py    # public API: build_map, suggest_neighbors, REGION_PROJECTIONS (populated in M4)
├── data.py        # Natural Earth fetch, cache, column normalization (M1)
├── geom.py        # projection presets, reprojection, topological simplification (M2)
├── borders.py     # adjacency graph + neighbor suggester (M5)
├── svg.py         # affine world→SVG, path emission, viewBox/style assembly (M3)
└── py.typed       # PEP 561 typed-library marker
```

## Quick Start (planned API)

> Not implemented yet — the snippet below reflects the planned public surface once milestones M1–M5 land.

```python
from pycarto import REGION_PROJECTIONS, build_map, suggest_neighbors

# Generate a map directly from a list of ISO alpha-3 codes
build_map(
    iso_codes=["BRN", "KHM", "IDN", "LAO", "MYS", "MMR", "PHL", "SGP", "THA", "TLS", "VNM"],
    output_path="Map_of_Southeast_Asia.svg",
    projection=REGION_PROJECTIONS["se_asia"],
    simplify_tolerance=4000,
)

# Or ask for neighbor suggestions to clean up the selection first
suggestions = suggest_neighbors(["FRA", "DEU", "ITA", "AUT"])
# -> [Suggestion(iso="CHE", reason="enclave", score=1.0,
#                neighbors_in_selection=("FRA", "DEU", "ITA", "AUT"))]

```
```python
# Dry-run via build_map: returns suggestions without writing the SVG
suggestions = build_map(
    iso_codes=["UKR", "POL", "LTU", "LVA", "RUS"],
    output_path="ignored.svg",
    suggest_only=True,
)
```

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
