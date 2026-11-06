"""Suggest stock names that are probably the same stock (SPEC.md §2). Suggestions only: you confirm."""
from __future__ import annotations

import difflib


def suggestions(keys: list[str], min_ratio: float = 0.85) -> list[list[str]]:
    """Groups of name keys that look alike: one is a word-prefix of the other, or they are nearly identical."""
    keys = sorted(set(k for k in keys if k))
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            short, long_ = (a, b) if len(a) <= len(b) else (b, a)
            prefix = len(short) >= 4 and (long_.startswith(short + " ") or long_.replace(" ", "").startswith(short.replace(" ", "")))
            if prefix or difflib.SequenceMatcher(None, a, b).ratio() >= min_ratio:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=lambda g: g[0])
