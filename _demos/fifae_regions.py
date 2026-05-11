"""FIFAe regional maps — demo + utility script.

Generates Liquipedia-style (borderless, ``#797979`` fill) SVG region maps for the three
FIFAe brackets we need:

- Asia East & Oceania
- Asia West
- North & Central America

For each region, the script combines the bracket participants with a curated list of
``suggest_neighbors`` enclaves + manual land-bridge fillers (per :data:`SUGGESTIONS`), runs
:func:`pycarto.suggest_neighbors` with ``shared_border_threshold=0.3`` against the combined
selection to surface the next round of candidates, then calls :func:`pycarto.build_map` with
the curated additions wired through ``suggestions=`` and ``unify_region=True`` to emit the
final SVG.

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

# Per-region projection overrides. ``asia_east_oceania`` participants span ~70°E (MDV) to ~172°E
# (NZL), so Robinson centered on lon_0=120 frames the bracket without antimeridian crossing.
# ``north_central_america`` re-centers on lon_0=-100 (continental US center) so Alaska sits
# naturally to the west of mainland USA instead of getting pulled to the canvas edge or wrapping
# past the antimeridian. ``asia_west`` (Gulf + UZB, ~36°E to ~64°E) sits cleanly inside one
# hemisphere with the default ``world`` preset.
PROJECTIONS: dict[str, str] = {
    "asia_east_oceania": "+proj=robin +lon_0=120 +ellps=WGS84",
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

# Actual participants in the FIFAe Nations League 2026 Week 2 Group Stage on Liquipedia.
# Sourced from the per-bracket pages on liquipedia.net/rocketleague (FIFAe_World_Cup/Nations_League/
# 2026/<bracket>/Week_2/Group_Stage). Note: Liquipedia uses the IOC code ``CAY`` for the Cayman
# Islands; Natural Earth uses ISO 3166-1 ``CYM`` which is what ``pycarto`` filters on.
FIFAE_REGIONS: dict[str, list[str]] = {
    "asia_east_oceania": [
        # Group A
        "AUS",
        "BGD",
        "GUM",
        "IDN",
        "IND",
        "LAO",
        "NPL",
        # Group B
        "BRN",
        "HKG",
        "KGZ",
        "MDV",
        "MYS",
        "NZL",
        "PNG",
    ],
    "asia_west": [
        "ARE",
        "BHR",
        "JOR",
        "OMN",
        "QAT",
        "SAU",
        "UZB",
    ],
    "north_central_america": [
        # Group A
        "CRI",
        "DOM",
        "PAN",
        "TTO",
        "USA",
        # Group B
        "CAN",
        "CYM",
        "GUY",
        "PRI",
        "SLV",
    ],
}

# Curated additions threaded through ``build_map(..., suggestions=...)``. Combines every
# enclave surfaced by ``suggest_neighbors`` (score 1.0 — all neighbors inside the bracket)
# with manual land-bridge fillers chosen by reviewing the unified-region SVG to close visible
# gaps between participant landmasses. Islands disconnected by sea (MDV, CYM, PRI, TTO, ...)
# are not bridged.
SUGGESTIONS: dict[str, list[str]] = {
    "asia_east_oceania": [
        # Enclave
        "TLS",
        # Land bridges — South Asia ↔ Indochina ↔ SE Asia mainland
        "BTN",
        "CHN",
        "MMR",
        "THA",
        "KHM",
        "VNM",
    ],
    "asia_west": [
        # Enclaves
        "YEM",
        "KWT",
        # Land bridges — Gulf ↔ Iranian plateau ↔ Central Asia / UZB
        "IRQ",
        "IRN",
        "TKM",
        "TJK",
        "AFG",
    ],
    "north_central_america": [
        # Enclave
        "HTI",
        # Land bridges — Central America corridor USA → CRI
        "MEX",
        "BLZ",
        "GTM",
        "HND",
        "NIC",
        # Land bridges — Guianas → Caribbean shore for GUY
        "SUR",
        "VEN",
    ],
}


def main() -> None:
    """Build every region in :data:`FIFAE_REGIONS` and print suggestions alongside."""
    for region, iso_codes in FIFAE_REGIONS.items():
        added = SUGGESTIONS.get(region, [])
        combined = list(iso_codes) + list(added)
        print(
            f"\n=== {region}  ({len(iso_codes)} participants + {len(added)} added = "
            f"{len(combined)} total) ==="
        )

        candidates = suggest_neighbors(combined, shared_border_threshold=0.3)
        if candidates:
            print(f"  suggest_neighbors(shared_border_threshold=0.3) -> {len(candidates)} candidate(s):")
            for c in candidates:
                via = ", ".join(c.neighbors_in_selection)
                print(f"    {c.iso:<5} reason={c.reason:<13} score={c.score:.3f}  via=[{via}]")
        else:
            print("  suggest_neighbors(shared_border_threshold=0.3) -> (none)")

        out = build_map(
            iso_codes=iso_codes,
            suggestions=added,
            output_path=f"fifae_{region}.svg",
            projection=PROJECTIONS.get(region, REGION_PROJECTIONS["world"]),
            unify_region=True,
            **CLIP_KWARGS.get(region, {}),
        )
        print(f"  wrote {out}")


if __name__ == "__main__":
    main()
