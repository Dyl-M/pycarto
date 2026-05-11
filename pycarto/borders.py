"""Adjacency graph, enclave detection, and shared-border scoring for neighbor suggestions.

Two scorers compose a neighbor suggester for regional map curation:

- **Enclaves**: candidate countries whose every land neighbor is already in the user's selection (score 1.0).
- **Shared border**: candidates whose shared-boundary length with the selection exceeds a configurable ratio of
  their own boundary (score in ``[0, 1]``, threshold-gated).

The adjacency graph runs on the **raw, unsimplified** Natural Earth frame — ``topojson.toposimplify`` would erode
shared boundaries below numerical noise and drop edges. ``geom_a.intersection(geom_b).length > 1e-6`` (degrees
on raw NE) gates pair adjacency: ``shapely.touches`` is brittle on Natural Earth's vertex-snapped polygons,
single-point intersections (length 0) don't count as borders.
"""

# Standard library
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

# Local
from pycarto.data import load_countries, select

if TYPE_CHECKING:
    # Third-party
    from shapely.geometry.base import BaseGeometry

# Pair adjacency threshold: ``geom.intersection(other).length`` greater than this counts as a shared border. Units
# are degrees on the raw Natural Earth frame (≈ 11 cm at the equator). Filters out single-point corner contacts
# (length = 0) and snap-noise intersections that ``shapely.touches`` would falsely flag as adjacency.
_ADJACENCY_EPSILON: Final[float] = 1e-6
# Symmetric degree-pad applied to ``selection.total_bounds`` before filtering candidate rows. Avoids quadratic
# blowup on the full ~250-row Natural Earth frame: only countries whose bbox lands within the buffered selection
# bbox are considered as candidate neighbors. ~1° = ~111 km on the equator — generous given typical regional gaps.
_BBOX_BUFFER_DEG: Final[float] = 1.0
# Sort priority for the public ``list[Suggestion]`` return: enclaves first (strictly stronger signal), then
# shared-border. Within each rank, descending score then ascending iso for deterministic diffs.
_REASON_RANK: Final[dict[str, int]] = {"enclave": 0, "shared_border": 1}

# TODO(post-v1): swap the inner candidate-by-candidate loop for a ``shapely.strtree.STRtree`` if profiling on
#  full-NE world selections shows it matters. ~1 s on regional selections, ~10 s worst-case continent-wide.


@dataclass(frozen=True)
class Suggestion:
    """A neighbor-country suggestion produced by :func:`suggest_neighbors`.

    Attributes:
        iso: ISO_A3_EH of the suggested country.
        reason: Why the country was suggested. ``"enclave"`` = every neighbor sits inside the user's selection;
            ``"shared_border"`` = high shared-border ratio with the selection.
        score: ``1.0`` for enclaves; ratio in ``[0, 1]`` for the shared-border scorer.
        neighbors_in_selection: ISO_A3_EH codes of the suggestion's neighbors that are already in the user's
            selection — useful for explaining the suggestion in UIs / logs.
    """

    iso: str
    reason: Literal["enclave", "shared_border"]
    score: float
    neighbors_in_selection: tuple[str, ...]


def _bbox_intersects(
    b1: tuple[float, float, float, float],
    b2: tuple[float, float, float, float],
) -> bool:
    """Standard 2D AABB overlap test. Edge-touching (equal coordinates) counts as overlap."""
    return not (b1[2] < b2[0] or b1[0] > b2[2] or b1[3] < b2[1] or b1[1] > b2[3])


