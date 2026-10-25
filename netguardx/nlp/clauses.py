"""Splitting free text into the clauses the grammar modules parse one at a time."""
from __future__ import annotations

import re

_SPLIT = re.compile(r"\.(?=\s|$)|[;\n]|,\s*(?:but\s+|and\s+)?|\s+but\s+")


def split_clauses(text: str) -> list[str]:
    """Sentence ends (not the dots inside addresses), semicolons, line breaks, and commas or "but"
    that join two requests.  A bare "and" never splits ("connect R2 and R3" is one clause)."""
    return [c for c in _SPLIT.split(text) if c and c.strip()]
