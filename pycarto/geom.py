"""Projection presets, reprojection, and topology-preserving simplification.

Three building blocks plus one constants table:

- :data:`REGION_PROJECTIONS` — PROJ string presets per region (LAEA, Robinson for world).
- :func:`auto_center_laea` — build a LAEA PROJ string from the WGS84 bbox center of a selection.
- :func:`reproject` — thin wrapper around ``GeoDataFrame.to_crs`` kept for testability.
- :func:`simplify_topological` — topology-preserving simplification via ``topojson``.
"""

# Standard library
from collections.abc import Iterable
import logging
from typing import Final
import warnings

# Third-party
from geopandas import GeoDataFrame
from shapely.geometry import MultiPolygon, box
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


def main_polygon_bounds(geom: BaseGeometry) -> tuple[float, float, float, float]:
    """Return the bbox of ``geom``'s dominant sub-polygon by area.

    Used by :func:`auto_center_laea` and :func:`pycarto.svg.affine_world_to_svg` to ignore Natural Earth's
    overseas-dependency aggregation when computing region-level bboxes: a ``MultiPolygon`` contributes only its
    largest part, not the union of all parts. Without this, selections that include `NLD` / `FRA` / `USA` /
    `GBR` would have their bboxes stretched across an ocean by Caribbean NL / French Guiana / Hawaii / etc.,
    pushing projection centers into open water and deforming the SVG canvas aspect ratio.

    Dispatch:
        - ``Polygon`` → ``geom.bounds`` (single-part input is its own dominant part).
        - ``MultiPolygon`` → bounds of ``max(geom.geoms, key=area)``. Python's stable :func:`max` returns the first
          equal-area sub-polygon by index — the project's tie-break contract.
        - Anything else (``GeometryCollection``, etc.) → defensive fall-back to ``geom.bounds``.

    Args:
        geom: A shapely geometry — typically a ``Polygon`` or ``MultiPolygon`` row from a ``GeoDataFrame``.

    Returns:
        A ``(minx, miny, maxx, maxy)`` tuple in the same units as ``geom`` (degrees for WGS84, meters for LAEA).
    """
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda part: part.area).bounds
    return geom.bounds


def drop_overseas(
    gdf: GeoDataFrame,
    *,
    iso_codes: Iterable[str] | None = None,
    iso_field: str = "ISO_A3_EH",
    top_n: int = 1,
) -> GeoDataFrame:
    """Reduce each ``MultiPolygon`` row to its ``top_n`` largest sub-polygons by area.

    Companion to :func:`main_polygon_bounds` on the geometry-column side: where
    ``main_polygon_bounds`` only reads the dominant sub-polygon's bbox for projection-center and
    canvas-size derivation, this rewrites the geometry itself so the dropped sub-polygons disappear
    from downstream simplification and SVG emission. Use this when the off-canvas leakage from
    overseas dependencies (Hawaii / Aleutians in ``USA``, Caribbean NL in ``NLD``, French Guiana
    in ``FRA``) leaves visible edge artifacts in the rendered map.

    ``iso_codes`` selectively targets specific countries — useful when a selection mixes rows that
    *need* dropping (USA's Hawaii / Aleutians) with rows that shouldn't be touched (Canada's
    Arctic Archipelago, Indonesia's island chain). ``None`` (the default) applies to every row.
    Codes are uppercased before matching, so case-insensitive on input.

    ``top_n`` controls how many sub-polygons survive. The default ``1`` keeps only the dominant
    sub-polygon (mainland). Higher values keep the next-largest pieces too — ``top_n=2`` on USA
    keeps contiguous 48 + Alaska, dropping Hawaii / PR / Aleutians. Useful when a country has
    multiple major landmasses that should all stay visible.

    Non-``MultiPolygon`` rows (single ``Polygon``, ``None``, ``GeometryCollection``, etc.) pass
    through unchanged. Ties between equal-area sub-polygons resolve to the first by index
    (Python stable :func:`sorted`), mirroring the tie-break contract locked in by ``overseas_tied_areas``.

    Args:
        gdf: Frame whose geometry column may contain ``MultiPolygon`` entries.
        iso_codes: Optional iterable of ISO codes restricting which rows are reduced. ``None``
            applies the reduction to every row.
        iso_field: Column to match ``iso_codes`` against. Defaults to ``"ISO_A3_EH"`` — same
            default as :func:`pycarto.data.select`.
        top_n: Number of largest sub-polygons to keep per targeted ``MultiPolygon`` row. Defaults
            to ``1`` (mainland only).

    Returns:
        A defensive copy of ``gdf`` with every targeted ``MultiPolygon`` row reduced to its top-``n``
        sub-polygons by area. Untargeted rows pass through. Index and non-geometry columns are
        preserved.
    """

    def _reduce(geom: BaseGeometry | None) -> BaseGeometry | None:
        if not isinstance(geom, MultiPolygon):
            return geom
        # Sort by area descending (stable). ``sorted`` is Python-stable so ties preserve original index.
        ordered = sorted(geom.geoms, key=lambda part: part.area, reverse=True)
        kept = ordered[:top_n]
        if len(kept) == 1:
            return kept[0]
        return MultiPolygon(kept)

    out = gdf.copy()
    if iso_codes is None:
        out["geometry"] = out.geometry.apply(_reduce)
    else:
        targets = {c.upper() for c in iso_codes}
        mask = out[iso_field].astype(str).str.upper().isin(targets)
        out.loc[mask, "geometry"] = out.loc[mask, "geometry"].apply(_reduce)
    return out


