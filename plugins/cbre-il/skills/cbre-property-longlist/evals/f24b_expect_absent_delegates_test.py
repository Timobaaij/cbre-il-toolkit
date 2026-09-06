#!/usr/bin/env python3
"""f24b_expect_absent_delegates_test.py - repairs' `expect` absence family delegates. (SEAM-13)

`repairs.py` carried its own unknown-value literal for the `expect` guard. A1 consolidated
eight such predicates into normalize.UNKNOWN_FORMS / looks_unknown; this was one of the nine
that remained, and it carried a stated `none` as absence, which contradicts contract C5 (the
extraction contract names `none` as a stated NEGATIVE, so it is data).

The site judges a property's CURRENT value against what an operator READ and typed, and the
documented invitation is `expect: {"f": "tbd"}` for a struck field holding None. It is NOT a
blanket looks_unknown site: expect_sentinel_test pins that a market phrase ("A consultar")
still trips the guard. So the delegation is a NARROWER slice of the master, stated as a rule
(a placeholder TOKEN is absence; a PHRASE is not) rather than as a second list, the same shape
as normalize.looks_unknown_code (the family minus a stated exemption).

What this pins:
  * repairs.py carries NO literal collection with two or more family members any more (the
    f05 guard's own AST test, applied to this one file);
  * the family the guard reads is a strict subset of normalize.UNKNOWN_FORMS;
  * settled semantics: ??, TBA, TBS, tbd, tbc, n/a, -, the dash, empty and whitespace are
    absence; a stated none/None is DATA; a market phrase is not absence; the bare alpha-2
    codes normalize exempts for code fields (na, nc, sc) are not absence here either;
  * the two `expect` outcomes that MOVE, both deliberate: `expect tbd` against a field holding
    "none" now SUPERSEDES (it used to match), and `expect none` against a struck field (None)
    now SUPERSEDES (it used to match). The card shows "none" for the first and "tbd" for the
    second, and the guard compares against what the operator reads;
  * the two that WIDEN: `expect TBA` and `expect ??` against a struck field now match;
  * everything expect_sentinel_test relies on still holds: tbd/None/''/dash match each other,
    a stated figure still supersedes, `_same` is untouched.
Offline; parses source and calls apply on a synthetic property.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import normalize as N                    # noqa: E402
import repairs as R                      # noqa: E402

FAILS = []
# the dash sentinel is spelled by code point so this file never carries the character itself
DASH = "\u2014"
FAMILY = {"tbd", "tbc", "tba", "tbs", "??", "n/a", "na", DASH, "poa", "to be confirmed"}


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _literal_sets(path: Path) -> list[tuple[int, set]]:
    """Every literal collection in `path` carrying two or more family members (f05's test)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def members(node):
        elts = []
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            elts = node.elts
        elif isinstance(node, ast.Dict):
            elts = [k for k in node.keys if k is not None]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("frozenset", "set", "tuple", "list") and node.args):
            return members(node.args[0])
        return {e.value for e in elts if isinstance(e, ast.Constant)
                and isinstance(e.value, str) and e.value.strip().lower().rstrip(".") in FAMILY}

    return [(n.lineno, m) for n in ast.walk(tree)
            if isinstance(n, (ast.Set, ast.List, ast.Tuple, ast.Dict, ast.Call))
            for m in [members(n)] if len(m) >= 2]


def canon(**over):
    p = {"id": 1, "park": "Alpha Park", "city": "Bor", "developer": "CTP", "country": "CZ",
         "areaUnit": "sq m", "status": "Available", "photo": "x", "gallery": ["x"]}
    p.update(over)
    return {"meta": {"client": "T", "units": {"area": "sq m"}}, "pois": [], "regions": {},
            "properties": [p]}


def guarded(field, expect_value, cur, new):
    """apply one guarded repair of `field`; returns (report, canonical). cur=None -> absent key."""
    c = canon(**({field: cur} if cur is not None else {}))
    e = [{"id": "rp-001", "property": {"key": "bor|ctp|alpha park", "id": 1},
          "expect": {field: expect_value}, "set": {field: new},
          "why": "the agent confirmed", "verified_by": "t@cbre.com"}]
    return R.apply(c, e), c


