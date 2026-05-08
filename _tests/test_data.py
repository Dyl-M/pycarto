"""Tests for ``pycarto.data``."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING
import zipfile

import pytest

from pycarto.data import NE_50M_SHP_NAME, ensure_natural_earth, load_countries, select

if TYPE_CHECKING:
    import geopandas as gpd


class _FakeUrlopenResponse:
    """Minimal stand-in for the context manager returned by ``urllib.request.urlopen``."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeUrlopenResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


@pytest.mark.parametrize("resolution", ["10m", "110m", "5m"])
def test_ensure_natural_earth_invalid_resolution(resolution: str) -> None:
    """Only resolution='50m' is supported in v1; others must raise NotImplementedError."""
    with pytest.raises(NotImplementedError, match="Only resolution='50m'"):
        ensure_natural_earth(resolution=resolution)


def test_ensure_natural_earth_returns_cached_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the shapefile already lives in the cache, no download is attempted."""
    cache = tmp_path / "_data"
    cache.mkdir()
    shp = cache / NE_50M_SHP_NAME
    shp.touch()
    monkeypatch.chdir(tmp_path)

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ensure_natural_earth should not download when cache is populated")

    monkeypatch.setattr("pycarto.data.urllib.request.urlopen", _no_network)

    assert ensure_natural_earth() == shp


def test_ensure_natural_earth_rejects_non_https_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defensive scheme guard rejects non-https URLs without hitting the network."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pycarto.data.NE_50M_URL", "http://example.invalid/foo.zip")

    with pytest.raises(RuntimeError, match="non-https URL"):
        ensure_natural_earth()


def test_ensure_natural_earth_downloads_and_extracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: download, extract, and return the resolved shapefile path."""
    monkeypatch.chdir(tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(NE_50M_SHP_NAME, b"fake shapefile bytes")
    payload = buf.getvalue()

    def _fake_urlopen(url: str, timeout: int = 30) -> _FakeUrlopenResponse:
        assert url.startswith("https://")
        assert timeout == 30
        return _FakeUrlopenResponse(payload)

    monkeypatch.setattr("pycarto.data.urllib.request.urlopen", _fake_urlopen)

    with pytest.warns(UserWarning, match="Downloading Natural Earth"):
        result = ensure_natural_earth()

    assert result == tmp_path / "_data" / NE_50M_SHP_NAME
    assert result.read_bytes() == b"fake shapefile bytes"


def test_load_countries_uppercases_columns(
    lowercase_columns_world: gpd.GeoDataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``load_countries`` uppercases non-geometry columns and preserves the geometry column verbatim."""
    geom_col = lowercase_columns_world.geometry.name
    monkeypatch.setattr("pycarto.data.gpd.read_file", lambda _shp: lowercase_columns_world)

    result = load_countries(shp_path=Path("ignored.shp"))

    assert all(c == geom_col or c.isupper() for c in result.columns)
    assert geom_col in result.columns


def test_select_filters_by_iso_a3_eh(fake_world: gpd.GeoDataFrame) -> None:
    """The roadmap M1 gate: load + select(['BEL','NLD','LUX']) returns 3 rows."""
    sel = select(fake_world, ["BEL", "NLD", "LUX"])
    assert sel.shape[0] == 3
    assert set(sel["ISO_A3_EH"]) == {"BEL", "NLD", "LUX"}


def test_select_falls_back_to_iso_a3(fake_world_no_eh: gpd.GeoDataFrame) -> None:
    """When ISO_A3_EH is absent, select transparently falls back to ISO_A3."""
    sel = select(fake_world_no_eh, ["BEL", "NLD", "LUX"])
    assert sel.shape[0] == 3
    assert set(sel["ISO_A3"]) == {"BEL", "NLD", "LUX"}


def test_select_warns_on_missing_codes(
    fake_world: gpd.GeoDataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing codes trigger BOTH a UserWarning and a logger warning."""
    with caplog.at_level(logging.WARNING, logger="pycarto.data"), pytest.warns(UserWarning, match="XYZ"):
        sel = select(fake_world, ["BEL", "NLD", "XYZ"])
    assert sel.shape[0] == 2
    assert any("XYZ" in record.getMessage() for record in caplog.records)


def test_select_raises_on_empty_result(fake_world: gpd.GeoDataFrame) -> None:
    """An empty selection raises ValueError rather than returning an empty frame silently."""
    with pytest.raises(ValueError, match="No countries matched"):
        select(fake_world, ["XYZ"])


def test_select_raises_on_missing_filter_field(fake_world: gpd.GeoDataFrame) -> None:
    """If neither the requested column nor its _EH-stripped fallback exists, raise ValueError."""
    gdf = fake_world.drop(columns=["ISO_A3_EH"])
    with pytest.raises(ValueError, match="Neither 'ISO_A3_EH' nor fallback 'ISO_A3'"):
        select(gdf, ["BEL"])
