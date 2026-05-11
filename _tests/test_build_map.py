"""Tests for ``pycarto.build_map`` orchestration."""

# Standard library
from pathlib import Path

# Third-party
import geopandas as gpd
import pytest
from pytest_regressions.file_regression import FileRegressionFixture
from shapely.geometry import MultiPolygon, box

# Local
from pycarto import build_map
from pycarto.geom import REGION_PROJECTIONS


@pytest.fixture
def fake_world_shp(tmp_path: Path, fake_world: gpd.GeoDataFrame) -> Path:
    """Persist ``fake_world`` to disk so ``build_map`` can read it via ``shp_path``.

    Synthetic-only so the test runs without network — real-NE end-to-end coverage lives in the
    ``@pytest.mark.network`` golden-snapshot test below.
    """
    shp = tmp_path / "fake_world.shp"
    fake_world.to_file(shp)
    return shp


def test_build_map_writes_svg_with_default_auto_center(tmp_path: Path, fake_world_shp: Path) -> None:
    """Default ``projection=None`` derives a LAEA via ``auto_center_laea`` and the SVG lands at ``output_path``."""
    out = build_map(["BEL", "NLD", "LUX"], tmp_path / "benelux.svg", shp_path=fake_world_shp)

    assert isinstance(out, Path)
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert body.count("<path ") == 3
    # Path id sort lowercase: be, lu, nl.
    assert 'id="be"' in body
    assert 'id="lu"' in body
    assert 'id="nl"' in body
    assert body.startswith('<?xml version="1.0"')


def test_build_map_uses_explicit_projection_when_provided(tmp_path: Path, fake_world_shp: Path) -> None:
    """Caller can pass any PROJ string — preset or custom; ``auto_center_laea`` is bypassed."""
    out = build_map(
        ["BEL", "NLD", "LUX"],
        tmp_path / "benelux_europe.svg",
        projection=REGION_PROJECTIONS["europe"],
        shp_path=fake_world_shp,
    )

    assert isinstance(out, Path)
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_build_map_merges_suggestions_into_selection(tmp_path: Path, fake_world_shp: Path) -> None:
    """``suggestions`` extends ``iso_codes`` (curate-and-rebuild flow)."""
    out = build_map(
        ["BEL", "NLD"],
        tmp_path / "merged.svg",
        suggestions=["LUX"],
        shp_path=fake_world_shp,
    )

    assert isinstance(out, Path)
    body = out.read_text(encoding="utf-8")
    # LUX came in via ``suggestions``, not ``iso_codes``.
    assert 'id="lu"' in body
    assert body.count("<path ") == 3


def test_build_map_dedupes_overlap_between_iso_codes_and_suggestions(tmp_path: Path, fake_world_shp: Path) -> None:
    """An ISO code in both ``iso_codes`` and ``suggestions`` is selected once, not twice."""
    out = build_map(
        ["BEL", "NLD"],
        tmp_path / "dedup.svg",
        suggestions=["NLD", "LUX"],  # NLD overlaps; LUX is new.
        shp_path=fake_world_shp,
    )

    assert isinstance(out, Path)
    body = out.read_text(encoding="utf-8")
    assert body.count('id="nl"') == 1
    assert body.count("<path ") == 3


def test_build_map_lowercase_iso_input_works(tmp_path: Path, fake_world_shp: Path) -> None:
    """ISO codes are upper-cased before matching, so lowercase callers don't have to pre-format."""
    out = build_map(["bel", "nld"], tmp_path / "lower.svg", shp_path=fake_world_shp)

    assert isinstance(out, Path)
    body = out.read_text(encoding="utf-8")
    assert 'id="be"' in body
    assert 'id="nl"' in body


def test_build_map_simplify_tolerance_zero_short_circuits(tmp_path: Path, fake_world_shp: Path) -> None:
    """``simplify_tolerance=0`` → no-simplify defensive copy via ``simplify_topological``; SVG still emits."""
    out = build_map(
        ["BEL", "NLD", "LUX"],
        tmp_path / "no_simplify.svg",
        simplify_tolerance=0,
        shp_path=fake_world_shp,
    )

    assert isinstance(out, Path)
    assert out.exists()


def test_build_map_suggest_only_returns_list_of_suggestions(tmp_path: Path, fake_world_shp: Path) -> None:
    """``suggest_only=True`` calls :func:`pycarto.borders.suggest_neighbors` and returns its ``list[Suggestion]``."""
    result = build_map(
        ["BEL", "NLD"],
        tmp_path / "ignored.svg",
        suggest_only=True,
        shp_path=fake_world_shp,
    )
    assert isinstance(result, list)


