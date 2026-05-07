"""Tests for the pycarto package initialization."""

import re

from pycarto import __author__, __version__


def test_version_is_string() -> None:
    """Verify that __version__ is a string."""
    assert isinstance(__version__, str)


def test_version_value() -> None:
    """Verify that __version__ follows semantic versioning format."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_author() -> None:
    """Verify that __author__ matches the expected value."""
    assert __author__ == "Dylan Monfret"
