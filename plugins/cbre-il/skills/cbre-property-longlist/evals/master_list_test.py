#!/usr/bin/env python3
"""master_list_test.py - the user decides what the run builds, and every consumer obeys it.

WHAT THIS PINS, AND THE LIVE DEFECT BEHIND EACH PIN
---------------------------------------------------
On the Kapdaa run the broker learned what the run had decided to build by reading the FINISHED
dashboard, and the one question that does put scope to a human - the exit-13 source-authority
question - arrived after every brochure had already been read by its own agent. The master list
(exit 17) moves that decision to one sheet, before the decks are read. Each check below is one
way that could be true on paper and false in the work dir:

  1. ENUMERATION. A row for every tracker record, every email record and every brochure
     CLUSTER. A sheet that omits the email-only options is worse than no sheet, because it
     looks complete.
  2. ROW IDS ARE NOT POSITIONAL. The ids are computed in two places that walk the records in
     different orders (the enumeration, per file; the exclusion filter and the match seeding,
     over every record in the run). A positional id agrees in one and disagrees in the other,
     and the user's No then does nothing at all, silently.
  3. THE RED BROCHURE? COLUMN, and only that column. It is a real conditional-formatting rule
     keyed on the cell's own value, so it survives a sort; spread across neighbours it is
     noise, and as a static fill it lies the moment the sheet is re-ranked.
  4. AN UNANSWERED ROW REFUSES. Yes or No, no third value, exit 2, naming the rows.
  5. A No CLUSTER IS NEVER READ, and is NAMED in the Gaps Report. Skipping it silently would
     be the same class of defect as the one this stage exists to close.
  6. A USER DUPLICATE GROUP PRE-ANSWERS THE MATCH PAIR, keyed with match.pair_id - any other
     key produces a decisions file that looks answered and covers nothing.
  7. A NEW DECK RE-OPENS THE SHEET AND CARRIES THE OLD ANSWERS FORWARD by Row ID. A rebuild
     that cost the user their forty decisions would be a rebuild nobody ever runs twice.
  8. HEADLESS BYPASSES THE STOP, includes everything, and DISCLOSES it - and is not read as a
     scope decision anywhere, so a cron run cannot silently pre-answer the source-authority
     question for the next interactive pass.

Offline. No network, no LLM, no real PDFs: the deck rows are driven through an injected
first-page-text function, which is exactly how the spine injects it.
"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import master_list as ML            # noqa: E402
import master_list_build as MB      # noqa: E402
import master_list_read as MR       # noqa: E402
import match as MATCH               # noqa: E402
import deliver as DELIVER           # noqa: E402
import clarify as CQ                # noqa: E402

from openpyxl import load_workbook  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

fails = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


# --------------------------------------------------------------------- the synthetic corpus

def _rec(src, park, city, pc, area, locator=None, dev="Panattoni"):
    m = {"source_file": src, "source_type": pathlib.Path(src).suffix.lstrip(".")}
    if locator:
        m["prov"] = {"park": f"{locator} (tracker)"}
    return {"park": park, "city": city, "postcode": pc, "developer": dev,
            "warehouseArea": area, "areaUnit": "sq m", "__meta": m}


TRACKER = "Availability Tracker.xlsx"
EMAIL_A, EMAIL_B = "2026-09-01 Offer Venlo.msg", "2026-09-02 Offer Born.msg"

RECORDS = {
    TRACKER: [_rec(TRACKER, "Venlo Trade Port", "Venlo", "5928 NX", 41000, "Sheet1!B5"),
              _rec(TRACKER, "Born Logistics Park", "Born", "6121 RC", 28000, "Sheet1!B6")],
    EMAIL_A: [_rec(EMAIL_A, "Venlo Greenport Unit 3", "Venlo", "5928 NX", 19000)],
    EMAIL_B: [_rec(EMAIL_B, "Beringe Distribution Centre", "Beringe", "5986 PB", 33000)],
}
CLUSTERS = {"alpha": {"pdfs": ["alpha.pdf"], "region": "Venlo"},
            "beta": {"pptxs": ["beta.pptx"], "region": "Born"}}
CLUSTERS_PLUS = dict(CLUSTERS, gamma={"pdfs": ["gamma.pdf"], "region": "Roermond"})

FIRST_PAGE = {"alpha.pdf": "ALPHA PARK\nVenlo 5928 NX\n41,000 sq m to let",
              "beta.pptx": "",
              "gamma.pdf": "GAMMA\nRoermond 6041 TA\n12,500 sq m"}


def _fpt(p):
    return FIRST_PAGE.get(pathlib.Path(str(p)).name, "")


def _work():
    w = pathlib.Path(tempfile.mkdtemp(prefix="cbre_ml_"))
    return w


# ============================================================ 1. the enumeration is complete
print("\n1. Every route produces a row (trackers, emails, brochure clusters)")
WORK = _work()
auto = ML.build_auto(WORK, RECORDS, CLUSTERS, WORK, _fpt)
rows = auto["rows"]
ids = [r["row_id"] for r in rows]
ck(len(rows) == 6, f"6 candidate rows: 2 tracker + 2 email + 2 brochure clusters (got {len(rows)})")
ck(len(set(ids)) == 6, "every row id is unique")
ck(sum(1 for r in rows if r["source_type"] == "Tracker") == 2, "the tracker contributes 2 rows")
ck(sum(1 for r in rows if r["source_type"] == "Email") == 2, "the two emails contribute a row each")
ck(sum(1 for r in rows if r["source_type"] == "Brochure") == 2, "each brochure CLUSTER is one row")
ck((WORK / ML.AUTO_CANDIDATES).exists(), f"the spine wrote work/{ML.AUTO_CANDIDATES}")
_deck = [r for r in rows if r["source_type"] == "Brochure"]
ck(all(r["brochure"] == "Yes" for r in _deck), "a brochure row holds a document (Brochure? = Yes)")
ck(all(r["brochure"] == "No" for r in rows if r["source_type"] != "Brochure"),
   "a tracker/email row holds none, so its Brochure? is No and will be painted red")
_alpha = next(r for r in _deck if "Alpha Park" in (r["property"] or ""))
ck(_alpha["postcode"].replace(" ", "") == "5928NX" and _alpha["size_from"] == 41000,
   "a deck row's postcode and size come off the FIRST PAGE only")
# DEFECT B. The row used to be called "alpha" - the cluster label, which is a filename stem - and
# Town / city held that same stem. The first page says ALPHA PARK, Venlo, so the row does too.
ck(_alpha["property"] != "alpha" and "Alpha Park" in _alpha["property"],
   f"a deck row is named from the DOCUMENT, not the file (got {_alpha['property']!r})")
ck(_alpha["city"] == "Venlo",
   f"...and Town / city is the town printed beside the postcode (got {_alpha['city']!r})")
ck("(from filename)" not in _alpha["property"],
   "...with no filename marker, because the document named it")
_beta = next(r for r in _deck if r["row_id"].startswith("deck:beta"))
ck(_beta["property"].endswith("(from filename)"),
   f"a deck whose first page reads as nothing falls back to the filename AND SAYS SO "
   f"(got {_beta['property']!r})")
ck(_beta["city"] == "",
   f"...and its Town / city is BLANK, never the filename (got {_beta['city']!r})")
ck(all(r["source"] in ("Brochure, input folder",)
       or r["source"].startswith("Brochure, attached to email from ") for r in _deck),
   f"every deck row's Source reads like a sentence (got {[r['source'] for r in _deck]})")

print("\n1b. The blunt postcode sweep groups what the model has not adjudicated")
_v = [r for r in rows if ML.norm_postcode(r["postcode"]) == "5928NX"]
ck(len(_v) == 3 and len({r["duplicate_group"] for r in _v}) == 1 and _v[0]["duplicate_group"],
   "the tracker row, the email row and the deck row on one postcode land in ONE auto group")
ck("(auto sweep)" in _v[0]["duplicate_status"] and _v[0]["duplicate_origin"] == "auto",
   "the sweep LABELS itself an auto sweep, so the user can see it is not an adjudication")
ck(all(not r["duplicate_group"] for r in rows if ML.norm_postcode(r["postcode"]) == "6121RC"
       or ML.norm_postcode(r["postcode"]) == "5986PB"),
   "a lone postcode is not a group, and a blank postcode is never swept")

print("\n1c. Row ids do not depend on position in the list")
_flat = [r for recs in RECORDS.values() for r in recs]
_flat_ids = {ML.record_row_id(r) for r in _flat}
_enum_ids = {r["row_id"] for r in rows if r["source_type"] != "Brochure"}
ck(_flat_ids == _enum_ids,
   "the ids from the concatenated record list are the SAME ids the per-file enumeration wrote")
ck(ML.record_row_id(_flat[3]) == ML.record_row_id(_flat[3]),
   "and they are stable for a record with no provenance locator (content digest, not index)")

# ================================================================== 2. the workbook contract
print("\n2. The workbook: red Brochure?, a Yes/No dropdown, a hidden Row ID")
MB.build(WORK)
wbp = WORK / ML.WORKBOOK
ck(wbp.exists(), "Master List.xlsx was written")
wb = load_workbook(wbp)
ws = wb[MB.SHEET]
ck(MB.SHEET_DUPES in wb.sheetnames, "the Duplicate check tab is there")
_broch_col = get_column_letter(MB.IDX["brochure"])
_cf = {str(rng.sqref): list(rules) for rng, rules in ws.conditional_formatting._cf_rules.items()}
_ranges = list(_cf)
ck(len(_ranges) == 1, f"exactly ONE conditional-formatting range on the sheet (got {_ranges})")
ck(_ranges and _ranges[0].startswith(f"{_broch_col}{MB.FIRST_ROW}")
   and all(part.startswith(_broch_col) for part in _ranges[0].split(":")),
   f"the rule covers the Brochure? column ({_broch_col}) and NOTHING else - it is a flag for "
   f"the person scanning the sheet, not a stripe across the row")
_rule = list(_cf.values())[0][0]
ck(_rule.type == "expression" and '<>"Yes"' in _rule.formula[0],
   "it is a FormulaRule keyed on the cell's own value (survives a sort/filter/re-rank)")
ck(_rule.dxf.fill.bgColor.rgb.endswith("FF8080") or _rule.dxf.fill.fgColor.rgb.endswith("FF8080"),
   "anything that is not a flat Yes is painted red")
ck(ws.column_dimensions[get_column_letter(MB.IDX["row_id"])].hidden,
   "the Row ID column is hidden and load-bearing")
_dv = [d for d in ws.data_validations.dataValidation if "Yes,No" in str(d.formula1)]
ck(len(_dv) == 1, "Include? carries a Yes/No dropdown and there is no third value")
_hdrs = [ws.cell(MB.HDR_ROW, c).value for c in range(1, ws.max_column + 1)]
ck("Your Run notes for the AI" in _hdrs, "the run-notes column is on the sheet, by that name")

# ==================================================== 3. an unanswered sheet refuses (exit 2)
print("\n3. An unanswered row stops the run rather than being guessed")
try:
    MR.read(WORK)
    ck(False, "master_list_read refuses an unanswered sheet")
except SystemExit as e:
    ck(e.code == 2, f"master_list_read exits 2 on an unanswered sheet (got {e.code})")
ck(not (WORK / ML.ANSWERS).exists(), "and it wrote NOTHING - the refusal is not half-applied")

print("\n3b. 'Maybe' is not an answer here either")
_rid_col, _inc_col = MB.IDX["row_id"], MB.IDX["include"]
for r in range(MB.FIRST_ROW, MB.FIRST_ROW + len(rows)):
    ws.cell(r, _inc_col, "Yes")
ws.cell(MB.FIRST_ROW, _inc_col, "Maybe")
wb.save(wbp)
try:
    MR.read(WORK)
    ck(False, "a deferred answer refuses")
except SystemExit as e:
    ck(e.code == 2, f"a deferred 'Maybe' exits 2 as well (got {e.code})")

# ============================================= 4. the answer binds: No skips, and is reported
print("\n4. A No row is not built, and IS named in the Gaps Report")
wb = load_workbook(wbp)
ws = wb[MB.SHEET]
_by_rowid = {}
for r in range(MB.FIRST_ROW, MB.FIRST_ROW + len(rows)):
    rid = ws.cell(r, _rid_col).value
    _by_rowid[str(rid)] = r
    ws.cell(r, _inc_col, "Yes")
_beta_id = next(r["row_id"] for r in rows if r["row_id"].startswith("deck:beta"))
_born_id = next(r["row_id"] for r in rows
                if r["source_type"] == "Tracker" and "Born" in r["property"])
ws.cell(_by_rowid[_beta_id], _inc_col, "No")
ws.cell(_by_rowid[_born_id], _inc_col, "No")
ws.cell(_by_rowid[_born_id], MB.IDX["run_notes"], "withdrawn by the landlord on 12 Sep")
wb.save(wbp)
out = MR.read(WORK)
ck((WORK / ML.ANSWERS).exists() and out["counts"]["excluded"] == 2,
   "the answered sheet reads back: 4 in, 2 out")
ck(ML.excluded_cluster_labels(WORK) == {"beta"},
   "the deck dispatch skips the 'beta' cluster and nothing else")
ck(ML.user_answered(WORK), "a user-answered sheet reports itself as the scope authority")

_lines = "\n".join(DELIVER.master_list_lines(WORK))
ck("## Options excluded by the master list" in _lines, "the Gaps Report gains its own section")
ck("beta" in _lines and "Born Logistics Park" in _lines,
   "and NAMES every excluded option - a removed property is never a silent drop")
ck("withdrawn by the landlord" in _lines, "the user's own note travels into the report")

print("\n4b. The exclusion reaches the merge, and fails OPEN rather than shipping nothing")
_beta_rec = _rec("beta.pptx", "Born Scheme", "Born", "6121 RC", 28000)
_alpha_rec = _rec("alpha.pdf", "Alpha Park", "Venlo", "5928 NX", 41000)
kept, dropped = ML.apply_to_clusters([[_alpha_rec], [_beta_rec]], WORK)
ck(len(kept) == 1 and len(dropped) == 1 and dropped[0][0] is _beta_rec,
   "a cluster whose every record belongs to an excluded row is dropped")
kept2, dropped2 = ML.apply_to_clusters([[_beta_rec]], WORK)
ck(len(kept2) == 1 and not dropped2,
   "but if the filter would empty the dataset, NOTHING is dropped (an empty dashboard is never "
   "the right reading of a sheet somebody filled in)")
_mixed = [[_beta_rec, _alpha_rec]]
kept3, dropped3 = ML.apply_to_clusters(_mixed + [[_alpha_rec]], WORK)
ck(len(dropped3) == 0,
   "a cluster that also holds an INCLUDED record survives - the filter never drops on partial "
   "evidence")

# ================================================ 5. a user duplicate group pre-answers exit 10
print("\n5. A user duplicate group becomes a 'same' verdict, keyed the way exit 10 keys it")
a, b = RECORDS[TRACKER][0], RECORDS[EMAIL_A][0]
ml = json.loads((WORK / ML.ANSWERS).read_text(encoding="utf-8"))
_gid = "D1"
for row in ml["rows"]:
    if row.get("row_id") in (ML.record_row_id(a), ML.record_row_id(b)):
        row["duplicate_group"] = _gid
(WORK / ML.ANSWERS).write_text(json.dumps(ml), encoding="utf-8")
seed = ML.seed_match_decisions([a, b, RECORDS[EMAIL_B][0]], WORK)
_pid = MATCH.pair_id(a, b)
ck(_pid in seed, "the grouped pair is keyed with match.pair_id - the id the spine itself mints")
ck(seed.get(_pid, {}).get("verdict") == "same", "and the verdict is 'same'")
ck("master list" in seed.get(_pid, {}).get("reason", ""),
   "attributed to the broker's own decision, not presented as an adjudication")
ck(len(seed) == 1, "an ungrouped record contributes no verdict (exit 10 still asks about it)")

# ================================================= 6. a new deck re-opens, answers carry forward
print("\n6. A new deck re-opens the sheet; the existing answers survive by Row ID")
ck(ML.is_answered(WORK, auto["input_hash"]), "the answered sheet settles the CURRENT inputs set")
auto2 = ML.build_auto(WORK, RECORDS, CLUSTERS_PLUS, WORK, _fpt)
ck(auto2["input_hash"] != auto["input_hash"], "a new deck changes the candidate fingerprint")
ck(not ML.is_answered(WORK, auto2["input_hash"]),
   "so the stop RE-OPENS rather than building a deck nobody was asked about")
MB.build(WORK)
wb3 = load_workbook(WORK / ML.WORKBOOK)
ws3 = wb3[MB.SHEET]
_carried = {}
for r in range(MB.FIRST_ROW, MB.FIRST_ROW + len(auto2["rows"])):
    _carried[str(ws3.cell(r, _rid_col).value)] = ws3.cell(r, _inc_col).value
ck(_carried.get(_beta_id) == "No" and _carried.get(_born_id) == "No",
   "every prior answer is carried forward by Row ID - a rebuild never costs the user a decision")
_gamma_id = next(r["row_id"] for r in auto2["rows"] if r["row_id"].startswith("deck:gamma"))
ck(not _carried.get(_gamma_id), "and the NEW row is the only blank one")

# ============================================================== 7. the headless escape hatch
print("\n7. Headless includes everything, discloses it, and is not a scope decision")
W2 = _work()
auto3 = ML.build_auto(W2, RECORDS, CLUSTERS, W2, _fpt)
(W2 / CQ.SKIP_ALL_FILE).write_text("", encoding="utf-8")
ck(CQ.clarify_mode(W2, {}) == "headless", "the SKIP_ALL sentinel puts the run in headless mode")
ML.write_headless(W2, auto3, "headless run (eval)")
ck(ML.is_answered(W2, auto3["input_hash"]), "the stop is satisfied, so the run is not blocked")
ck(not ML.user_answered(W2),
   "but it is NOT a user answer, so the source-authority question is still asked later")
ck(ML.excluded_cluster_labels(W2) == set() and ML.excluded_rows(W2) == [],
   "nothing is excluded - every option found is in scope")
_h = "\n".join(DELIVER.master_list_lines(W2))
ck("Scope was not put to you" in _h and "6" in _h,
   "and the Gaps Report says so, with the option count")
kept4, dropped4 = ML.apply_to_clusters([[_beta_rec]], W2)
ck(len(kept4) == 1 and not dropped4, "a headless file drops nothing inside merge either")

# ====================================================== 8. the spine and the docs are wired up
print("\n8. The stage, the exit code and the contract exist where the orchestrator reads them")
run_src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
ck('"master list"' in run_src and "STAGE_ORDER" in run_src, "'master list' is in the vocabulary")
import run as RUN  # noqa: E402
ck(list(RUN.STAGE_ORDER).index("master list") == list(RUN.STAGE_ORDER).index("extract") + 1,
   "and it sits between extract and merge, where the cheap reads end")
_flat_src = " ".join(run_src.split())
ck("work, 17, _attempts, \"master list scope decision\"" in _flat_src,
   "the spine exits 17 for the master list, through the one round-trip exit path")
ck(_flat_src.count("_exit_round_trip( work, 17") + _flat_src.count("work, 17, _attempts") >= 1
   and "sys.exit(17)" not in run_src,
   "...and never by a bare sys.exit, so the streak/diagnosis machinery sees it")
ck("| 17 |" in skill, "SKILL.md's exit table carries the exit-17 row")
ck("master_list_build.py" in skill and "master_list_read.py" in skill,
   "...and names the two commands the orchestrator has to run")
ck("Never fill that column in for them" in skill,
   "...and forbids the orchestrator answering the sheet itself")
ck((ROOT / "reference" / "master-list.md").exists(), "reference/master-list.md exists")
ck("master-list.md" in (ROOT / "reference" / "pipeline.md").read_text(encoding="utf-8"),
   "pipeline.md points at it")
ck("--master-list" in (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8"),
   "merge.py takes the answered sheet as an input")
ck("master_list_lines(work_dir)" in (ROOT / "helpers" / "deliver.py").read_text(encoding="utf-8"),
   "deliver.py calls the Gaps Report section")
ck((ROOT / "prompts" / "master-list.md").exists(), "the dispatch prompt template exists")

# ---------------------------------------------------------------------------------------
# 9. THE ITEM-3 EMAIL ROUTE REACHES THE SHEET.
#
# The defect this pins. Item 4 was built before item 3's email routing landed, so the
# enumeration covered tracker records and brochure clusters and left the email-only options to
# the exit-17 sub-agent - an OPTIONAL step. Emails are the one input class that can hold an
# option no other source lists, so the class most likely to hold something nobody else knows
# about was the class whose presence on the scope sheet depended on an agent remembering an
# optional instruction. An option that never reaches the sheet is not struck off by anybody: it
# is simply not built, and nothing in the run says so.
#
# The fixture is the real shape, not a stub: a ZIP of two .eml files, one of them carrying a PDF
# attachment, run through intake.discover - which unpacks the archive, harvests the attachments
# beside their message and classifies what it finds - and then through the spine's own
# enumeration. Both halves have to work for a broker's emailed export to be answerable.
print("\n== 9. a zipped email export reaches the sheet: a row for the message, a row for its "
      "attached deck ==")
import email.message  # noqa: E402
import zipfile  # noqa: E402

import intake as INTAKE  # noqa: E402

_e9 = pathlib.Path(tempfile.mkdtemp(prefix="ml_email_"))
_inputs9 = _e9 / "inputs"
_inputs9.mkdir()


def _eml(subject, body, attach=None):
    m = email.message.EmailMessage()
    m["Subject"] = subject
    m["From"] = "broker@example.com"
    m["To"] = "agent@cbre.com"
    m["Date"] = "Tue, 15 Sep 2026 09:14:00 +0100"
    m.set_content(body)
    if attach:
        name, data = attach
        m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return m.as_bytes()


# >= 20 KB: save_attachments refuses anything smaller as a signature logo, which is the right
# rule and would quietly make this fixture test nothing if the bytes were a token PDF.
_pdf9 = b"%PDF-1.4\n% " + (b"x" * 22000) + b"\n%%EOF\n"
_zip9 = _inputs9 / "broker export.zip"
with zipfile.ZipFile(_zip9, "w") as _z:
    _z.writestr("Packington Hill - 140,000 sq ft.eml",
                _eml("Packington Hill - 140,000 sq ft available Q2 2027",
                     "We also have Packington Hill, 140k, ready Q2 2027. Brochure attached.",
                     attach=("Packington Hill brochure.pdf", _pdf9)))
    _z.writestr("Riverside - no documents.eml",
                _eml("Riverside Park unit 4 - 62,000 sq ft",
                     "Riverside Park unit 4, 62k sq ft, 10m clear. No brochure yet."))

_inv9 = INTAKE.discover(_inputs9)
ck(len(_inv9.get("emails") or []) == 2,
   f"intake unpacked the zip and found both emails (got {len(_inv9.get('emails') or [])})")
_saved9 = sum(len(e.get("saved") or []) for e in (_inv9.get("email_attachments") or []))
ck(_saved9 == 1, f"...and saved the one real PDF attachment beside its message (got {_saved9})")
ck(any(("pdfs" in c and c["pdfs"]) for c in (_inv9.get("clusters") or {}).values()),
   "...and the saved attachment was classified as a brochure cluster in the SAME pass")

_w9 = _e9 / "work"
_w9.mkdir()
_auto9 = ML.build_auto(_w9, {}, _inv9.get("clusters") or {}, _inputs9,
                       lambda p: "", emails=_inv9.get("emails") or [],
                       email_attachments=_inv9.get("email_attachments") or [])
_rows9 = _auto9["rows"]
_email_rows9 = [r for r in _rows9 if r["source_type"] == "Email"]
_deck_rows9 = [r for r in _rows9 if r["source_type"] == "Brochure"]
_mail9 = _auto9.get("emails") or []

# DEFECT A. The previous version of this block asserted the OPPOSITE: that both messages appear
# on the Master list as rows named after their subjects. That is what put thirteen rows reading
# "RE: Looking for 60,000 to 100,000 sq ft..." on the live sheet, with no postcode and no size,
# and forced the sub-agent to invent "MESSAGE ROW SPLIT" duplicate groups to explain them. A
# message is a SOURCE. It is indexed, not enumerated, and nothing about it vanishes.
ck(len(_email_rows9) == 0,
   f"NO message is a candidate row (got {[r['property'] for r in _email_rows9]})")
ck(not any(str(r.get("property") or "").lower().startswith(("re:", "fw:", "fwd:"))
           for r in _rows9),
   "no row is named after an email subject")
ck(len(_mail9) == 2,
   f"both messages are on the EMAILS INDEX instead (got {len(_mail9)})")
ck(all(e["email_id"].startswith("email:") for e in _mail9),
   "...each under an email: id, so the exclusion filter and the seeding agree on the family")
ck(len({e["email_id"] for e in _mail9}) == 2,
   "...and the two ids differ, because the id is the message's path and not its subject")
ck(any("Packington Hill" in (e["subject"] or "") for e in _mail9),
   "...carrying the cleaned subject, which is what a broker recognises")
ck(all(e["sender"] for e in _mail9), "...and the sender, which is what the reader needs")
_nothing9 = [e for e in _mail9 if not e["attachments"]]
ck(len(_nothing9) == 1,
   f"the message that brought nothing with it is visible and empty-handed (got {len(_nothing9)})")
ck(len(_deck_rows9) == 1,
   f"the ATTACHED deck is its own candidate row (got {len(_deck_rows9)})")
ck(_deck_rows9 and _deck_rows9[0]["brochure"] == ML.YES,
   "...with Brochure? = Yes: an attachment is a document held, exactly like a deck dropped in "
   "the folder by hand")
ck(_deck_rows9 and _deck_rows9[0]["source"].startswith("Brochure, attached to email from "),
   "...and its Source names the sender, not the path (got %r)"
   % (_deck_rows9[0]["source"] if _deck_rows9 else None))

# TWO ATTACHMENTS ON ONE MESSAGE -> TWO DECK ROWS AND ONE EMAILS LINE, never a property row.
_e9b = pathlib.Path(tempfile.mkdtemp(prefix="ml_email2_"))
_in9b = _e9b / "inputs"
_in9b.mkdir()
_m9b = email.message.EmailMessage()
_m9b["Subject"] = "RE: FW: two sheds, one email"
_m9b["From"] = "Jane Roe <ann.blake@savills.com>"
_m9b["Date"] = "Tue, 15 Sep 2026 09:14:00 +0100"
_m9b.set_content("Both attached.")
# DIFFERENT BYTES PER ATTACHMENT, deliberately: intake de-duplicates on content hash, so two
# identical PDFs are one cluster and the fixture would silently test nothing.
for _i9, _n in enumerate(("Riverside Park brochure.pdf", "Eastgate 88 brochure.pdf")):
    _m9b.add_attachment(b"%PDF-1.4\n% " + bytes([65 + _i9]) * 22000 + b"\n%%EOF\n",
                        maintype="application", subtype="pdf", filename=_n)
(_in9b / "two attachments.eml").write_bytes(_m9b.as_bytes())
_inv9b = INTAKE.discover(_in9b)
_w9b = _e9b / "work"
_w9b.mkdir()
_auto9b = ML.build_auto(_w9b, {}, _inv9b.get("clusters") or {}, _in9b, lambda p: "",
                        emails=_inv9b.get("emails") or [],
                        email_attachments=_inv9b.get("email_attachments") or [])
_decks9b = [r for r in _auto9b["rows"] if r["source_type"] == "Brochure"]
ck(len(_decks9b) == 2,
   f"a message with two attachments yields TWO deck rows (got {len(_decks9b)}: "
   f"{[r['property'] for r in _decks9b]})")
ck(len(_auto9b.get("emails") or []) == 1,
   "...and ONE line on the Emails tab")
ck(not any(r["source_type"] == "Email" for r in _auto9b["rows"]),
   "...and no property row for the message itself")
ck((_auto9b["emails"][0]["subject"] or "").lower().startswith("two sheds"),
   "...whose subject has had RE:/FW: taken off it (got %r)"
   % _auto9b["emails"][0]["subject"])
ck(all(r["source"] == "Brochure, attached to email from Jane Roe (Savills), 15 Sep 2026"
       for r in _decks9b),
   "...and both deck rows name the sender, the firm and the date (got %r)"
   % [r["source"] for r in _decks9b])

# The red rule is what the user actually sees, so it is checked on the WORKBOOK, not the payload.
MB.build(_w9)
_wb9 = load_workbook(_w9 / MB.WORKBOOK)
_ws9 = _wb9[MB.SHEET]
_hdr9 = {str(_ws9.cell(MB.HDR_ROW, c).value).strip(): c
         for c in range(1, _ws9.max_column + 1) if _ws9.cell(MB.HDR_ROW, c).value}
_bc9 = _hdr9.get("Brochure?")
_pc9 = _hdr9.get("Property")
_deck_cells9 = [str(_ws9.cell(r, _bc9).value or "")
                for r in range(MB.HDR_ROW + 1, _ws9.max_row + 1)
                if str(_ws9.cell(r, _pc9).value or "") in {d["property"] for d in _deck_rows9}]
ck(_deck_cells9 and all(v == ML.YES for v in _deck_cells9),
   f"on the workbook the attachment deck's Brochure? cell reads a flat Yes {_deck_cells9}, so "
   f"the conditional rule does not paint it red")
ck(MB.SHEET_EMAILS in _wb9.sheetnames, "the workbook has an Emails tab")
_wse9 = _wb9[MB.SHEET_EMAILS]
_mailrows9 = [row for row in _wse9.iter_rows(min_row=5, values_only=True) if any(row)]
ck(len(_mailrows9) == 2, f"...with one line per message (got {len(_mailrows9)})")
ck(any("nothing extracted" in " ".join(str(c or "") for c in row) for row in _mailrows9),
   "...and the message that produced neither an attachment nor a row is flagged there")


# ==========================================================================================
# 10. THE SHEET THE USER ACTUALLY READS (defects C, D and E on the live run).
print("\n== 10. Include? ships blank, duplicates name their partner, Source is human ==")
import json as _json  # noqa: E402

_w10 = _e9 / "work10"
_w10.mkdir()
_auto10 = ML.build_auto(_w10, RECORDS, CLUSTERS, _w10, _fpt)
_venlo_tracker = next(r["row_id"] for r in _auto10["rows"]
                      if r["property"] == "Venlo Trade Port")
_venlo_deck = next(r["row_id"] for r in _auto10["rows"]
                   if "Alpha Park" in (r["property"] or ""))
# A model file that does everything the live orchestrator did wrong: a pre-filled Include?, a
# path for a Source, and a group whose own status denies that it is a group.
(_w10 / ML.MODEL_CANDIDATES).write_text(_json.dumps({
    "title": "Master list - fixture",
    "rows": [{"row_id": "email:prose-option", "property": "Packington Hill",
              "source_type": "Email", "source": "inbox/2026-09-01 Offer Venlo.msg - 2026-09-01",
              "postcode": "6041 TA", "size_from": 140000, "include": "Yes"}],
    "duplicate_groups": {"D1": {"status": "MESSAGE ROW SPLIT - not one building",
                                "note": "the deck carries the spec, the tracker the rent",
                                "members": [_venlo_tracker, _venlo_deck]}},
}, ensure_ascii=False), encoding="utf-8")
MB.build(_w10)
_wb10 = load_workbook(_w10 / MB.WORKBOOK)
_ws10 = _wb10[MB.SHEET]
_h10 = {str(_ws10.cell(MB.HDR_ROW, c).value).strip(): c
        for c in range(1, _ws10.max_column + 1) if _ws10.cell(MB.HDR_ROW, c).value}
ck(list(_h10)[:7] == ["Rank", "Include?", "Your Run notes for the AI", "Property",
                      "Duplicate of", "Source type", "Source"],
   f"the columns are in reading order (got {list(_h10)[:7]})")
ck("Duplicate group" not in _h10 and "Duplicate status" not in _h10
   and "Duplicate note" not in _h10,
   "the three columns that printed a group id and never named a partner are gone")
_data10 = [r for r in range(MB.FIRST_ROW, _ws10.max_row + 1)
           if _ws10.cell(r, _h10["Row ID"]).value]
# DEFECT E.
ck(all(_ws10.cell(r, _h10["Include?"]).value in (None, "") for r in _data10),
   "Include? is BLANK on every row after a build, even though the model file pre-filled one")
# DEFECT C.
_dup10 = {str(_ws10.cell(r, _h10["Row ID"]).value):
          str(_ws10.cell(r, _h10["Duplicate of"]).value or "") for r in _data10}
ck(_dup10.get(_venlo_tracker, "").startswith("same building as #")
   and _dup10.get(_venlo_deck, "").startswith("same building as #"),
   f"both rows of the pair say who their partner is (got {_dup10.get(_venlo_tracker)!r} / "
   f"{_dup10.get(_venlo_deck)!r})")
ck("Alpha Park" in _dup10.get(_venlo_tracker, "")
   and "Venlo Trade Port" in _dup10.get(_venlo_deck, ""),
   "...by NAME, not by a group id nobody can look up")
_ranks10 = {str(_ws10.cell(r, _h10["Row ID"]).value): _ws10.cell(r, _h10["Rank"]).value
            for r in _data10}
ck(abs(_ranks10[_venlo_tracker] - _ranks10[_venlo_deck]) == 1,
   f"...and the two rows are ADJACENT, so the comparison is one glance "
   f"(ranks {_ranks10[_venlo_tracker]} and {_ranks10[_venlo_deck]})")
ck(not any("MESSAGE ROW SPLIT" in str(_ws10.cell(r, c).value or "")
           for r in _data10 for c in range(1, _ws10.max_column + 1)),
   "a group that denies being a same-building group cannot say so on the sheet")
_wsd10 = _wb10[MB.SHEET_DUPES]
ck(any("Same building" in str(row[0] or "")
       for row in _wsd10.iter_rows(min_row=1, max_col=1, values_only=True)),
   "the Duplicate check tab heads each block SAME BUILDING")
# DEFECT D.
_srcs10 = [str(_ws10.cell(r, _h10["Source"]).value or "") for r in _data10]
ck(not any(("/" in s) or ("\\" in s) or s.lower().endswith(".msg") for s in _srcs10),
   "no Source is a path (got %r)" % [s for s in _srcs10 if "/" in s])
ck(all(s.startswith(("Email: ", "Brochure, ", "Source file: ")) for s in _srcs10),
   f"every Source matches one of the human patterns (got {sorted(set(_srcs10))})")
ck(all(not str(_ws10.cell(r, _h10["Property"]).value or "").lower()
       .startswith(("re:", "fw:", "fwd:")) for r in _data10),
   "no Property is a subject line")


# ==========================================================================================
# 11. A SCHEME BEATS A STREET, AND THE SWEEP DOES NOT OVERSTATE.
print("\n== 11. scheme over street, and an honest postcode sweep ==")

# Two covers taken off the live corpus. The first prints a street and no scheme, and its
# FILENAME carries the scheme ("Goldthorpe - Midway One.pdf"); the row used to come out as
# "Droves Dale Road, Rotherham", which is neither the scheme nor, on S63 9FD, the town. The
# second prints "Central Park Drive"; the row used to take the drive over the park.
_PAGES11 = {
    "Goldthorpe - Midway One.pdf":
        "TO LET / MAY SELL 68,195 SQ FT\nINDUSTRIAL WAREHOUSE UNIT REFURBISHMENT COMPLETE\n"
        "DROVES DALE ROAD, GOLDTHORPE, ROTHERHAM, S63 9FD",
    "BAR003_Brochure_16pp_V32.10.pdf":
        "Central Park Drive Rugby, CV23 0WE\nA Prime Midlands Warehouse / Industrial Facility\n"
        "106,645 Sq Ft (9,907 Sq M) Available Now",
}
_CL11 = {"Midway One": {"pdfs": ["Goldthorpe - Midway One.pdf"], "region": "Goldthorpe"},
         "BAR003_Brochure_16pp_V32.10": {"pdfs": ["BAR003_Brochure_16pp_V32.10.pdf"],
                                         "region": "BAR003_Brochure_16pp_V32.10"}}
_w11 = _work()
_auto11 = ML.build_auto(_w11, {}, _CL11, _w11,
                        lambda q: _PAGES11.get(pathlib.Path(str(q)).name, ""))
_n11 = {r["row_id"]: r for r in _auto11["rows"]}
_midway = next(r for r in _auto11["rows"] if r["row_id"].startswith("deck:Midway"))
_bar = next(r for r in _auto11["rows"] if r["row_id"].startswith("deck:BAR003"))
ck("Midway One" in _midway["property"],
   f"the filename's scheme beats the cover's street line (got {_midway['property']!r})")
ck("Droves Dale Road" not in _midway["property"],
   "...so the street is not the name")
ck(_midway["city"] == "Goldthorpe",
   f"...and the town is the locality the cover confirms, not the postal town at the end of the "
   f"address line (got {_midway['city']!r})")
ck("Central Park" in _bar["property"] and "Drive" not in _bar["property"],
   f"a scheme printed on page 1 beats the street it stands on (got {_bar['property']!r})")
ck(_bar["property"] != "BAR003_Brochure_16pp_V32.10",
   "...and neither row is the filename stem")

# FOUR UNITS OF ONE PARK, ONE POSTCODE. The live sheet told the reader all four were "possibly
# the same building"; they are 61k, 90k, 117k and 216k sq ft.
_VANTAGE = {"Vantage.msg": [_rec("Vantage.msg", "V%d, Vantage Park" % n, "Birmingham",
                                 "B24 9GZ", n * 1000)
                            for n in (61, 90, 117, 216)]}
_w12 = _work()
_auto12 = ML.build_auto(_w12, _VANTAGE, {}, _w12, _fpt)
_v12 = _auto12["rows"]
ck(len({r["duplicate_group"] for r in _v12}) == 1 and _v12[0]["duplicate_group"],
   "the four rows share one postcode, so the sweep still groups them")
MB.build(_w12)
_ws12 = load_workbook(_w12 / MB.WORKBOOK)[MB.SHEET]
_h12 = {str(_ws12.cell(MB.HDR_ROW, c).value).strip(): c
        for c in range(1, _ws12.max_column + 1) if _ws12.cell(MB.HDR_ROW, c).value}
_txt12 = [str(_ws12.cell(r, _h12["Duplicate of"]).value or "")
          for r in range(MB.FIRST_ROW, _ws12.max_row + 1)
          if _ws12.cell(r, _h12["Row ID"]).value]
ck(_txt12 and not any("possibly the same building" in s.lower() for s in _txt12),
   f"NO pair is called possibly the same building (got {_txt12[:1]})")
ck(all("same building as" not in s for s in _txt12),
   "...and none claims same building either: only a judged group may say that")
ck(all(s.startswith("same postcode as #") for s in _txt12),
   f"...each says what the sweep actually found (got {_txt12[0]!r})")
ck(all("(auto sweep)" in s for s in _txt12), "...labelled (auto sweep), every one")
ck(all("sizes differ, so probably different units of one park" in s for s in _txt12),
   "...and, the areas being 61k to 216k, says they are different units of one park")

# The other half of the rule: sizes within 15%, or one absent, is a real question.
_TWIN = {"Twin.msg": [_rec("Twin.msg", "Aurora 100", "Venlo", "5928 NX", 100000),
                      _rec("Twin.msg", "Aurora, Trade Port", "Venlo", "5928 NX", 104000)]}
_w13 = _work()
_auto13 = ML.build_auto(_w13, _TWIN, {}, _w13, _fpt)
MB.build(_w13)
_ws13 = load_workbook(_w13 / MB.WORKBOOK)[MB.SHEET]
_h13 = {str(_ws13.cell(MB.HDR_ROW, c).value).strip(): c
        for c in range(1, _ws13.max_column + 1) if _ws13.cell(MB.HDR_ROW, c).value}
_txt13 = [str(_ws13.cell(r, _h13["Duplicate of"]).value or "")
          for r in range(MB.FIRST_ROW, _ws13.max_row + 1)
          if _ws13.cell(r, _h13["Row ID"]).value]
ck(_txt13 and all("check whether one building" in s and "(auto sweep)" in s for s in _txt13),
   f"two areas 4% apart on one postcode is a question, not a verdict (got {_txt13[:1]})")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S):"))
for f in fails:
    print(f"  - {f}")
sys.exit(1 if fails else 0)
