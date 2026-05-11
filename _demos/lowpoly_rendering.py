"""FIFAe regional maps — low-poly variant with small-polygon culling.

Mirrors :mod:`_demos.fifae_regions` (same participants, projections, clipping, curated
suggestions) but cranks :func:`pycarto.geom.simplify_topological`'s tolerance for a faceted
low-poly look, and inserts a local :func:`drop_small_polygons` step after simplification to
cull the tiny-island specks that survive aggressive simplification.

To insert the extra step the script bypasses :func:`pycarto.build_map` and walks the
``data → geom → svg`` pipeline by hand. Pipeline order::

    load_countries → select → drop_overseas → reproject → clip_to_canvas →
    simplify_topological → drop_small_polygons → render_svg → write_text

Outputs land in ``_img/`` (gitignored) under ``fifae_lowpoly_<region>.svg``.

Run::

    uv run python _demos/lowpoly_rendering.py
"""

# Standard library
from pathlib import Path
from typing import Any

# Third-party
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

# Local
from pycarto.data import load_countries, select
from pycarto.geom import (
    REGION_PROJECTIONS,
    clip_to_canvas,
    drop_overseas,
    reproject,
    simplify_topological,
)
from pycarto.svg import render_svg

# Tolerance in projection units (meters for LAEA / Robinson here). Each vertex may deviate
# by up to ``SIMPLIFY_TOLERANCE`` meters from the original, so the value roughly bounds the
# size of the smallest feature that survives. Reference points:
#   ``4_000``                  pycarto default — clean coastlines
#   ``15_000``–``30_000``      visibly faceted, still recognizable
#   ``50_000``–``150_000``     heavily stylized blob (Liquipedia ``Map_of_Europe.svg`` aspect)
# Note: pycarto emits one ``<path>`` per country, so even at very high tolerance the SVG
# keeps N paths (visually merged by ``unify_region=True``) — not a literal single polygon.
SIMPLIFY_TOLERANCE: float = 50_000.0

# Drop any sub-polygon whose area (m² in the projected CRS) falls below this threshold.
# Reference points (rough mental yardstick — actual area depends on the projection's local
# distortion, so tune against the rendered output):
#   ``1e8``    100 km² — a 10 km × 10 km square. Keeps Maldives-tier specks.
#   ``1e9``    1 000 km² — a 30 km × 30 km square. Maldives / Cayman / small specks gone.
#   ``1e10``   10 000 km² — a 100 km × 100 km square. Starts losing Cyprus / Jamaica.
MIN_POLYGON_AREA: float = 1e9

# Per-region projection overrides (see ``_demos/fifae_regions.py`` for rationale).
PROJECTIONS: dict[str, str] = {
    "asia_east_oceania": "+proj=robin +lon_0=120 +ellps=WGS84",
    "north_central_america": "+proj=robin +lon_0=-100 +ellps=WGS84",
}

# Per-region clipping / canvas knobs (see ``_demos/fifae_regions.py`` for rationale).
CLIP_KWARGS: dict[str, dict[str, Any]] = {
    "asia_east_oceania": {"clip_to_canvas": True},
    "asia_west": {"clip_to_canvas": True},
    "north_central_america": {"drop_overseas": {"USA": 2}, "fit_canvas_to_geometry": True},
}

# FIFAe Nations League 2026 Week 2 Group Stage participants per bracket.
FIFAE_REGIONS: dict[str, list[str]] = {
    "asia_east_oceania": [
        "AUS", "BGD", "GUM", "IDN", "IND", "LAO", "NPL",
        "BRN", "HKG", "KGZ", "MDV", "MYS", "NZL", "PNG",
    ],
    "asia_west": [
        "ARE", "BHR", "JOR", "OMN", "QAT", "SAU", "UZB",
    ],
    "north_central_america": [
        "CRI", "DOM", "PAN", "TTO", "USA",
        "CAN", "CYM", "GUY", "PRI", "SLV",
    ],
}

# Curated enclaves + land-bridge fillers (same set as ``_demos/fifae_regions.py``).
SUGGESTIONS: dict[str, list[str]] = {
    "asia_east_oceania": ["TLS", "BTN", "CHN", "MMR", "THA", "KHM", "VNM"],
    "asia_west": ["YEM", "KWT", "IRQ", "IRN", "TKM", "TJK", "AFG"],
    "north_central_america": ["HTI", "MEX", "BLZ", "GTM", "HND", "NIC", "SUR", "VEN"],
}


def _filter_sub_polygons(geom: BaseGeometry, min_area: float) -> BaseGeometry:
    """Keep only sub-polygons whose area meets ``min_area``; return empty Polygon if none."""
    if isinstance(geom, Polygon):
        return geom if geom.area >= min_area else Polygon()
    if isinstance(geom, MultiPolygon):
        kept = [p for p in geom.geoms if p.area >= min_area]
        if not kept:
            return Polygon()
        return kept[0] if len(kept) == 1 else MultiPolygon(kept)
    return geom


def drop_small_polygons(gdf: gpd.GeoDataFrame, *, min_area: float) -> gpd.GeoDataFrame:
    """Filter each row's geometry to sub-polygons whose area >= ``min_area`` (projected units).

    Rows whose sub-polygons all fall below the threshold collapse to an empty Polygon, which
    :func:`pycarto.svg.render_svg` then drops via its empty-``d`` filter.
    """
    out = gdf.copy()
    out["geometry"] = out.geometry.apply(lambda g: _filter_sub_polygons(g, min_area))
    return out


def render_region(region: str, iso_codes: list[str]) -> Path:
    """Run the build_map-equivalent pipeline by hand, with the small-polygon cull inserted."""
    added = SUGGESTIONS.get(region, [])
    codes = sorted({c.upper() for c in iso_codes} | {c.upper() for c in added})
    clip_kwargs = CLIP_KWARGS.get(region, {})

    selection = select(load_countries(), codes)

    drop_kwarg = clip_kwargs.get("drop_overseas", False)
    if isinstance(drop_kwarg, dict):
        for iso, top_n in drop_kwarg.items():
            selection = drop_overseas(selection, iso_codes=[iso], top_n=top_n)
    elif drop_kwarg is True:
        selection = drop_overseas(selection)

    projection = PROJECTIONS.get(region, REGION_PROJECTIONS["world"])
    projected = reproject(selection, projection)

    if clip_kwargs.get("clip_to_canvas", False):
        projected = clip_to_canvas(projected)

    simplified = simplify_topological(projected, SIMPLIFY_TOLERANCE)
    cleaned = drop_small_polygons(simplified, min_area=MIN_POLYGON_AREA)

    svg_document = render_svg(
        cleaned,
        country_borders=False,
        fit_to_geometry=clip_kwargs.get("fit_canvas_to_geometry", False),
    )

    out = Path.cwd() / "_img" / f"fifae_lowpoly_{region}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg_document, encoding="utf-8")
    return out


def main() -> None:
    """Build every region in :data:`FIFAE_REGIONS` with the low-poly + cull pipeline."""
    print(f"simplify_tolerance = {SIMPLIFY_TOLERANCE:g}   min_polygon_area = {MIN_POLYGON_AREA:g}")
    for region, iso_codes in FIFAE_REGIONS.items():
        added = SUGGESTIONS.get(region, [])
        print(f"\n=== {region}  ({len(iso_codes)} participants + {len(added)} added) ===")
        out = render_region(region, iso_codes)
        print(f"  wrote {out}")


if __name__ == "__main__":
    main()
