"""Shared helpers for the Kato-Longlist skill."""
import os, re, csv, json, yaml, urllib.parse

KATO_ORIGIN = "https://agency.kato.app"

# THE MARKET, IN ONE PLACE. Kato is a UK agency platform and every field this skill reads off
# it is UK-shaped (GBP per sq ft, EPC bands, a UK postal code), so the country is a constant of
# the skill rather than a per-property fact - and it was written out as a bare literal twice,
# once as a name in the tracker's 'Country' column and once as a code in the generated
# project.yaml. Named here because a THIRD consumer now needs the same value: patch_canonical
# repairs the country the pipeline ships (see MARKET_COUNTRY_ISO's use there), and a repair
# keyed off a different literal from the tracker's is a repair that can disagree with the
# evidence it claims to restore.
MARKET_COUNTRY_NAME = "United Kingdom"
MARKET_COUNTRY_ISO = "GB"

_BARE_UNIT = re.compile(r"(?i)^units?\b[\s\w\-\/&]{0,4}$")


class PairingError(RuntimeError):
    """Raised by match_canonical_to_our when it cannot pair EVERY pipeline property.

    No caller catches it, on purpose. A partial pairing is the defect this module exists to
    prevent, and a partial pairing that is caught and logged is indistinguishable, in the
    output an operator actually reads, from a clean run."""


def display_name(p):
    """A descriptive, UNIQUE card title. The upstream record's address.name is often blank
    or a bare 'Unit 2', which leaves cards untitled and - worse - lets the pipeline's
    matcher merge two distinct nameless units on one shared estate. So compose from the
    address: take the unit designator + the scheme name, never leaving it blank.

    IT LIVES HERE, not in toolkit_tracker, because it is now needed on BOTH sides of the
    pairing. toolkit_tracker writes this composed string into the tracker's 'Property'
    column; the pipeline's column dictionary maps that header to canonical `park`; so
    match_canonical_to_our's name fallback has to compare THIS string against `park`. It
    used to compare the raw address.name, which is a different string for exactly the
    nameless-unit properties the fallback exists to catch. toolkit_tracker re-exports the
    name so its own callers and CLI are unchanged."""
    a = p.get("address") or {}
    name = (a.get("name") or "").strip()
    addr = ", ".join(x for x in [(a.get("line1") or "").strip(), (a.get("line2") or "").strip()] if x)
    segs = [s.strip() for s in addr.split(",") if s.strip()]
    scheme = next((s for s in segs if not _BARE_UNIT.match(s)), "")
    unit = next((s for s in segs if _BARE_UNIT.match(s)), "")
    if name and not _BARE_UNIT.match(name):
        return name                                   # already descriptive
    if name:                                          # bare unit -> enrich with scheme
        return f"{name}, {scheme}" if scheme and scheme.lower() not in name.lower() else name
    if unit and scheme:
        return f"{unit}, {scheme}"                    # blank name, addr has both
    if scheme:
        return scheme
    # last resort: the folder's middle segment ("<NN> - <Street Town> - <code>" -> "Street Town")
    fol = re.sub(r"^\d+\s*-\s*", "", p.get("folder") or "")
    pc = a.get("postcode")
    if pc and fol.endswith(pc):
        fol = fol[: -len(pc)].rstrip(" -")
    return fol or addr or "tbd"


def norm_postcode(v):
    """Compare postal codes case-folded with ALL whitespace removed, so the same code
    written 'QX1 2CD' on one side and 'qx12cd' on the other is one key. Deliberately
    country-agnostic: this helper must not learn any national postal-code grammar, because
    the skill is generic and a grammar is the fastest way to silently reject a valid code
    from a country nobody tested."""
    if v is None:
        return None
    s = re.sub(r"\s+", "", str(v)).strip().upper()
    return s or None


def _norm_name(v):
    if not v:
        return None
    return re.sub(r"\s+", " ", str(v)).strip().lower() or None


