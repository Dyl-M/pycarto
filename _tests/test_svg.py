"""Tests for ``pycarto.svg``."""

# Third-party
import geopandas as gpd
import pytest
from pytest_regressions.file_regression import FileRegressionFixture
from shapely.geometry import LineString, MultiPolygon, Polygon, box

# Local
from pycarto.svg import affine_world_to_svg, geom_to_path, render_svg

# ----------------------------------------------------------------------------------------------------------------------
# geom_to_path
# ----------------------------------------------------------------------------------------------------------------------


def test_geom_to_path_polygon_exact_string() -> None:
    """A simple square produces the expected ``M…L…Z`` string with one M, one Z, and L for each subsequent vertex."""
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # exterior closes by appending the first coord → 5 coords total → 1 M + 4 L + 1 Z.
    assert geom_to_path(poly) == "M0.0,0.0L10.0,0.0L10.0,10.0L0.0,10.0L0.0,0.0Z"


def test_geom_to_path_multipolygon_emits_one_subpath_per_part() -> None:
    """A 2-part MultiPolygon emits two ``M…Z`` subpaths joined by a single space."""
    a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    b = Polygon([(5, 5), (6, 5), (6, 6), (5, 6)])
    out = geom_to_path(MultiPolygon([a, b]))

    parts = out.split(" ")
    assert len(parts) == 2
    assert all(p.startswith("M") and p.endswith("Z") for p in parts)
    # 4-vertex ring + closing coord = 5 coords → 1 M + 4 L + 1 Z per subpath.
    assert all(p.count("M") == 1 and p.count("L") == 4 and p.count("Z") == 1 for p in parts)


def test_geom_to_path_polygon_with_hole_emits_exterior_plus_interior() -> None:
    """A polygon with one interior ring → 2 subpaths (exterior + hole)."""
    ext = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(2, 2), (4, 2), (4, 4), (2, 4)]
    out = geom_to_path(Polygon(ext, [hole]))

    parts = out.split(" ")
    assert len(parts) == 2
    assert all(p.startswith("M") and p.endswith("Z") for p in parts)


def test_geom_to_path_none_returns_empty() -> None:
    """``None`` input → empty string (the render_svg "skip this row" sentinel)."""
    assert geom_to_path(None) == ""


def test_geom_to_path_empty_polygon_returns_empty() -> None:
    """Empty geometry → empty string, before any ring iteration is attempted."""
    assert geom_to_path(Polygon()) == ""


def test_geom_to_path_unsupported_type_returns_empty() -> None:
    """Non-(Multi)Polygon input (e.g. LineString) is silently treated as empty rather than crashing."""
    assert geom_to_path(LineString([(0, 0), (1, 1)])) == ""


def test_geom_to_path_rounds_to_one_decimal() -> None:
    """Coordinates round to 1 decimal place; full-precision floats never leak into the output."""
    poly = Polygon([(1.234, 5.678), (2.345, 5.678), (2.345, 6.789)])
    out = geom_to_path(poly)
    assert "M1.2,5.7" in out
    assert "L2.3,5.7" in out
    assert "L2.3,6.8" in out
    assert "1.234" not in out
    assert "5.678" not in out


# ----------------------------------------------------------------------------------------------------------------------
# affine_world_to_svg
# ----------------------------------------------------------------------------------------------------------------------


def test_affine_world_to_svg_returns_defensive_copy(projected_square: gpd.GeoDataFrame) -> None:
    """Output is a new frame; the input gdf and its geometry are untouched."""
    original_geom = projected_square.geometry.iloc[0]

    out, _, _ = affine_world_to_svg(projected_square)

    assert out is not projected_square
    # Input geometry identity preserved (no in-place mutation aliased back into the caller's frame).
    assert projected_square.geometry.iloc[0] is original_geom


