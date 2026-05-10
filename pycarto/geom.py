"""Projection presets, reprojection, and topology-preserving simplification.

Three building blocks plus one constants table:

- :data:`REGION_PROJECTIONS` — PROJ string presets per region (LAEA, Robinson for world).
- :func:`auto_center_laea` — build a LAEA PROJ string from the WGS84 bbox center of a selection.
- :func:`reproject` — thin wrapper around ``GeoDataFrame.to_crs`` kept for testability.
- :func:`simplify_topological` — topology-preserving simplification via ``topojson``.
"""

# Standard library
import logging
from typing import Final
import warnings

# Third-party
from geopandas import GeoDataFrame
import topojson as tp

logger = logging.getLogger(__name__)

REGION_PROJECTIONS: Final[dict[str, str]] = {
    "europe": "+proj=laea +lat_0=52 +lon_0=10 +ellps=WGS84",
    "asia": "+proj=laea +lat_0=35 +lon_0=100 +ellps=WGS84",
    "se_asia": "+proj=laea +lat_0=10 +lon_0=115 +ellps=WGS84",
    "mena": "+proj=laea +lat_0=27 +lon_0=30 +ellps=WGS84",
    "africa": "+proj=laea +lat_0=0 +lon_0=20 +ellps=WGS84",
    "north_america": "+proj=laea +lat_0=45 +lon_0=-100 +ellps=WGS84",
    "south_america": "+proj=laea +lat_0=-15 +lon_0=-60 +ellps=WGS84",
    "oceania": "+proj=laea +lat_0=-25 +lon_0=155 +ellps=WGS84",
    "world": "+proj=robin +ellps=WGS84",
}

# TODO(pre-v1): auto_center_laea is fooled by Natural Earth's admin_0 aggregation of overseas territories into
#  their parent country (e.g. NLD includes the Caribbean Netherlands, FRA includes French Guiana / DOM-TOM, USA
#  includes Hawaii / Alaska). The resulting bbox spans oceans and the auto-derived center sits in open water.
#  Needs a smarter centering strategy before v1 — candidates: largest-polygon bbox per row, area-weighted
#  centroid, or sourcing centers from ne_50m_admin_0_map_subunits. Full subunit-level splitting can stay post-v1.


def auto_center_laea(gdf: GeoDataFrame) -> str:
    """Build a LAEA PROJ string centered on the WGS84 bbox of ``gdf``.

    Uses the bbox center (``(minx + maxx) / 2``, ``(miny + maxy) / 2``) rather than the geometry centroid:
    deterministic, free of geographic-CRS centroid warnings, and matches the round-number style of the
    :data:`REGION_PROJECTIONS` presets.

    Antimeridian-spanning selections (bbox width > 180°) emit both a :class:`UserWarning` and a ``pycarto.geom`` logger
    warning — LAEA distorts severely across the dateline and the bbox center is meaningless. The PROJ string is still
    returned so callers can decide what to do.

    Caveat: Natural Earth's ``admin_0_countries`` shapefile aggregates overseas territories into their parent
    country polygon (e.g. Caribbean Netherlands inside ``NLD``, French Guiana inside ``FRA``, Hawaii / Alaska inside
    ``USA``). For selections containing such countries the bbox stretches across oceans and the auto-derived center
    lands in open water — fall back to a :data:`REGION_PROJECTIONS` preset for now. A smarter centering strategy is
    a tracked pre-v1 fix (see the ``TODO(pre-v1)`` next to :data:`REGION_PROJECTIONS`).

    Args:
        gdf: Selection in a geographic CRS (typically EPSG:4326 from :func:`pycarto.data.select`).

    Returns:
        A ``+proj=laea`` PROJ string with ``lat_0`` / ``lon_0`` rounded to 4 decimals.

    Raises:
        ValueError: If ``gdf.crs`` is missing or not geographic — the bbox would be in projected units
            (e.g. meters) and the resulting PROJ string would be nonsense.
    """
    if gdf.crs is None or not gdf.crs.is_geographic:
        raise ValueError(f"auto_center_laea expects a geographic CRS (e.g. EPSG:4326); got crs={gdf.crs!r}")
    minx, miny, maxx, maxy = gdf.total_bounds
    if (maxx - minx) > 180:
        msg = (
            f"Selection bbox spans {maxx - minx:.1f}° longitude (>180°). "
            "LAEA will distort severely across the antimeridian; consider an explicit projection."
        )
        warnings.warn(msg, UserWarning, stacklevel=2)
        logger.warning(msg)
    lon_0 = (minx + maxx) / 2
    lat_0 = (miny + maxy) / 2
    return f"+proj=laea +lat_0={lat_0:.4f} +lon_0={lon_0:.4f} +ellps=WGS84"


def reproject(gdf: GeoDataFrame, projection: str) -> GeoDataFrame:
    """Reproject ``gdf`` to ``projection``.

    Thin wrapper around :meth:`GeoDataFrame.to_crs` — kept as its own symbol so M3/M4 can substitute or mock the
    projection step in isolation, and so the public API stays uniform across the geom-pipeline functions.

    Args:
        gdf: Frame to reproject.
        projection: PROJ string or anything ``to_crs`` accepts (EPSG int, dict, etc.).

    Returns:
        A new ``GeoDataFrame`` in the requested CRS.
    """
    return gdf.to_crs(projection)


def simplify_topological(gdf: GeoDataFrame, tolerance: float) -> GeoDataFrame:
    """Apply topology-preserving simplification via :mod:`topojson`.

    Builds a :class:`topojson.Topology`, runs ``toposimplify`` so shared boundaries between adjacent countries are
    simplified as a single arc (preventing the gaps that per-geometry ``shapely.simplify`` would introduce), and returns
    the result as a :class:`GeoDataFrame`.

    ``tolerance`` is in **projection units** — meters for LAEA, degrees if the frame is still in WGS84.
    Target band on 1:50m LAEA is 2000-5000 m. ``tolerance <= 0`` short-circuits to a defensive copy of
    ``gdf`` (not the input object itself, so callers can mutate the result without aliasing back into
    their selection) — lets M4 wire ``build_map`` without special-casing the no-simplification path.

    Args:
        gdf: Projected frame (typically the output of :func:`reproject`).
        tolerance: Simplification tolerance in projection units.

    Returns:
        A new ``GeoDataFrame``: simplified, or a defensive copy of ``gdf`` when ``tolerance <= 0``.
    """
    if tolerance <= 0:
        return gdf.copy()
    topo = tp.Topology(gdf, prequantize=False)
    return topo.toposimplify(tolerance).to_gdf()
