"""Tests for ``pycarto.borders`` — M4 stubs only; M5 fills the bodies."""

# Standard library
from dataclasses import FrozenInstanceError

# Third-party
import pytest

# Local
from pycarto.borders import Suggestion, suggest_neighbors


def test_suggestion_dataclass_fields() -> None:
    """``Suggestion`` schema matches the roadmap §M5 spec."""
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


def test_suggest_neighbors_stub_raises_not_implemented() -> None:
    """M5 will fill the body; until then it must surface a clear NotImplementedError."""
    with pytest.raises(NotImplementedError, match="lands in M5"):
        suggest_neighbors(["FRA", "DEU"])
