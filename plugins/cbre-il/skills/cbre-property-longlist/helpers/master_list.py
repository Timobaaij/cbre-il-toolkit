#!/usr/bin/env python3
"""master_list.py - the spine side of the MASTER LIST: enumerate every candidate option the
run has found so far, key each one durably, and read the user's answer back for the four
places that obey it.

WHY THIS STAGE EXISTS AT ALL
----------------------------
On the Kapdaa run the broker learned what the run had decided to build by reading the FINISHED
dashboard. Everything before that point decided scope on its own: the tracker contributed one
row per line whether or not the line was a live option, a brochure that happened to be in the
folder became a card, an option named only in an email body reached the deliverable only if a
later agent happened to write a record for it, and the one question that asks a human which
source governs the longlist - the exit-13 source-authority question - is asked AFTER matching
and merging have settled, which is after every brochure has already been read by its own vision
agent. That ordering has two costs and they are different costs:

  * MONEY AND TIME. One reader agent per deck, vision on the raster ones, is the most expensive
    step in the pipeline, and it ran on decks the broker would have struck off in two seconds.
  * TRUST. By the time the authority question arrives, the run has already formed an opinion
    about what exists, and the question is phrased in terms of that opinion ("these 14 are only
    in the brochures"). A broker answering it is editing the run's conclusion rather than
    setting the run's scope.

So the inventory is put in front of the user FIRST, in one sheet, and only the rows they mark
Yes are built. The sheet is the single source of truth for scope from that point on.

WHERE IT SITS, AND WHY NOT SOMEWHERE CHEAPER
--------------------------------------------
After the cheap reads (tracker rows, email bodies), before the deck readers. Earlier is
cheaper and useless: before anything is read the run knows filenames and nothing else, and a
sheet of filenames is not a decision a broker can take. Later is cleaner and too late: after
match and merge every brochure has already been read, which is precisely the cost this exists
to avoid paying on rows nobody wanted.

The price of the middle position is that option identity is NOT final when the sheet is built:
two rows on it can be one building. That is why the sheet carries duplicate groups (the model's
adjudication, with a blunt postcode sweep behind it) rather than pretending the rows are
distinct, and why the user's groups are written back into work/match_decisions.json as `same`
verdicts instead of being thrown away - the pairs the user already grouped are not asked again
at exit 10.

WHAT LIVES HERE AND WHAT LIVES IN THE TWO PORTED SCRIPTS
--------------------------------------------------------
This module is the SPINE's half: it enumerates candidate rows from the records already on disk
plus the brochure clusters intake found, keys them, runs the postcode sweep, and reads the
answered sheet back for the four consumers (deck dispatch, source authority, match seeding, the
Gaps Report). `master_list_build.py` turns the candidates into the workbook and
`master_list_read.py` turns the answered workbook into work/master_list.json; both are ported
from kato-longlist, which has run this pattern in anger, and both are standalone CLIs because
the user's answer arrives between them.

ROW IDENTITY IS THE WHOLE CONTRACT. Every answer is keyed on a Row ID that must survive a
re-run, a re-sort of the sheet and a second email export. A tracker row is keyed on its source
file plus the sheet!cell locator the extractor already recorded in `__meta.prov`; an email row
the same way on its message; a brochure row on its cluster's file set. None of those depend on
position in a list, so a user who sorts the sheet by size loses nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

AUTO_CANDIDATES = "master_candidates_auto.json"   # written by the spine
MODEL_CANDIDATES = "master_candidates.json"       # written by the orchestrator (judgement)
WORKBOOK = "Master List.xlsx"
MANIFEST = "master_list_manifest.json"
ANSWERS = "master_list.json"                      # written by master_list_read.py
EXTERNAL = "master_list_external.json"            # the disclosure a wrapper-owned scope leaves

# ------------------------------------------------------------------ scope owned upstream

def external_scope(cfg: dict | None) -> dict | None:
    """`master_list: {mode: external, confirmed_by: "..."}` from project.yaml, or None.

    WHAT IT IS FOR. A wrapper skill can already own the scope decision. kato-longlist does: it
    builds its OWN master list at its step 2.5, puts that workbook to the operator, reads it back,
    and only then generates this skill's project.yaml and inputs folder from the rows that
    survived. The spine's exit-17 stop would then put a SECOND sheet in front of the same person,
    listing the same options they had just finished striking off, with no new information on it.
    A gate that asks a question the user has visibly already answered does not get answered
    carefully the second time; it gets answered "Yes to everything" for the rest of its life, and
    then it protects nothing on the run where it mattered.

    WHAT IT DELIBERATELY DOES NOT DO. It declines the stop and NOTHING else. It is not an answer,
    so `master_list.json` is not written and none of the four consumers can read one: the source
    authority is not derived from it (the exit-13 question is asked exactly as it was before this
    stage existed), no `same` verdicts are seeded into `match_decisions.json`, and no deck is
    skipped. The run is byte-identical to the pre-master-list spine apart from one line in the
    Gaps Report saying where scope was settled. Anything more would mean a wrapper's config key
    silently suppressing a question this skill asks on its own evidence.

    ABSENT MEANS INTERACTIVE. A missing key, an unparseable one, a misspelt mode - all of them
    leave the stop in place. The failure of a scope gate must be that it fires when it need not,
    never that a typo in a config file turns it off.
    """
    ml = (cfg or {}).get("master_list")
    if not isinstance(ml, dict):
        return None
    if str(ml.get("mode") or "").strip().lower() != "external":
        return None
    by = str(ml.get("confirmed_by") or "").strip()
    return {"mode": "external",
            "confirmed_by": by or "(not stated in project.yaml master_list.confirmed_by)"}


def write_external(work: Path, scope: dict, n_candidates=None) -> dict:
    """Record the declined stop under its OWN filename, never as an answer.

    A separate file rather than a flag inside `master_list.json` because the four consumers all
    read `master_list.json` and one of them - the source authority - acts on its mere presence.
    A shared file would need every one of them to remember to check a mode field, and the first
    one that forgot would hand a wrapper's config key the power to delete options from a client's
    longlist. There is nothing to remember if the file they read does not exist.
    """
    payload = {"mode": "external", "confirmed_by": str(scope.get("confirmed_by") or ""),
               "candidates_seen": n_candidates}
    Path(work, EXTERNAL).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return payload


YES, NO = "Yes", "No"

# Source-file suffixes that make a record an EMAIL record rather than a tracker row. Kept here
# rather than imported from clarify.AUTHORITY_FAMILIES because that mapping deliberately has no
# email family (an email may never EXCLUDE anything under the authority answer), while this one
# has to label an email row on the sheet so the user can see where the option came from.
EMAIL_EXTS = (".msg", ".eml")
TRACKER_EXTS = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")
DECK_EXTS = (".pdf", ".pptx", ".ppt")


# --------------------------------------------------------------------------- small helpers

def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def norm_postcode(v) -> str:
    """Whitespace- and case-insensitive postcode key for the blunt sweep.

    Deliberately NOT a country-aware parser. The sweep's whole job is to be cruder than the
    model's adjudication and catch what the model missed, and a parser that rejected 'DE74 2DF'
    because it is not the Dutch shape would silently stop catching duplicates on exactly the
    corpora this skill is used on. An empty string is never a key: a blank postcode is absence
    of evidence and grouping on it would put every unlocated row in one meaningless group.
    """
    s = re.sub(r"[^A-Za-z0-9]+", "", str(v or "")).upper()
    return s if len(s) >= 4 else ""


def _locator(rec: dict) -> str:
    """The first provenance locator the record carries ('Sheet1!B14', 'p3', ...), or ''.

    This is the record's own statement of WHERE it came from inside its file, written by the
    extractor, so it is stable across re-extractions of an unchanged file. It is what makes a
    tracker row's id survive a re-run: the alternative, the record's index in the parsed list,
    moves the moment a row is inserted above it, which would silently re-ask the user about
    every row below the insertion.
    """
    prov = ((rec.get("__meta") or {}).get("prov") or {})
    if isinstance(prov, dict):
        for v in prov.values():
            tok = str(v or "").split()[0].strip() if str(v or "").strip() else ""
            if "!" in tok or re.match(r"^p\d+$", tok):
                return tok
    return ""


def source_file(rec: dict) -> str:
    return str((rec.get("__meta") or {}).get("source_file") or "")


def record_row_id(rec: dict) -> str:
    """The Row ID for a tracker or email record: `<family>:<source file>|<locator or digest>`.

    NOT POSITIONAL, and that is load-bearing rather than tidy. The id is computed in two places
    that see the records in DIFFERENT orders - the candidate enumeration walks one record file at
    a time, while the match seeding and the exclusion filter walk every record in the run
    concatenated - so an id containing a list index would agree in one of them and silently
    disagree in the other. The failure that produces is the worst kind available here: the sheet
    would look answered, the ids would not resolve, and the user's No would quietly do nothing.

    A record's own provenance locator ('Sheet1!B14') is the first choice, because the extractor
    writes it and it survives a re-extraction of an unchanged file. A record with no locator
    falls back to a digest of its own values, which is order-independent for the same reason and
    changes only when the record itself changes - and a changed record set re-opens the sheet
    anyway, with every still-matching answer carried forward by Row ID.
    """
    src = Path(source_file(rec)).name
    # `source_type` is consulted as well as the extension because an EMAIL record does not carry
    # a filename in `source_file`: extract_email stamps the SUBJECT there ("RE: Packington Hill"),
    # which ends in none of EMAIL_EXTS. Keying on the extension alone therefore filed every email
    # record under the tracker family, and the row on the sheet said "Source file" where the user
    # needed to read "Email" before deciding whether a one-line mention in prose is a real option.
    meta_type = str((rec.get("__meta") or {}).get("source_type") or "").strip().lower()
    fam = "email" if (src.lower().endswith(EMAIL_EXTS) or meta_type == "email") else "row"
    loc = _locator(rec)
    if not loc:
        payload = json.dumps({k: v for k, v in sorted(rec.items()) if k != "__meta"},
                             ensure_ascii=False, default=str)
        loc = "h" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{fam}:{src}|{loc}"


def email_row_id(rel_path) -> str:
    """The Row ID for one EMAIL MESSAGE: `email:<basename>|<digest of its path in the folder>`.

    Keyed on the message's path inside the inputs folder rather than on its subject or its
    position. Two brokers send "RE: your requirement" on the same morning and the subjects
    collide; the per-email folder keeps the files apart, so the path is the only thing here that
    separates them - the same reasoning that re-keyed `extract_email.from_email_index` on the
    relative path in item 3, and the same failure if it is ignored: two messages sharing one row,
    one broker's No silently striking the other broker's option.
    """
    rel = Path(str(rel_path)).as_posix().lower()
    h = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"email:{Path(rel).name}|{h}"


def cluster_row_id(label: str, files) -> str:
    """The Row ID for one brochure cluster: its label plus a digest of its file set.

    The digest is in the id on purpose. A cluster is the unit the deck reader is dispatched on,
    so if a second brochure joins the cluster the thing the user said Yes to is not the thing
    the run would now read, and the row must be re-offered rather than inherit an answer given
    about a different document set.
    """
    names = sorted(Path(str(f)).name for f in (files or []))
    h = hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(label or "deck")).strip("_")[:40] or "deck"
    return f"deck:{slug}|{h}"


def _num(v):
    if v in (None, "", "tbd"):
        return None
    try:
        return float(str(v).replace(",", "").replace(" ", ""))
    except Exception:
        return None


# --------------------------------------------------- naming a row after the thing, not the file
#
# THE DEFECT THIS BLOCK EXISTS FOR (live run "Test Run Brochures Only", exit 17). Every one of
# the 23 deck rows on that sheet was named after its FILE and had the same filename repeated in
# Town / city: "Brochure Final" (it is Rotherham 125), "New Logo" (Park Farm Road, Scunthorpe),
# "Savills GV 2026" (Valley Road, Barnsley), "BAR003_Brochure_16pp_V32.10",
# "20260414-Total-Park-Telford-Brochure_v06". A filename is what the sender's marketing team
# called a PDF. It is not the building, and a scope sheet whose Property column is a list of
# document names cannot be answered: the reader cannot tell which shed they are striking off.
#
# So the name is derived from the DOCUMENT first and the filename only as a marked fallback.
# Everything below is deterministic and cheap - it reads the first page's text layer, which the
# enumeration already reads for the postcode and the size, and nothing more.

_STOPWORDS = {"the", "a", "an", "of", "and", "at", "in", "on", "to", "for", "unit's"}

# Tokens that say "this filename is a DOCUMENT name, not a property name". Every one of these was
# taken off the live corpus: "- Brochure Final", "- New Logo", "Savills GV 2026", "16pp", "V32.10",
# "_v06", "13pp Bro V6", "Site layouts for PPH 021025", "Brochure January 2026".
_DOC_NOISE = re.compile(
    r"^(?:brochure|brochures|bro|flyer|flyers|particulars|final|draft|copy|logo|new|version|"
    r"ver|marketing|pack|deck|scan|scanned|untitled|document|doc|email|mail|site|sites|layout|"
    r"layouts|gv|a4|a3|pdf|pptx|ppt|jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    r"jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)$",
    re.IGNORECASE)
# version / date / page-count tokens: v06, V32.10, 16pp, 13pp, 20260414, 021025, 2026
_VERSION_TOKEN = re.compile(r"^(?:v\d[\d.]*|\d+pp|\d{4}|\d{6}|\d{8})$", re.IGNORECASE)

# A county or region is not a town. Stripped off the tail of an address segment before the town
# is taken, so "Scunthorpe North Lincolnshire" is Scunthorpe and "Gateshead Tyne & Wear" is
# Gateshead, rather than a county in the Town / city column.
_COUNTIES = [
    "north lincolnshire", "lincolnshire", "leicestershire", "staffordshire", "shropshire",
    "tyne & wear", "tyne and wear", "greater manchester", "south yorkshire", "west yorkshire",
    "north yorkshire", "east yorkshire", "west midlands", "east midlands", "west yorks",
    "northamptonshire", "derbyshire", "nottinghamshire", "warwickshire", "worcestershire",
    "hertfordshire", "bedfordshire", "cambridgeshire", "oxfordshire", "cheshire", "lancashire",
    "county durham", "merseyside", "united kingdom", "england", "uk",
]

# What a scheme or a street is CALLED. Deliberately short: a keyword list that reaches for
# everything starts matching prose ("the park and ride"), and a name invented out of prose is
# worse on this sheet than a blank the user can see.
#
# A SCHEME IS NOT A STREET, and the sheet must not offer one when it means the other. The live
# Midway One deck prints "DROVES DALE ROAD, GOLDTHORPE" on its cover and the row came out called
# "Droves Dale Road"; the Rugby deck prints "Central Park Drive" and the row took the drive
# rather than the park. A reader looking for Midway One at Central Park cannot find either. So
# the two keyword sets are separate and the scheme is always tried first.
_SCHEME_KW = r"PARK|POINT|GATEWAY|LINK|CAMPUS|CROSS|ESTATE|QUARTER|HUB|CENTRE|CENTER"
_STREET_KW = r"APPROACH|ROAD|STREET|WAY|DRIVE|LANE|AVENUE|CLOSE|CRESCENT"


def _place_rx(kw: str):
    return re.compile(r"\b((?:[A-Z][A-Za-z0-9'&‐-]*\s+){1,3}(?:%s))\b"
                      % "|".join(k + "|" + k.capitalize() for k in kw.split("|")))


_SCHEME_RX = _place_rx(_SCHEME_KW)
_STREET_RX = _place_rx(_STREET_KW)
# The negative lookahead is not decoration. "UNIT 121,832 SQ FT" is a FLOOR AREA, and without it
# the live Stafford Park 7 row came out as "Unit 121, Stafford Park 7" - a unit number invented
# out of a size, on the one sheet whose whole job is to be trustworthy about what a row is.
_UNIT_RX = re.compile(r"\b(?:UNIT|PLOT)\s+([0-9]{1,3}[A-Za-z]?)(?![\d,.·])",
                      re.IGNORECASE)
_PC_RX = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|\d{4}\s?[A-Z]{2}|\d{5})\b")

_ARROWS = "→←⇒⇐➡"


def clean_subject(subject) -> str:
    """An email subject with the reply/forward scaffolding and the arrows taken off.

    The live sheet showed "RE: →  Looking for 60,000 to 100,000 sq ft of Industrial/Log..."
    as a PROPERTY name. A subject is never a property name here, but it is still the only human
    handle on a message, so the Emails tab shows it - cleaned, because "RE: RE: FW:" and a
    tracking arrow are the mail client's noise, not the broker's words.
    """
    s = str(subject or "").strip()
    for ch in _ARROWS:
        s = s.replace(ch, " ")
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^\s*(?:re|fw|fwd|aw|tr|antw|vs)\s*[:\-]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"^\s*\[(?:external|extern|ext)\]\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _title(s: str) -> str:
    """Title-case a SHOUTED cover line, leave a line that already has case alone.

    Brochure covers are set in caps ("JUNCTION 1 / M18, ROTHERHAM"); dropping that straight into
    the Property column makes the sheet read like a fire alarm. A string that already carries
    lower-case letters is left exactly as the document wrote it - "iP2C iPort" and
    "SmartParc SEGRO" are how those schemes are spelt and re-casing them would be an error.
    """
    # U+2010 / U+2011 are the typographic hyphens a designer set the cover line in: the live
    # Flagstaff 42 deck prints "Ashby-De-La-Zouch" with them. They look like a hyphen, they do
    # not compare like one, and a town that will not match itself is a town nobody can filter on.
    s = re.sub(r"[‐‑]", "-", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-")
    if not s or any(c.islower() for c in s):
        return s
    out = []
    for w in s.split(" "):
        out.append(w if (len(w) <= 3 and w.isalpha() and w.isupper() and len(w) > 1
                         and w in ("M18", "A1M")) else
                   ("-".join(p.capitalize() if p.isalpha() else p for p in w.split("-"))
                    if w.isalpha() or "-" in w else w))
    return " ".join(out)


def _haystacks(text: str) -> tuple:
    """(word-separated lowercase text, alnum-only lowercase text) for confirming a name.

    The second one is not redundant. Brochure covers letter-space their titles
    ("S M A R T PA R C  S E G R O", "L E T C H W O R T H", "UNI T 1 WOR K S O P LI NK"), so the
    word "worksop" genuinely is not in that page's word list while the page is plainly about
    Worksop Link. Collapsing to alnum lets a token of four characters or more be confirmed by
    substring; shorter tokens still need a real word match, because "one" would otherwise be
    confirmed by "stone".
    """
    low = str(text or "").lower()
    words = re.sub(r"[^a-z0-9]+", " ", low)
    return " " + words.strip() + " ", re.sub(r"[^a-z0-9]+", "", low)


def _confirmed(tokens, hay) -> int:
    words, flat = hay
    n = 0
    for t in tokens:
        if (" %s " % t) in words or (len(t) >= 4 and t in flat):
            n += 1
    return n


def split_run_together(s: str) -> str:
    """"MPC2" -> "MPC 2", "LutterworthMAGNA" -> "Lutterworth MAGNA", "Unit1" -> "Unit 1".

    Conservatively. The first cut split every boundary and turned "iP2C iPort" into the tokens
    i / p / 2 / c, none of which the document confirms, so a perfectly good scheme name failed
    its own confirmation test and the row fell back to the filename. The second cut split
    "SmartParc" into "Smart Parc" and misspelt a brand on the sheet. So a letter-to-letter
    boundary only splits when the right-hand side SHOUTS ("LutterworthMAGNA"), which is a
    filename joining two names, and a letter-to-digit boundary splits on three letters or more
    ("MPC2", "Unit1", "Rotherham125") but never inside a short brand token ("iP2C").
    """
    s = re.sub(r"[_/]+", " ", str(s or ""))
    s = re.sub(r"(?<=[a-z]{3})(?=[A-Z]{3})", " ", s)
    s = re.sub(r"(?<=[A-Za-z]{3})(?=\d)", " ", s)
    s = re.sub(r"(?<=\d{2})(?=[A-Za-z]{3})", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _sig_tokens(s: str) -> list:
    """The significant words of a candidate name, compared against what the document prints."""
    out = []
    for w in re.split(r"[^A-Za-z0-9]+", split_run_together(s)):
        w = w.strip().lower()
        if w and w not in _STOPWORDS:
            out.append(w)
    return out


def filename_name_candidates(stem: str) -> list:
    """The property-name candidates hiding in a filename, noise stripped.

    A deck filename is usually "<the property> - <what the file is>", and which side is which
    varies by sender: "Rotherham125 - Brochure Final" puts the property first,
    "WOLVERHAMPTON - Wolverhampton 144" puts it second. So both sides are offered and the
    DOCUMENT decides between them (see `deck_name`). Document words, version tags, page counts
    and the leading job number brokers prefix ("17585 Park Farm Road Scunthorpe") are dropped:
    they are facts about a PDF, never about a building.
    """
    stem = re.sub(r"\.(pdf|pptx|ppt)$", "", str(stem or ""), flags=re.IGNORECASE)
    sides = [s for s in re.split(r"\s+[-\\u2013]\s+", stem) if s.strip()] or [stem]
    out = []
    for side in sides:
        words = [w for w in re.split(r"[_\s]+", side.replace("-", " ")) if w]
        keep = [w for w in words if not _DOC_NOISE.match(w) and not _VERSION_TOKEN.match(w)]
        while len(keep) > 1 and re.fullmatch(r"\d+", keep[0]):
            keep.pop(0)          # a leading job number ("17513", "01_"), not part of the name
        # A stopword left stranded at an edge by the noise strip ("Site layouts for PPH 021025"
        # -> "for PPH") reads as a broken sentence on the sheet, which is how the live workbook
        # ended up offering a building called "for PPH".
        while keep and keep[0].lower() in _STOPWORDS:
            keep.pop(0)
        while keep and keep[-1].lower() in _STOPWORDS:
            keep.pop()
        cand = split_run_together(" ".join(keep)).strip(" ,.-_")
        if cand:
            out.append(cand)
    return out


def town_from_text(head: str) -> str:
    """The town the document itself prints beside its postcode, or ''.

    Taken from the LINE THE POSTCODE IS ON and nowhere else, because that line is the only place
    on a cover page where a word is reliably a settlement rather than a scheme, a county or the
    agent's own address. A county tail is stripped ("Scunthorpe North Lincolnshire" -> Scunthorpe)
    and the last word of what is left is the town. Nothing is looked up and nothing is guessed:
    a cover page with a bare postcode returns '', and a blank Town / city beats a wrong one.
    """
    for line in str(head or "").splitlines():
        m = _PC_RX.search(line.upper())
        if not m:
            continue
        before = line[:m.start()]
        segs = [s.strip(" .,|·") for s in re.split(r"[,.|·]", before)]
        segs = [s for s in segs if s and not re.fullmatch(r"[\W\d\s]+", s)]
        while segs and segs[-1].lower() in _COUNTIES:
            segs.pop()
        if not segs:
            continue
        seg = segs[-1]
        low = seg.lower()
        for c in _COUNTIES:
            if low.endswith(" " + c):
                seg = seg[: len(seg) - len(c) - 1].strip()
                break
        words = seg.split()
        if not words:
            continue
        town = _title(words[-1])
        # A "town" of one or two characters, or a pure number, is the tail of a broken address
        # line, not a place. Say nothing rather than print it.
        if len(re.sub(r"\W", "", town)) >= 3 and not town.isdigit():
            return town
    return ""


def _longest_place(rx, head: str) -> str:
    best = ""
    for m in rx.finditer(re.sub(r"\s+", " ", str(head or ""))):
        cand = m.group(1).strip()
        # A generic word swept in by the 1-to-3-word prefix ("Scunthorpe Site Foxhills Industrial
        # Estate" on the live PPH slide deck) is scaffolding, not part of the name.
        cand = re.sub(r"^(?:The|Site|Overview|Our|New|Former|Proposed)\s+", "", cand)
        if len(cand) > len(best):
            best = cand
    return _title(best)


def scheme_from_text(head: str) -> str:
    """The longest PARK / ESTATE / GATEWAY phrase the first page prints, or ''."""
    return _longest_place(_SCHEME_RX, head)


def street_from_text(head: str) -> str:
    """The longest ROAD / STREET / DRIVE phrase the first page prints, or ''.

    Ranked BELOW both the scheme on the page and a name the filename carries, because a street
    is where a building stands and a scheme is what it is called. Somebody sent the brochure
    saying "Midway One"; nobody will come back asking about Droves Dale Road.
    """
    return _longest_place(_STREET_RX, head)


def address_from_text(head: str) -> str:
    """The address the postcode sits in, up to two segments, or ''. The last document tier."""
    for line in str(head or "").splitlines():
        m = _PC_RX.search(line.upper())
        if not m:
            continue
        segs = [s.strip(" .,|·") for s in re.split(r"[,|·]", line[:m.start()])]
        segs = [s for s in segs if s and not re.fullmatch(r"[\W\d\s]+", s)]
        while segs and segs[-1].lower() in _COUNTIES:
            segs.pop()
        if segs:
            return _title(", ".join(segs[-2:]))
    return ""


def deck_name(cluster_label: str, file_names, head: str) -> tuple:
    """(property name, town, from_filename?, why) for one brochure cluster.

    FOUR TIERS, DOCUMENT FIRST, AND THE FALLBACK SAYS SO:

      1. a filename candidate the DOCUMENT CONFIRMS. Half or more of its significant words appear
         on the first page, so it is the building's own name that merely happens to be carried on
         the filename ("Bridgewater Business Park Leigh", "Total Park Telford", "Valley Road
         Barnsley", "Park Farm Road Scunthorpe"). A single unconfirmable word with no number is
         never accepted: "Goldthorpe" is a town, not the option.
      2. the longest park or street phrase printed on the first page.
      3. the address segments the postcode sits in.
      4. the cleaned filename, MARKED "(from filename)", so the reader knows this row is named
         after a PDF and can distrust it accordingly.

    The unit number is prepended when the page states one and the name does not already carry it,
    because "Unit 2, Total Park Telford" is a decision a human can take and "Total Park Telford"
    on its own is not, when the park has six units.
    """
    hay = _haystacks(head)
    unit = ""
    mu = _UNIT_RX.search(head or "")
    if mu:
        unit = "Unit %s" % mu.group(1).upper()

    stems = []
    for f in (file_names or []):
        stems.append(Path(str(f)).stem)
    if cluster_label and str(cluster_label) not in stems:
        stems.append(str(cluster_label))

    best, best_score = "", 0.0
    for stem in stems:
        for cand in filename_name_candidates(stem):
            toks = _sig_tokens(cand)
            if not toks:
                continue
            if len(toks) < 2 and not any(c.isdigit() for c in cand):
                continue
            ratio = _confirmed(toks, hay) / float(len(toks))
            if ratio >= 0.5 and (ratio, len(toks)) > (best_score, len(_sig_tokens(best))):
                best, best_score = _title(re.sub(r"\s+", " ", cand)), ratio
    why, from_fn = "", False
    if best:
        why = "named from the deck's first page (the filename agrees)"
    else:
        # THE FALLBACK CHAIN, SCHEME FIRST. Tier order: the scheme printed on page 1; then a name
        # the FILENAME carries even though page 1 does not repeat it ("Midway One"); then the
        # street; then the address round the postcode; then the raw filename. The street used to
        # sit above the filename and produced "Droves Dale Road, Rotherham" for a building the
        # market calls Midway One.
        best = scheme_from_text(head)
        why = "named from the scheme on the deck's first page"
        if not best:
            cands = [c for s in stems for c in filename_name_candidates(s)
                     if len(_sig_tokens(c)) >= 2 or any(ch.isdigit() for ch in c)]
            if cands:
                best, from_fn = _title(max(cands, key=len)), True
                why = ("page 1 states no scheme, so this row is named from the FILE - treat it "
                       "as a label, not a fact")
        if not best:
            best = street_from_text(head)
            why = "named from the street on the deck's first page"
        if not best:
            best = address_from_text(head)
            why = "named from the address beside the postcode on the deck's first page"
        if not best:
            cands = [c for s in stems for c in filename_name_candidates(s)]
            best = _title(max(cands, key=len)) if cands else _title(str(cluster_label or ""))
            why = ("the deck's first page has no readable name, so this row is named after the "
                   "FILE - treat it as a label, not a fact")
            from_fn = bool(best)
    if unit and best and unit.lower() not in best.lower() and "unit" not in best.lower():
        best = "%s, %s" % (unit, best)
    town = town_from_text(head)
    # A filename's other side, one word long and printed on page 1, is the locality the document
    # itself agrees with: "Goldthorpe - Midway One.pdf" over a cover that says GOLDTHORPE. It
    # beats the postal town at the end of the address line, which on S63 9FD is Rotherham.
    for stem in stems:
        for side in filename_name_candidates(stem):
            toks = _sig_tokens(side)
            if (len(toks) == 1 and len(toks[0]) >= 4 and _confirmed(toks, hay) == 1
                    and toks[0] not in (best or "").lower()):
                town = _title(side)
                break
    if town and best and town.lower() not in best.lower():
        best = "%s, %s" % (best, town)
    if from_fn and best:
        best = "%s (from filename)" % best
    return best or str(cluster_label or ""), town, from_fn, why


# ------------------------------------------------------- saying WHO a row came from, in English
#
# DEFECT D on the live sheet: Source read "mail_unpacked/mail/Emakl.msg - 2026-09-07 13:19:08"
# and "17585 Park Farm Road Scunthorpe - New Logo.pdf". Neither tells the person answering the
# sheet the one thing they need in order to answer it: who sent this, and when.

_ORGS = {
    "cushwake.com": "Cushman & Wakefield", "savills.com": "Savills",
    "knightfrank.com": "Knight Frank", "avisonyoung.com": "Avison Young",
    "avisonyoung.co.uk": "Avison Young", "cbre.com": "CBRE", "colliers.com": "Colliers",
    "jll.com": "JLL", "lsh.co.uk": "Lambert Smith Hampton", "geraldeve.com": "Gerald Eve",
    "cpp.uk": "Commercial Property Partners", "cppartners.co.uk": "Commercial Property Partners",
    "mounseysurveyors.co.uk": "Mounsey Surveyors", "bulleysbradbury.co.uk": "Bulleys Bradbury",
    "pph-commercial.co.uk": "PPH Commercial", "htare.co.uk": "HTA Real Estate",
    "dtre.com": "DTRE", "m1agency.co.uk": "M1 Agency", "burbageredhill.co.uk": "Burbage Realty",
}


def sender_parts(raw) -> tuple:
    """(display name, organisation) from a From header, best effort and never invented.

    An Exchange run picks up X.500 noise ("Lowe, Jonathan @ CBRE </O=EXCHANGELABS/OU=...>"), so
    the address half is only trusted when it actually looks like an address. An organisation the
    domain does not name is left blank rather than guessed from the display name, because a
    wrong firm beside a broker's name on a scope sheet is a thing a colleague will repeat.
    """
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not s:
        return "", ""
    addr = ""
    m = re.search(r"<([^<>]+)>\s*$", s)
    if m:
        addr, s = m.group(1).strip(), s[: m.start()].strip()
    elif "@" in s and " " not in s:
        addr, s = s, ""
    name = s.strip(' "\'')
    org = ""
    if "@" in addr:
        dom = addr.rsplit("@", 1)[1].strip().lower().strip(">")
        org = _ORGS.get(dom, "")
        if not org and "." in dom and "exchangelabs" not in dom:
            lab = dom.split(".")[0]
            org = lab.upper() if len(lab) <= 3 else lab.replace("-", " ").title()
    if not name:
        name = addr.split("@")[0].replace(".", " ").title() if addr else ""
    # A trailing "(...)" is taken off FIRST. The live corpus has
    # "Hale, Robin (Avison Young - UK)": leaving the bracket on blocked the surname flip below
    # and the sheet printed "Hale, Robin (Avison Young - UK)" where it should read "Robin Hale".
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", name)
    if m:
        name = m.group(1).strip()
        org = org or re.sub(r"\s*-\s*UK$", "", m.group(2).strip())
    # "Lowe, Jonathan @ CBRE" - Exchange's own display form. Flip it, and take the firm it names.
    m = re.match(r"^([^,]+),\s*([^@]+?)\s*@\s*(.+)$", name)
    if m:
        name = "%s %s" % (m.group(2).strip(), m.group(1).strip())
        org = org or m.group(3).strip()
    elif "," in name:
        a, _, b = name.partition(",")
        if b.strip() and " " not in b.strip():
            name = "%s %s" % (b.strip(), a.strip())
    name = re.sub(r"\s+(B\.Sc\.?|MRICS|MSc|\(Hons\)|FRICS)\b.*$", "", name).strip(" ,")
    name = re.sub(r"/[A-Z]{2,4}$", "", name).strip()
    return name, org


def human_date(v) -> str:
    """'7 Sep 2026' from whatever shape the reader handed us, or '' - never a raw timestamp."""
    s = str(v or "").strip()
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return "%d %s %s" % (int(m.group(3)), months[int(m.group(2)) - 1], m.group(1))
        except Exception:
            return ""
    # A .msg comes back ISO; a .eml comes back with its raw RFC 2822 header
    # ("Tue, 15 Sep 2026 09:14:00 +0100"). Both are dates a person can read once, and the source
    # line is the one place on the sheet where an unparsed one shows as a missing fact.
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)
        return "%d %s %s" % (d.day, months[d.month - 1], d.year)
    except Exception:
        return ""


def email_source_text(sender_raw, date) -> str:
    """"Email: Alex Morgan (Cushman & Wakefield), 7 Sep 2026" - the Source an adult can read."""
    name, org = sender_parts(sender_raw)
    who = name or "unknown sender"
    if org:
        who = "%s (%s)" % (who, org)
    d = human_date(date)
    return "Email: %s%s" % (who, (", " + d) if d else "")


def deck_source_text(sender_raw, date, in_email: bool) -> str:
    """Where a deck came from: an attachment names its sender, a loose file names the folder."""
    if not in_email:
        return "Brochure, input folder"
    name, org = sender_parts(sender_raw)
    who = name or "unknown sender"
    if org:
        who = "%s (%s)" % (who, org)
    d = human_date(date)
    return "Brochure, attached to email from %s%s" % (who, (", " + d) if d else "")


# ------------------------------------------------------------------- candidate enumeration

def _record_rows(records_by_file: dict) -> list:
    """One candidate row per tracker / email record already on disk.

    Deliberately permissive about missing fields, for the same reason the Kato port is: an
    option first named in one line of an email ('we also have Packington Hill, 140k, Q2 2027')
    has no coordinates and no agent, and refusing it here would push exactly the options this
    step exists to surface back out of the inventory. Blanks ship as blanks; the row still
    carries a Yes/No decision.
    """
    rows = []
    for src, recs in sorted(records_by_file.items()):
        base = Path(src).name
        low = base.lower()
        if low.endswith(DECK_EXTS):
            continue  # a deck's records belong to its cluster row, not to a row of their own
        for r in recs:
            if not isinstance(r, dict) or r.get("unreadable"):
                continue
            # Per record, not per file: an email record's `source_file` is its SUBJECT, so the
            # file-level extension test alone labelled it "Source file". See record_row_id.
            meta_type = str((r.get("__meta") or {}).get("source_type") or "").strip().lower()
            src_type = ("Email" if (low.endswith(EMAIL_EXTS) or meta_type == "email")
                        else "Tracker" if low.endswith(TRACKER_EXTS) else "Source file")
            name = (r.get("park") or r.get("address") or r.get("city") or "").strip()
            if not name:
                # A row with no name at all cannot be judged by a human, and inventing one
                # ("Option 7") would put a decision in front of the user that they cannot take.
                # It is counted in `unnamed` on the candidates file instead, so the count on the
                # sheet's footer and the count of records the run holds can be reconciled.
                continue
            loc = _locator(r)
            rows.append({
                "row_id": record_row_id(r),
                "property": name,
                "source_type": src_type,
                "source": f"{base}{(' ' + loc) if loc else ''}",
                "source_files": [base],
                "record_locator": loc,
                "address": str(r.get("address") or ""),
                "postcode": str(r.get("postcode") or ""),
                "city": str(r.get("city") or ""),
                "lat": _num(r.get("lat")),
                "lon": _num(r.get("lng")),
                "size_from": _num(r.get("warehouseArea")),
                "size_to": _num(r.get("warehouseArea")),
                "size_unit": str(r.get("areaUnit") or ""),
                "rent": str(r.get("warehouseRent") or ""),
                "availability": str(r.get("status") or ""),
                "agent": str(r.get("landlord") or r.get("developer") or ""),
                "files": [],
                "brochure": NO,
                "brochure_detail": "No document held for this row - it is source text only",
                "notes": "",
            })
    return rows


def email_index(folder: Path, emails, email_attachments=None) -> list:
    """One entry per EMAIL MESSAGE on disk - for the EMAILS TAB, never for the Master list.

    WHY THIS IS NO LONGER A CANDIDATE ROW (defect A on the live run "Test Run Brochures Only").
    The previous version of this function put one MASTER-LIST row per .msg on the scope sheet,
    named after the subject. On that run it produced sixteen rows reading
    "RE: →  Looking for 60,000 to 100,000 sq ft of Industrial/Log..." with no postcode, no
    size and a raw path for a Source. A message is not a building. It is a SOURCE, and asking a
    human to answer Yes or No to a source is asking a question with no correct answer: "No" to
    Alex Morgan's email is not a decision about any of the four units it names.

    It also poisoned everything downstream. Because a message was a row, the orchestrator had to
    invent ten "MESSAGE ROW SPLIT - not one building" duplicate groups tying each message to the
    buildings it mentions, and those pseudo-groups are what made the Duplicate group column
    unreadable. A duplicate group means SAME BUILDING, TWO SOURCES. "This message mentions these
    buildings" is a different relation entirely, and the only way to stop it being expressed is
    to stop the message being a row.

    NOTHING VANISHES, WHICH IS THE OTHER HALF OF THE ARGUMENT THAT PUT THESE ROWS HERE IN THE
    FIRST PLACE. An email reaches the sheet by exactly two routes now - its ATTACHED DECKS, which
    are already rows and now carry the sender and date in their Source, and the EMAIL-ONLY OPTIONS
    the master-list sub-agent reads out of the prose at exit 17. Every message is listed on the
    workbook's Emails tab with its sender, date, cleaned subject, attachments and the master-list
    rows that came from it, and a message that produced neither an attachment nor an orchestrator
    row is flagged there as "nothing extracted". The reader can still see every message; they are
    just not asked to make a scope decision about one.

    Attachments are never re-saved: `save_attachment_bytes=False`. intake already wrote them
    beside their email before classification, and a second write does not merge with the first,
    it clusters as its own option and the client sees the same building on two cards
    (`extract_email.extract` says the same thing for the same reason).
    """
    rows: list = []
    if not emails:
        return rows
    try:
        import extract_email as EM
    except Exception:
        # The enumeration is best-effort by contract: a run that cannot import the email reader
        # must still put its tracker rows and its decks to the user rather than wedge.
        return rows
    # extract() walks ONE directory and does not recurse, so it is called once per directory that
    # actually holds an email. The alternative - pointing it at the inputs root - would silently
    # miss every message that arrived inside a zip, which intake unpacks into a subfolder, and a
    # zipped export is the commonest shape a broker's email dump takes.
    # WHAT EACH MESSAGE BROUGHT WITH IT comes from the INVENTORY, not from the re-read above.
    # The re-read passes save_attachment_bytes=False (it must: intake already wrote those bytes,
    # and a second write clusters as a second option), and that path returns an empty `saved`
    # list by construction. Reading the row's attachments off the parse would therefore have
    # printed "no attachments" beside an email that shipped a brochure - a statement on the
    # user's scope sheet that is not merely absent but wrong. intake's own `email_attachments`
    # record is the one place that knows what was written.
    _att_by_email: dict = {}
    for _e in (email_attachments or []):
        if not isinstance(_e, dict):
            continue
        _k = Path(str(_e.get("email") or "")).as_posix().lower()
        if _k:
            _att_by_email[_k] = [str(s.get("file") or "") if isinstance(s, dict) else str(s)
                                 for s in (_e.get("saved") or [])]
    dirs = sorted({Path(str(rel)).parent.as_posix() for rel in emails})
    seen_ids = set()
    for d in dirs:
        sub = Path(folder) / d if d not in ("", ".") else Path(folder)
        if not sub.is_dir():
            continue
        try:
            recs = EM.extract(sub, save_attachment_bytes=False) or []
        except Exception:
            continue
        # extract() reports the subject in __meta.source_file and not the filename it came from,
        # so the messages are re-paired with the directory listing in the same sorted order the
        # reader used. Both sides sort the same directory, so the pairing is positional only
        # across a list neither side reorders.
        files = [p for p in sorted(sub.iterdir())
                 if p.is_file() and p.suffix.lower() in EMAIL_EXTS]
        if len(files) != len(recs):
            # A corrupt message is dropped by neither side (extract writes an `unreadable` stub),
            # but if the counts ever diverge the pairing is a guess, and a guessed provenance on
            # a scope sheet is worse than a missing row. Say nothing rather than mislabel.
            continue
        for p, r in zip(files, recs):
            if not isinstance(r, dict) or r.get("unreadable"):
                continue
            rel = (Path(d) / p.name).as_posix() if d not in ("", ".") else p.name
            subject = str(r.get("subject") or "").strip()
            rid = email_row_id(rel)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            atts = [a for a in _att_by_email.get(rel.lower(), []) if a]
            name, org = sender_parts(r.get("from"))
            # source_files carries BOTH spellings on purpose: the attachment-era records stamp
            # __meta.source_file as the email's FILENAME, while extract_email's own body records
            # stamp it as the SUBJECT. The exclusion filter matches records to rows on that field,
            # so an entry that listed only one of the two would accept the user's No and then
            # fail to remove half of what the No was about.
            rows.append({
                "email_id": rid,
                "email_file": rel,
                "file_name": p.name,
                "sender": name,
                "sender_raw": str(r.get("from") or ""),
                "organisation": org,
                "date": human_date(r.get("date")),
                "date_raw": str(r.get("date") or ""),
                "subject": clean_subject(subject),
                "subject_raw": subject,
                "attachments": [Path(a).name for a in atts],
                "attachment_paths": atts,
                "source_text": email_source_text(r.get("from"), r.get("date")),
                "source_files": [p.name] + ([subject] if subject else []),
            })
    return rows


def _cluster_rows(clusters: dict, folder: Path, first_page_text, emails=None) -> list:
    """One candidate row per BROCHURE CLUSTER - the unit a reader agent is dispatched on.

    Per cluster, not per file, because the cluster is what the run would read as one option and
    what the user is therefore being asked about. Postcode and size come from the first page's
    text, which is the cheapest evidence that exists before the expensive read; it is explicitly
    NOT treated as data anywhere else - nothing from this row reaches a card. If the user
    includes the row, the reader agent reads the deck properly and overwrites all of this.

    THE NAME NO LONGER COMES FROM THE FILE (defect B on the live run). It used to be the cluster
    label - a filename stem - and the Town / city column held that same stem, which is how the
    sheet came to show a building called "New Logo" in a town called "New Logo". `deck_name`
    reads the first page and only falls back to a cleaned filename, marked as such. Town / city
    is document-derived or blank; a filename is never allowed into it, because a wrong town is a
    fact a colleague will act on and a blank one is a question they will ask.

    The ROW ID is unchanged (`cluster_row_id`, the label plus a digest of the file set), because
    it is the record's provenance locator and not its name. A better name must not re-open a row
    the user has already answered.
    """
    rows = []
    by_attachment = {}
    for e in (emails or []):
        for a in (e.get("attachment_paths") or []):
            by_attachment[Path(str(a)).as_posix().lower()] = e
            by_attachment[Path(str(a)).name.lower()] = e
    for label, cl in sorted((clusters or {}).items()):
        files = [*(cl.get("pdfs") or ([cl["pdf"]] if cl.get("pdf") else [])),
                 *(cl.get("pptxs") or ([cl["pptx"]] if cl.get("pptx") else []))]
        if not files:
            continue
        names = [Path(str(f)).name for f in files]
        head = ""
        try:
            head = first_page_text(folder / files[0]) or ""
        except Exception:
            head = ""
        pc = ""
        m = _PC_RX.search(head.upper())
        if m:
            pc = m.group(1)
        size = None
        ms = re.search(r"([\d][\d,\.]{3,})\s*(?:sq\s*\.?\s*(?:ft|m)|m2|m²|sqft|sqm)",
                       head, re.I)
        if ms:
            size = _num(ms.group(1))
        name, town, from_fn, why = deck_name(label, files, head)
        em = None
        for f in files:
            em = (by_attachment.get(Path(str(f)).as_posix().lower())
                  or by_attachment.get(Path(str(f)).name.lower()))
            if em:
                break
        src = deck_source_text(em.get("sender_raw") if em else "",
                               em.get("date_raw") if em else "", bool(em))
        note = ("Postcode and size here are the deck's FIRST PAGE only - a cheap look, not the "
                "read. Include the row and the deck is read properly. This row is %s." % why)
        if em:
            note += (" It arrived as an attachment to \"%s\"%s."
                     % (em.get("subject") or em.get("file_name"),
                        (" from " + em["sender"]) if em.get("sender") else ""))
        rows.append({
            "row_id": cluster_row_id(label, files),
            "property": name,
            "source_type": "Brochure",
            "source": src,
            "source_detail": "; ".join(names),
            "source_files": names,
            "cluster": str(label),
            "email_file": em.get("email_file") if em else "",
            "address": "",
            "postcode": pc,
            "city": town,
            "lat": None, "lon": None,
            "size_from": size, "size_to": size,
            "size_unit": "",
            "rent": "", "availability": "",
            "agent": (("%s, %s" % (em["sender"], em["organisation"])).strip(", ")
                      if em and (em.get("sender") or em.get("organisation")) else ""),
            "files": names,
            "brochure": YES,
            "brochure_detail": "Yes - %d deck(s) on disk: %s" % (len(names), "; ".join(names)),
            "notes": note,
        })
    return rows


def _gnum(gid) -> int:
    m = re.search(r"(\d+)$", str(gid) or "")
    return int(m.group(1)) if m else 0


SAME_BUILDING = "Same building, more than one source"
SAME_BUILDING_LOW = "Same building, more than one source - lower confidence"
# The blunt sweep's own hedge. It groups on postal code alone, and one big park shares a postcode
# across genuinely separate units - the live corpus has four Vantage Park units at B24 9GZ. The
# sweep must still say something (a duplicate nobody caught puts one building on the client's
# dashboard twice) but it must not say SAME BUILDING about four different sheds.
SWEEP_DIFFER = "Same postcode (auto sweep) - sizes differ, probably different units of one park"
SWEEP_CHECK = "Same postcode (auto sweep) - check whether one building"
SIZE_TOLERANCE = 0.15   # two stated areas this far apart are not one building quoted twice


def _sizes_differ(a: dict, b: dict) -> bool:
    """Both areas stated and more than 15% apart, so this pair is not one building.

    The live sheet grouped V60, V90, V117 and V216 at B24 9GZ and told the reader all four were
    "possibly the same building". They are 61k, 90k, 117k and 216k sq ft: four units of one park,
    which is the ordinary shape of a park listing and not a duplicate at all. A postcode alone is
    worth flagging, but a flag that overstates what it found is a flag people learn to ignore.
    """
    x = a.get("size_to") or a.get("size_from")
    y = b.get("size_to") or b.get("size_from")
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return False
    hi = max(abs(x), abs(y))
    return hi > 0 and abs(x - y) / hi > SIZE_TOLERANCE


def _group_status(members: list, declared: str) -> str:
    """Every group on this sheet means SAME BUILDING. The only variable is confidence.

    The live run's groups included ten called "MESSAGE ROW SPLIT - not one building", which is
    the model saying, in the status column, that the group is NOT a duplicate group. That is not
    a thing this column can mean. With the message rows gone the relation cannot arise, and this
    normalises whatever the model writes onto the one meaning the column has, so a future model
    cannot smuggle a different one back in. Two members with two DIFFERENT postcodes are still
    grouped - the model may know something the postcodes do not - but they are marked as the
    weaker claim, because that is the group a reader should look at twice.
    """
    pcs = {norm_postcode(m.get("postcode")) for m in members} - {""}
    low = len(pcs) > 1 or "lower confidence" in str(declared or "").lower()
    return SAME_BUILDING_LOW if low else SAME_BUILDING


def duplicate_partner_text(row: dict, members: list) -> str:
    """"same building as #35 Wolverhampton 144 (brochure)" - on BOTH rows of the pair.

    DEFECT C. The sheet used to print "D8" and nothing else, and it sorted by group, which
    scattered the ranks (1, 2, 3, 4, 37, 50, 38...) and left the reader to hunt for the partner
    of a group id. A duplicate is a statement about two rows, so it belongs on both of them, in
    the words a person would use, naming the partner by the rank they can actually see.
    """
    others = sorted([m for m in members if m.get("row_id") != row.get("row_id")],
                    key=lambda x: x.get("rank") or 0)
    if not others:
        return ""

    def _name(m, kind=True):
        return ("#%s %s%s" % (m.get("rank") or "?", m.get("property") or "?",
                              (" (%s)" % (str(m.get("source_type") or "row").strip().lower()))
                              if kind else ""))

    # ONLY A JUDGED GROUP SAYS "SAME BUILDING". The sweep has seen a postcode and nothing else,
    # so it says what it actually knows and labels itself, every time, as the machine.
    if str(row.get("duplicate_origin") or "") != "auto":
        return "same building as " + "; ".join(_name(m) for m in others)
    differ = [m for m in others if _sizes_differ(row, m)]
    check = [m for m in others if m not in differ]
    parts = []
    if differ:
        parts.append("same postcode as %s (auto sweep): sizes differ, so probably different "
                     "units of one park" % "; ".join(_name(m, kind=False) for m in differ))
    if check:
        parts.append("same postcode as %s (auto sweep): check whether one building"
                     % "; ".join(_name(m, kind=False) for m in check))
    return "; ".join(parts)


def apply_duplicates(rows: list, model_groups: dict | None = None) -> dict:
    """Group rows that may be the same building: the model's groups first, then a blunt sweep.

    The model's groups WIN where they exist - it has read the emails and can tell a phase of a
    scheme from a re-listing of it. The sweep then runs on postal code alone over what is left
    and is deliberately crude. It over-groups (one big park shares a postcode across genuinely
    separate units) and it SAYS SO in the status text, because the two errors are not
    symmetrical: a group the user glances at and dismisses costs a second, and a duplicate
    nobody caught puts the same building on the client's dashboard twice.

    Rows with no usable postcode are never swept. An empty string is not evidence of anything,
    and grouping on it would hand the user one meaningless group of every unlocated row.
    """
    by_id = {r["row_id"]: r for r in rows}
    meta, n = {}, 0
    for gid, g in sorted((model_groups or {}).items()):
        members = [by_id[m] for m in (g.get("members") or []) if m in by_id]
        if len(members) < 2:
            continue
        n = max(n, _gnum(gid))
        status = _group_status(members, g.get("status"))
        meta[gid] = {"origin": "model", "status": status,
                     "members": [r["row_id"] for r in members]}
        for r in members:
            r["duplicate_group"] = gid
            r["duplicate_status"] = status
            r["duplicate_origin"] = "model"
            r["duplicate_note"] = g.get("note") or ""

    buckets: dict = {}
    for r in rows:
        if r.get("duplicate_group"):
            continue
        pc = norm_postcode(r.get("postcode"))
        if pc:
            buckets.setdefault(pc, []).append(r)
    for pc, group in sorted(buckets.items()):
        if len(group) < 2:
            continue
        n += 1
        gid = "D%d" % n
        sizes = {r.get("size_to") or r.get("size_from") for r in group}
        same_size = len(sizes) == 1 and None not in sizes
        spread = any(_sizes_differ(a, b) for i, a in enumerate(group) for b in group[i + 1:])
        status = (SAME_BUILDING + " - same postcode and floor area (auto sweep)" if same_size
                  else SWEEP_DIFFER if spread else SWEEP_CHECK)
        note = ("Automatic check on postal code %s only, not adjudicated: %s. %s"
                % (pc, "; ".join(r["property"] for r in group),
                   "Identical floor area, so most likely one option listed more than once."
                   if same_size else
                   "Floor areas more than %d%% apart, so these read as separate units of one "
                   "park rather than one building listed twice." % int(SIZE_TOLERANCE * 100)
                   if spread else
                   "Could be one option quoted twice, or neighbouring units; the sizes do not "
                   "settle it."))
        meta[gid] = {"origin": "auto", "status": status,
                     "members": [r["row_id"] for r in group]}
        for r in group:
            r["duplicate_group"] = gid
            r["duplicate_status"] = status
            r["duplicate_origin"] = "auto"
            r["duplicate_note"] = note
    for r in rows:
        r.setdefault("duplicate_group", "")
        r.setdefault("duplicate_status", "")
        r.setdefault("duplicate_origin", "")
        r.setdefault("duplicate_note", "")
    return meta


def fingerprint(rows: list) -> str:
    """A digest of the ROW IDENTITY SET, and nothing else.

    This is the resume predicate for the whole stage: an answered sheet is honoured for as long
    as the set of things there were to answer about has not changed, and a new deck or a new
    email changes it, which re-opens the exit with every still-matching answer carried forward
    by Row ID. Deliberately NOT a digest of the row VALUES: re-reading the same tracker can
    produce a cosmetically different size string, and re-asking a broker forty questions because
    a number gained a decimal place is how a gate gets disabled by the people it protects.
    """
    ids = sorted(str(r.get("row_id") or "") for r in rows or [])
    return hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:16]


def build_auto(work: Path, records_by_file: dict, clusters: dict, folder: Path,
               first_page_text, emails=None, email_attachments=None) -> dict:
    """Write work/master_candidates_auto.json - the spine's half of the candidate set.

    Three routes in, all deterministic: tracker records, email records an agent has already
    written, and one row per brochure CLUSTER - which is where an attachment that arrived
    stapled to a .msg ends up, because intake saves it beside its email and classifies it in
    the same pass, exactly like a brochure dropped in the folder by hand.

    A MESSAGE IS NOT A ROUTE. It is a source, and it is indexed (`emails`) rather than
    enumerated; see `email_index` for the defect that taught us the difference. The options an
    email names in its PROSE and nowhere else are added by the master-list sub-agent at exit 17,
    which is the one thing here a deterministic pass genuinely cannot do.

    `emails` is the inventory's email list (paths relative to the inputs folder). It defaults to
    None so a caller that predates the email route gets the old behaviour rather than a TypeError.
    """
    rec_rows = _record_rows(records_by_file)
    mail = email_index(folder, emails, email_attachments)
    # The email index is NOT a source of master-list rows (see `email_index`). It is read here
    # so a deck that arrived as an attachment can say who sent it and when, and it is written to
    # the candidates file so the builder can put every message on the Emails tab.
    rows = rec_rows + _cluster_rows(clusters, folder, first_page_text, mail)
    for r in rows:
        if r.get("source_type") == "Email" and not str(r.get("source") or "").strip():
            r["source"] = "Email: sender not recorded"
    groups = apply_duplicates(rows)
    payload = {
        "rows": rows,
        "emails": mail,
        "duplicate_groups": groups,
        "input_hash": fingerprint(rows),
        "counts": {"rows": len(rows),
                   "from_records": sum(1 for r in rows if r["source_type"] != "Brochure"),
                   "from_emails": sum(1 for r in rows if r["source_type"] == "Email"),
                   "from_brochures": sum(1 for r in rows if r["source_type"] == "Brochure"),
                   "messages": len(mail)},
    }
    p = Path(work) / AUTO_CANDIDATES
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


# --------------------------------------------------------------------- reading the answer

def load_answers(work: Path) -> dict:
    return _read_json(Path(work) / ANSWERS, {}) or {}


def is_answered(work: Path, current_hash: str = "") -> bool:
    """True when a master_list.json on disk settles THIS inputs set.

    Two ways it is not settled: there is no file, or the file answers a different set of rows
    (a deck or an email arrived after it was answered). The second case re-opens the stop; the
    builder then carries every still-matching answer forward by Row ID, so re-opening costs the
    user the new rows and nothing else.
    """
    ml = load_answers(work)
    if not ml or not (ml.get("rows") or ml.get("skipped")):
        return False
    if current_hash and str(ml.get("input_hash") or "") != str(current_hash):
        return False
    return True


def user_answered(work: Path) -> bool:
    """True only for a sheet a PERSON filled in.

    The headless bypass writes the same file with `skipped: true`, and that file must not be
    read as a scope decision: it includes everything by default, so treating it as the source
    authority would mean a cron run silently declares itself authoritative and suppresses the
    exit-13 question that would otherwise have been asked on the next interactive pass.
    """
    ml = load_answers(work)
    return bool(ml) and not ml.get("skipped") and bool(ml.get("rows"))


def _rows_of(ml: dict) -> list:
    return [r for r in (ml.get("rows") or []) if isinstance(r, dict)]


def excluded_cluster_labels(work: Path) -> set:
    """Cluster labels whose rows are ALL No - the decks the reader dispatch must skip.

    'All No' rather than 'any No' because a cluster carries exactly one row today, and an
    any-No rule would become a silent data-loss bug the moment that stops being true.
    """
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return set()
    by_cluster: dict = {}
    for r in _rows_of(ml):
        cl = str(r.get("cluster") or "")
        if cl:
            by_cluster.setdefault(cl, []).append(str(r.get("include") or ""))
    return {cl for cl, answers in by_cluster.items()
            if answers and all(a == NO for a in answers)}


def excluded_rows(work: Path) -> list:
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return []
    return [r for r in _rows_of(ml) if str(r.get("include") or "") == NO]


def _excluded_keys(ml: dict) -> tuple:
    """(record ids, deck filenames) the user excluded, as two lookup sets."""
    rec_ids, deck_files = set(), set()
    for r in _rows_of(ml):
        if str(r.get("include") or "") != NO:
            continue
        rid = str(r.get("row_id") or "")
        if rid.startswith("deck:"):
            deck_files |= {str(f).lower() for f in (r.get("source_files") or [])}
        elif rid:
            rec_ids.add(rid)
    return rec_ids, deck_files


def record_excluded(rec: dict, rec_ids: set, deck_files: set) -> bool:
    src = Path(source_file(rec)).name.lower()
    if src and src in deck_files:
        return True
    return record_row_id(rec) in rec_ids


def apply_to_clusters(clusters: list, work_or_answers) -> tuple:
    """Split settled match clusters into (kept, dropped) per the answered master list.

    The same three safety properties as `merge.apply_source_authority`, for the same reason -
    this is the only other code in the skill that can remove a property from a client's own
    longlist:

      * a cluster NO record of which maps to an excluded row is always kept;
      * a cluster is dropped only when EVERY record in it maps to a row the user marked No,
        so a deck that turned out to describe an included option keeps that option alive;
      * if the filter would empty the dataset nothing is dropped, because an empty dashboard is
        never the right reading of a sheet somebody filled in.

    `dropped` is returned, never discarded: deliver.py names each one in the Gaps Report.
    """
    ml = (work_or_answers if isinstance(work_or_answers, dict)
          else load_answers(work_or_answers))
    if not ml or ml.get("skipped"):
        return list(clusters or []), []
    rec_ids, deck_files = _excluded_keys(ml)
    if not rec_ids and not deck_files:
        return list(clusters or []), []
    kept, dropped = [], []
    for cl in clusters or []:
        recs = list(cl or [])
        hits = [record_excluded(r, rec_ids, deck_files) for r in recs]
        if recs and all(hits):
            dropped.append(cl)
        else:
            kept.append(cl)
    if not kept:
        return list(clusters or []), []
    return kept, dropped


def seed_match_decisions(records: list, work: Path) -> dict:
    """The user's duplicate groups, expressed as `same` verdicts keyed the way exit 10 keys them.

    A group on the sheet is a human saying 'these rows are one building'. Exit 10 exists to ask
    a sub-agent that same question about pairs nobody has answered, so a group the user already
    settled must not come back as a question - it would be asking the person who owns the
    deliverable to re-confirm their own decision through an intermediary.

    Keyed with `match.pair_id`, which is the id the spine itself would generate for the pair:
    an order-independent sha1 of the two records' (match_key + area). Writing any other key
    would produce a file that looks answered and covers nothing.

    Rows map to records the same way the exclusion filter maps them, so the two can never
    disagree about which record a row is. A group whose rows resolve to fewer than two records
    yields nothing - typically a group over two decks that have not been read yet, which is
    correct: those pairs cannot exist until their records do, and this runs again next pass.
    """
    import match as _m
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return {}
    by_group: dict = {}
    for r in _rows_of(ml):
        g = str(r.get("duplicate_group") or "").strip()
        if g and str(r.get("include") or "") in (YES, NO):
            by_group.setdefault(g, []).append(r)
    if not by_group:
        return {}
    # row_id -> [records], built once over the whole record set
    members: dict = {}
    for rec in (records or []):
        if not isinstance(rec, dict):
            continue
        src = Path(source_file(rec)).name.lower()
        rid = record_row_id(rec)
        members.setdefault(rid, []).append(rec)
        members.setdefault(f"file:{src}", []).append(rec)
    out = {}
    for gid, rows in sorted(by_group.items()):
        recs: list = []
        for r in rows:
            rid = str(r.get("row_id") or "")
            if rid.startswith("deck:"):
                for f in (r.get("source_files") or []):
                    recs += members.get(f"file:{str(f).lower()}", [])
            else:
                recs += members.get(rid, [])
        # de-duplicate by identity, keep order
        seen, uniq = set(), []
        for rec in recs:
            if id(rec) not in seen:
                seen.add(id(rec))
                uniq.append(rec)
        for a_i in range(len(uniq)):
            for b_i in range(a_i + 1, len(uniq)):
                a, b = uniq[a_i], uniq[b_i]
                if _m.match_key(a) == _m.match_key(b) and a is b:
                    continue
                out[_m.pair_id(a, b)] = {
                    "verdict": "same",
                    "reason": (f"the broker grouped these on the master list as duplicate "
                               f"group {gid} - their decision, not an adjudication"),
                }
    return out


def write_headless(work: Path, auto: dict, reason: str) -> dict:
    """Include EVERYTHING, disclosed, for a run that has nobody to ask.

    A cron or SKIP_ALL run cannot stop for a sheet, and refusing to run would be worse than
    including everything: the run's honest behaviour without a master list is exactly what it
    did before this stage existed. What must never happen is that the bypass looks like an
    answer, so `skipped: true` rides on the file, `user_answered` returns False for it (the
    source-authority question is therefore still asked on the next interactive pass) and
    deliver.py prints the disclosure in the Gaps Report.
    """
    payload = {
        "skipped": True,
        "reason": reason,
        "input_hash": str((auto or {}).get("input_hash") or ""),
        "counts": {"rows": len((auto or {}).get("rows") or []),
                   "included": len((auto or {}).get("rows") or []), "excluded": 0},
        "rows": [{"row_id": r.get("row_id"), "property": r.get("property"),
                  "include": YES, "run_notes": "", "cluster": r.get("cluster"),
                  "source_files": r.get("source_files") or [],
                  "duplicate_group": r.get("duplicate_group") or ""}
                 for r in ((auto or {}).get("rows") or [])],
    }
    Path(work, ANSWERS).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return payload
