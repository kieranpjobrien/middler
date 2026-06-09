"""Align the same fixture across feeds and merge their books into one event.

The Odds API and odds-api.io use different event ids, so the same match must be
recognised by sport + kickoff proximity + team names (via the confidence-gated
:class:`~middler.match.entity.EntityMatcher`). Once matched, the two feeds' books
are merged — deduplicated by canonical bookmaker key so a single book is never
counted twice. The result feeds the unchanged detection engine, now with more
books per event and a second source's view of the sharp references.
"""

from __future__ import annotations

from middler.books import canonical_book
from middler.match.entity import EntityMatcher
from middler.models import BookMarket, Event


def _newer(candidate: BookMarket, current: BookMarket) -> bool:
    """True if ``candidate`` should replace ``current`` for the same book+market."""
    if candidate.last_update and current.last_update:
        return candidate.last_update > current.last_update
    if candidate.last_update and not current.last_update:
        return True
    if not candidate.last_update and not current.last_update:
        return len(candidate.outcomes) > len(current.outcomes)
    return False


def merge_events(events: list[Event]) -> Event:
    """Merge several feed-events for the *same* fixture into one.

    Args:
        events: Events believed to be the same fixture (≥1). The first is treated
            as primary for identity (id, teams, commence).

    Returns:
        A single :class:`Event` whose books are deduplicated by canonical key.
    """
    primary = events[0]
    groups: dict[tuple[str, str], BookMarket] = {}
    for event in events:
        for bm in event.book_markets:
            key = (canonical_book(bm.bookmaker), bm.market_key)
            existing = groups.get(key)
            if existing is None or _newer(bm, existing):
                groups[key] = BookMarket(
                    bookmaker=key[0], market_key=bm.market_key, outcomes=bm.outcomes, last_update=bm.last_update
                )
    return Event(
        id=primary.id,
        sport_key=primary.sport_key,
        sport_title=primary.sport_title,
        commence_time=primary.commence_time,
        home_team=primary.home_team,
        away_team=primary.away_team,
        status=primary.status,
        book_markets=list(groups.values()),
    )


def best_fixture_match(
    target: Event, candidates: list[Event], matcher: EntityMatcher, tolerance_minutes: int = 90
) -> Event | None:
    """Find the candidate event that is the same fixture as ``target``.

    A match requires kickoff within ``tolerance_minutes`` and *both* teams to
    match confidently (so we never merge the wrong game). Among qualifying
    candidates, the highest combined team-name score wins.

    Args:
        target: The fixture to match (from the primary feed).
        candidates: Events from the other feed.
        matcher: A configured entity matcher.
        tolerance_minutes: Allowed difference in kickoff time.

    Returns:
        The best matching candidate, or None if none qualify.
    """
    if target.home_team is None or target.away_team is None:
        return None
    best: Event | None = None
    best_score = 0.0
    for cand in candidates:
        if cand.home_team is None or cand.away_team is None:
            continue
        if abs((cand.commence_time - target.commence_time).total_seconds()) > tolerance_minutes * 60:
            continue
        home = matcher.match(target.home_team, [cand.home_team])
        away = matcher.match(target.away_team, [cand.away_team])
        if home.confident and away.confident and (home.score + away.score) > best_score:
            best, best_score = cand, home.score + away.score
    return best


def align_and_merge(
    primary: list[Event],
    secondary: list[Event],
    matcher: EntityMatcher | None = None,
    tolerance_minutes: int = 90,
) -> list[Event]:
    """Enrich each primary event with a matched secondary event's books.

    Args:
        primary: Events from the primary feed (drive identity and scheduling).
        secondary: Events from the secondary feed.
        matcher: Entity matcher (a default is created if omitted).
        tolerance_minutes: Kickoff-time tolerance for fixture matching.

    Returns:
        One merged event per primary event (unmatched primaries pass through
        unchanged).
    """
    matcher = matcher or EntityMatcher()
    remaining = list(secondary)
    merged: list[Event] = []
    for event in primary:
        match = best_fixture_match(event, remaining, matcher, tolerance_minutes)
        if match is not None:
            merged.append(merge_events([event, match]))
            remaining.remove(match)
        else:
            merged.append(event)
    return merged