def _unit_key(our, idx):
    """WHICH PHYSICAL UNIT one of our records describes, keyed EXACTLY as dedupe_props keys it.

    This is the evidence that tells apart the two same-postcode cases the pairing must never
    treat alike, and it is the only thing that does:

      * ONE BUILDING LISTED TWICE. Kato surfaces a match request PER BROKER, so the identical
        unit arrives as several of our records. Same postal code AND the same exact floor
        area: dedupe_props merges those into ONE tracker row, so ONE pipeline property comes
        back for the whole group and every member of it carries the same underlying facts.
        They MUST share a key, or the legitimate case the docstring below promises to pair
        stops pairing and the run refuses a corpus that is perfectly fine.

      * TWO DIFFERENT UNITS ON ONE SHARED ESTATE. Same postal code, DIFFERENT areas: two
        genuinely different physical units essentially never share an exact sq ft figure.
        dedupe_props leaves both, the tracker ships two rows, and two pipeline properties come
        back. They MUST NOT share a key, or one building's photos, description, landlord and
        certificates are written onto the other building's card - which is the incident this
        whole module exists to prevent.

    THE AREA IS USED HERE AND NOWHERE ELSE, and that does not contradict the "WHY NOT THE
    FLOOR AREA" note below. That note is about comparing OUR area against the PIPELINE's: the
    pipeline owns the figure it publishes and is free to restate it (a warehouse-only figure
    where we hold a total, a gross-to-net adjustment), so the moment it does, a cross-side
    area key misses. Both figures here are OURS, out of one extractor on one basis, and they
    are only ever compared with each other. No cross-side key is created, and nothing the
    pipeline restates can move this key.

    IT IS dedupe_props' KEY DELIBERATELY, RAW POSTCODE AND ALL - not norm_postcode's. These
    two functions have to agree about what one unit IS, because "the group dedupe_props
    merged" is precisely the set for which exactly one pipeline property exists. Normalising
    the code here would fold a pair that dedupe_props left as two tracker rows (two rows, two
    pipeline properties) into one key, and turn a run that pairs correctly today into a hard
    refusal.

    No code, or no area -> a key of this record's OWN, mirroring dedupe_props' `not all(key)`
    bail-out. Nothing licenses calling such a record a duplicate of anything, and inventing a
    duplicate is the same misattribution running in the other direction."""
    pc = (our.get("address") or {}).get("postcode")
    sqft = (our.get("size") or {}).get("sqft")
    if pc and sqft:
        return ("unit", pc, sqft)
    return ("record", idx)


def _coord_tiebreak(cp, ds, idxs):
    """Narrow several same-postcode candidates (dataset INDICES) to the geographically closest.

    Indices, not record dicts, because the caller reserves whole UNITS and therefore has to be
    able to ask which unit each surviving candidate belongs to - and two of our records can be
    equal dicts, so identity by value is not available.

    A plain squared-degree distance is enough and is NOT a sloppy haversine: this only ever
    separates entries that already share a postal code, so they are a few hundred metres
    apart at most and the latitude distortion of unprojected degrees cannot reorder them.
    Anything that cannot be compared (either side missing or non-numeric coordinates) leaves
    the candidate list untouched rather than dropping candidates, so a bad coordinate can
    never turn a pairable property into an unpairable one."""
    lat, lng = cp.get("lat"), cp.get("lng")
    if lat is None or lng is None:
        return idxs
    scored = []
    for i in idxs:
        m = (ds[i].get("coordinates") or {}).get("map") or {}
        try:
            d = (float(m["lat"]) - float(lat)) ** 2 + (float(m["lng"]) - float(lng)) ** 2
        except (KeyError, TypeError, ValueError):
            continue
        scored.append((d, i))
    if not scored:
        return idxs
    best = min(d for d, _ in scored)
    return [i for d, i in scored if d == best]

