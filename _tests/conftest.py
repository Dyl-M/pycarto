"""Shared pytest fixtures for pycarto tests."""

# Third-party
import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box


@pytest.fixture
def fake_world() -> gpd.GeoDataFrame:
    """A 5-country synthetic frame with the Natural Earth Elaborate-Heuristic columns."""
    return gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["BEL", "NLD", "LUX", "FRA", "DEU"],
            "ISO_A2_EH": ["BE", "NL", "LU", "FR", "DE"],
            "NAME": ["Belgium", "Netherlands", "Luxembourg", "France", "Germany"],
            "geometry": [
                box(2, 49, 7, 52),
                box(3, 50, 7, 54),
                box(5, 49, 7, 50),
                box(-5, 42, 8, 51),
                box(5, 47, 15, 55),
            ],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def fake_world_no_eh(fake_world: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lower-resolution-style frame: ISO_A3 / ISO_A2 (no _EH suffix)."""
    return fake_world.rename(columns={"ISO_A3_EH": "ISO_A3", "ISO_A2_EH": "ISO_A2"})


@pytest.fixture
def lowercase_columns_world(fake_world: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Same shape as ``fake_world`` but every non-geometry column is lower-cased."""
    geom_col = fake_world.geometry.name
    return fake_world.rename(columns={c: c.lower() for c in fake_world.columns if c != geom_col})


@pytest.fixture
def country_with_overseas() -> gpd.GeoDataFrame:
    """One-row gdf modelling a metropolitan polygon plus a tiny overseas dependency.

    Mirrors Natural Earth's ``admin_0_countries`` aggregation (Caribbean NL inside ``NLD`` etc.). The metropolitan
    box dominates by area so ``_main_polygon_bounds`` picks it; M2.5 asserts the auto-derived center stays inside
    that bbox rather than drifting into the Atlantic.
    """
    metropolitan = box(2, 49, 7, 52)  # 5deg x 3deg = 15 deg2 in NW Europe
    overseas = box(-70, 12, -67, 13)  # 3deg x 1deg = 3 deg2 in the Caribbean
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["XYZ"], "geometry": [MultiPolygon([metropolitan, overseas])]},
        crs="EPSG:4326",
    )


@pytest.fixture
def overseas_tied_areas() -> gpd.GeoDataFrame:
    """One-row gdf with two equal-area sub-polygons — locks the M2.5 first-by-index tie-break."""
    first = box(0, 0, 2, 2)  # area = 4
    second = box(50, 50, 52, 52)  # area = 4
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["TIE"], "geometry": [MultiPolygon([first, second])]},
        crs="EPSG:4326",
    )


@pytest.fixture
def adjacent_polygons() -> gpd.GeoDataFrame:
    """Two adjacent polygons sharing a wiggly edge — *not* a straight line.

    The intermediate vertices on the shared boundary deviate slightly from x=5 (alternating ±0.05) so that
    Douglas-Peucker has real work to do: with collinear vertices, perpendicular distance is zero and the
    simplifier is a no-op, which would make the M2 topology-preservation gate vacuous.
    """
    left = Polygon([(0, 0), (5, 0), (5.05, 1.2), (4.95, 2.5), (5.05, 3.7), (5, 5), (0, 5)])
    right = Polygon([(5, 0), (10, 0), (10, 5), (5, 5), (5.05, 3.7), (4.95, 2.5), (5.05, 1.2)])
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["AAA", "BBB"], "geometry": [left, right]},
        crs="EPSG:4326",
    )
