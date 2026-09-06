#!/usr/bin/env python3
"""f05_no_private_sentinel_sets_test.py - a NEW private sentinel-set literal under helpers/ fails. (F5)

The parity eval (f05_sentinel_parity_test.py) proves the consumers it KNOWS about agree. This
one catches the consumer nobody knows about yet: it parses every helpers/*.py with `ast` and
flags any set / frozenset / list / tuple literal (and dict key set) whose string constants
include two or more members of the unknown family. That is the shape every private copy took.

THE ALLOWLIST IS THE KNOWN RESIDUE, NOT A LICENCE. normalize.UNKNOWN_FORMS is the master and is
allowed by definition. The other entries are literals in files A1 did not own in the 2026-09-05
remediation, each tagged with the Wave-2 owner and a stated reason. When an owner delegates one,
its entry goes stale; the eval prints a NOTE rather than failing so a Wave-2 agent removing a
copy does not turn a file it does not own red - but the note is a chore, delete the entry.
Anything NOT on the list fails, with file, line and the members it carries.

Offline; parses source only.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
TEMPLATE = ROOT / "assets" / "dashboard_template.html"

# the dash sentinel is spelled by code point so this file never carries the character itself
FAMILY = {"tbd", "tbc", "tba", "tbs", "??", "n/a", "na", "\u2014", "poa", "to be confirmed"}

# (file, enclosing name) -> reason. `enclosing name` is the assigned variable when the literal
# is the value of an assignment, else the innermost function that contains it.
ALLOW = {
    ("normalize.py", "UNKNOWN_FORMS"):
        "THE master family (contract C5); the one legitimate literal",
    ("clarify.py", "DECLINE_TOKENS"):
        "NOT a predicate over a value: this is the ANSWER VOCABULARY, the words a broker types "
        "to decline a question ('skip', 'no preference'). It overlaps the family by coincidence "
        "of spelling, not of meaning, and delegating it would make a broker who typed a real "
        "unknown-looking answer indistinguishable from one who declined to answer.",
    ("run.py", "_SENTINELS"):
        "the import-failure FALLBACK behind run._filled. `_filled` delegates to "
        "normalize.looks_unknown and reaches this only when normalize cannot be imported at "
        "all, a state in which nothing else in the pipeline works either. It cannot diverge "
        "in practice because it is never consulted while the master is reachable.",
}

# EVERY OTHER ENTRY WAS DELETED ON 2026-09-06, and that is the point of this note.
# The 2026-09-05 remediation started with EIGHT private copies of this family in files their
# author did not own: two `_EXPECT_ABSENT` twins, `_CERT_SENTINELS`, `merge._is_sentinel`, the
# per-property notes list, and three in the gate runner. Measured before the work, the nine
# live predicates disagreed on 13 of 22 probe values; the sentinel this pipeline writes for
# itself was DATA to the shared reader and UNKNOWN to every copy, and a stated "none" was
# deleted by four of them against the extraction contract's explicit rule.
#
# Each owner delegated its own and the entry went stale, which is what left this list holding
# only the master and one unreachable fallback. Two of them needed a NARROWER reading rather
# than the shared one, and took a named predicate instead of keeping a literal:
# `looks_unknown_code` where the value is a two-letter country CODE (three family members are
# also assigned ISO alpha-2 codes), and `repairs._absent_like` where a market PHRASE must still
# trip the `expect` guard. Narrower is fine; private is not.
#
# So an addition here is not routine. It means a tenth reading of "absent" has appeared, and
# the reason had better name the KIND of value it judges and why the master and the two named
# narrowings all fail it.

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _members(node: ast.AST) -> set:
    """The family members among a literal collection's string constants."""
    elts = []
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        elts = node.elts
    elif isinstance(node, ast.Dict):
        elts = [k for k in node.keys if k is not None]
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
          and node.func.id in ("frozenset", "set", "tuple", "list") and node.args):
        return _members(node.args[0])
    out = set()
    for e in elts:
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            v = e.value.strip().lower().rstrip(".")
            if v in FAMILY:
                out.add(e.value)
    return out


def _scan(path: Path) -> list[tuple[int, str, set]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    found = []
    # parent links, so a literal can be named by its assignment target or enclosing function
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def enclosing_name(node: ast.AST) -> str:
        cur = node
        while cur is not None:
            par = parents.get(id(cur))
            if isinstance(par, (ast.Assign, ast.AnnAssign)):
                tgt = par.targets[0] if isinstance(par, ast.Assign) else par.target
                if isinstance(tgt, ast.Name):
                    return tgt.id
            if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return par.name
            cur = par
        return "<module>"

    seen_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            m = _members(node)
            if len(m) >= 2:
                seen_calls.add(id(node.args[0]))
                found.append((node.lineno, enclosing_name(node), m))
        elif isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)) and id(node) not in seen_calls:
            m = _members(node)
            if len(m) >= 2:
                found.append((node.lineno, enclosing_name(node), m))
    return found


def main() -> int:
    print("== helpers/*.py: every literal collection carrying two or more family members ==")
    used = set()
    total = 0
    for f in sorted(HELPERS.glob("*.py")):
        for lineno, name, members in _scan(f):
            total += 1
            key = (f.name, name)
            if key in ALLOW:
                used.add(key)
                print(f"  [known] {f.name}:{lineno} {name} {sorted(members)}  <- {ALLOW[key][:60]}...")
            else:
                ck(False, f"NEW private sentinel set: {f.name}:{lineno} in `{name}` carries {sorted(members)} "
                          f"- delegate to normalize.looks_unknown() instead")
    ck(("normalize.py", "UNKNOWN_FORMS") in used, "normalize.UNKNOWN_FORMS is present (the master)")
    ck(total >= 1, f"{total} literal collections scanned against the allowlist")
    for key in sorted(set(ALLOW) - used):
        print(f"  [NOTE] allowlist entry no longer matches anything: {key} - delete it")

    print()
    print("== the consumers A1 owned carry NO literal any more ==")
    for f in ("_common.py", "build_dashboard.py", "deliver.py", "enrich.py"):
        hits = _scan(HELPERS / f)
        ck(not hits, f"{f}: no private sentinel literal ({[(l, n) for l, n, _ in hits]})")

    print()
    print("== the chrome: exactly one JS list carries the family ==")
    tpl = TEMPLATE.read_text(encoding="utf-8")
    pairs = re.findall(r'"tbd"[^\n]{0,160}"tbc"|"tbc"[^\n]{0,160}"tbd"', tpl)
    ck(len(pairs) == 1, f"one JS literal names both 'tbd' and 'tbc' (the UNKNOWN_FORMS mirror); found {len(pairs)}")
    hand = re.findall(r'===\s*"(?:tbd|tbc|\?\?|n/a|tba|tbs)"', tpl)
    ck(not hand, f"no JS code compares a value against a sentinel string by hand (found {len(hand)}: "
                 f"detailHTML/Flyover isTbd and certName all delegate to isAbsent)")

    print()
    if FAILS:
        print(f"F05 NO-PRIVATE-SENTINEL-SETS TEST: FAIL ({len(FAILS)})")
        return 1
    print("F05 NO-PRIVATE-SENTINEL-SETS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
