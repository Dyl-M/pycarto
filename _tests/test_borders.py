"""Tests for ``pycarto.borders`` — Suggestion schema + suggest_neighbors algorithm."""

# Standard library
from dataclasses import FrozenInstanceError
from pathlib import Path

# Third-party
import geopandas as gpd
import pytest

# Local
from pycarto.borders import Suggestion, suggest_neighbors


def _persist(gdf: gpd.GeoDataFrame, tmp_path: Path, name: str = "data.shp") -> Path:
    """Persist a synthetic ``GeoDataFrame`` to disk so ``suggest_neighbors`` can load it via ``shp_path``."""
    shp = tmp_path / name
    gdf.to_file(shp)
    return shp


# ----------------------------------------------------------------------------------------------------------------------
# Suggestion dataclass
# ----------------------------------------------------------------------------------------------------------------------


def test_suggestion_dataclass_fields() -> None:
    """``Suggestion`` carries iso, reason, score, and the tuple of neighbors-in-selection that justified it."""
    s = Suggestion(iso="CHE", reason="enclave", score=1.0, neighbors_in_selection=("FRA", "DEU", "ITA", "AUT"))
    assert s.iso == "CHE"
    assert s.reason == "enclave"
    assert s.score == 1.0
    assert s.neighbors_in_selection == ("FRA", "DEU", "ITA", "AUT")


def test_suggestion_is_frozen() -> None:
    """``frozen=True`` so callers can hash / compare suggestions and can't mutate them downstream."""
    s = Suggestion(iso="CHE", reason="enclave", score=1.0, neighbors_in_selection=("FRA",))
    with pytest.raises(FrozenInstanceError):
        # noinspection PyDataclass
        s.iso = "ABC"  # type: ignore[misc]


# ----------------------------------------------------------------------------------------------------------------------
# suggest_neighbors — enclave detection
# ----------------------------------------------------------------------------------------------------------------------


def test_suggest_neighbors_finds_enclave(tmp_path: Path, enclave_synthetic: gpd.GeoDataFrame) -> None:
    """A central polygon fully surrounded by the selection is suggested with ``reason="enclave"``, score 1.0."""
    shp = _persist(enclave_synthetic, tmp_path)
    result = suggest_neighbors(["NTH", "STH", "EST", "WST"], shp_path=shp)

    ctr_entries = [s for s in result if s.iso == "CTR"]
    assert ctr_entries, "expected CTR in suggestions"
    ctr = ctr_entries[0]
    assert ctr.reason == "enclave"
    assert ctr.score == 1.0
    assert set(ctr.neighbors_in_selection) == {"NTH", "STH", "EST", "WST"}


def test_suggest_neighbors_skips_island_zero_neighbors(tmp_path: Path, island_no_neighbors: gpd.GeoDataFrame) -> None:
    """A candidate with no neighbors must NOT be flagged as an enclave (vacuous ``all([])`` would lie)."""
    shp = _persist(island_no_neighbors, tmp_path)
    result = suggest_neighbors(["AAA"], shp_path=shp)

    assert all(s.iso != "ISL" for s in result)


def test_suggest_neighbors_enclaves_false_suppresses_enclave_suggestions(
    tmp_path: Path, enclave_synthetic: gpd.GeoDataFrame
) -> None:
    """``enclaves=False`` skips the enclave scorer; the candidate may still surface via shared-border instead."""
    shp = _persist(enclave_synthetic, tmp_path)
    result = suggest_neighbors(["NTH", "STH", "EST", "WST"], enclaves=False, shp_path=shp)

    # CTR may still appear with reason="shared_border" (its full perimeter is shared with the selection),
    # but never as an enclave when ``enclaves=False``.
    assert all(s.reason != "enclave" for s in result)


def test_suggest_neighbors_enclave_takes_precedence_over_shared_border(
    tmp_path: Path, enclave_synthetic: gpd.GeoDataFrame
) -> None:
    """A candidate qualifying as enclave produces exactly one Suggestion with ``reason="enclave"``, not two."""
    shp = _persist(enclave_synthetic, tmp_path)
    result = suggest_neighbors(["NTH", "STH", "EST", "WST"], shp_path=shp)

    ctr_entries = [s for s in result if s.iso == "CTR"]
    assert len(ctr_entries) == 1
    assert ctr_entries[0].reason == "enclave"


# ----------------------------------------------------------------------------------------------------------------------
# suggest_neighbors — shared-border ratio
# ----------------------------------------------------------------------------------------------------------------------


def test_suggest_neighbors_shared_border_above_threshold_passes(
    tmp_path: Path, shared_border_synthetic: gpd.GeoDataFrame
) -> None:
    """``CCC`` shares ~90.9% of its boundary with the selection — clears the default 0.5 threshold."""
    shp = _persist(shared_border_synthetic, tmp_path)
    result = suggest_neighbors(["AAA", "BBB"], shp_path=shp)

    ccc_entries = [s for s in result if s.iso == "CCC"]
    assert len(ccc_entries) == 1
    ccc = ccc_entries[0]
    assert ccc.reason == "shared_border"
    assert ccc.score == pytest.approx(20 / 22, rel=1e-3)
    assert set(ccc.neighbors_in_selection) == {"AAA", "BBB"}