def test_affine_world_to_svg_viewbox_origin_and_width(projected_square: gpd.GeoDataFrame) -> None:
    """Viewbox is ``(0, 0, width, height)`` and aligns with the returned ``height``."""
    _, viewbox, height = affine_world_to_svg(projected_square, width=1000, padding=10)
    assert viewbox == (0, 0, 1000, height)


def test_affine_world_to_svg_height_matches_aspect_ratio_for_square(projected_square: gpd.GeoDataFrame) -> None:
    """Square projected bbox + symmetric padding → height equals width."""
    _, _, height = affine_world_to_svg(projected_square, width=1000, padding=10)
    assert height == 1000


def test_affine_world_to_svg_height_matches_aspect_ratio_for_wide_bbox() -> None:
    """A 2:1 wide bbox produces a height ~half the width plus padding."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ["AA"], "geometry": [box(0, 0, 200, 100)]},
        crs="EPSG:3857",
    )
    _, _, height = affine_world_to_svg(gdf, width=1000, padding=10)
    # scale = (1000 - 20) / 200 = 4.9 → height = int(100 * 4.9 + 20) = 510.
    assert height == 510


def test_affine_world_to_svg_y_flip_lands_world_top_at_svg_top(projected_square: gpd.GeoDataFrame) -> None:
    """The world-space top edge (max-y) maps to the SVG-space top edge (min-y after Y-flip)."""
    out, _, height = affine_world_to_svg(projected_square, width=1000, padding=10)
    ys = [y for _, y in out.geometry.iloc[0].exterior.coords]
    # Square fills the canvas symmetrically: y range [padding, height - padding].
    assert min(ys) == pytest.approx(10.0)
    assert max(ys) == pytest.approx(height - 10.0)


def test_affine_world_to_svg_padding_inset_on_all_sides(projected_square: gpd.GeoDataFrame) -> None:
    """Output bbox is inset from ``(0, 0, width, height)`` by ``padding`` on every side."""
    out, _, height = affine_world_to_svg(projected_square, width=1000, padding=10)
    minx, miny, maxx, maxy = out.total_bounds
    assert minx == pytest.approx(10.0)
    assert miny == pytest.approx(10.0)
    assert maxx == pytest.approx(990.0)
    assert maxy == pytest.approx(height - 10.0)


def test_affine_world_to_svg_ignores_overseas_dependencies(country_with_overseas: gpd.GeoDataFrame) -> None:
    """Canvas bounds derive from the metropolitan polygon, not the metropolitan + overseas span.

    ``country_with_overseas`` is a 1-row gdf whose MultiPolygon = ``box(2, 49, 7, 52)`` (5x3 metropolitan) +
    ``box(-70, 12, -67, 13)`` (3x1 Caribbean). ``affine_world_to_svg`` doesn't validate CRS, so we pass the
    WGS84 fixture directly — the largest-sub-polygon math is unit-agnostic.

    Naive ``total_bounds``: ``(-70, 12, 7, 52)`` → ``map_w=77, map_h=40`` →
    ``scale = 980/77 = 12.727`` → ``height = int(40*12.727 + 20) = 529``.

    With per-row ``main_polygon_bounds`` aggregation: bounds from metropolitan only → ``map_w=5, map_h=3`` →
    ``scale = 980/5 = 196`` → ``height = int(3*196 + 20) = 608``.

    The 529-vs-608 delta is the unambiguous signal that the per-row largest-sub-polygon aggregation is wired in.
    """
    _, _, height = affine_world_to_svg(country_with_overseas, width=1000, padding=10)
    assert height == 608


def test_affine_world_to_svg_fit_to_geometry_expands_to_total_bounds(
    country_with_overseas: gpd.GeoDataFrame,
) -> None:
    """``fit_to_geometry=True`` switches the canvas to ``gdf.total_bounds`` — overseas parts get included."""
    # total_bounds=(-70,12,7,52) → map_w=77, map_h=40 → scale=980/77≈12.727 → height=int(40*scale+20)=529
    _, _, height = affine_world_to_svg(country_with_overseas, width=1000, padding=10, fit_to_geometry=True)
    assert height == 529


@pytest.mark.parametrize(
    ("geom", "label"),
    [
        (box(5, 0, 5, 10), "zero_width"),
        (box(0, 5, 10, 5), "zero_height"),
    ],
    ids=["zero_width", "zero_height"],
)
def test_affine_world_to_svg_rejects_degenerate_bbox(geom: object, label: str) -> None:
    """A degenerate bbox (zero width or height) raises ValueError instead of dividing by zero or corrupting silently."""
    gdf = gpd.GeoDataFrame({"ISO_A2_EH": ["AA"], "geometry": [geom]}, crs="EPSG:3857")
    expected_axis = "width=0" if label == "zero_width" else "height=0"
    with pytest.raises(ValueError, match=f"Degenerate projected bbox.*{expected_axis}"):
        affine_world_to_svg(gdf)


def test_affine_world_to_svg_rejects_all_empty_geometry_frame() -> None:
    """All-empty frame falls through the ``if bounds:`` branch to ``total_bounds`` (NaN), then trips the guard."""
    gdf = gpd.GeoDataFrame({"ISO_A2_EH": ["AA"], "geometry": [Polygon()]}, crs="EPSG:3857")
    with pytest.raises(ValueError, match=r"Degenerate projected bbox.*nan"):
        affine_world_to_svg(gdf)


# ----------------------------------------------------------------------------------------------------------------------
# render_svg
# ----------------------------------------------------------------------------------------------------------------------


def test_render_svg_paths_sorted_by_id() -> None:
    """Output paths appear in id-sorted order regardless of input row order, so SVG diffs stay stable."""
    gdf = gpd.GeoDataFrame(
        {
            "ISO_A2_EH": ["XX", "AA", "MM"],
            "geometry": [box(0, 0, 1, 1), box(2, 2, 3, 3), box(4, 4, 5, 5)],
        },
        crs="EPSG:3857",
    )
    out = render_svg(gdf)
    pos_aa, pos_mm, pos_xx = out.index('id="aa"'), out.index('id="mm"'), out.index('id="xx"')
    assert pos_aa < pos_mm < pos_xx


def test_render_svg_id_lower_default_lowercases() -> None:
    """Default ``id_lower=True`` emits the Wikimedia-style lowercase id."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ["BE"], "geometry": [box(0, 0, 1, 1)]},
        crs="EPSG:3857",
    )
    out = render_svg(gdf)
    assert 'id="be"' in out
    assert 'id="BE"' not in out


