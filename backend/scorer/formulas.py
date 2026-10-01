"""Shared normalization helpers from instructions.md's "Normalization Notes",
plus SerpApi field parsing (duration strings, relative/absolute dates).
Reused by scorer/metadata_filter.py (Phase 3) and ranker/rank.py (Phase 5)."""
import math
import re
from datetime import datetime

_RELATIVE_DATE_RE = re.compile(
    r"(\d+)\s*(year|yr|y|month|mo|week|wk|w|day|d|hour|hr|h)s?\s*ago", re.IGNORECASE
)
_UNIT_TO_DAYS = {
    "year": 365, "yr": 365, "y": 365,
    "month": 30, "mo": 30,
    "week": 7, "wk": 7, "w": 7,
    "day": 1, "d": 1,
    "hour": 1 / 24, "hr": 1 / 24, "h": 1 / 24,
}


def parse_duration_to_seconds(length_text: str) -> int | None:
    """Parses "H:MM:SS" or "MM:SS" (SerpApi's `length` field format)."""
    if not length_text:
        return None
    parts = length_text.strip().split(":")
    if not all(p.isdigit() for p in parts):
        return None
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        return None
    return h * 3600 + m * 60 + s


def parse_date_to_age_years(date_text: str) -> float | None:
    """Handles both formats SerpApi returns depending on engine:
    - relative, from engine=youtube search results: "3y ago", "5 months ago"
    - absolute, from engine=youtube_video: "Oct 27, 2025", "Premiered Mar 12, 2023"
    """
    if not date_text:
        return None
    text = date_text.replace("Premiered", "").strip()

    m = _RELATIVE_DATE_RE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = n * _UNIT_TO_DAYS.get(unit, 365)
        return days / 365.0

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return (datetime.now() - dt).days / 365.0
        except ValueError:
            continue
    return None


def recency_score(age_years: float | None) -> float:
    """instructions.md: 1.0 if <6mo, 0.8 if <1yr, 0.5 if <3yr, 0.2 if older.
    Unknown age scores the same as the oldest bucket rather than being dropped."""
    if age_years is None:
        return 0.2
    if age_years < 0.5:
        return 1.0
    if age_years < 1:
        return 0.8
    if age_years < 3:
        return 0.5
    return 0.2


def normalized_view_count(views: int | None, max_views_in_set: int) -> float:
    """log10(views) / log10(max_views_in_set)."""
    if not views or views <= 0 or max_views_in_set <= 1:
        return 0.0
    return math.log10(views) / math.log10(max_views_in_set)


def channel_authority_score(subscribers: int | None) -> float:
    """log10(subscribers) / 8, capped at 1.0."""
    if not subscribers or subscribers <= 0:
        return 0.0
    return min(math.log10(subscribers) / 8, 1.0)
