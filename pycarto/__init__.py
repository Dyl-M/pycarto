"""Generate region SVG maps from a list of country ISO codes."""

# Standard library
from collections.abc import Iterable
from pathlib import Path

# Local
from pycarto.borders import Suggestion, suggest_neighbors
from pycarto.data import load_countries, select
from pycarto.geom import REGION_PROJECTIONS, auto_center_laea, reproject, simplify_topological
from pycarto.svg import render_svg

__version__ = "0.0.0"
__author__ = "Dylan Monfret"

__all__: list[str] = [
    # Metadata
    "__author__",
    "__version__",
    # Public API
    "REGION_PROJECTIONS",
    "Suggestion",
    "build_map",
    "suggest_neighbors",
]


def build_map(
    iso_codes: Iterable[str],
    output_path: str | Path,
    *,
    projection: str | None = None,
    simplify_tolerance: float = 4_000.0,
    width: int = 1000,
    padding: int = 10,
    id_field: str = "ISO_A2_EH",
    id_lower: bool = True,
    filter_field: str = "ISO_A3_EH",
    shp_path: Path | None = None,
    suggest_only: bool = False,
    suggestions: Iterable[str] | None = None,
) -> Path | list[Suggestion]:
    """Generate a region SVG from a list of ISO codes by composing data → geom → svg.

    Pipeline (default ``suggest_only=False``):

    1. :func:`pycarto.data.load_countries` reads the Natural Earth shapefile (or ``shp_path``).
    2. :func:`pycarto.data.select` filters down to ``iso_codes`` (union ``suggestions``) on ``filter_field``.
    3. :func:`pycarto.geom.auto_center_laea` derives a LAEA PROJ string when ``projection is None``.
    4. :func:`pycarto.geom.reproject` projects the selection.
    5. :func:`pycarto.geom.simplify_topological` runs topology-preserving simplification (or short-circuits
       when ``simplify_tolerance <= 0``).
    6. :func:`pycarto.svg.render_svg` emits the final SVG document, which is written to ``output_path``.

    When ``suggest_only=True`` the function short-circuits after de-duping the input codes and delegates to
    :func:`pycarto.borders.suggest_neighbors`. No shapefile is read and no SVG is written.

    Args:
        iso_codes: ISO codes (alpha-3 by default, see ``filter_field``) of the countries to include. Case-insensitive
            on input — uppercased before lookup.
        output_path: Destination ``.svg`` file. **A bare filename (no directory component) is resolved under**
            ``Path.cwd() / "_img"`` — mirrors the ``_data/`` cache pattern in :mod:`pycarto.data`. Pass an
            explicit directory (``"out/foo.svg"``) or an absolute path to bypass the default folder. Parent
            directories are created if missing. Ignored when ``suggest_only=True``.
        projection: PROJ string (e.g. a :data:`pycarto.REGION_PROJECTIONS` preset). ``None`` → derive via
            :func:`pycarto.geom.auto_center_laea` from the selection's WGS84 bbox. Selections spanning the
            antimeridian (>180° longitude) will surface the M2 :class:`UserWarning` from ``auto_center_laea``.
        simplify_tolerance: ``topojson.toposimplify`` tolerance in projection units (meters for LAEA). ``<= 0``
            short-circuits to a no-simplify defensive copy via :func:`pycarto.geom.simplify_topological`.
        width: SVG canvas width in pixels.
        padding: Pixel margin applied symmetrically on all four sides of the canvas.
        id_field: Column whose value becomes each ``<path>``'s ``id`` attribute.
        id_lower: Lowercase the id (Wikimedia / Liquipedia convention).
        filter_field: Column to filter ``iso_codes`` against (default ``ISO_A3_EH``).
        shp_path: Override Natural Earth fetch by pointing at an existing shapefile (typically used in tests).
        suggest_only: When ``True``, return suggestions and skip geom + svg work entirely. Body lands in M5 —
            currently raises :class:`NotImplementedError` via the :func:`suggest_neighbors` stub.
        suggestions: Additional codes to merge into the selection (curate-and-rebuild flow). Use case: the caller
            ran :func:`suggest_neighbors`, reviewed the result, and now wants to rebuild the map with the
            accepted neighbors included.

    Returns:
        On ``suggest_only=False`` → the :class:`~pathlib.Path` to the written SVG.
        On ``suggest_only=True`` → a ``list[Suggestion]`` from :func:`suggest_neighbors`.
    """
    codes = sorted({c.upper() for c in iso_codes})
    if suggestions:
        codes = sorted({*codes, *(c.upper() for c in suggestions)})

    if suggest_only:
        return suggest_neighbors(codes, shp_path=shp_path)

    countries = load_countries(shp_path)
    selection = select(countries, codes, filter_field=filter_field)

    proj = projection if projection is not None else auto_center_laea(selection)
    projected = reproject(selection, proj)
    simplified = simplify_topological(projected, simplify_tolerance)

    svg_document = render_svg(
        simplified,
        id_field=id_field,
        id_lower=id_lower,
        width=width,
        padding=padding,
    )

    out = Path(output_path)
    if not out.is_absolute() and out.parent == Path("."):
        # Bare filename (no directory component) → default to ``./_img/`` under cwd, resolved at call time so
        # callers can ``chdir`` or override via tests. Mirrors :func:`pycarto.data.ensure_natural_earth`'s
        # ``Path.cwd() / "_data"``.
        out = Path.cwd() / "_img" / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg_document, encoding="utf-8")
    return out
