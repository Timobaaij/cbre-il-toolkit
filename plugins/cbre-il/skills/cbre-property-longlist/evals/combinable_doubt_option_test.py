#!/usr/bin/env python3
"""combinable_doubt_option_test.py - a COMBINABLE reader doubt gets Python's sum as an option. (3.2b)

THE MEASURED FAILURE (2026-09-26 test run). Ten of twelve broker questions were per-floor office
doubts: the reader offered each printed line ('3,080 sq ft (GF)', '6,155 sq ft (FF)', ...) and,
correctly, refused to add them. The natural answer, "add them", was not an option, and the lander
is selection-first, so the operator hand-wrote five repairs saying "broker: sum all".

THE RULE PINNED HERE (clarify side). When the reader declares `combinable: true`, the doubt names
ONE field and every option leads with a figure in ONE shared unit, clarify appends Python's sum as
one more option ('10,855 sq ft (3 printed lines combined)') and carries the parts, the sum and the
value text on the question and on the emitted landable stamp. The question id is computed BEFORE
the option is appended, so it is identical with and without the flag (a park-level field hashes
its option set). Mixed units, a bare number, prose, a single option, an ambiguous figure or a
missing flag give no synthesis. Decimal and comma-decimal parts are written so normalize reads
the sum back exactly. The lander half (landing `value_text`, the `why`) is run.py's (IA-7b).

Every name is invented. Offline. Run: python evals/combinable_doubt_option_test.py"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402
import normalize as N  # noqa: E402

FAILS: list = []

PARTS = ["3,080 sq ft (GF)", "6,155 sq ft (FF)", "1,620 sq ft (SF)"]


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _doubt(options=None, field="officeArea", combinable=True, **over):
    d = {"subject": "office area",
         "question": "the schedule prints three office lines and no office total; which is it?",
         "field": field, "options": list(PARTS if options is None else options),
         "default": (options or PARTS)[0],
         "why_it_matters": "the office figure is on the card"}
    if combinable is not None:
        d["combinable"] = combinable
    d.update(over)
    return d


def _rec(doubt, park="Harrow Vale", unit="Unit 7", src="harrow_vale.pdf", **fields):
    r = {"park": park, "unit": unit, "city": "Eastmere", "areaUnit": "sq ft",
         "warehouseArea": 120000, "__meta": {"source_file": src, "doubts": [doubt]}}
    r.update(fields)
    return r


def synthesis() -> None:
    print("1. three same-unit parts -> Python's sum is appended as an option")
    qs = CQ.agent_doubt_questions([_rec(_doubt())])
    ck(len(qs) == 1, f"one question ({len(qs)})")
    q = qs[0]
    want = "10,855 sq ft (3 printed lines combined)"
    ck(q.get("options") == PARTS + [want], f"options are the reader's three + the sum ({q.get('options')})")
    c = q.get("combinable") or {}
    ck(c.get("sum") == 10855 and c.get("unit") == "sq ft" and c.get("value_text") == "10,855 sq ft",
       f"combinable carries sum/unit/value_text ({c})")
    ck(c.get("parts") == PARTS and c.get("first") == PARTS[0] and c.get("option") == want,
       "combinable carries the parts verbatim, the first line and the option string")
    ck(want in q.get("question", ""), "the question text names the offered sum")
    ck(q.get("answer_handling", "").startswith("applied"), "the question stays an APPLIED doubt")
    ck("to_apply_by_hand" not in q, "no hand-repair skeleton on an applied doubt")
    ck(CQ._is_combinable({"combinable": "YES"}) and CQ._is_combinable({"combinable": True})
       and not CQ._is_combinable({"combinable": "no"}) and not CQ._is_combinable({}),
       "_is_combinable: true / 'yes' / 'true' only")


def id_stability() -> None:
    print("2. the id is keyed on the READER's options, with or without the flag")
    a = CQ.agent_doubt_questions([_rec(_doubt())])[0]["id"]
    b = CQ.agent_doubt_questions([_rec(_doubt(combinable=None))])[0]["id"]
    ck(a == b, f"per-unit field: same id with and without combinable ({a} / {b})")
    park_opts = ["2 miles (J10)", "3 miles (J11)"]
    pa = CQ.agent_doubt_questions([_rec(_doubt(park_opts, field="motorway"))])[0]
    pb = CQ.agent_doubt_questions([_rec(_doubt(park_opts, field="motorway", combinable=None))])[0]
    ck(pa.get("combinable") is not None, "the park-level doubt did get a synthesis (the test is live)")
    ck(pa["id"] == pb["id"], f"park-level field (option set hashed): same id ({pa['id']} / {pb['id']})")


def refusals() -> None:
    print("3. no synthesis where a sum would be a guess")
    cases = {
        "mixed units, sq ft + sq m": ["300 sq ft (GF)", "30 sq m (FF)"],
        "mixed units, sq m first": ["30 sq m (GF)", "300 sq ft (FF)"],
        "a bare number (no unit)": ["3,080 (GF)", "6,155 sq ft (FF)"],
        "one option": ["3,080 sq ft (GF)"],
        "an ambiguous US decimal (normalize reads it 1000x off)": ["1,234.5 sq ft", "100 sq ft"],
    }
    for label, opts in cases.items():
        q = CQ.agent_doubt_questions([_rec(_doubt(opts))])[0]
        ck("combinable" not in q and q.get("options") == opts[:6],
           f"{label}: options unchanged, no combinable ({q.get('options')})")
        ck(bool(q.get("combinable_refused")), f"{label}: a diagnostic reason is recorded "
           f"({q.get('combinable_refused')!r})")
    # a range does not lead with ONE figure, so it is the D4 prose-option case: refused the
    # landing promise before synthesis is even considered
    rq = CQ.agent_doubt_questions([_rec(_doubt(["3,000-3,500 sq ft", "1,000 sq ft"]))])[0]
    ck("combinable" not in rq and rq.get("unlandable_options") == ["3,000-3,500 sq ft"],
       f"a range: no synthesis, and D4 marks it unlandable ({rq.get('unlandable_options')})")
    q = CQ.agent_doubt_questions([_rec(_doubt(["the combined office lines", "3,080 sq ft (GF)"]))])[0]
    ck("combinable" not in q and q.get("unlandable_options"),
       "prose option on an arithmetic field: no synthesis, still unlandable (D4 intact)")
    q = CQ.agent_doubt_questions([_rec(_doubt(combinable=None))])[0]
    ck("combinable" not in q and len(q.get("options") or []) == 3, "no flag: no synthesis")
    q = CQ.agent_doubt_questions([_rec(_doubt(combinable=False))])[0]
    ck("combinable" not in q, "combinable: false -> no synthesis")
    two = _doubt()
    two["fields"] = ["warehouseArea"]
    q = CQ.agent_doubt_questions([_rec(two)])[0]
    ck("combinable" not in q, "two declared fields: no field stamp, no synthesis")
    ck(CQ.combined_option("officeArea", ["4 docks (N)", "3 docks (S)"])["value_text"] == "7 docks",
       "a non-area unit sums when every part states the SAME unit words")


def emit_stamp() -> None:
    print("4. emit's landable stamp carries the option and the combinable block")
    w = Path(tempfile.mkdtemp(prefix="comb_emit_"))
    qs = CQ.agent_doubt_questions([_rec(_doubt())])
    pend = CQ.pending(w, qs)
    ck(len(pend) == 1, f"the doubt is pending ({len(pend)})")
    CQ.emit(w, pend)
    land = CQ.landable(w)
    st = land.get(qs[0]["id"]) or {}
    ck(st.get("options", [])[-1:] == ["10,855 sq ft (3 printed lines combined)"],
       f"stamp options include the sum ({st.get('options')})")
    c = st.get("combinable") or {}
    ck(set(c) == {"parts", "sum", "unit", "value_text", "option", "first"},
       f"stamp combinable block has exactly the six keys ({sorted(c)})")
    ck(c.get("value_text") == "10,855 sq ft" and c.get("parts") == PARTS, "stamp block values")
    six = [f"{n},000 sq ft (L{n})" for n in range(1, 7)]
    q7 = CQ.agent_doubt_questions([_rec(_doubt(six), unit="Unit 9")])[0]
    ck(len(q7.get("options") or []) == 7, f"six parts + the sum = 7 options ({len(q7.get('options') or [])})")
    w2 = Path(tempfile.mkdtemp(prefix="comb_emit7_"))
    CQ.emit(w2, CQ.pending(w2, [q7]))
    st7 = CQ.landable(w2).get(q7["id"]) or {}
    ck(len(st7.get("options") or []) == 7 and st7["options"][-1].startswith("21,000 sq ft"),
       "the stamp keeps all seven (slice widened from 6 to 8)")


def locale() -> None:
    print("5. decimal / comma-decimal parts format through normalize")
    c = CQ.combined_option("officeArea", ["1.234,5 m² (EG)", "2.000,25 m² (OG)"])
    ck(c is not None and c["unit"] == "sq m", f"comma-decimal parts combine in sq m ({c})")
    ck(c and N.normalize_number(c["value_text"]) == 3234.75,
       f"normalize reads the sum back exactly ({c and c['value_text']})")
    c2 = CQ.combined_option("plotArea", ["2.5 acres", "1.25 acres"])
    ck(c2 and c2["value_text"] == "3.75 acres" and N.normalize_number(c2["value_text"]) == 3.75,
       f"point-decimal parts ({c2 and c2['value_text']})")
    c3 = CQ.combined_option("officeArea", ["12 500 m2", "1 500 m2"])
    ck(c3 and N.normalize_number(c3["value_text"]) == 14000 and c3["unit"] == "sq m",
       f"space-grouped metric parts ({c3 and c3['value_text']})")
    c4 = CQ.combined_option("officeArea", ["999 sq ft", "1 sq ft"])
    ck(c4 and c4["value_text"] == "1,000 sq ft", f"grouping as merge writes it ({c4 and c4['value_text']})")


def merge_expect() -> None:
    print("6. merge's own office sum is read on a COPY (for 3.2c)")
    r = _rec(_doubt(), officeGroundFloor="3,080 sq ft", officeFirstFloor="6,155 sq ft",
             officeSecondFloor="1,620 sq ft")
    before = copy.deepcopy(r)
    q = CQ.agent_doubt_questions([r])[0]
    me = q.get("merge_expect") or {}
    ck(me.get("status") == "computed" and me.get("value") == 10855 and me.get("unit") == "sq ft",
       f"merge_expect = merge's computed sum ({me})")
    ck(r == before, "the record is untouched")
    ck(CQ._merge_office_expect(r, "warehouseArea") is None, "only officeArea has a merge sum")
    ck(CQ._merge_office_expect(None, "officeArea") is None, "a non-record gives None, never a crash")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    synthesis()
    id_stability()
    refusals()
    emit_stamp()
    locale()
    merge_expect()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"COMBINABLE DOUBT OPTION TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("COMBINABLE DOUBT OPTION TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
