"""Adjacency graph, enclave detection, and shared-border scoring for neighbor suggestions.

Implementation lands in M5 — M4 forward-declares the public surface (:class:`Suggestion` and
:func:`suggest_neighbors`) so :func:`pycarto.build_map` can wire ``suggest_only=True`` against a stable
signature. M5 only fills the body; no signature churn.
"""

# Standard library
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Suggestion:
    """A neighbor-country suggestion produced by :func:`suggest_neighbors`.

    Schema is locked in M4 per the roadmap; M5 fills the body of :func:`suggest_neighbors` to actually produce them.

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


def suggest_neighbors(
    iso_codes: list[str],
    *,
    enclaves: bool = True,
    shared_border_threshold: float = 0.5,
    shp_path: Path | None = None,
) -> list[Suggestion]:
    """Suggest neighbor countries (full enclaves + high shared-border ratio) for ``iso_codes``.

    M5 fills the body — currently a stub that raises :class:`NotImplementedError`. The signature is locked here so
    :func:`pycarto.build_map`'s ``suggest_only=True`` path can delegate to it without churning.

    Args:
        iso_codes: ISO_A3_EH codes of the user's current selection.
        enclaves: Include full-enclave suggestions (every neighbor in the selection → score 1.0). Defaults to ``True``.
        shared_border_threshold: Minimum shared-border ratio for a country to be suggested via that scorer. Range
            ``[0, 1]``. Defaults to ``0.5``.
        shp_path: Override Natural Earth fetch by pointing at an existing shapefile (typically used in tests).

    Returns:
        A list of :class:`Suggestion` records. Empty list when no candidate clears either scorer.

    Raises:
        NotImplementedError: Always, until M5 fills the body.
    """
    raise NotImplementedError("suggest_neighbors lands in M5 — see _docs/roadmap.md")