def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not cfg.get("work_dir"):
        cfg["work_dir"] = os.path.dirname(os.path.abspath(config_path))
    cfg.setdefault("image_max_px", 1200)
    cfg.setdefault("image_quality", 70)
    cfg.setdefault("headless", True)
    cfg.setdefault("emails_zip", "Emails.zip")
    return cfg

def match_canonical_to_our(canon_properties, ds):
    """Pair each pipeline canonical property with ITS OWN entry in our _dataset.json.

    WHY NOT LIST POSITION. The pipeline assigns canonical ids 1..N after its own
    cross-source dedup, which drops the odd duplicate listing (the same building quoted by
    two brokers) - so canonical id != our dataset 'order' from that point on, and a
    positional zip silently pairs every property after the first dropped duplicate with the
    WRONG source record (photos, description, EPC, landlord all misattributed).

    WHY NOT THE FLOOR AREA. The key used to be (rounded coordinates, floor area). Both
    halves look stable and only one is: the PIPELINE owns the area it publishes, and it may
    bind a warehouse-only figure where we hold a total, or apply a gross-to-net adjustment.
    The moment it does, the key misses.

    WHY A MISS IS NOW FATAL. A miss used to be a bare `continue`: no error, no count, no
    warning. The callers printed a paired count that nobody compared against the expected
    one, so a partial pairing read as a success. That has shipped - a run paired a small
    fraction of its properties and the rest silently kept whatever content the pipeline
    happened to capture, losing every injected description, landlord and link. Silence is
    the whole defect, so an incomplete pairing raises PairingError and no caller catches it.

    THE KEY IS THE POSTAL CODE. It is present on both sides (we write it into the tracker's
    'Postcode' column and the pipeline's column dictionary maps that header to canonical
    `postcode`), it identifies the physical unit rather than its list position, and it is
    immune to every area adjustment. Coordinates are the TIEBREAK only, for the case where
    one code holds more than one of our entries - two units on one shared estate. They are
    deliberately NOT a fallback key: two units in one postal district routinely geocode to
    the SAME point, so a coordinates-only key is ambiguous exactly where it would be used.

    THE NAME NOW NARROWS AS WELL AS FALLING BACK, and it compares like with like. The
    pipeline side supplies `park`, which is the composed display title this module wrote into
    the tracker's 'Property' column, so this side composes the same string with
    display_name(). It used to read the raw address.name, which differs from `park` for
    exactly the nameless-unit properties the fallback exists to catch - so the old fallback
    could only ever fire by accident. It is also no longer reachable ONLY when the postcode
    key finds nothing: it is applied INSIDE a postcode group that holds more than one unit,
    because that is the case it settles best. Two units on one shared estate have DIFFERENT
    composed titles (the unit designator is the very thing display_name preserves and
    enriches) while routinely geocoding to the SAME point, so the name separates them exactly
    where the coordinate tiebreak cannot. A name that matches nothing narrows nothing, on the
    same principle as the coordinate tiebreak: never turn a pairable property unpairable.

    ONE SOURCE RECORD SERVES ONE PROPERTY, AND THAT IS NOW ENFORCED. Keying on the postal
    code with coordinates as a tiebreak still left the hole this function was written to
    close. When the tiebreak could not narrow (two units on one estate geocoding to one
    point), BOTH pipeline properties took `max(candidates, key=description length)` - the same
    record, twice - and nothing checked that a record was used once. Two units, different
    areas, different folders, one source record, no error: one building's photos,
    description, landlord and certificates written onto the other building's card, silently,
    which is the exact failure mode behind this project. So candidates are now resolved as
    UNITS (see _unit_key) and a unit is CLAIMED when a property takes it; a claimed unit is
    off the table for every other property.

    RESOLUTION IS ELIMINATION, AND IT IS ORDER-INDEPENDENT. Every property's candidate units
    come from positive evidence first (postcode, then the composed name, then coordinates);
    only then is the claim rule applied, repeatedly, taking whichever property is down to a
    single unclaimed unit and removing that unit from everyone else. A first-come-first-served
    walk would instead have answered the SAME corpus differently depending on canonical id
    order, and would refuse the ordinary case where one of two same-point units matches on its
    name and the other is left by elimination.

    WHAT IS NOT GUESSED. A property still holding two or more candidate units, or whose every
    candidate has been claimed by another property, is NOT resolved by picking the richest
    description - that is the defect, not a tiebreak. It raises PairingError with what was
    tried, exactly as an unpairable property already did, because a wrong pick here is
    invisible in the deliverable and a refusal costs one re-run. Two units the pipeline itself
    merged into one property land here on purpose: both records hold facts for that one card
    and no evidence says which, so it is a question for the operator, not a coin toss.

    Returns a list of (cp, our) tuples, ALWAYS len(canon_properties) long, in canonical order,
    and NEVER the same source record twice."""
    by_pc, by_name, unit = {}, {}, []
    for i, our in enumerate(ds):
        unit.append(_unit_key(our, i))
        pc = norm_postcode((our.get("address") or {}).get("postcode") or our.get("postcode"))
        if pc:
            by_pc.setdefault(pc, []).append(i)
        nm = _norm_name(display_name(our))
        if nm:
            by_name.setdefault(nm, []).append(i)

    def _units(idxs):
        return {unit[i] for i in idxs}

    # PASS 1 - POSITIVE EVIDENCE ONLY. No elimination here, so the candidate set a property
    # earns on its own evidence does not depend on which properties were resolved before it.
    todo = []
    for cp in canon_properties:
        tried = []
        pc = norm_postcode(cp.get("postcode"))
        idxs = list(by_pc.get(pc) or []) if pc else []
        tried.append("postcode key %s -> %d candidate(s) in %d unit(s)"
                     % (repr(pc) if pc else "(absent on the pipeline side)",
                        len(idxs), len(_units(idxs))))
        if len(_units(idxs)) > 1:
            nm = _norm_name(cp.get("park"))
            named = [i for i in idxs if i in set(by_name.get(nm) or [])] if nm else []
            tried.append("composed-name narrowing park=%r -> %d candidate(s) in %d unit(s)"
                         % (cp.get("park"), len(named), len(_units(named))))
            if named:
                idxs = named
        if len(_units(idxs)) > 1:
            narrowed = _coord_tiebreak(cp, ds, idxs)
            tried.append("coordinate tiebreak %d -> %d candidate(s) in %d unit(s)"
                         % (len(idxs), len(narrowed), len(_units(narrowed))))
            idxs = narrowed
        if not idxs:
            nm = _norm_name(cp.get("park"))
            idxs = list(by_name.get(nm) or []) if nm else []
            tried.append("composed-name fallback park=%r -> %d candidate(s) in %d unit(s)"
                         % (cp.get("park"), len(idxs), len(_units(idxs))))
        todo.append({"cp": cp, "tried": tried, "idxs": idxs, "our": None})

    # PASS 2 - CLAIM AND ELIMINATE, to a fixed point. Each round resolves every property that
    # is down to ONE unclaimed unit; claiming that unit can leave a neighbour with one, so the
    # rounds repeat until a round banks nothing. Terminates because a round either resolves at
    # least one property or breaks.
    claimed = {}                       # unit key -> the pipeline property holding it
    while True:
        progressed = False
        for e in todo:
            if e["our"] is not None:
                continue
            live = [i for i in e["idxs"] if unit[i] not in claimed]
            if len(_units(live)) != 1:
                continue
            claimed[unit[live[0]]] = e["cp"]
            # ONE unit, possibly several of our records: a genuine same-building duplicate
            # listing (two brokers, one property, merged into one tracker row by
            # dedupe_props). Any of them carries the same underlying facts, so prefer the
            # richest description - which is also the record dedupe_props made primary, i.e.
            # the one holding `_dedupe_folders` and therefore every sibling's documents.
            e["our"] = max((ds[i] for i in live),
                           key=lambda o: len(o.get("curated_description") or ""))
            if len(live) > 1:
                e["tried"].append("one unit listed %d times (same postal code AND the same "
                                  "area, so dedupe_props merged them into this single tracker "
                                  "row) -> took the richest description" % len(live))
            progressed = True
        if not progressed:
            break

    unpaired = [e for e in todo if e["our"] is None]
    if unpaired:
        n, total = len(unpaired), len(canon_properties)
        out = ["PAIRING UNSAFE: %d of %d pipeline propert%s could not be tied to EXACTLY ONE "
               "source record. Their injected content (description, landlord, EPC, brochure "
               "/ video / website / street-view links, photos, site plan) would be SILENTLY "
               "ABSENT from the deliverable - or, worse, taken from another building - so "
               "this run stops here." % (n, total, "y" if n == 1 else "ies")]
        for e in unpaired:
            cp = e["cp"]
            live = [i for i in e["idxs"] if unit[i] not in claimed]
            if not e["idxs"]:
                why = "no source record matched on any key"
            elif not live:
                why = ("every candidate record is already bound to another pipeline property "
                       "(%s) - a source record serves ONE property"
                       % ", ".join(sorted({"id %s" % claimed[unit[i]].get("id")
                                           for i in e["idxs"] if unit[i] in claimed})))
            else:
                why = ("AMBIGUOUS: %d distinct units still qualify (%s) and no evidence "
                       "separates them" % (len(_units(live)),
                                           "; ".join(sorted(display_name(ds[i]) or "?"
                                                            for i in live))))
            out.append("  - pipeline id %s  park=%r  postcode=%r  coords=(%s, %s)"
                       % (cp.get("id"), cp.get("park"), cp.get("postcode"),
                          cp.get("lat"), cp.get("lng")))
            out += ["      tried: %s" % t for t in e["tried"]]
            out.append("      %s" % why)
        out.append("  our dataset holds %d record(s) in %d unit(s), %d record(s) under a "
                   "postal code." % (len(ds), len(set(unit)),
                                     sum(len(v) for v in by_pc.values())))
        out.append("  Most likely causes, in order: the tracker's 'Postcode' column was not "
                   "bound to `postcode` in the pipeline's column-map step; the source record "
                   "carries no postal code; the pipeline merged two of our rows into one "
                   "property (then BOTH rows hold facts for it and only you can say which "
                   "belongs on the card); or two units on one estate share a postal code, "
                   "geocode to one point AND no longer carry the composed title we wrote into "
                   "the tracker's 'Property' column - check the column map first, then give "
                   "the two units distinguishable titles.")
        raise PairingError("\n".join(out))

    pairs = [(e["cp"], e["our"]) for e in todo]
    # Belt and braces on the one invariant whose failure is invisible downstream. The claim
    # rule above already makes it impossible, and it is asserted anyway because EVERY caller
    # (patch_canonical, inject_photos, bind_site_plans) writes content through this pairing:
    # a re-used record misattributes a building silently, and an `assert` would evaporate
    # under -O exactly when someone runs this in a hurry.
    seen = {}
    for cp, our in pairs:
        if id(our) in seen:
            raise PairingError(
                "PAIRING UNSAFE: source record %r is bound to pipeline ids %s AND %s. One "
                "record cannot evidence two buildings; this is a bug in "
                "match_canonical_to_our's claim rule, not a data problem."
                % (display_name(our), seen[id(our)].get("id"), cp.get("id")))
        seen[id(our)] = cp
    return pairs

