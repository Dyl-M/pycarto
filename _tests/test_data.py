"""Tests for ``pycarto.data``."""

# Standard library
from collections.abc import Callable
import io
import logging
from pathlib import Path
import zipfile

# Third-party
import geopandas as gpd
import httpxyz
import pytest

# Local
from pycarto.data import NE_50M_SHP_NAME, NE_50M_URL, ensure_natural_earth, load_countries, select


# Duck-typed stand-in: only ``status_code``, ``content``, and ``reason_phrase`` are wired because that's what
# ``pycarto.data.ensure_natural_earth`` reads. Extend this if the SUT starts using ``text`` / ``headers`` / ``url``.
class _FakeHttpxResponse:
    """Minimal stand-in for the response returned by ``httpxyz.get``."""

    def __init__(self, status_code: int, content: bytes, reason: str = "OK") -> None:
        """Record the canned status code, reason phrase, and body bytes."""
        self.status_code = status_code
        self.content = content
        self.reason_phrase = reason


def _fake_httpx_get_returning(response: _FakeHttpxResponse) -> Callable[..., _FakeHttpxResponse]:
    """Return an ``httpxyz.get`` look-alike that records each call and hands back the supplied canned response.

    The returned callable exposes a ``calls`` list attribute holding ``(args, kwargs)`` tuples — useful for asserting
    that the SUT passed the expected URL / timeout / follow_redirects.
    """
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _get(*args: object, **kwargs: object) -> _FakeHttpxResponse:
        """Record the call and return the canned response."""
        calls.append((args, kwargs))
        return response

    _get.calls = calls
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
    fake_get = _fake_httpx_get_returning(fake_response)
    monkeypatch.setattr("pycarto.data.httpxyz.get", fake_get)

    with pytest.warns(UserWarning, match="Downloading Natural Earth"):
        result = ensure_natural_earth()

    assert result == tmp_path / "_data" / NE_50M_SHP_NAME
    assert result.read_bytes() == b"fake shapefile bytes"
    # SUT must pass the canonical URL plus the timeout / redirect flags advertised in the docstring.
    assert fake_get.calls == [((NE_50M_URL,), {"timeout": 30.0, "follow_redirects": True})]


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

    # HTTP failure preempts cache creation entirely (mkdir is deferred until just before extraction).
    assert not (tmp_path / "_data").exists()


def test_ensure_natural_earth_wraps_network_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport error from ``httpxyz`` surfaces as ``RuntimeError`` so the dep type doesn't leak to callers."""
    monkeypatch.chdir(tmp_path)

    def _raise_network(*_args: object, **_kwargs: object) -> None:
        """Stand in for ``httpxyz.get`` and raise the kind of error a DNS failure would produce."""
        raise httpxyz.ConnectError("simulated transport failure")

    monkeypatch.setattr("pycarto.data.httpxyz.get", _raise_network)

    with (
        pytest.raises(RuntimeError, match="Network error fetching"),
        pytest.warns(UserWarning, match="Downloading Natural Earth"),
    ):
        ensure_natural_earth()


def test_ensure_natural_earth_rejects_zip_slip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zip whose entries escape the staging directory is rejected before any file lands in the cache."""
    monkeypatch.chdir(tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"never write this outside staging")
        zf.writestr(NE_50M_SHP_NAME, b"benign")
    payload = buf.getvalue()

    fake_response = _FakeHttpxResponse(status_code=200, content=payload)
    monkeypatch.setattr("pycarto.data.httpxyz.get", _fake_httpx_get_returning(fake_response))

    with (
        pytest.raises(RuntimeError, match="zip-slip"),
        pytest.warns(UserWarning, match="Downloading Natural Earth"),
    ):
        ensure_natural_earth()

    assert not (tmp_path / "_data" / NE_50M_SHP_NAME).exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_ensure_natural_earth_rejects_bundle_missing_expected_shp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the bundle extracts cleanly but doesn't contain the expected shapefile, raise rather than cache it."""
    monkeypatch.chdir(tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("some_other_file.txt", b"surprise")
    payload = buf.getvalue()

    fake_response = _FakeHttpxResponse(status_code=200, content=payload)
    monkeypatch.setattr("pycarto.data.httpxyz.get", _fake_httpx_get_returning(fake_response))

    with (
        pytest.raises(RuntimeError, match=f"did not contain {NE_50M_SHP_NAME!r}"),
        pytest.warns(UserWarning, match="Downloading Natural Earth"),
    ):
        ensure_natural_earth()

    assert not (tmp_path / "_data" / NE_50M_SHP_NAME).exists()
    assert list((tmp_path / "_data").iterdir()) == []


def test_ensure_natural_earth_atomic_on_extract_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure mid-extract must leave the cache root empty so the next call retries cleanly."""
    monkeypatch.chdir(tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(NE_50M_SHP_NAME, b"valid bytes")
    payload = buf.getvalue()

    fake_response = _FakeHttpxResponse(status_code=200, content=payload)
    monkeypatch.setattr("pycarto.data.httpxyz.get", _fake_httpx_get_returning(fake_response))

    def _failing_extractall(_self: zipfile.ZipFile, path: str) -> None:
        """Simulate writing a partial file into staging before the OS errors out."""
        Path(path, "partial.shp").write_bytes(b"corrupted")
        raise OSError("simulated disk full")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", _failing_extractall)

    with (
        pytest.raises(OSError, match="simulated disk full"),
        pytest.warns(UserWarning, match="Downloading Natural Earth"),
    ):
        ensure_natural_earth()

    cache = tmp_path / "_data"
    assert not (cache / NE_50M_SHP_NAME).exists()
    assert not (cache / "partial.shp").exists()
    assert list(cache.iterdir()) == []


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


def test_select_accepts_lowercase_iso_codes(fake_world: gpd.GeoDataFrame) -> None:
    """Codes are uppercased before the lookup, so lowercase input matches uppercase column values."""
    sel = select(fake_world, ["bel", "nld", "lux"])
    assert sel.shape[0] == 3
    assert set(sel["ISO_A3_EH"]) == {"BEL", "NLD", "LUX"}


def test_select_does_not_fall_back_for_non_eh_field(fake_world: gpd.GeoDataFrame) -> None:
    """Non-`_EH` filter fields hard-fail when missing; no silent fallback to a stripped variant."""
    with pytest.raises(ValueError, match=r"'ISO_A3_FOO' is not present") as exc_info:
        select(fake_world, ["BEL"], filter_field="ISO_A3_FOO")
    assert "fallback" not in str(exc_info.value)
