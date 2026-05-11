"""Tests for the pycarto package initialization."""

# Standard library
import re

# Local
import pycarto
from pycarto import Suggestion, __author__, __version__, build_map, suggest_neighbors


def test_version_is_string() -> None:
    """Verify that __version__ is a string."""
    assert isinstance(__version__, str)


def test_version_value() -> None:
    """Verify that __version__ follows semantic versioning format."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_author() -> None:
    """Verify that __author__ matches the expected value."""
    assert __author__ == "Dylan Monfret"


def test_public_api_exports() -> None:
    """``from pycarto import ...`` exposes the public surface: build_map, suggest_neighbors, Suggestion."""
    assert callable(build_map)
    assert callable(suggest_neighbors)
    assert Suggestion.__name__ == "Suggestion"


def test_dunder_all_lists_public_api() -> None:
    """``__all__`` covers metadata + the three public-API symbols."""
    assert set(pycarto.__all__) == {
        "__author__",
        "__version__",
        "Suggestion",
        "build_map",
        "suggest_neighbors",
    }