def test_render_svg_id_lower_false_preserves_case() -> None:
    """``id_lower=False`` is the escape hatch for non-Wikimedia targets that want the original case."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ["BE"], "geometry": [box(0, 0, 1, 1)]},
        crs="EPSG:3857",
    )
    out = render_svg(gdf, id_lower=False)
    assert 'id="BE"' in out
    assert 'id="be"' not in out


def test_render_svg_skips_empty_and_sentinel_ids() -> None:
    """Rows with id ``""``, ``"  "``, ``"-99"``, or ``"nan"`` are dropped — only the valid id renders."""
    gdf = gpd.GeoDataFrame(
        {
            "ISO_A2_EH": ["AA", "-99", "nan", "  ", ""],
            "geometry": [box(0, 0, 1, 1), box(2, 2, 3, 3), box(4, 4, 5, 5), box(6, 6, 7, 7), box(8, 8, 9, 9)],
        },
        crs="EPSG:3857",
    )
    out = render_svg(gdf)
    assert out.count("<path ") == 1
    assert 'id="aa"' in out


def test_render_svg_skips_empty_geometry_rows() -> None:
    """Rows whose geometry produces an empty ``d`` string are dropped before emission."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ["AA", "BB"], "geometry": [box(0, 0, 100, 100), Polygon()]},
        crs="EPSG:3857",
    )
    out = render_svg(gdf)
    assert 'id="aa"' in out
    assert 'id="bb"' not in out