def dedupe_props(props):
    """Kato surfaces one match-request PER BROKER, so the identical physical unit often
    arrives as several rows (the identical unit quoted separately by three different
    agencies) - a client-facing longlist must show it once, not 2-3 times (found by the
    G-visual/G-images reviewers: one estate's unit repeated under each agency, inflating
    the property count with what look like duplicate listings). Group by (postcode, size) -
    two DIFFERENT physical units essentially never share an exact sq ft figure - keep the
    entry with the richest curated_description as primary. Shared by both the toolkit
    tracker (dashboard) and the client Excel, so both deliverables list the same set of
    distinct opportunities. The dropped duplicates' broker/agent detail is recorded ONLY
    on the primary's `_dedupe_note` key - an internal audit note, never written into
    "summary"/"description" (client-facing copy must carry zero broker attribution).

    `_dedupe_folders` carries the merged siblings' property FOLDERS onto the primary, for
    one reason: the documents are per-folder, and "richest description" does not mean
    "holds the brochure". One broker can submit the same unit with a fuller write-up and
    no attachment while another attaches the only brochure there is. Without the sibling
    folders, toolkit_tracker would look in the primary's folder alone, find nothing, and
    report a row as having no machine-readable source while its brochure sat one folder
    away. Same underscore contract as `_dedupe_note`: internal, never a client-facing
    field, and absent from the tracker HEADERS so it cannot leak into a deliverable."""
    groups = {}
    for p in props:
        key = ((p.get("address") or {}).get("postcode"), (p.get("size") or {}).get("sqft"))
        groups.setdefault(key, []).append(p)
    out = []
    for key, group in groups.items():
        if len(group) == 1 or not all(key):
            out.extend(group)
            continue
        primary = max(group, key=lambda p: len(p.get("curated_description") or ""))
        others = [p for p in group if p is not primary]
        extra_notes = []
        for o in others:
            r = o.get("rent") or {}
            agents = "; ".join(a.get("name") for a in (o.get("agents") or []) if a.get("name"))
            bit = f"Also quoted via {o.get('folder')}"
            if agents:
                bit += f" ({agents})"
            if r.get("text"):
                bit += f": {r['text']}"
            extra_notes.append(bit)
        # Copy unconditionally: the primary is a live _dataset.json record and neither the
        # audit note nor the sibling folders belong on the shared object.
        primary = dict(primary)
        if extra_notes:
            primary["_dedupe_note"] = f"Same unit submitted by multiple brokers - {'; '.join(extra_notes)}."
        # Set even when there are no notes to make: a merged sibling can carry the only
        # brochure while carrying no rent or agent text worth noting.
        sib = [o.get("folder") for o in others if o.get("folder")]
        if sib:
            primary["_dedupe_folders"] = sib
        out.append(primary)
    return out

