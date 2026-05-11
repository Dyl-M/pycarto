"""Shared pytest fixtures for pycarto tests."""

# Third-party
import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

# Local
from pycarto.data import select
from pycarto.geom import REGION_PROJECTIONS, reproject


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
    box dominates by area so ``main_polygon_bounds`` picks it, and the auto-derived projection center stays
    inside that bbox rather than drifting into the Atlantic.
    """
    metropolitan = box(2, 49, 7, 52)  # 5deg x 3deg = 15 deg2 in NW Europe
    overseas = box(-70, 12, -67, 13)  # 3deg x 1deg = 3 deg2 in the Caribbean
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["XYZ"], "geometry": [MultiPolygon([metropolitan, overseas])]},
        crs="EPSG:4326",
    )


@pytest.fixture
def overseas_tied_areas() -> gpd.GeoDataFrame:
    """One-row gdf with two equal-area sub-polygons — locks the first-by-index tie-break."""
    first = box(0, 0, 2, 2)  # area = 4
    second = box(50, 50, 52, 52)  # area = 4
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["TIE"], "geometry": [MultiPolygon([first, second])]},
        crs="EPSG:4326",
    )


@pytest.fixture
def projected_square() -> gpd.GeoDataFrame:
    """One-row gdf with a 100x100 square in a generic projected CRS — for ``affine_world_to_svg`` mechanics tests.

    The CRS is set so the frame looks like real input from :func:`pycarto.geom.reproject`; ``affine_world_to_svg``
    doesn't validate it. The 100x100 square makes hand-derivable scale math easy: at ``width=1000, padding=10``,
    ``scale = 980 / 100 = 9.8`` so the canvas comes out 1000x1000 with 10 px insets on every side.
    """
    return gpd.GeoDataFrame(
        {"ISO_A2_EH": ["AA"], "geometry": [box(0, 0, 100, 100)]},
        crs="EPSG:3857",
    )


@pytest.fixture
def benelux_projected(fake_world: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """BEL/NLD/LUX subset of ``fake_world`` reprojected to LAEA Europe.

    Built on synthetic boxes from ``fake_world`` rather than real Natural Earth geometry so the SVG snapshot
    stays deterministic and the test runs without network — real-shapefile coverage lives in the
    ``@pytest.mark.network`` end-to-end tests.
    """
    return reproject(select(fake_world, ["BEL", "NLD", "LUX"]), REGION_PROJECTIONS["europe"])


@pytest.fixture
def enclave_synthetic() -> gpd.GeoDataFrame:
    """5-country frame where the central polygon is fully enclosed by 4 frame strips.

    Used by enclave-detection tests: with selection ``{"NTH","STH","EST","WST"}``, the candidate ``"CTR"``
    has every neighbor in the selection (single-point corner contacts between strips fall below the adjacency
    epsilon and don't count) → score 1.0.
    """
    return gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["CTR", "NTH", "STH", "EST", "WST"],
            "ISO_A2_EH": ["CT", "NT", "ST", "ES", "WS"],
            "NAME": ["Center", "North", "South", "East", "West"],
            "geometry": [
                box(4, 4, 6, 6),  # CTR
                box(3, 6, 7, 7),  # NTH (shares y=6 edge with CTR)
                box(3, 3, 7, 4),  # STH (shares y=4 edge with CTR)
                box(6, 4, 7, 6),  # EST (shares x=6 edge with CTR)
                box(3, 4, 4, 6),  # WST (shares x=4 edge with CTR)
            ],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def shared_border_synthetic() -> gpd.GeoDataFrame:
    """4-country layout where ``CCC`` is wedged between ``AAA`` and ``BBB`` and shares a high-ratio border with both.

    ``DDD`` (a tiny strip on top of ``CCC``) is intentionally left out of the test selection so ``CCC`` has at
    least one neighbor outside the selection — that's what stops the enclave scorer from claiming ``CCC`` and
    forces the shared-border path. With selection ``{"AAA","BBB"}`` the ratio is
    ``(10 + 10) / 22 ≈ 0.909`` which clears the default 0.5 threshold.
    """
    return gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["AAA", "BBB", "CCC", "DDD"],
            "ISO_A2_EH": ["AA", "BB", "CC", "DD"],
            "NAME": ["A", "B", "C", "D"],
            "geometry": [
                box(0, 0, 1, 10),  # AAA — selection
                box(2, 0, 3, 10),  # BBB — selection
                box(1, 0, 2, 10),  # CCC — candidate (tall thin column)
                box(1, 10, 2, 11),  # DDD — outside selection (forces non-enclave)
            ],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def island_no_neighbors() -> gpd.GeoDataFrame:
    """Selection mass plus a disjoint island that lands inside the buffered candidate bbox but touches nothing.

    Locks the zero-neighbor enclave guard: vacuous ``all([])`` would otherwise falsely flag the island as an
    enclave of any selection. With selection ``{"AAA"}`` the bbox buffer puts ``ISL`` in the candidate set, but
    its ``intersection.length`` against ``AAA`` is 0 → empty neighbors → skipped, not suggested.
    """
    return gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["AAA", "ISL"],
            "ISO_A2_EH": ["AA", "IS"],
            "NAME": ["A", "Island"],
            "geometry": [
                box(0, 0, 10, 10),  # AAA — main land mass
                box(11, 0, 12, 1),  # ISL — disjoint, inside buffered bbox (touches at minx=11)
            ],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def adjacent_polygons() -> gpd.GeoDataFrame:
    """Two adjacent polygons sharing a wiggly edge — *not* a straight line.

    The intermediate vertices on the shared boundary deviate slightly from x=5 (alternating ±0.05) so that
    Douglas-Peucker has real work to do: with collinear vertices, perpendicular distance is zero and the
    simplifier is a no-op, which would make the topology-preservation gate vacuous.
    """
    left = Polygon([(0, 0), (5, 0), (5.05, 1.2), (4.95, 2.5), (5.05, 3.7), (5, 5), (0, 5)])
    right = Polygon([(5, 0), (10, 0), (10, 5), (5, 5), (5.05, 3.7), (4.95, 2.5), (5.05, 1.2)])
    return gpd.GeoDataFrame(
        {"ISO_A3_EH": ["AAA", "BBB"], "geometry": [left, right]},
        crs="EPSG:4326",
    )