def suggest_neighbors(
    iso_codes: Iterable[str],
    *,
    enclaves: bool = True,
    shared_border_threshold: float = 0.5,
    shp_path: Path | None = None,
) -> list[Suggestion]:
    """Suggest neighbor countries (full enclaves + high shared-border ratio) for ``iso_codes``.

    Algorithm:

    1. Load the **raw, unsimplified** Natural Earth frame (or ``shp_path``).
    2. Filter candidates: countries not in the selection whose bbox intersects the buffered selection bbox.
    3. Build an adjacency map: for each candidate, record neighbors (selection rows + other candidates) whose
       intersection length exceeds the per-degree epsilon.
    4. Score:

       - **Enclave** (when ``enclaves=True``) — candidate has at least one neighbor and every neighbor is in the
         selection → emit with ``reason="enclave"``, ``score=1.0``. Skip the shared-border scorer for that
         candidate (enclave is the strictly stronger signal).
       - **Shared border** — sum of shared lengths with selection neighbors divided by the candidate's full
         boundary length; emit when ``score >= shared_border_threshold``.
    5. Sort: ``(reason_rank, -score, iso)`` — enclaves first, then descending score within each reason, with iso
       breaking ties for stable diffs.

    Args:
        iso_codes: ISO_A3_EH codes of the user's current selection. Case-insensitive on input — uppercased before
            lookup, matching :func:`pycarto.data.select`.
        enclaves: Include full-enclave suggestions (every neighbor in the selection → score 1.0). Defaults to
            ``True``. Set ``False`` to skip the enclave scorer entirely (a candidate that *would* qualify as an
            enclave still falls through to the shared-border scorer).
        shared_border_threshold: Minimum shared-border ratio for a country to be suggested via that scorer. Range
            ``[0, 1]``. Defaults to ``0.5``.
        shp_path: Override Natural Earth fetch by pointing at an existing shapefile (typically used in tests).

    Returns:
        A list of :class:`Suggestion` records, sorted ``(reason_rank, -score, iso)``. Empty list when no candidate
        clears either scorer.
    """
    raw = load_countries(shp_path)
    selection_codes = sorted({c.upper() for c in iso_codes})
    selection = select(raw, selection_codes)

    sminx, sminy, smaxx, smaxy = (float(v) for v in selection.total_bounds)
    buffered_bbox: tuple[float, float, float, float] = (
        sminx - _BBOX_BUFFER_DEG,
        sminy - _BBOX_BUFFER_DEG,
        smaxx + _BBOX_BUFFER_DEG,
        smaxy + _BBOX_BUFFER_DEG,
    )

    candidates_mask = ~raw["ISO_A3_EH"].isin(selection_codes) & raw.geometry.apply(
        lambda g: _bbox_intersects(g.bounds, buffered_bbox)
    )
    candidates = raw[candidates_mask]

    selection_geoms: list[tuple[str, BaseGeometry]] = [
        (str(iso), geom) for iso, geom in selection[["ISO_A3_EH", "geometry"]].itertuples(index=False, name=None)
    ]
    candidate_geoms: list[tuple[str, BaseGeometry]] = [
        (str(iso), geom) for iso, geom in candidates[["ISO_A3_EH", "geometry"]].itertuples(index=False, name=None)
    ]
    cand_geom_lookup: dict[str, BaseGeometry] = dict(candidate_geoms)
    selection_set: set[str] = set(selection_codes)

    suggestions: list[Suggestion] = []
    for cand_iso, cand_geom in candidate_geoms:
        nbrs: dict[str, float] = {}
        for sel_iso, sel_geom in selection_geoms:
            shared = cand_geom.intersection(sel_geom).length
            if shared > _ADJACENCY_EPSILON:
                nbrs[sel_iso] = shared
        for other_iso, other_geom in candidate_geoms:
            if other_iso == cand_iso:
                continue
            shared = cand_geom.intersection(other_geom).length
            if shared > _ADJACENCY_EPSILON:
                nbrs[other_iso] = shared

        if not nbrs:
            # Zero-neighbor candidate (an island, or a polygon that bbox-prefiltered in but doesn't actually
            # touch anything). Vacuous ``all([])`` would falsely flag this as an enclave — bail explicitly.
            continue
        in_selection = {n for n in nbrs if n in selection_set}
        if not in_selection:
            # The bbox prefilter brought this candidate in, but its borders are entirely with other non-selected
            # countries. Not a useful suggestion — skip.
            continue

        if enclaves and all(n in selection_set for n in nbrs):
            suggestions.append(
                Suggestion(
                    iso=cand_iso,
                    reason="enclave",
                    score=1.0,
                    neighbors_in_selection=tuple(sorted(in_selection)),
                )
            )
            continue  # enclave wins; do not also score this candidate as shared_border.

        shared_len = sum(nbrs[n] for n in in_selection)
        ratio = shared_len / cand_geom_lookup[cand_iso].boundary.length
        if ratio >= shared_border_threshold:
            suggestions.append(
                Suggestion(
                    iso=cand_iso,
                    reason="shared_border",
                    score=ratio,
                    neighbors_in_selection=tuple(sorted(in_selection)),
                )
            )

    suggestions.sort(key=lambda s: (_REASON_RANK[s.reason], -s.score, s.iso))
    return suggestions
