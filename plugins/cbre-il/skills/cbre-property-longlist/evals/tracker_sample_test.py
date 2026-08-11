#!/usr/bin/env python3
"""tracker_sample_test.py - the mapper sees a VALUE for every populated column. (B12)

tracker_structure shipped data_rows[:5], a blind head slice. A column populated only from
row 6 onward therefore showed the mapping sub-agent five blank cells. The column was never
invisible - its header always ships, and a dictionary miss names it in unmapped_headers -
which is worse than invisible: the agent is pointed at the column and handed an all-blank
sample as its evidence, and the contract says answer `field: null` when unsure. The blind
VERIFY pass is disarmed identically, so both passes agree and diff_tracker_maps reports
nothing. A silent agreement between two disarmed passes is the worst possible outcome.

Greedy set-cover replaces the slice. Python chooses which EVIDENCE to show; it never
decides what a column means. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import extract_xlsx as X  # noqa: E402


def _sheet(csv_rows, d, name="t.csv"):
    p = Path(d) / name
    p.write_text("\n".join(",".join(str(c) for c in r) for r in csv_rows), encoding="utf-8")
    return p


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_trk_"))

    # 40 rows; "Clear Height" is populated ONLY on row 40 - the exact shape that was invisible
    hdr = ["Park", "City", "Developer", "Size sq m", "Rent", "Clear Height"]
    rows = [hdr]
    for i in range(1, 40):
        rows.append([f"Park {i}", "Corby", "Dev", 10000 + i, 6.5, ""])
    rows.append(["Park 40", "Corby", "Dev", 25000, 7.0, 12.5])

    got = X.tracker_structure(_sheet(rows, d))
    ck(len(got) == 1, f"the sheet is detected as a tracker ({len(got)})")
    if not got:
        print(f"\nTRACKER SAMPLE TEST: FAIL ({len(fails)})")
        return 1
    s = got[0]
    ci = hdr.index("Clear Height")
    seen = [r[ci] for r in s["sample_rows"] if ci < len(r) and str(r[ci]).strip()]
    ck(bool(seen), f"the row-40-only column HAS a value in the sample {ascii(str(seen))}")
    ck("12.5" in " ".join(seen), "and it is the real value, not a placeholder")

    # every populated column must be covered, not just the awkward one
    for c_i, name in enumerate(hdr):
        vals = [r[c_i] for r in s["sample_rows"] if c_i < len(r) and str(r[c_i]).strip()]
        ck(bool(vals), f"column {ascii(name)} has at least one sampled value")

    ck(len(s["sample_rows"]) <= 12, f"the cap is respected ({len(s['sample_rows'])})")
    ck(len(s.get("sample_row_numbers") or []) == len(s["sample_rows"]),
       "every sampled row is locatable by its 1-based sheet row")
    ck("unsampled_columns" not in s, "nothing is declared unsampled when everything is covered")

    # determinism: the same sheet must give the same sample, or the cache hash churns
    again = X.tracker_structure(_sheet(rows, d, "t2.csv"))
    ck(again[0]["sample_rows"] == s["sample_rows"], "the selection is deterministic")

    # OVERFLOW must be DECLARED, never silently truncated
    wide_hdr = [f"Col{i}" for i in range(30)]
    wide = [wide_hdr]
    for i in range(30):                       # each row populates exactly ONE column
        wide.append(["" for _ in range(30)])
        wide[-1][i] = f"v{i}"
    wide.insert(1, ["Park A"] + ["" for _ in range(29)])
    w = X.tracker_structure(_sheet(wide, d, "wide.csv"))
    if w:
        ck(len(w[0]["sample_rows"]) <= 12, "a wide tracker still respects the cap")
        ck(w[0].get("unsampled_columns"),
           "and DECLARES the columns nobody sampled (a silent cap reads as 'all covered')")

    # the head is still shown when the cover leaves budget - a human reads this manifest
    small = [hdr] + [[f"P{i}", "Corby", "Dev", 10000, 6.0, 10.0] for i in range(1, 4)]
    sm = X.tracker_structure(_sheet(small, d, "small.csv"))
    ck(sm and sm[0]["sample_row_numbers"] == [2, 3, 4],
       f"a small sheet still shows its first rows {ascii(str(sm[0]['sample_row_numbers'] if sm else None))}")

    if fails:
        print(f"\nTRACKER SAMPLE TEST: FAIL ({len(fails)})")
        return 1
    print("\nTRACKER SAMPLE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
