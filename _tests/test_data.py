"""Tests for ``pycarto.data``."""

# Standard library
from collections.abc import Callable
import io
import logging
from pathlib import Path
import zipfile

# Third-party
import geopandas as gpd
import pytest

# Local
from pycarto.data import NE_50M_SHP_NAME, ensure_natural_earth, load_countries, select


class _FakeHttpxResponse:
    """Minimal stand-in for the response returned by ``httpxyz.get``."""

    def __init__(self, status_code: int, content: bytes, reason: str = "OK") -> None:
        """Record the canned status code, reason phrase, and body bytes."""
        self.status_code = status_code
        self.content = content
        self.reason_phrase = reason


def _fake_httpx_get_returning(response: _FakeHttpxResponse) -> Callable[..., _FakeHttpxResponse]:
    """Return an ``httpxyz.get`` look-alike that always hands back the supplied canned response."""

    def _get(*_args: object, **_kwargs: object) -> _FakeHttpxResponse:
        """Ignore the URL and kwargs the SUT passes; return the captured response."""
        return response

    return _get


@pytest.mark.parametrize("resolution", ["10m", "110m", "5m"])
def test_ensure_natural_earth_invalid_resolution(resolution: str) -> None:
    """Only resolution='50m' is supported in v1; others must raise NotImplementedError."""
    with pytest.raises(NotImplementedError, match="Only resolution='50m'"):
        ensure_natural_earth(resolution=resolution)


def test_ensure_natural_earth_returns_cached_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the shapefile already lives in the cache, no connection is opened."""
    cache = tmp_path / "_data"
    cache.mkdir()
    shp = cache / NE_50M_SHP_NAME
    shp.touch()
    monkeypatch.chdir(tmp_path)

    def _no_network(*_args: object, **_kwargs: object) -> None:
        """Fail loudly if the SUT tries to open a connection."""
        raise AssertionError("ensure_natural_earth should not connect when cache is populated")

    monkeypatch.setattr("pycarto.data.httpxyz.get", _no_network)

    assert ensure_natural_earth() == shp


def test_ensure_natural_earth_rejects_non_https_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defensive scheme guard rejects non-https URLs without opening a connection."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pycarto.data.NE_50M_URL", "http://example.invalid/foo.zip")

    with pytest.raises(RuntimeError, match="non-https URL"):
        ensure_natural_earth()


def test_ensure_natural_earth_downloads_and_extracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: GET, extract, and return the resolved shapefile path."""
    monkeypatch.chdir(tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(NE_50M_SHP_NAME, b"fake shapefile bytes")
    payload = buf.getvalue()

    fake_response = _FakeHttpxResponse(status_code=200, content=payload)
    monkeypatch.setattr("pycarto.data.httpxyz.get", _fake_httpx_get_returning(fake_response))

    with pytest.warns(UserWarning, match="Downloading Natural Earth"):
        result = ensure_natural_earth()

    assert result == tmp_path / "_data" / NE_50M_SHP_NAME
    assert result.read_bytes() == b"fake shapefile bytes"


def test_ensure_natural_earth_raises_on_http_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-200 response surfaces as a ``RuntimeError`` so it doesn't corrupt the cache."""
    monkeypatch.chdir(tmp_path)

    fake_response = _FakeHttpxResponse(status_code=404, content=b"", reason="Not Found")
    monkeypatch.setattr("pycarto.data.httpxyz.get", _fake_httpx_get_returning(fake_response))

    # The download-attempt UserWarning fires before we know it'll fail; that's honest behaviour
    # (warning describes the attempt, error describes the failure), so just acknowledge it.
    with (
        pytest.raises(RuntimeError, match="HTTP 404 Not Found"),
        pytest.warns(UserWarning, match="Downloading Natural Earth"),
    ):
        ensure_natural_earth()

    # Cache directory was created but is empty — no half-extracted state.
    assert not (tmp_path / "_data" / NE_50M_SHP_NAME).exists()


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