def requirement_id(url):
    m = re.search(r"/requirements/(\d+)", url or "")
    if not m:
        raise SystemExit(f"Could not parse requirement id from url: {url!r}")
    return int(m.group(1))

def sanitize(s, maxlen=120):
    if not s:
        return ""
    s = re.sub(r'[\\/:*?"<>|]', "-", str(s))
    s = re.sub(r"\s+", " ", s).strip().strip(". ")
    return s[:maxlen].strip()

def property_folder(order, name, postcode):
    base = f"{int(order):02d} - {name}" + (f" - {postcode}" if postcode else "")
    return sanitize(base)

def imgix_resize(url, max_px, quality):
    """Add imgix params so the CDN returns a web-sized image directly.
    Constrain BOTH width and height to max_px (fit=max preserves aspect and never
    enlarges), so the LONGEST side is capped - w alone only caps width."""
    if not url or "imgix.net" not in url:
        return url
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query))
    q.update({"w": str(max_px), "h": str(max_px), "fit": "max",
              "auto": "format,compress", "q": str(quality)})
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))

def ensure_image_limits(path, max_px, max_bytes=500 * 1024, quality=70):
    """Safety net: guarantee an image is <=max_px on its longest side and <max_bytes.
    No-op when the file already complies (the imgix-resized majority), so it stays cheap.
    Handles images from hosts other than imgix that couldn't be resized at source."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(path); im.load()
    except Exception:
        return False
    if max(im.size) <= max_px and os.path.getsize(path) <= max_bytes:
        return False
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255)); bg.paste(rgba, mask=rgba.split()[-1]); im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if max(im.size) > max_px:
        s = max_px / float(max(im.size))
        im = im.resize((max(1, int(im.size[0] * s)), max(1, int(im.size[1] * s))), Image.LANCZOS)
    root, _ = os.path.splitext(path); out = root + ".jpg"
    data = None
    for qy in [quality, 60, 50, 40, 32, 25]:
        im.save(out, "JPEG", quality=qy, optimize=True, progressive=True)
        if os.path.getsize(out) <= max_bytes:
            break
    if out.lower() != path.lower() and os.path.exists(path):
        os.remove(path)
    return True

def read_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

# ---- Source Ledger upsert (shared by the Kato post-toolkit injection steps) ----
# The toolkit writes source_ledger.csv from the TRACKER only, so it records "no usable photo"
# for every property and holds no gallery/plan rows. Our inject_photos / bind_site_plans steps
# add real imagery AFTER that, so they MUST upsert ledger rows or the ledger's attribution is
# false (a displayed image with no/'(none)' source is an honesty defect the reviewers catch).
LEDGER_HEADER = ["property_id", "record_type", "field", "value", "source_file", "source_locator",
                 "source_type", "extractor", "confidence", "conflict_note", "verified"]

def upsert_ledger(ledger_path, new_rows, managed):
    """Drop every existing row for a (property_id, field) in `managed` (so a re-run never
    duplicates and a superseded row - e.g. the toolkit's 'no usable photo' gap row - is removed),
    keep all others, then append new_rows. Mirrors patch_canonical.upsert_ledger."""
    kept = []
    if os.path.exists(ledger_path):
        with open(ledger_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (str(row.get("property_id")), row.get("field")) not in managed:
                    kept.append(row)
    with open(ledger_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        w.writeheader()
        for row in kept + list(new_rows):
            w.writerow({k: row.get(k, "") for k in LEDGER_HEADER})

# ---- field derivation from a raw match-detail response -------------------
FILE_FIELDS = ["brochures", "files", "floor_plans", "epcs", "goad_plans", "particulars", "other_files"]

def _dedup(items):
    seen, out = set(), []
    for it in items:
        u = it.get("url")
        if u and u not in seen:
            seen.add(u); out.append(it)
    return out

def derive(raw, list_item=None):
    """Turn a raw match-detail dict into a flat, source-tagged record."""
    li = list_item or {}
    sd = raw.get("society_disposal") or {}
    L = sd.get("letting") or {}
    c = L.get("content") or {}
    mk = L.get("marketing") or {}
    a = L.get("address") or {}
    pos = L.get("position") or {}
    fin = raw.get("financials") or {}
    tl = L.get("transport_links") or {}

    def files(kind_fields):
        out = []
        for k in kind_fields:
            for f in (L.get(k) or []):
                out.append({"name": f.get("name"), "ext": f.get("ext"), "size": f.get("size"),
                            "kind": f.get("type_string"), "url": f.get("url")})
        return _dedup(out)

    def nearest(arr):
        out = []
        for s in (arr or [])[:3]:
            d = s.get("distance")
            out.append(f"{s.get('name')} ({d}mi, {s.get('time')})" if d is not None else s.get("name"))
        return "; ".join(x for x in out if x)

    threads = raw.get("message_threads") or {}
    messages = []
    for tk, t in threads.items():
        for m in (t or {}).get("messages", []) or []:
            messages.append({
                "thread": tk,
                "sender": (m.get("user") or {}).get("name"),
                "org": ((m.get("user") or {}).get("organisation") or {}).get("name"),
                "body": m.get("body"),
                "created_at": m.get("created_at"),
            })

    def money(node):
        if not node or node.get("na"):
            return None
        return node.get("value_sqft") if node.get("value_sqft") is not None else (node.get("value") or node.get("comment"))

    epc = c.get("epc") or {}
    epc_val = epc.get("band") or epc.get("value") or (epc.get("string") if epc.get("string") not in (None, "-") else None)

    return {
        "match_id": raw.get("id"),
        "status": raw.get("status_readable") or raw.get("status"),
        "to_let": bool(L.get("to_let") or sd.get("to_let")),
        "for_sale": bool(L.get("for_sale") or sd.get("for_sale")),
        "tenure": sd.get("tenure_string"),
        "possession": sd.get("possession"),
        "address": {
            "name": a.get("name"), "line1": a.get("line1"), "line2": a.get("line2"),
            "town": a.get("town"), "county": a.get("county"), "postcode": a.get("postcode"),
            "uprn": a.get("uprn"),
            "full": ", ".join([x for x in [a.get("name"), a.get("line1"), a.get("line2"),
                                           a.get("town"), a.get("county"), a.get("postcode")] if x]),
        },
        "area": (li.get("submarkets") if isinstance(li.get("submarkets"), str) else None),
        "coordinates": {"map": pos.get("map"), "street_view": pos.get("street_view")},
        "size": {"from": (c.get("size") or {}).get("from"), "to": (c.get("size") or {}).get("to"),
                 "string": (c.get("size") or {}).get("string")},
        "rent_kato": {"string": (c.get("rent") or {}).get("string"),
                      "from": (c.get("rent") or {}).get("from"), "to": (c.get("rent") or {}).get("to")},
        "price": {"string": (c.get("price") or {}).get("string"), "value": (c.get("price") or {}).get("value")},
        "service_charge": money(c.get("service_charge")),
        "rates_payable": money(c.get("business_rate")),
        "estate_charge": money(c.get("estate_charge")),
        "total_sqft": (fin.get("total") or {}).get("value"),
        "total_pa": (fin.get("total_per_annum") or {}).get("value"),
        "epc": epc_val,
        "lease": (c.get("lease") or {}).get("string"),
        "building_types": c.get("building_types_string"),
        "fitted_space": c.get("fitted_space_string"),
        "key_points": [k.get("name") for k in (mk.get("key_points") or []) if k.get("name")],
        "amenities": [f"{x.get('label')}: {x.get('value')}" for x in (L.get("amenities_specifications") or [])],
        "summary": mk.get("summary"), "description": mk.get("description"),
        "location_text": mk.get("location"), "notes": mk.get("notes"),
        "website": c.get("microsite_url") or c.get("website_url") or mk.get("public_website_link"),
        "videos": [{"description": v.get("description"), "url": v.get("url")} for v in (c.get("videos") or [])],
        "documents": files(FILE_FIELDS),
        "images": [{"name": f.get("name"), "url": f.get("url")} for f in (L.get("images") or [])],
        "available_spaces": [{"name": s.get("name") or s.get("floor"), "sqft": s.get("sizeSqFt") or s.get("size"),
                              "avail": s.get("availability")} for s in (L.get("available_spaces") or [])],
        "tube": nearest(tl.get("tube_stations")),
        "train": nearest(tl.get("train_stations")),
        "agents": [{"name": u.get("name"), "position": u.get("position"), "tel": u.get("tel"),
                    "mobile": u.get("mobile"), "email": u.get("email")} for u in (L.get("assigned_users") or [])],
        "agent_organisation": sd.get("organisation"),
        "landlord_confidential": bool(L.get("landlord_confidential")),
        "landlord_companies": [x.get("name") for x in (L.get("landlord_companies") or [])],
        "messages": messages,
        "published_at": sd.get("published_at"), "updated_at": sd.get("updated_at"),
        "group_position": li.get("group_position"),
    }
