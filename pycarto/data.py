"""Natural Earth fetch, cache, and country-frame normalization.

Three pieces:

- :func:`ensure_natural_earth` — download + extract the Natural Earth 1:50m bundle into ``./_data/``.
- :func:`load_countries` — read the shapefile into a ``GeoDataFrame`` with column names normalized to upper case.
- :func:`select` — filter the frame by ISO codes, with ``ISO_*_EH`` → ``ISO_*`` fallback for lower-resolution
  shapefiles.
"""

# Standard library
from collections.abc import Iterable
import io
import logging
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import warnings
import zipfile

# Third-party
import geopandas as gpd
from geopandas import GeoDataFrame
import httpxyz

# Natural Earth canonical distribution endpoint. Serves the latest published release (no version pin):
# regenerated outputs may differ if Natural Earth ships a new vintage between runs.
NE_50M_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
NE_50M_SHP_NAME = "ne_50m_admin_0_countries.shp"

# TODO(post-v1): pin reproducibility by recording an expected SHA256 of the zip and verifying on download. The
#  natural-earth-vector GitHub repo does not ship the bundled zip as a release asset or repo path, so URL-based pinning
#  isn't viable; content-hash pinning is the realistic option.

# TODO(post-v1): support resolutions "10m" and "110m" (the signature already accepts the parameter).

logger = logging.getLogger(__name__)


def ensure_natural_earth(resolution: str = "50m") -> Path:
    """Download and extract the pinned Natural Earth bundle to the cache directory.

    Args:
        resolution: Natural Earth resolution. Only ``"50m"`` is supported in v1.

    Returns:
        Absolute path to the extracted ``.shp`` file.

    Raises:
        NotImplementedError: If ``resolution`` is anything other than ``"50m"``.
        RuntimeError: If the pinned URL is not ``https://``, the GET fails (transport error or non-200), the zip
            contains a path-traversal entry, or the bundle is missing the expected shapefile.
    """
    if resolution != "50m":
        raise NotImplementedError(f"Only resolution='50m' is supported in v1 (got {resolution!r}).")

    # Resolved at call time (not import time) so that callers can chdir or override via tests.
    cache_dir = Path.cwd() / "_data"
    shp_path = cache_dir / NE_50M_SHP_NAME
    if shp_path.exists():
        return shp_path

    parsed = urlparse(NE_50M_URL)
    if parsed.scheme != "https":
        raise RuntimeError(f"Refusing to fetch non-https URL: {NE_50M_URL!r}")

    msg = f"Downloading Natural Earth 1:50m countries to {cache_dir}…"
    warnings.warn(msg, UserWarning, stacklevel=3)
    logger.info(msg)
    try:
        response = httpxyz.get(NE_50M_URL, timeout=30.0, follow_redirects=True)
    except httpxyz.RequestError as exc:
        raise RuntimeError(f"Network error fetching {NE_50M_URL!r}: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download {NE_50M_URL!r}: HTTP {response.status_code} {response.reason_phrase}")
    # Stage extraction in a temp dir inside the cache, then move each file into place atomically. Prevents an
    # interrupted extract from poisoning the cache, and contains zip-slip even though Natural Earth is a trusted source.
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pycarto-ne50m-", dir=cache_dir) as staging_str:
        staging = Path(staging_str)
        staging_resolved = staging.resolve()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            for member in zf.infolist():
                if not (staging / member.filename).resolve().is_relative_to(staging_resolved):
                    raise RuntimeError(f"Refusing to extract zip-slip entry: {member.filename!r}")
            zf.extractall(staging)
        if not (staging / NE_50M_SHP_NAME).exists():
            raise RuntimeError(f"Bundle from {NE_50M_URL!r} did not contain {NE_50M_SHP_NAME!r}")
        for entry in staging.iterdir():
            os.replace(entry, cache_dir / entry.name)
    return shp_path


def _normalize_columns_inplace(gdf: GeoDataFrame) -> GeoDataFrame:
    """Uppercase every non-geometry column. Mutates ``gdf`` in place and returns it."""
    geom_col = gdf.geometry.name
    gdf.columns = [c if c == geom_col else c.upper() for c in gdf.columns]
    return gdf


def load_countries(shp_path: Path | None = None) -> GeoDataFrame:
    """Read the Natural Earth countries shapefile into a column-normalized ``GeoDataFrame``.

    Args:
        shp_path: Path to a shapefile. If ``None``, falls back to :func:`ensure_natural_earth`.

    Returns:
        Raw frame with non-geometry columns uppercased.
    """
    shp = shp_path or ensure_natural_earth()
    return _normalize_columns_inplace(gpd.read_file(shp))


def select(
    gdf: GeoDataFrame,
    iso_codes: Iterable[str],
    *,
    filter_field: str = "ISO_A3_EH",
) -> GeoDataFrame:
    """Filter ``gdf`` to rows whose ``filter_field`` value is in ``iso_codes``.

    When ``filter_field`` ends with ``_EH`` and is missing, falls back to the ``_EH``-stripped column
    (e.g. ``ISO_A3``) — useful for lower-resolution Natural Earth shapefiles that omit the Elaborate-Heuristic
    columns. Non-``_EH`` filter fields hard-fail rather than degrading silently. Input codes are uppercased before
    matching, so lowercase input works. Emits both a :class:`UserWarning` and a logger warning when any requested code
    is missing from the frame.

    Args:
        gdf: Source frame, typically the output of :func:`load_countries`.
        iso_codes: Codes to include. Case-insensitive on input — uppercased before lookup.
        filter_field: Column to filter on. Defaults to ``ISO_A3_EH``.

    Returns:
        Filtered copy of ``gdf``.

    Raises:
        ValueError: If ``filter_field`` is missing (and its ``_EH`` fallback, when applicable, is also missing), or if
            no rows match any requested code.
    """
    effective_field = filter_field
    if effective_field not in gdf.columns:
        if filter_field.endswith("_EH"):
            fallback = filter_field.removesuffix("_EH")
            if fallback in gdf.columns:
                effective_field = fallback
            else:
                raise ValueError(
                    f"Neither {filter_field!r} nor fallback {fallback!r} is present in the frame; "
                    f"available columns: {sorted(gdf.columns)}"
                )
        else:
            raise ValueError(f"{filter_field!r} is not present in the frame; available columns: {sorted(gdf.columns)}")

    codes = [c.upper() for c in iso_codes]
    sel = gdf[gdf[effective_field].isin(codes)].copy()

    if sel.empty:
        raise ValueError(f"No countries matched in column {effective_field!r}. Requested codes: {codes}")

    missing = sorted(set(codes) - set(sel[effective_field]))
    if missing:
        msg = f"Country codes not found in {effective_field}: {missing}"
        warnings.warn(msg, UserWarning, stacklevel=2)
        logger.warning("Country codes not found in %s: %s", effective_field, missing)

    return sel
