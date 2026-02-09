"""Documentation Config Tests

Validates the doc pointer data structures and accessor functions
used by the install wizard and web UI to surface helpful links.

Exit criteria verified:
1. DOC_POINTERS has all four entries (landing, tutorial, stories, docs)
2. Each pointer is a DocPointer with required fields
3. get_docs_for_category() filters correctly
4. get_doc() returns the right pointer or None
5. All URLs are valid https:// strings
"""

from amplifier_distro.docs_config import (
    DOC_POINTERS,
    DocPointer,
    get_doc,
    get_docs_for_category,
)


class TestDocPointers:
    """Verify DOC_POINTERS dict has correct entries and structure."""

    EXPECTED_IDS = {"landing", "tutorial", "stories", "docs"}

    def test_has_all_expected_pointers(self):
        assert set(DOC_POINTERS.keys()) == self.EXPECTED_IDS

    def test_count_is_four(self):
        assert len(DOC_POINTERS) == 4

    def test_each_pointer_is_doc_pointer_type(self):
        for did, pointer in DOC_POINTERS.items():
            assert isinstance(pointer, DocPointer), f"{did} should be DocPointer"

    def test_each_pointer_has_required_fields(self):
        for did, pointer in DOC_POINTERS.items():
            assert isinstance(pointer.id, str) and pointer.id == did
            assert isinstance(pointer.title, str) and len(pointer.title) > 0
            assert isinstance(pointer.url, str) and pointer.url.startswith("https://")
            assert isinstance(pointer.description, str) and len(pointer.description) > 0
            assert isinstance(pointer.category, str) and len(pointer.category) > 0

    def test_all_urls_are_https(self):
        for did, pointer in DOC_POINTERS.items():
            assert pointer.url.startswith("https://"), f"{did} URL should be https"

    def test_landing_pointer(self):
        p = DOC_POINTERS["landing"]
        assert p.title == "Amplifier"
        assert p.category == "landing"
        assert "github.com/microsoft/amplifier" in p.url

    def test_tutorial_pointer(self):
        p = DOC_POINTERS["tutorial"]
        assert p.title == "Amplifier Tutorial"
        assert p.category == "tutorial"

    def test_stories_pointer(self):
        p = DOC_POINTERS["stories"]
        assert p.title == "Amplifier Stories"
        assert p.category == "stories"

    def test_docs_pointer(self):
        p = DOC_POINTERS["docs"]
        assert p.title == "Amplifier Documentation"
        assert p.category == "reference"


class TestGetDocsForCategory:
    """Verify get_docs_for_category() filters correctly."""

    def test_landing_category(self):
        result = get_docs_for_category("landing")
        assert len(result) == 1
        assert result[0].id == "landing"

    def test_tutorial_category(self):
        result = get_docs_for_category("tutorial")
        assert len(result) == 1
        assert result[0].id == "tutorial"

    def test_stories_category(self):
        result = get_docs_for_category("stories")
        assert len(result) == 1
        assert result[0].id == "stories"

    def test_reference_category(self):
        result = get_docs_for_category("reference")
        assert len(result) == 1
        assert result[0].id == "docs"

    def test_nonexistent_category_returns_empty(self):
        result = get_docs_for_category("nonexistent")
        assert result == []

    def test_returns_list_of_doc_pointers(self):
        result = get_docs_for_category("landing")
        assert all(isinstance(dp, DocPointer) for dp in result)


class TestGetDoc:
    """Verify get_doc() returns correct results."""

    def test_existing_doc(self):
        result = get_doc("landing")
        assert result is not None
        assert result.id == "landing"

    def test_all_ids_resolve(self):
        for did in DOC_POINTERS:
            assert get_doc(did) is not None

    def test_nonexistent_doc_returns_none(self):
        assert get_doc("nonexistent") is None

    def test_empty_string_returns_none(self):
        assert get_doc("") is None

    def test_returns_same_object_as_dict(self):
        for did in DOC_POINTERS:
            assert get_doc(did) is DOC_POINTERS[did]
