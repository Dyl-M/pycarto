"""Tests for ``pycarto.build_map`` orchestration (M4)."""

# Standard library
from pathlib import Path

# Third-party
import geopandas as gpd
import pytest

# Local
from pycarto import build_map
from pycarto.geom import REGION_PROJECTIONS


@pytest.fixture
def fake_world_shp(tmp_path: Path, fake_world: gpd.GeoDataFrame) -> Path:
    """Persist ``fake_world`` to disk so ``build_map`` can read it via ``shp_path``.

    Synthetic-only — mirrors the M3 testing pattern. Real-NE end-to-end coverage stays deferred to M6's
    ``network``-marked test.
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


def test_build_map_suggest_only_delegates_to_stub_and_raises(tmp_path: Path, fake_world_shp: Path) -> None:
    """``suggest_only=True`` calls the M5 stub ``suggest_neighbors``, which raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="lands in M5"):
        build_map(
            ["BEL", "NLD"],
            tmp_path / "ignored.svg",
            suggest_only=True,
            shp_path=fake_world_shp,
        )


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
    with pytest.raises(NotImplementedError):
        build_map(["BEL", "NLD"], target, suggest_only=True, shp_path=fake_world_shp)
    assert not target.exists()