def main() -> int:
    print("f24b_expect_absent_delegates_test - one fewer private sentinel set")

    print("== source: no private literal ==")
    hits = _literal_sets(ROOT / "helpers" / "repairs.py")
    ck(not hits, f"helpers/repairs.py carries no literal collection with 2+ family members ({hits})")
    ck(hasattr(R, "_EXPECT_ABSENT") and isinstance(R._EXPECT_ABSENT, frozenset),
       "the guard's family is still introspectable as repairs._EXPECT_ABSENT")
    fam = set(getattr(R, "_EXPECT_ABSENT", set()))
    ck(fam and fam < set(N.UNKNOWN_FORMS),
       f"that family is a STRICT subset of normalize.UNKNOWN_FORMS ({len(fam)} of {len(N.UNKNOWN_FORMS)})")
    ck("none" not in fam, "a stated `none` is not in the family (contract C5: it is data)")
    ck({"tbd", "tbc", "tba", "tbs", "??", "n/a", "-", "", DASH} <= fam,
       "the settled tokens are all in the family")
    ck(not ({"na", "nc", "sc"} & fam), "normalize's code-like exemptions are not absence here")
    ck(not any(" " in f for f in fam), "no multi-word market phrase is in the family")

    print("== _absent_like: settled semantics ==")
    for v, want in ((None, True), ("", True), ("   ", True), ("tbd", True), ("TBC", True),
                    ("tba", True), ("TBS", True), ("??", True), ("n/a", True), ("-", True),
                    (DASH, True),
                    ("none", False), ("None", False), ("NONE", False),
                    ("A consultar", False), ("auf anfrage", False), ("to be confirmed", False),
                    ("na", False), ("nc", False), ("sc", False),
                    ("EUR 45", False), (0, False), (41000, False)):
        ck(R._absent_like(v) is want, f"_absent_like({v!r}) is {want}")

    print("== the `expect` guard: what moved, and why it is right ==")
    r, c = guarded("warehouseRent", "tbd", "none", "EUR 45 / sq m / yr")
    ck(not r["applied"] and len(r["superseded"]) == 1 and c["properties"][0]["warehouseRent"] == "none",
       "MOVED: expect 'tbd' against a field holding a stated 'none' now SUPERSEDES (the card shows 'none')")
    r, c = guarded("warehouseRent", "none", None, "EUR 45 / sq m / yr")
    ck(not r["applied"] and len(r["superseded"]) == 1,
       "MOVED: expect 'none' against a struck field (None) now SUPERSEDES (the card shows 'tbd')")
    r, c = guarded("warehouseArea", "TBA", None, 62818)
    ck(len(r["applied"]) == 1 and c["properties"][0]["warehouseArea"] == 62818,
       "WIDENED: expect 'TBA' against a struck field matches and the value lands")
    r, c = guarded("warehouseArea", "??", None, 62818)
    ck(len(r["applied"]) == 1, "WIDENED: expect '??' against a struck field matches")

    print("== the `expect` guard: what did not move ==")
    for want, cur in (("tbd", None), (None, "tbd"), ("tbd", ""), (DASH, None), ("tbc", "tbd")):
        r, c = guarded("warehouseArea", want, cur, 62818)
        ck(len(r["applied"]) == 1 and not r["superseded"],
           f"absence still matches absence: expect {want!r} vs current {cur!r}")
    r, c = guarded("warehouseArea", "tbd", 41000, 62818)
    ck(not r["applied"] and len(r["superseded"]) == 1 and c["properties"][0]["warehouseArea"] == 41000,
       "a stated figure still SUPERSEDES and is untouched")
    r, c = guarded("warehouseRent", "tbd", "A consultar", "EUR 45 / sq m / yr")
    ck(not r["applied"] and len(r["superseded"]) == 1,
       "a market phrase still trips the guard (expect_sentinel_test's pin holds)")
    ck(R._same(None, "tbd") is False, "_same is untouched")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
