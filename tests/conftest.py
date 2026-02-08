"""Shared test fixtures for amplifier-distro acceptance tests."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def src_root(project_root):
    """Return the src/ directory."""
    return project_root / "src"