def test_suggest_neighbors_shared_border_below_threshold_filtered(
    tmp_path: Path, shared_border_synthetic: gpd.GeoDataFrame
) -> None:
    """With selection ``{"AAA"}`` only, ``CCC``'s ratio (~0.455) is below the default 0.5 → filtered out."""
    shp = _persist(shared_border_synthetic, tmp_path)
    result = suggest_neighbors(["AAA"], shp_path=shp)

    assert all(s.iso != "CCC" for s in result)


def test_suggest_neighbors_custom_threshold_filters_appropriately(
    tmp_path: Path, shared_border_synthetic: gpd.GeoDataFrame
) -> None:
    """Lowering ``shared_border_threshold`` to 0.3 lets the ~0.455-ratio candidate through."""
    shp = _persist(shared_border_synthetic, tmp_path)
    result = suggest_neighbors(["AAA"], shared_border_threshold=0.3, shp_path=shp)

    isos = [s.iso for s in result]
    assert "CCC" in isos


def test_suggest_neighbors_neighbors_in_selection_only_contains_selection_isos(
    tmp_path: Path, shared_border_synthetic: gpd.GeoDataFrame
) -> None:
    """``neighbors_in_selection`` is a subset of the input selection — no candidate-only neighbors leak in."""
    shp = _persist(shared_border_synthetic, tmp_path)
    result = suggest_neighbors(["AAA", "BBB"], shp_path=shp)

    selection = {"AAA", "BBB"}
    for s in result:
        assert set(s.neighbors_in_selection) <= selection


# ----------------------------------------------------------------------------------------------------------------------
# suggest_neighbors — sort order
# ----------------------------------------------------------------------------------------------------------------------


def test_suggest_neighbors_sort_order_enclaves_first_then_descending_score() -> None:
    """Sort key is ``(reason_rank, -score, iso)``: enclaves precede shared_border; within each, score descends."""
    suggestions = [
        Suggestion(iso="ZZZ", reason="shared_border", score=0.6, neighbors_in_selection=("AAA",)),
        Suggestion(iso="MMM", reason="enclave", score=1.0, neighbors_in_selection=("BBB",)),
        Suggestion(iso="AAA", reason="shared_border", score=0.9, neighbors_in_selection=("CCC",)),
        Suggestion(iso="NNN", reason="enclave", score=1.0, neighbors_in_selection=("DDD",)),
    ]
    suggestions.sort(key=lambda s: ({"enclave": 0, "shared_border": 1}[s.reason], -s.score, s.iso))
    reasons = [s.reason for s in suggestions]
    isos = [s.iso for s in suggestions]
    # Enclaves first (alphabetical iso tiebreaker on tied score 1.0), then shared_border by descending score.
    assert reasons == ["enclave", "enclave", "shared_border", "shared_border"]
    assert isos == ["MMM", "NNN", "AAA", "ZZZ"]


# ----------------------------------------------------------------------------------------------------------------------
# Network-marked fixture cases (real Natural Earth 1:50m)
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.network
def test_suggest_neighbors_central_europe_surfaces_che() -> None:
    """``["FRA","DEU","ITA","AUT"]`` surfaces ``CHE`` via the shared-border scorer.

    Switzerland is "almost an enclave" but Natural Earth 1:50m records a measurable border with Liechtenstein
    (LIE), which is not in the selection — strict-definition enclave detection therefore falls through to the
    shared-border scorer. The shared-with-selection length covers most of CHE's perimeter (LIE contributes only
    a tiny fragment), so the score lands well above 0.5.
    """
    result = suggest_neighbors(["FRA", "DEU", "ITA", "AUT"])
    che_entries = [s for s in result if s.iso == "CHE"]
    assert che_entries, "expected CHE in suggestions"
    che = che_entries[0]
    assert che.reason == "shared_border"
    assert che.score > 0.5


@pytest.mark.network
def test_suggest_neighbors_baltic_corridor_finds_blr_as_enclave() -> None:
    """``["UKR","POL","LTU","LVA","RUS"]`` flags ``BLR`` as enclave — all NE-1:50m neighbors are in the selection."""
    result = suggest_neighbors(["UKR", "POL", "LTU", "LVA", "RUS"])
    blr_entries = [s for s in result if s.iso == "BLR"]
    assert blr_entries, "expected BLR in suggestions"
    blr = blr_entries[0]
    assert blr.reason == "enclave"
    assert blr.score == 1.0


@pytest.mark.network
def test_suggest_neighbors_benelux_threshold_lowered_suggests_lux() -> None:
    """``["BEL","NLD"]`` with ``shared_border_threshold=0.3`` surfaces ``LUX``.

    Luxembourg shares its borders with BEL, FRA, and DEU — only one of those is in the selection, so the strict
    enclave scorer doesn't fire. Lowered threshold lets the partial shared-border ratio through.
    """
    result = suggest_neighbors(["BEL", "NLD"], shared_border_threshold=0.3)
    isos = [s.iso for s in result]
    assert "LUX" in isos
