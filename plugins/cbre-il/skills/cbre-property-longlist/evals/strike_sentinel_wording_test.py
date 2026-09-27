#!/usr/bin/env python3
"""strike_sentinel_wording_test.py - fix 3.17 (2026-09-26 test run).

The plausibility strike wrote a hard-coded "tbd". `epc` is not in STRING_FIELDS, so
fill_render_sentinels never mapped it and a card shipped the literal 'tbd' beside every other
field's 'TBC'. And ONE wording served both a bad FIGURE and a phrase with NO figure: an epc of
"Available upon request" was reported as "the parsed value ... may be a parse or unit error",
and the Gaps line said the source "DOES state a value ... the parsed figure fell outside the
plausibility band" - sending the broker to look for a number the page never prints.

Pins:
  * a real merge.py run strikes epc "Available upon request" to normalize.BLANK;
  * its conflicts note takes the NO-FIGURE branch ("a phrase with no figure"), and a numeric
    strike (clearHeight "400m") keeps the numeric branch ("falls outside the clearHeight ");
  * neither note carries the old literal "ships tbd";
  * the deliver Gaps line for the no-figure case lacks "DOES state a value"; the numeric one
    keeps it;
  * the render guard maps a residual 'tbd' / 'TBD' to BLANK (in-flight canonicals).

Run: python evals/strike_sentinel_wording_test.py"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

import _common as C  # noqa: E402
import deliver  # noqa: E402
import normalize as N  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _r(src, park, city, **kw):
    r = {"park": park, "city": city, "country": "GB", "developer": "Dev",
         "warehouseArea": 200000, "areaUnit": "sq ft",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1"}}
    r.update(kw)
    return r


def _run_merge(recs):
    d = Path(tempfile.mkdtemp(prefix="cbre_strike_word_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    if not (d / "c.json").exists():
        return None, out
    return json.loads((d / "c.json").read_text(encoding="utf-8")), out


def main() -> int:
    NOFIG = "Available upon request"
    recs = [_r("Alpha.pdf", "Alpha Park Unit 1", "Corby", epc=NOFIG),
            _r("Beta.pdf", "Beta Logistics 2", "Rugby", warehouseArea=150000, clearHeight="400m")]
    canon, out = _run_merge(recs)
    ck(canon is not None, "merge completes" + ("" if canon else f": {ascii(out[-300:])}"))
    if canon is None:
        print("\nFAIL strike_sentinel_wording_test")
        return 1
    props = {q.get("park"): q for q in canon.get("properties") or []}
    conflicts = (canon.get("meta") or {}).get("conflicts") or []
    a = props.get("Alpha Park Unit 1") or {}
    b = props.get("Beta Logistics 2") or {}

    def notes(pid, field):
        return [c for c in conflicts if str(c).startswith(f"id {pid} {field}:")]

    ck(a.get("epc") == N.BLANK, f"the no-figure epc is struck to BLANK {N.BLANK!r} ({a.get('epc')!r})")
    ck(b.get("clearHeight") == N.BLANK,
       f"the numeric clearHeight is struck to BLANK ({b.get('clearHeight')!r})")
    na, nb = notes(a.get("id"), "epc"), notes(b.get("id"), "clearHeight")
    ck(len(na) == 1 and "a phrase with no figure" in na[0] and NOFIG in na[0]
       and f"ships {N.BLANK}" in na[0],
       f"no-figure note: names the phrase, says it has no figure, ships BLANK ({ascii(na[:1])[:120]})")
    ck(bool(na) and "parse or unit error" not in na[0],
       "no-figure note does not call the phrase a parse/unit error")
    ck(len(nb) == 1 and "falls outside the clearHeight " in nb[0] and f"ships {N.BLANK}" in nb[0],
       f"numeric note keeps the band wording ({ascii(nb[:1])[:120]})")
    ck(not any("ships tbd" in str(c) for c in conflicts), "no note carries the old literal 'ships tbd'")
    struck = {(str(e.get("id")), e.get("field")): e for e in (canon.get("meta") or {}).get("struck") or []}
    ck((str(a.get("id")), "epc") in struck and struck[(str(a.get("id")), "epc")].get("value") == NOFIG,
       "meta.struck keeps the raw text of the no-figure strike")

    # clearHeight is a CORE field, whose Gaps line is CLOSE advice (never _close_note), so the
    # numeric Gaps branch is exercised with a digit-bearing epc strike row on Beta (synthetic,
    # the report_honesty_struck_test way).
    canon["meta"].setdefault("struck", []).append(
        {"id": b.get("id"), "field": "epc", "value": "C55", "source_file": "Beta.pdf",
         "locator": "page 1"})
    rep = deliver.gaps_report(canon, "t")
    a_line = [ln for ln in rep.splitlines() if "Alpha Park Unit 1" in ln and "`epc`" in ln]
    b_line = [ln for ln in rep.splitlines() if "Beta Logistics 2" in ln and "`epc`" in ln]
    ck(bool(a_line) and "DOES state a value" not in a_line[0].split("`epc`", 1)[1].split("; `", 1)[0]
       and "a phrase with no figure" in a_line[0],
       f"Gaps line (no figure): no 'DOES state a value' ({ascii(a_line[:1])[:160]})")
    ck(bool(b_line) and "DOES state a value" in b_line[0],
       "Gaps line (numeric): keeps 'DOES state a value'")
    ck("DOES state a value" not in deliver._close_note("epc", {"source_file": "x.pdf", "value": NOFIG})
       and "DOES state a value" in deliver._close_note("epc", {"source_file": "x.pdf", "value": "C55"}),
       "_close_note branches on a digit in the struck value")

    g = C.fill_render_sentinels({"id": 1, "epc": "tbd", "gatehouse": "TBD"})
    ck(g.get("epc") == N.BLANK and g.get("gatehouse") == N.BLANK,
       "render guard: residual 'tbd' / 'TBD' render as BLANK")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} strike_sentinel_wording_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
