"""Affine world-to-SVG transform, SVG path emission, and document assembly.

Three building blocks composed by M4's ``build_map``:

- :func:`geom_to_path` — (Multi)Polygon → SVG ``d`` attribute string.
- :func:`affine_world_to_svg` — Y-flip + scale a projected frame into SVG pixel space.
- :func:`render_svg` — sort by id, emit one ``<path>`` per row, wrap in an SVG document.
"""

# Standard library
import logging
from typing import Final
from xml.sax.saxutils import escape

# Third-party
from geopandas import GeoDataFrame
from shapely.affinity import affine_transform
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

# Local
from pycarto.geom import main_polygon_bounds

logger = logging.getLogger(__name__)

# Style theming is explicitly out-of-scope for v1 (see roadmap "Final scope decisions"); each ``<path>`` carries
# its styling on SVG presentation attributes rather than via an embedded ``<style>`` block. Embedded ``<style>``
# isn't reliably honored by every SVG renderer (some IDE previews and image-processing tools ignore it), and
# presentation attributes render identically across every spec-compliant viewer.
_COUNTRY_FILL: Final[str] = "#d8d8d8"
_BORDER_STROKE: Final[str] = "#555"
_BORDER_STROKE_WIDTH: Final[str] = "0.6"
# Sentinel ids dropped before emission. ``-99`` is Natural Earth's "no code assigned" marker;
# ``nan`` covers stringified missing values; the empty string covers blank / whitespace-only ids.
_SKIP_IDS: Final[frozenset[str]] = frozenset({"", "-99", "nan"})


def geom_to_path(geom: BaseGeometry | None) -> str:
    """Render a (Multi)Polygon as an SVG ``d`` attribute string.

    Walks each polygon's exterior + interior rings, emits one ``M…L…Z`` subpath per ring, joins subpaths with a single
    space. Coordinates round to 1 decimal place — at the default 1000 px width this is 0.1 px precision (visually
    lossless) and shrinks the SVG by ~3-4x versus full float repr.

    Returns an empty string for ``None``, empty geometry, or non-(Multi)Polygon input. :func:`render_svg` treats an
    empty ``d`` as "skip this row" so degenerate geometry never produces a stray ``<path d=""/>`` in the output.

    Args:
        geom: A shapely geometry. Typically ``Polygon`` or ``MultiPolygon``; anything else (``LineString``,
            ``GeometryCollection``, etc.) is silently treated as empty.

    Returns:
        The SVG ``d`` attribute string, or ``""`` for empty / unsupported input.
    """
    if geom is None or geom.is_empty:
        return ""
    if isinstance(geom, MultiPolygon):
        polys: list[Polygon] = list(geom.geoms)
    elif isinstance(geom, Polygon):
        polys = [geom]
    else:
        return ""

    parts: list[str] = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            head = f"M{coords[0][0]:.1f},{coords[0][1]:.1f}"
            tail = "".join(f"L{x:.1f},{y:.1f}" for x, y in coords[1:])
            parts.append(f"{head}{tail}Z")
    return " ".join(parts)


def affine_world_to_svg(
    gdf: GeoDataFrame,
    *,
    width: int = 1000,
    padding: int = 10,
) -> tuple[GeoDataFrame, tuple[int, int, int, int], int]:
    """Y-flip and isotropically scale a projected frame into SVG pixel space.

    Each row contributes the bbox of its largest sub-polygon by area (via
    :func:`pycarto.geom.main_polygon_bounds`) — same M2.5 strategy that ``auto_center_laea`` uses. Without this,
    Natural Earth's aggregation of overseas dependencies into the parent country (Caribbean NL inside ``NLD``,
    French Guiana inside ``FRA``, Hawaii / Alaska inside ``USA``) would project into far-flung coordinates and
    pull the affine bbox across the canvas, deforming the aspect ratio (the M3.5 fix). Tiny overseas sub-polygons
    *still appear* in the rendered geometry and project to off-canvas SVG coordinates — they're outside the
    viewBox so renderers clip them, but the path data stays in the file. A future opt-in ``drop_overseas``
    helper would strip them entirely.

    Computes a single scale factor from the corrected bbox so the map fits ``width - 2 * padding`` pixels
    horizontally; height is derived from the aspect ratio. Applies a shapely affine transform with matrix
    ``[scale, 0, 0, -scale, -minx*scale + padding, maxy*scale + padding]`` so:

    - x grows left-to-right (no flip);
    - y grows top-to-bottom (the negation flips world Y to SVG's screen-down convention);
    - the bbox top-left corner lands at ``(padding, padding)`` and the bottom-right at
      ``(width - padding, height - padding)``.

    Returns a new :class:`GeoDataFrame` (defensive copy, mirroring :func:`pycarto.geom.simplify_topological`) so callers
    can mutate the result without aliasing back into their original frame. ``height`` is returned alongside the viewbox
    so callers writing the SVG ``height`` attribute don't have to unpack the tuple.

    Args:
        gdf: A projected frame (typically the output of :func:`pycarto.geom.reproject`). The CRS is not validated —
            running this on geographic-CRS input would scale degrees as if they were meters and produce a deformed
            map.
        width: Output SVG width in pixels.
        padding: Margin in pixels around the map (applied symmetrically on all four sides).

    Returns:
        A 3-tuple ``(transformed_gdf, viewbox, height)`` where ``viewbox`` is ``(0, 0, width, height)`` and ``height``
        is the derived integer pixel height.

    Raises:
        ValueError: If the aggregated bounding box is degenerate (zero / negative / NaN width or height) — a
            single point, a vertical / horizontal strip, or an all-empty-geometry frame. The scale factor would
            otherwise divide by zero or silently collapse the canvas.
    """
    bounds = [main_polygon_bounds(g) for g in gdf.geometry if isinstance(g, BaseGeometry) and not g.is_empty]
    if bounds:
        mins_x, mins_y, maxs_x, maxs_y = zip(*bounds, strict=True)
        minx, miny = float(min(mins_x)), float(min(mins_y))
        maxx, maxy = float(max(maxs_x)), float(max(maxs_y))
    else:
        # All-empty frame: total_bounds is NaN; the guard below catches it.
        minx, miny, maxx, maxy = gdf.total_bounds
    map_w = maxx - minx
    map_h = maxy - miny
    if not (map_w > 0 and map_h > 0):
        # Catches zero, negative, AND NaN (NaN comparisons return False).
        raise ValueError(
            f"Degenerate projected bbox (width={map_w}, height={map_h}); cannot derive a meaningful SVG scale."
        )
    scale = (width - 2 * padding) / map_w
    height = int(map_h * scale + 2 * padding)
    matrix = (scale, 0.0, 0.0, -scale, -minx * scale + padding, maxy * scale + padding)
    out = gdf.copy()
    out["geometry"] = out.geometry.apply(lambda g: affine_transform(g, matrix))
    return out, (0, 0, width, height), height


