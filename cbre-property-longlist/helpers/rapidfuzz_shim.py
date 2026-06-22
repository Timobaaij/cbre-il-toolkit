"""rapidfuzz_shim.py - a minimal rapidfuzz stand-in for sandboxes where rapidfuzz
cannot be installed (no pip / no network). Implements ONLY the calls this skill
uses:

  fuzz.ratio(a, b)            -> 0..100
  fuzz.token_sort_ratio(a, b) -> 0..100   (order-insensitive)
  fuzz.token_set_ratio(a, b)  -> 0..100   (order- and duplicate-insensitive)
  process.extractOne(query, choices[, scorer, score_cutoff]) -> (choice, score, key) | None

Backed by the stdlib `difflib`. This is a FALLBACK only: the callers do
    try: from rapidfuzz import fuzz
    except Exception: from rapidfuzz_shim import fuzz
so real rapidfuzz is always preferred where present and never shadowed. The
scores approximate rapidfuzz's (close enough for the dedup threshold of 88 and
the column-map threshold of 90), and the shim is only active when rapidfuzz is
absent; the coverage gate still polices the resulting merges, so a marginal
difference in a borderline match cannot ship a silent duplicate.
"""
from __future__ import annotations

import difflib


def _ratio(a: str, b: str) -> float:
    a, b = (a or ""), (b or "")
    if not a and not b:
        return 100.0
    return 100.0 * difflib.SequenceMatcher(None, a, b).ratio()


class _Fuzz:
    @staticmethod
    def ratio(a, b, **kwargs) -> float:
        return _ratio(str(a), str(b))

    @staticmethod
    def token_sort_ratio(a, b, **kwargs) -> float:
        sa = " ".join(sorted(str(a).split()))
        sb = " ".join(sorted(str(b).split()))
        return _ratio(sa, sb)

    @staticmethod
    def token_set_ratio(a, b, **kwargs) -> float:
        # mirrors rapidfuzz: compare the shared-token core against each full side
        ta, tb = set(str(a).split()), set(str(b).split())
        inter = " ".join(sorted(ta & tb))
        sa = (inter + " " + " ".join(sorted(ta - tb))).strip()
        sb = (inter + " " + " ".join(sorted(tb - ta))).strip()
        if not inter:
            return _ratio(sa, sb)
        return max(_ratio(inter, sa), _ratio(inter, sb), _ratio(sa, sb))


fuzz = _Fuzz()


class _Process:
    @staticmethod
    def extractOne(query, choices, scorer=None, score_cutoff=0, **kwargs):
        score = scorer or fuzz.ratio
        items = choices.items() if hasattr(choices, "items") else enumerate(choices)
        best = None
        for key, choice in items:
            s = score(query, choice)
            if best is None or s > best[1]:
                best = (choice, s, key)
        if best is not None and best[1] >= (score_cutoff or 0):
            return best
        return None


process = _Process()
