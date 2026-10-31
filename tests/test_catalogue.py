"""The WCAG 2.2 catalogue and the mapping from axe-core rule tags to success criteria."""

from wcag_scanner.axe_runner import sc_from_tags
from wcag_scanner.criteria import CRITERIA, in_scope


def test_wcag22_catalogue():
    assert len(CRITERIA) == 86
    assert len(in_scope("A")) == 31
    assert len(in_scope("AA")) == 55
    assert "4.1.1" not in {c.id for c in CRITERIA}  # removed in WCAG 2.2


def test_axe_tags_map_to_criteria():
    assert sc_from_tags(["cat.color", "wcag2aa", "wcag143", "wcag1410"]) == ["1.4.3", "1.4.10"]