def clip_to_canvas(gdf: GeoDataFrame) -> GeoDataFrame:
    """Clip every geometry to the union bbox of all rows' main sub-polygons.

    Computes the canvas bbox via :func:`main_polygon_bounds` aggregation (same strategy used by
    :func:`auto_center_laea` and :func:`pycarto.svg.affine_world_to_svg`), then
    intersects each row's geometry with that bbox. Sub-polygons fully outside become empty and
    disappear from the rendered SVG; sub-polygons crossing the boundary get cleanly cut with
    straight edges; sub-polygons fully inside survive unchanged.

    Compared to :func:`drop_overseas` — which keeps only each row's largest sub-polygon — this
    preserves additional sub-polygons that are visually *inside* the canvas (Vancouver Island /
    Newfoundland / PEI in Canada, Tasmania in Australia, secondary islands in Indonesia /
    Philippines / Japan / New Zealand) while still removing the off-canvas outliers that would
    otherwise render as jagged clipped silhouettes at the SVG edges (Alaska / Hawaii in USA,
    Canadian Arctic Archipelago, Aleutians wrapping past the antimeridian).

    Typically run **after** :func:`reproject` so the canvas bbox is computed in projected
    coordinates — running this on antimeridian-spanning WGS84 input would yield a degenerate
    bbox that wraps the wrong way around the globe.

    Args:
        gdf: Frame whose geometry should be clipped to the canvas. Usually the output of
            :func:`reproject`.

    Returns:
        A defensive copy of ``gdf`` with each geometry intersected against the union main bbox.
        Sub-polygons fully outside the bbox produce empty geometry (silently dropped by
        :func:`pycarto.svg.render_svg`).
    """
    bounds = [main_polygon_bounds(g) for g in gdf.geometry if isinstance(g, BaseGeometry) and not g.is_empty]
    if not bounds:
        return gdf.copy()
    mins_x, mins_y, maxs_x, maxs_y = zip(*bounds, strict=True)
    canvas = box(min(mins_x), min(mins_y), max(maxs_x), max(maxs_y))

    def _clip(geom: BaseGeometry | None) -> BaseGeometry | None:
        if not isinstance(geom, BaseGeometry) or geom.is_empty:
            return geom
        return geom.intersection(canvas)

    out = gdf.copy()
    out["geometry"] = out.geometry.apply(_clip)
    return out


def auto_center_laea(gdf: GeoDataFrame) -> str:
    """Build a LAEA PROJ string centered on the WGS84 bbox of ``gdf``.

    Uses the bbox center (``(minx + maxx) / 2``, ``(miny + maxy) / 2``) rather than the geometry centroid:
    deterministic, free of geographic-CRS centroid warnings, and matches the round-number style of the
    :data:`REGION_PROJECTIONS` presets.

    Each row contributes the bbox of its largest sub-polygon by area (via :func:`main_polygon_bounds`), not its
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
    bounds = [main_polygon_bounds(g) for g in gdf.geometry if isinstance(g, BaseGeometry) and not g.is_empty]
    if bounds:
        mins_x, mins_y, maxs_x, maxs_y = zip(*bounds, strict=True)
        minx, miny = float(min(mins_x)), float(min(mins_y))
        maxx, maxy = float(max(maxs_x)), float(max(maxs_y))
    else:
        # Degenerate selection (no usable geometry): preserve ``total_bounds``' NaN-propagating behavior.
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

    Thin wrapper around :meth:`GeoDataFrame.to_crs` — kept as its own symbol so callers can substitute or mock
    the projection step in isolation, and so the public API stays uniform across the geom-pipeline functions.

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
    their selection) — lets ``build_map`` wire this step in without special-casing the no-simplification path.

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
