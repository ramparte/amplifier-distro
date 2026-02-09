"""Documentation pointer configuration for Amplifier Distro.

Defines external documentation URLs as structured pointers that can be
updated in one place when sites move. The install wizard and web UI
use these to show helpful links without hardcoding URLs everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocPointer:
    id: str
    title: str
    url: str
    description: str
    category: str  # "tutorial", "reference", "stories", "landing"


# ---------------------------------------------------------------------------
#  Pointers
# ---------------------------------------------------------------------------

DOC_POINTERS: dict[str, DocPointer] = {
    "landing": DocPointer(
        id="landing",
        title="Amplifier",
        url="https://github.com/microsoft/amplifier",
        description="What is Amplifier - main landing page",
        category="landing",
    ),
    "tutorial": DocPointer(
        id="tutorial",
        title="Amplifier Tutorial",
        url="https://ramparte.github.io/amplifier-tutorial",
        description="Step-by-step tutorial and learning path",
        category="tutorial",
    ),
    "stories": DocPointer(
        id="stories",
        title="Amplifier Stories",
        url="https://ramparte.github.io/amplifier-stories",
        description="Case studies, presentations, and content",
        category="stories",
    ),
    "docs": DocPointer(
        id="docs",
        title="Amplifier Documentation",
        url="https://github.com/microsoft/amplifier/tree/main/docs",
        description="Technical documentation and guides",
        category="reference",
    ),
}


# ---------------------------------------------------------------------------
#  Accessors
# ---------------------------------------------------------------------------


def get_docs_for_category(category: str) -> list[DocPointer]:
    """Return all doc pointers matching the given category."""
    return [dp for dp in DOC_POINTERS.values() if dp.category == category]


def get_doc(doc_id: str) -> DocPointer | None:
    """Return a single doc pointer by ID, or None if not found."""
    return DOC_POINTERS.get(doc_id)
