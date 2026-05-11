"""Tests for ``pycarto.geom``."""

# Standard library
import logging
import math

# Third-party
import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

# Local
from pycarto.geom import (
    REGION_PROJECTIONS,
    auto_center_laea,
    clip_to_canvas,
    drop_overseas,
    reproject,
    simplify_topological,
)


def test_region_projections_contains_expected_keys() -> None:
    """All region presets from the intro doc are present and map to non-empty PROJ strings."""
    expected = {
        "europe",
        "asia",
        "se_asia",
        "mena",
        "africa",
        "north_america",
        "south_america",
        "oceania",
        "world",
    }
    assert set(REGION_PROJECTIONS) == expected
    assert all(isinstance(v, str) and v.startswith("+proj=") for v in REGION_PROJECTIONS.values())


def test_auto_center_laea_returns_bbox_center() -> None:
    """Center is the bbox midpoint, formatted to 4 decimals."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["FOO"], "geometry": [box(-10, 20, 30, 60)]},
        crs="EPSG:4326",
    )
    proj = auto_center_laea(gdf)
    # bbox center: lon = (-10 + 30) / 2 = 10.0, lat = (20 + 60) / 2 = 40.0
    assert proj == "+proj=laea +lat_0=40.0000 +lon_0=10.0000 +ellps=WGS84"


def test_auto_center_laea_warns_on_antimeridian_span(caplog: pytest.LogCaptureFixture) -> None:
    """Selections wider than 180° emit BOTH a UserWarning and a pycarto.geom logger warning."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["WIDE"], "geometry": [box(-179, -10, 179, 10)]},
        crs="EPSG:4326",
    )
    with caplog.at_level(logging.WARNING, logger="pycarto.geom"), pytest.warns(UserWarning, match=">180"):
        auto_center_laea(gdf)
    assert any(">180" in record.getMessage() for record in caplog.records)


def test_auto_center_laea_rejects_non_geographic_crs() -> None:
    """A projected gdf is rejected — bbox would be in meters and the PROJ string would be nonsense."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["FOO"], "geometry": [box(0, 0, 100_000, 100_000)]},
        crs="EPSG:3857",
    )
    with pytest.raises(ValueError, match="geographic CRS"):
        auto_center_laea(gdf)


def test_auto_center_laea_rejects_missing_crs() -> None:
    """A frame with no CRS is rejected too — we can't tell if the bbox is in degrees or meters."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["FOO"], "geometry": [box(0, 0, 1, 1)]},
        crs=None,
    )
    with pytest.raises(ValueError, match="geographic CRS"):
        auto_center_laea(gdf)


def test_auto_center_laea_ignores_overseas_dependencies(country_with_overseas: gpd.GeoDataFrame) -> None:
    """Center sits inside the metropolitan bbox, not over the Atlantic between metropolitan and overseas parts."""
    proj = auto_center_laea(country_with_overseas)
    # Metropolitan box is (2, 49, 7, 52) → bbox center (lon=4.5, lat=50.5).
    assert proj == "+proj=laea +lat_0=50.5000 +lon_0=4.5000 +ellps=WGS84"


def test_auto_center_laea_tiebreak_picks_first_by_index(overseas_tied_areas: gpd.GeoDataFrame) -> None:
    """When sub-polygons tie on area, max() returns the first by index — center reflects polygon a, not b."""
    proj = auto_center_laea(overseas_tied_areas)
    # First sub-polygon (0, 0, 2, 2) → bbox center (lon=1.0, lat=1.0).
    assert proj == "+proj=laea +lat_0=1.0000 +lon_0=1.0000 +ellps=WGS84"


def test_auto_center_laea_empty_geometry_falls_back_to_total_bounds() -> None:
    """All-empty-geometry frames hit the defensive fallback, preserving ``total_bounds``' NaN-propagating behavior."""
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["NOPE"], "geometry": [Polygon()]},
        crs="EPSG:4326",
    )
    proj = auto_center_laea(gdf)
    assert "nan" in proj.lower()
    # Sanity check: the formatted center is genuinely NaN, not a finite degenerate value.
    lat = float(proj.split("+lat_0=")[1].split()[0])
    lon = float(proj.split("+lon_0=")[1].split()[0])
    assert math.isnan(lat)
    assert math.isnan(lon)


def test_drop_overseas_collapses_multipolygon_to_largest_part(country_with_overseas: gpd.GeoDataFrame) -> None:
    """``MultiPolygon`` row collapses to its largest sub-polygon by area; smaller parts are stripped."""
    result = drop_overseas(country_with_overseas)
    geom = result.geometry.iloc[0]
    # Metropolitan box (2, 49, 7, 52) is 15 deg² vs overseas (-70, 12, -67, 13) at 3 deg² → metropolitan wins.
    assert isinstance(geom, Polygon)
    assert geom.bounds == (2.0, 49.0, 7.0, 52.0)


