"""FIFAe regional maps — demo + utility script.

Generates Liquipedia-style (borderless, ``#797979`` fill) SVG region maps for the three
FIFAe brackets we need:

- Asia East & Oceania
- Asia West
- North & Central America

For each region, the script first runs :func:`pycarto.suggest_neighbors` with
``shared_border_threshold=0.3`` and prints candidate additions, then calls
:func:`pycarto.build_map` with ``unify_region=True`` and the Robinson world projection
preset to emit the final SVG.

Outputs land in ``_img/`` (gitignored), resolved relative to the current working
directory at call time.

Run::

    uv run python _demos/fifae_regions.py
"""

# Standard library
from typing import Any

# Local
from pycarto import build_map, suggest_neighbors
from pycarto.geom import REGION_PROJECTIONS

# Per-region projection overrides. ``asia_east_oceania`` spans the antimeridian (~100°E to ~170°W),
# so Robinson centered on lon_0=0 (the ``world`` preset) splits the bracket across the canvas edges;
# recentering on lon_0=180 keeps it contiguous. ``north_central_america`` re-centers on lon_0=-100
# (continental US center) so Alaska sits naturally to the west of mainland USA instead of getting
# pulled to the canvas edge or wrapping past the antimeridian. ``asia_west`` sits cleanly inside one
# hemisphere with the default ``world`` preset.
PROJECTIONS: dict[str, str] = {
    "asia_east_oceania": "+proj=robin +lon_0=180 +ellps=WGS84",
    "north_central_america": "+proj=robin +lon_0=-100 +ellps=WGS84",
}

# Per-region clipping strategy. The Asia regions use ``clip_to_canvas=True`` so secondary islands
# (Indonesia / Philippines / Japan archipelago, NZ both islands, Tasmania) are preserved while
# off-canvas outliers are trimmed. North & Central America keeps USA's two largest sub-polygons
# (contiguous 48 + Alaska) and drops the rest (Hawaii, Aleutians, Puerto Rico, territories); Canada
# is left intact so the Arctic Archipelago stays. The canvas is sized to ``total_bounds`` to fit
# Alaska + Canada Arctic without clipping.
CLIP_KWARGS: dict[str, dict[str, Any]] = {
    "asia_east_oceania": {"clip_to_canvas": True},
    "asia_west": {"clip_to_canvas": True},
    "north_central_america": {"drop_overseas": {"USA": 2}, "fit_canvas_to_geometry": True},
}

FIFAE_REGIONS: dict[str, list[str]] = {
    "asia_east_oceania": [
        # East Asia
        "CHN",
        "HKG",
        "JPN",
        "KOR",
        "MAC",
        "MNG",
        "PRK",
        "TWN",
        # Southeast Asia
        "BRN",
        "IDN",
        "KHM",
        "LAO",
        "MMR",
        "MYS",
        "PHL",
        "SGP",
        "THA",
        "TLS",
        "VNM",
        # Oceania
        "AUS",
        "FJI",
        "NZL",
        "PNG",
        "SLB",
        "TON",
        "VUT",
        "WSM",
    ],
    "asia_west": [
        # Middle East
        "ARE",
        "BHR",
        "IRN",
        "IRQ",
        "JOR",
        "KWT",
        "LBN",
        "OMN",
        "PSE",
        "QAT",
        "SAU",
        "SYR",
        "YEM",
        # Central Asia
        "AFG",
        "KAZ",
        "KGZ",
        "TJK",
        "TKM",
        "UZB",
        # South Asia
        "BGD",
        "BTN",
        "IND",
        "LKA",
        "MDV",
        "NPL",
        "PAK",
    ],
    "north_central_america": [
        "BLZ",
        "CAN",
        "CRI",
        "GTM",
        "HND",
        "MEX",
        "NIC",
        "PAN",
        "SLV",
        "USA",
    ],
}


def main() -> None:
    """Build every region in :data:`FIFAE_REGIONS` and print suggestions alongside."""
    for region, iso_codes in FIFAE_REGIONS.items():
        print(f"\n=== {region}  ({len(iso_codes)} countries) ===")

        suggestions = suggest_neighbors(iso_codes, shared_border_threshold=0.3)
        if suggestions:
            print(f"  suggest_neighbors(shared_border_threshold=0.3) -> {len(suggestions)} candidate(s):")
            for s in suggestions:
                via = ", ".join(s.neighbors_in_selection)
                print(f"    {s.iso:<5} reason={s.reason:<13} score={s.score:.3f}  via=[{via}]")
        else:
            print("  suggest_neighbors(shared_border_threshold=0.3) -> (none)")

        out = build_map(
            iso_codes=iso_codes,
            output_path=f"fifae_{region}.svg",
            projection=PROJECTIONS.get(region, REGION_PROJECTIONS["world"]),
            unify_region=True,
            **CLIP_KWARGS.get(region, {}),
        )
        print(f"  wrote {out}")


if __name__ == "__main__":
    main()