def test_build_map_defaults_bare_filename_to_img_folder(
    tmp_path: Path,
    fake_world_shp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare filename (no directory component) → resolved under ``Path.cwd() / "_img"``; folder created if missing."""
    monkeypatch.chdir(tmp_path)
    out = build_map(["BEL", "NLD"], "benelux.svg", shp_path=fake_world_shp)

    assert out == tmp_path / "_img" / "benelux.svg"
    assert out.exists()
    # Folder was created (no preexisting `_img/` under tmp_path).
    assert out.parent.is_dir()


def test_build_map_respects_explicit_directory_in_output_path(tmp_path: Path, fake_world_shp: Path) -> None:
    """An explicit subdirectory bypasses the ``_img/`` default; missing parents are created."""
    target = tmp_path / "custom" / "benelux.svg"
    out = build_map(["BEL", "NLD"], target, shp_path=fake_world_shp)

    assert out == target
    assert out.exists()


def test_build_map_suggest_only_does_not_write_output(tmp_path: Path, fake_world_shp: Path) -> None:
    """``suggest_only=True`` short-circuits *before* any disk I/O (no SVG write)."""
    target = tmp_path / "should_not_exist.svg"
    result = build_map(["BEL", "NLD"], target, suggest_only=True, shp_path=fake_world_shp)
    assert isinstance(result, list)
    assert not target.exists()


def test_build_map_unify_region_drops_country_strokes(tmp_path: Path, fake_world_shp: Path) -> None:
    """``unify_region=True`` paints each country with a same-color stroke — no dark per-country borders."""
    out = build_map(
        ["BEL", "NLD", "LUX"],
        tmp_path / "benelux_unified.svg",
        unify_region=True,
        shp_path=fake_world_shp,
    )

    assert isinstance(out, Path)
    body = out.read_text(encoding="utf-8")
    # All 3 country paths are present with a same-color stroke; no region overlay element is emitted.
    assert 'id="be"' in body
    assert 'id="lu"' in body
    assert 'id="nl"' in body
    assert body.count('stroke="#797979"') == 3
    assert 'stroke="#555"' not in body
    assert 'id="region"' not in body


def test_build_map_unify_region_default_off_keeps_country_strokes(tmp_path: Path, fake_world_shp: Path) -> None:
    """Default ``unify_region=False`` keeps the per-country dark border stroke."""
    out = build_map(["BEL", "NLD", "LUX"], tmp_path / "with_borders.svg", shp_path=fake_world_shp)

    assert isinstance(out, Path)
    body = out.read_text(encoding="utf-8")
    assert body.count('stroke="#555"') == 3
    assert 'stroke="#797979"' not in body


def test_build_map_suggest_only_overrides_unify_region(tmp_path: Path, fake_world_shp: Path) -> None:
    """``suggest_only=True`` short-circuits before any geom / svg work; ``unify_region`` is a no-op in that path."""
    target = tmp_path / "should_not_exist.svg"
    result = build_map(
        ["BEL", "NLD"],
        target,
        suggest_only=True,
        unify_region=True,
        shp_path=fake_world_shp,
    )
    assert isinstance(result, list)
    assert not target.exists()


# ----------------------------------------------------------------------------------------------------------------------
# drop_overseas — strips overseas sub-polygons before SVG emission
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def overseas_country_shp(tmp_path: Path) -> Path:
    """One-row shapefile modelling a metropolitan polygon + a tiny overseas dependency.

    Mirrors the Natural Earth aggregation pattern (Caribbean NL inside ``NLD``, Alaska inside ``USA``, etc.).
    The metropolitan box dominates by area so ``drop_overseas`` keeps it and strips the overseas part.
    """
    metropolitan = box(2, 49, 7, 52)  # 5 x 3 = 15 deg²
    overseas = box(-70, 12, -67, 13)  # 3 x 1 = 3 deg² — projects off-canvas to the west
    gdf = gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["XYZ"],
            "ISO_A2_EH": ["XY"],
            "NAME": ["Land"],
            "geometry": [MultiPolygon([metropolitan, overseas])],
        },
        crs="EPSG:4326",
    )
    shp = tmp_path / "land.shp"
    gdf.to_file(shp)
    return shp


def test_build_map_drop_overseas_strips_subpath_from_svg(tmp_path: Path, overseas_country_shp: Path) -> None:
    """``drop_overseas=True`` collapses the ``MultiPolygon`` to one ring → SVG path has a single ``M`` subpath."""
    out = build_map(
        ["XYZ"],
        tmp_path / "with.svg",
        projection=REGION_PROJECTIONS["europe"],
        drop_overseas=True,
        shp_path=overseas_country_shp,
    )
    d_attr = out.read_text(encoding="utf-8").split(' d="', 1)[1].split('"', 1)[0]
    assert d_attr.count("M") == 1


def test_build_map_drop_overseas_default_keeps_subpaths(tmp_path: Path, overseas_country_shp: Path) -> None:
    """Default ``drop_overseas=False`` keeps every sub-polygon → SVG path has multiple ``M`` subpaths."""
    out = build_map(
        ["XYZ"],
        tmp_path / "without.svg",
        projection=REGION_PROJECTIONS["europe"],
        shp_path=overseas_country_shp,
    )
    d_attr = out.read_text(encoding="utf-8").split(' d="', 1)[1].split('"', 1)[0]
    assert d_attr.count("M") == 2


def test_build_map_drop_overseas_suggest_only_no_op(tmp_path: Path, overseas_country_shp: Path) -> None:
    """``suggest_only=True`` short-circuits before geom work — ``drop_overseas`` is a no-op in that path."""
    target = tmp_path / "should_not_exist.svg"
    result = build_map(
        ["XYZ"],
        target,
        suggest_only=True,
        drop_overseas=True,
        shp_path=overseas_country_shp,
    )
    assert isinstance(result, list)
    assert not target.exists()


def test_build_map_clip_to_canvas_strips_off_canvas_paths(tmp_path: Path, overseas_country_shp: Path) -> None:
    """``clip_to_canvas=True`` removes the overseas sub-polygon so the SVG has a single ``M`` subpath."""
    out = build_map(
        ["XYZ"],
        tmp_path / "clipped.svg",
        projection=REGION_PROJECTIONS["europe"],
        clip_to_canvas=True,
        shp_path=overseas_country_shp,
    )
    d_attr = out.read_text(encoding="utf-8").split(' d="', 1)[1].split('"', 1)[0]
    assert d_attr.count("M") == 1


def test_build_map_drop_overseas_dict_keeps_top_n_per_iso(tmp_path: Path) -> None:
    """``drop_overseas={"AAA": 2}`` keeps the 2 largest sub-polygons of AAA; default top_n for others."""
    big = box(0, 0, 10, 10)  # area 100
    medium = box(20, 20, 25, 25)  # area 25
    small = box(30, 30, 31, 31)  # area 1 — should be dropped
    gdf = gpd.GeoDataFrame(
        {
            "ISO_A3_EH": ["AAA"],
            "ISO_A2_EH": ["AA"],
            "NAME": ["A"],
            "geometry": [MultiPolygon([big, medium, small])],
        },
        crs="EPSG:4326",
    )
    shp = tmp_path / "land.shp"
    gdf.to_file(shp)

    out = build_map(
        ["AAA"],
        tmp_path / "out.svg",
        projection=REGION_PROJECTIONS["europe"],
        drop_overseas={"AAA": 2},
        shp_path=shp,
    )
    d_attr = out.read_text(encoding="utf-8").split(' d="', 1)[1].split('"', 1)[0]
    # 3 sub-polygons → top_n=2 → 2 ``M`` subpaths in the resulting path.
    assert d_attr.count("M") == 2


def test_build_map_drop_overseas_with_iso_list_targets_named_rows(tmp_path: Path, fake_world_shp: Path) -> None:
    """``drop_overseas=["BEL"]`` only reduces BEL — other rows keep their full geometry."""
    # ``fake_world`` rows are single Polygons so the reduction is a no-op geometrically, but the call must
    # still type-check and run without error. (Synthetic MultiPolygon coverage lives in test_geom.py.)
    out = build_map(
        ["BEL", "NLD", "LUX"],
        tmp_path / "targeted.svg",
        drop_overseas=["BEL"],
        shp_path=fake_world_shp,
    )
    assert isinstance(out, Path)
    assert out.exists()


def test_build_map_fit_canvas_to_geometry_uses_total_bounds(tmp_path: Path, overseas_country_shp: Path) -> None:
    """``fit_canvas_to_geometry=True`` sizes the canvas to total_bounds — different SVG height vs default."""
    height_default = int(
        build_map(
            ["XYZ"],
            tmp_path / "default.svg",
            projection=REGION_PROJECTIONS["europe"],
            shp_path=overseas_country_shp,
        )
        .read_text(encoding="utf-8")
        .split('height="', 1)[1]
        .split('"', 1)[0]
    )
    height_fit = int(
        build_map(
            ["XYZ"],
            tmp_path / "fit.svg",
            projection=REGION_PROJECTIONS["europe"],
            fit_canvas_to_geometry=True,
            shp_path=overseas_country_shp,
        )
        .read_text(encoding="utf-8")
        .split('height="', 1)[1]
        .split('"', 1)[0]
    )
    # The two strategies must produce different canvases when overseas parts exist — proves the kwarg is wired in.
    assert height_default != height_fit


# ----------------------------------------------------------------------------------------------------------------------
# Network-marked real-NE end-to-end gate
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.network
def test_build_map_se_asia_real_ne_golden_snapshot(
    tmp_path: Path,
    file_regression: FileRegressionFixture,
) -> None:
    """README SE Asia example round-trips through real Natural Earth 1:50m to a stable SVG snapshot."""
    out = build_map(
        iso_codes=["BRN", "KHM", "IDN", "LAO", "MYS", "MMR", "PHL", "SGP", "THA", "TLS", "VNM"],
        output_path=tmp_path / "Map_of_Southeast_Asia.svg",
        projection=REGION_PROJECTIONS["se_asia"],
        simplify_tolerance=4000,
    )
    file_regression.check(out.read_text(encoding="utf-8"), extension=".svg")