def test_drop_overseas_passes_single_polygon_rows_through(fake_world: gpd.GeoDataFrame) -> None:
    """Single-``Polygon`` rows (no overseas to drop) survive unchanged geometrically."""
    result = drop_overseas(fake_world)
    assert result.geometry.geom_equals(fake_world.geometry).all()


def test_drop_overseas_returns_defensive_copy(country_with_overseas: gpd.GeoDataFrame) -> None:
    """Output is a separate frame — mutating it doesn't leak back into the caller's selection."""
    result = drop_overseas(country_with_overseas)
    result.loc[result.index[0], "ISO_A3_EH"] = "ZZZ"
    assert country_with_overseas.iloc[0]["ISO_A3_EH"] == "XYZ"


def test_drop_overseas_tiebreak_picks_first_by_index(overseas_tied_areas: gpd.GeoDataFrame) -> None:
    """Two equal-area sub-polygons → first by index wins, mirroring the ``main_polygon_bounds`` tie-break."""
    result = drop_overseas(overseas_tied_areas)
    geom = result.geometry.iloc[0]
    assert isinstance(geom, Polygon)
    # ``first = box(0, 0, 2, 2)`` is index 0 → wins the tie.
    assert geom.bounds == (0.0, 0.0, 2.0, 2.0)


def test_drop_overseas_with_iso_codes_targets_named_rows_only() -> None:
    """An ``iso_codes`` filter reduces only the named rows; untargeted rows keep all sub-polygons."""
    big_left = box(0, 0, 10, 10)
    small_island = box(20, 20, 22, 22)
    multi = MultiPolygon([big_left, small_island])
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["AAA", "BBB"], "geometry": [multi, multi]},
        crs="EPSG:4326",
    )
    # Drop only AAA's secondary sub-polygon. BBB keeps both.
    result = drop_overseas(gdf, iso_codes=["AAA"])
    aaa_geom = result.geometry.iloc[0]
    bbb_geom = result.geometry.iloc[1]
    assert isinstance(aaa_geom, Polygon)
    assert aaa_geom.bounds == (0.0, 0.0, 10.0, 10.0)
    assert isinstance(bbb_geom, MultiPolygon)
    assert len(bbb_geom.geoms) == 2


def test_drop_overseas_iso_codes_case_insensitive() -> None:
    """``iso_codes`` are uppercased before matching, so lowercase input works."""
    big = box(0, 0, 10, 10)
    small = box(20, 20, 22, 22)
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["AAA"], "geometry": [MultiPolygon([big, small])]},
        crs="EPSG:4326",
    )
    result = drop_overseas(gdf, iso_codes=["aaa"])  # lowercase input
    assert isinstance(result.geometry.iloc[0], Polygon)


def test_drop_overseas_top_n_keeps_n_largest_subpolygons() -> None:
    """``top_n=2`` keeps the two largest sub-polygons by area; smaller ones are dropped."""
    big = box(0, 0, 10, 10)  # area 100 — largest
    medium = box(20, 20, 25, 25)  # area 25 — second
    small = box(30, 30, 31, 31)  # area 1 — third (dropped)
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["AAA"], "geometry": [MultiPolygon([small, big, medium])]},  # intentionally unordered
        crs="EPSG:4326",
    )
    result = drop_overseas(gdf, top_n=2)
    geom = result.geometry.iloc[0]
    assert isinstance(geom, MultiPolygon)
    assert len(geom.geoms) == 2
    bounds = sorted(p.bounds for p in geom.geoms)
    assert bounds == [(0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 25.0, 25.0)]


def test_clip_to_canvas_strips_subpolygon_fully_outside_canvas(country_with_overseas: gpd.GeoDataFrame) -> None:
    """A sub-polygon entirely outside the union main bbox is clipped to empty."""
    # Single-row frame → canvas bbox = metropolitan (2, 49, 7, 52). Overseas at (-70, 12, -67, 13) is
    # fully outside. ``intersection(canvas)`` returns just the metropolitan polygon.
    result = clip_to_canvas(country_with_overseas)
    geom = result.geometry.iloc[0]
    # Result is the metropolitan polygon (possibly wrapped as MultiPolygon with one part).
    assert geom.bounds == (2.0, 49.0, 7.0, 52.0)


def test_clip_to_canvas_cuts_subpolygon_crossing_boundary() -> None:
    """A sub-polygon crossing the canvas boundary gets cleanly cut at the bbox edge."""
    # Row A defines the canvas (its main bbox is the largest). Row B is a MultiPolygon whose main
    # sub-polygon is small (inside the canvas) and whose secondary sub-polygon extends ABOVE the
    # canvas top → clip cuts the y > 10 strip away cleanly.
    inside_canvas = box(0, 0, 10, 10)
    # main sub-polygon (area=40) defines Row B's main bbox; secondary (area=36) is smaller, lives above y=10.
    multi = MultiPolygon([box(0, 0, 8, 5), box(2, 8, 8, 14)])  # disjoint by y; secondary extends to y=14
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["A", "B"], "geometry": [inside_canvas, multi]},
        crs="EPSG:4326",
    )
    result = clip_to_canvas(gdf)
    # Canvas bbox = union of main bboxes = (0, 0, 10, 10). Row B's secondary crosses y=10 → clipped.
    geom_b = result.geometry.iloc[1]
    assert geom_b.bounds[3] == 10.0
    # And the in-canvas main sub-polygon survives.
    assert geom_b.bounds[1] == 0.0