def test_render_svg_escapes_xml_special_chars_in_id() -> None:
    """``&`` in an id is XML-escaped to ``&amp;`` so the SVG attribute stays valid."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ["a&b"], "geometry": [box(0, 0, 1, 1)]},
        crs="EPSG:3857",
    )
    out = render_svg(gdf, id_lower=False)
    assert 'id="a&amp;b"' in out
    # The unescaped form must not appear in any attribute.
    assert 'id="a&b"' not in out


def test_render_svg_document_shape(projected_square: gpd.GeoDataFrame) -> None:
    """Output includes the XML prolog, viewBox, presentation-attribute styling, and the countries group."""
    out = render_svg(projected_square, width=1000, padding=10)

    assert out.startswith('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n')
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in out
    assert 'viewBox="0 0 1000 1000"' in out
    assert 'width="1000"' in out
    assert 'height="1000"' in out
    # No embedded ``<style>`` block — styling is on per-path presentation attributes for renderer compatibility.
    assert "<style>" not in out
    assert 'fill="#797979"' in out
    assert 'stroke="#555"' in out
    assert '<g id="countries">' in out
    assert out.endswith("</svg>\n")


def test_render_svg_escapes_double_quote_in_id() -> None:
    """Double-quotes in the id are escaped to ``&quot;`` so the SVG attribute stays well-formed."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A2_EH": ['a"b'], "geometry": [box(0, 0, 1, 1)]},
        crs="EPSG:3857",
    )
    out = render_svg(gdf, id_lower=False)
    assert 'id="a&quot;b"' in out
    # The raw quote must NOT close the attribute mid-value.
    assert 'id="a"b"' not in out


def test_render_svg_benelux_golden_snapshot(
    benelux_projected: gpd.GeoDataFrame,
    file_regression: FileRegressionFixture,
) -> None:
    """Benelux selection (synthetic fake_world subset, LAEA Europe) round-trips to a stable SVG snapshot."""
    file_regression.check(render_svg(benelux_projected), extension=".svg")


# ----------------------------------------------------------------------------------------------------------------------
# render_svg — country_borders flag
# ----------------------------------------------------------------------------------------------------------------------


def test_render_svg_country_borders_false_uses_same_color_stroke(benelux_projected: gpd.GeoDataFrame) -> None:
    """``country_borders=False`` paints stroke and fill the same color — covers sub-pixel anti-aliasing seams."""
    out_no_borders = render_svg(benelux_projected, country_borders=False)
    out_with_borders = render_svg(benelux_projected)

    # Fills are present in both modes.
    assert out_no_borders.count('fill="#797979"') == 3
    assert out_with_borders.count('fill="#797979"') == 3
    # ``country_borders=False`` → every country path carries a same-color stroke (no dark border).
    assert out_no_borders.count('stroke="#797979"') == 3
    assert 'stroke="#555"' not in out_no_borders
    # Default → each country path carries the dark border stroke directly.
    assert out_with_borders.count('stroke="#555"') == 3
    assert 'stroke="#797979"' not in out_with_borders


def test_render_svg_country_borders_false_emits_no_region_overlay(benelux_projected: gpd.GeoDataFrame) -> None:
    """``country_borders=False`` produces fill-only-looking output — no ``<path id="region">`` overlay element."""
    out = render_svg(benelux_projected, country_borders=False)

    assert 'id="region"' not in out
    # No element carries the dark ``#555`` border stroke in this mode.
    assert 'stroke="#555"' not in out


def test_render_svg_benelux_unified_golden_snapshot(
    benelux_projected: gpd.GeoDataFrame,
    file_regression: FileRegressionFixture,
) -> None:
    """Benelux + ``country_borders=False`` round-trips to a stable fills-only SVG snapshot."""
    file_regression.check(render_svg(benelux_projected, country_borders=False), extension=".svg")