def render_svg(
    gdf: GeoDataFrame,
    *,
    id_field: str = "ISO_A2_EH",
    id_lower: bool = True,
    width: int = 1000,
    padding: int = 10,
    country_borders: bool = True,
) -> str:
    r"""Render a projected ``GeoDataFrame`` as a complete SVG document string.

    Pipeline: :func:`affine_world_to_svg` → sort rows by ``id_field`` value → emit one ``<path>`` per surviving row
    via :func:`geom_to_path` → wrap in an ``<svg>`` document with a ``<g id="countries">`` grouping element.

    Rows are sorted by their (post-lowercase) id so SVG diffs stay stable across regenerations. Rows whose id is in
    ``{"", "-99", "nan"}`` after stripping, or whose geometry produces an empty ``d`` string, are dropped before
    emission — Natural Earth uses ``-99`` for un-coded territories, and ``<path id="-99"/>`` would be invalid HTML
    and brittle to style downstream.

    Styling is emitted as **SVG presentation attributes** on each ``<path>`` (``fill``, ``stroke``, etc.) rather
    than via an embedded ``<style>`` block. Some renderers (notably some IDE preview panes and image-processing
    libraries) skip embedded CSS, which would silently leave country borders defaulting to a black stroke;
    presentation attributes render identically across every spec-compliant viewer.

    Args:
        gdf: A projected frame, typically the output of :func:`pycarto.geom.simplify_topological` after
            :func:`pycarto.geom.reproject`. Must contain ``id_field`` and a geometry column.
        id_field: Column whose value becomes the ``<path>`` ``id`` attribute. Defaults to ``"ISO_A2_EH"`` (Wikimedia
            alpha-2 lowercase convention); set to ``"ISO_A3_EH"`` / ``"NAME"`` etc. for other targets.
        id_lower: Lowercase the id before emission. Defaults to ``True`` (Wikimedia convention).
        width: Output SVG width in pixels. Height is derived from the projected aspect ratio.
        padding: Margin in pixels around the map.
        country_borders: When ``True`` (default), each country ``<path>`` carries the dark border stroke.
            When ``False``, country paths render fill-only (``stroke="none"``) — used by
            :func:`pycarto.build_map` when ``unify_region=True`` so adjacent countries with the same fill blend
            into a single visual region.

    Returns:
        The full SVG document as a UTF-8-safe string with ``\\n`` line endings, ready for
        ``Path.write_text(..., encoding="utf-8")``.
    """
    transformed, viewbox, height = affine_world_to_svg(gdf, width=width, padding=padding)

    entries: list[tuple[str, str]] = []
    for _, row in transformed.iterrows():
        cid = str(row[id_field] or "").strip()
        if id_lower:
            cid = cid.lower()
        if cid in _SKIP_IDS:
            continue
        d_str = geom_to_path(row.geometry)
        if not d_str:
            continue
        entries.append((cid, d_str))
    entries.sort(key=lambda entry: entry[0])

    if country_borders:
        country_attrs = (
            f'fill="{_COUNTRY_FILL}" stroke="{_BORDER_STROKE}" stroke-width="{_BORDER_STROKE_WIDTH}" '
            'stroke-linejoin="round" vector-effect="non-scaling-stroke"'
        )
    else:
        country_attrs = f'fill="{_COUNTRY_FILL}" stroke="none"'

    # Default ``escape`` only handles ``<``, ``>``, ``&`` — extend to ``"`` so a configurable ``id_field``
    # carrying double-quotes (custom column, ``NAME`` variants in non-NE data, etc.) can't break the SVG attribute.
    paths = [f'  <path id="{escape(cid, {chr(34): "&quot;"})}" {country_attrs} d="{d_str}"/>' for cid, d_str in entries]
    viewbox_str = " ".join(str(v) for v in viewbox)
    body = "\n".join(paths)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox_str}" width="{width}" height="{height}">\n'
        '  <g id="countries">\n'
        f"{body}\n"
        "  </g>\n"
        "</svg>\n"
    )
