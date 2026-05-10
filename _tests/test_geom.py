"""Tests for ``pycarto.geom``."""

# Standard library
import logging
import math

# Third-party
import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

# Local
from pycarto.geom import REGION_PROJECTIONS, auto_center_laea, reproject, simplify_topological


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
    """All-empty-geometry frames hit the defensive fallback, preserving M2's NaN-propagating behavior."""
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
    """M2 gate: simplification removes vertices but the shared boundary survives intact (no gaps)."""
    simplified = simplify_topological(adjacent_polygons, tolerance=0.5)
    # Sanity check: simplification actually did work — otherwise the topology check below is vacuous.
    original_vertex_count = sum(len(g.exterior.coords) for g in adjacent_polygons.geometry)
    simplified_vertex_count = sum(len(g.exterior.coords) for g in simplified.geometry)
    assert simplified_vertex_count < original_vertex_count, "toposimplify did not remove any vertices"
    geom_a, geom_b = simplified.geometry.iloc[0], simplified.geometry.iloc[1]
    shared = geom_a.intersection(geom_b)
    assert shared.length > 0, "Adjacent countries lost their shared boundary after simplification"
