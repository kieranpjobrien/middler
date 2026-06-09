"""Entity matcher tests (rapidfuzz path; embedding fallback not exercised)."""

from __future__ import annotations

from middler.match.entity import EntityMatcher, normalise_name


def test_normalise_name_strips_filler_and_punctuation() -> None:
    assert normalise_name("Collingwood FC") == "collingwood"
    assert normalise_name("St. Kilda!!") == "st kilda"


def test_exact_match() -> None:
    m = EntityMatcher().match("Carlton", ["Carlton", "Collingwood"])
    assert m.method == "exact" and m.value == "Carlton" and m.confident


def test_alias_match() -> None:
    matcher = EntityMatcher(aliases={"Pies": "Collingwood"})
    m = matcher.match("Pies", ["Carlton", "Collingwood"])
    assert m.method == "alias" and m.value == "Collingwood" and m.confident


def test_fuzzy_match_typo() -> None:
    m = EntityMatcher().match("Collingwod", ["Carlton", "Collingwood"])
    assert m.method == "fuzzy" and m.value == "Collingwood" and m.confident
    assert m.score >= 0.85


def test_low_confidence_is_flagged_not_actioned() -> None:
    m = EntityMatcher().match("Brisbane Lions", ["Carlton", "Collingwood"])
    assert not m.confident  # surfaced, but never to be auto-actioned


def test_no_candidates() -> None:
    m = EntityMatcher().match("Carlton", [])
    assert m.value is None and m.method == "none"