def test_clip_to_canvas_preserves_single_polygon_inside_canvas(fake_world: gpd.GeoDataFrame) -> None:
    """Single-``Polygon`` rows fully inside the canvas bbox survive unchanged."""
    result = clip_to_canvas(fake_world)
    # Every row's bbox is inside the union bbox of all rows → intersection is the polygon itself.
    for original, clipped in zip(fake_world.geometry, result.geometry, strict=True):
        assert clipped.equals(original)


def test_clip_to_canvas_returns_defensive_copy(country_with_overseas: gpd.GeoDataFrame) -> None:
    """Output is a separate frame — mutating it doesn't leak back into the caller's selection."""
    result = clip_to_canvas(country_with_overseas)
    result.loc[result.index[0], "ISO_A3_EH"] = "ZZZ"
    assert country_with_overseas.iloc[0]["ISO_A3_EH"] == "XYZ"


def test_clip_to_canvas_all_empty_frame_returns_defensive_copy() -> None:
    """A frame where every row's geometry is empty returns a defensive copy without computing a canvas."""
    # No row contributes usable bounds → the function short-circuits before constructing the box.
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["A", "B"], "geometry": [Polygon(), Polygon()]},
        crs="EPSG:4326",
    )
    result = clip_to_canvas(gdf)
    assert result is not gdf
    assert list(result["ISO_A3_EH"]) == ["A", "B"]
    assert all(g.is_empty for g in result.geometry)


def test_clip_to_canvas_skips_empty_geometry_per_row() -> None:
    """Mixed frames with some empty geometries pass the empty rows through ``_clip`` untouched."""
    # Row A contributes the canvas bbox (0, 0, 10, 10). Row B's empty geometry hits the per-row guard
    # inside ``_clip`` and survives as empty — no intersection attempted (which would raise on empty geom).
    gdf = gpd.GeoDataFrame(
        {"ISO_A3_EH": ["A", "B"], "geometry": [box(0, 0, 10, 10), Polygon()]},
        crs="EPSG:4326",
    )
    result = clip_to_canvas(gdf)
    assert result.geometry.iloc[0].bounds == (0.0, 0.0, 10.0, 10.0)
    assert result.geometry.iloc[1].is_empty


def test_reproject_changes_crs(fake_world: gpd.GeoDataFrame) -> None:
    """Reprojecting from WGS84 to a LAEA preset changes both the CRS and the bounds units."""
    laea = REGION_PROJECTIONS["europe"]
    result = reproject(fake_world, laea)
    assert result.crs is not None
    assert result.crs.is_projected
    # Original WGS84 bounds are well within ±180/±90; LAEA bounds in meters span much larger absolute values.
    assert max(abs(v) for v in result.total_bounds) > 1_000


def test_simplify_topological_passthrough_on_zero_tolerance(adjacent_polygons: gpd.GeoDataFrame) -> None:
    """``tolerance=0`` returns a defensive copy with the same geometry, never the input object itself."""
    result = simplify_topological(adjacent_polygons, tolerance=0)
    assert result is not adjacent_polygons
    assert result.geometry.geom_equals(adjacent_polygons.geometry).all()


def test_simplify_topological_passthrough_on_negative(adjacent_polygons: gpd.GeoDataFrame) -> None:
    """Negative tolerances behave identically to zero: defensive copy, geometry preserved."""
    result = simplify_topological(adjacent_polygons, tolerance=-1.0)
    assert result is not adjacent_polygons
    assert result.geometry.geom_equals(adjacent_polygons.geometry).all()


def test_simplify_topological_preserves_topology(adjacent_polygons: gpd.GeoDataFrame) -> None:
    """Core topology gate: simplification removes vertices but the shared boundary survives intact (no gaps)."""
    simplified = simplify_topological(adjacent_polygons, tolerance=0.5)
    # Sanity check: simplification actually did work — otherwise the topology check below is vacuous.
    original_vertex_count = sum(len(g.exterior.coords) for g in adjacent_polygons.geometry)
    simplified_vertex_count = sum(len(g.exterior.coords) for g in simplified.geometry)
    assert simplified_vertex_count < original_vertex_count, "toposimplify did not remove any vertices"
    geom_a, geom_b = simplified.geometry.iloc[0], simplified.geometry.iloc[1]
    shared = geom_a.intersection(geom_b)
    assert shared.length > 0, "Adjacent countries lost their shared boundary after simplification"
    # ``render_svg`` sorts by ``id_field`` after simplification, so non-geometry columns must survive
    # the ``topojson`` round-trip.
    assert "ISO_A3_EH" in simplified.columns, "Non-geometry columns dropped by topojson.to_gdf()"
