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
from shapely.geometry import MultiPolygon
from shapely.geometry.base import BaseGeometry
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


def _main_polygon_bounds(geom: BaseGeometry) -> tuple[float, float, float, float]:
    """Return the bbox of ``geom``'s dominant sub-polygon by area.

    Used by :func:`auto_center_laea` to ignore Natural Earth's overseas-dependency aggregation: a ``MultiPolygon``
    contributes only its largest part, not the union of all parts.

    Dispatch:
        - ``Polygon`` → ``geom.bounds``.
        - ``MultiPolygon`` → bounds of ``max(geom.geoms, key=area)``. Python's stable :func:`max` returns the first
          equal-area sub-polygon by index, which the M2.5 tie-break test locks in.
        - Anything else (``GeometryCollection``, etc.) → defensive fall-back to ``geom.bounds``.

    Args:
        geom: A shapely geometry — typically a ``Polygon`` or ``MultiPolygon`` row from a ``GeoDataFrame``.

    Returns:
        A ``(minx, miny, maxx, maxy)`` tuple.
    """
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda part: part.area).bounds
    return geom.bounds


def auto_center_laea(gdf: GeoDataFrame) -> str:
    """Build a LAEA PROJ string centered on the WGS84 bbox of ``gdf``.

    Uses the bbox center (``(minx + maxx) / 2``, ``(miny + maxy) / 2``) rather than the geometry centroid:
    deterministic, free of geographic-CRS centroid warnings, and matches the round-number style of the
    :data:`REGION_PROJECTIONS` presets.

    Each row contributes the bbox of its largest sub-polygon by area (via :func:`_main_polygon_bounds`), not its
    full geometry. This keeps overseas dependencies from dragging the auto-center across an ocean — Natural Earth
    aggregates Caribbean Netherlands into ``NLD``, French Guiana into ``FRA``, Hawaii / Alaska into ``USA``, and so
    on, and those tiny sub-polygons would otherwise stretch the bbox by tens of degrees. Ties between equal-area
    sub-polygons resolve to the first by index (Python stable :func:`max`).

    Antimeridian-spanning selections (aggregated bbox width > 180°) emit both a :class:`UserWarning` and a
    ``pycarto.geom`` logger warning — LAEA distorts severely across the dateline and the bbox center is meaningless.
    The PROJ string is still returned so callers can decide what to do.

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
    bounds = [_main_polygon_bounds(g) for g in gdf.geometry if isinstance(g, BaseGeometry) and not g.is_empty]
    if bounds:
        mins_x, mins_y, maxs_x, maxs_y = zip(*bounds, strict=True)
        minx, miny = float(min(mins_x)), float(min(mins_y))
        maxx, maxy = float(max(maxs_x)), float(max(maxs_y))
    else:
        # Degenerate selection (no usable geometry): preserve M2's NaN-propagating behavior.
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
