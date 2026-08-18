"""Shared helpers for the Kato-Longlist skill."""
import os, re, csv, json, yaml, urllib.parse

KATO_ORIGIN = "https://agency.kato.app"

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
    """Pair each toolkit canonical property with ITS OWN entry in our _dataset.json.

    The toolkit assigns canonical ids 1..N after its own cross-source dedup, which drops
    the odd duplicate listing (e.g. the same building quoted by two brokers) - so canonical
    id != our dataset 'order' from that point on, and a positional zip/lookup silently pairs
    every property after the first dropped duplicate with the WRONG source record (photos,
    description, EPC, landlord etc. all misattributed). Match on (coordinates, size) instead,
    which survives the dedup because it identifies the physical unit, not its list position.
    Falls back to (name, size) for any coordinate-less property. Returns a list of (cp, our)
    tuples - one entry per canonical property that found a match (never fewer canon entries
    lost silently; a genuine miss is just absent from the returned list, exactly like the old
    `by_order.get(...)` returning None did).
    """
    def _key_coord(entry_lat, entry_lng, sqft):
        if entry_lat is None or entry_lng is None or sqft is None:
            return None
        return (round(entry_lat, 5), round(entry_lng, 5), sqft)

    def _key_name(name, sqft):
        if not name or sqft is None:
            return None
        return (re.sub(r"\s+", " ", str(name)).strip().lower(), sqft)

    by_coord, by_name = {}, {}
    for our in ds:
        m = (our.get("coordinates") or {}).get("map") or {}
        sqft = (our.get("size") or {}).get("sqft")
        name = (our.get("address") or {}).get("name")
        kc = _key_coord(m.get("lat"), m.get("lng"), sqft)
        if kc is not None:
            by_coord.setdefault(kc, []).append(our)
        kn = _key_name(name, sqft)
        if kn is not None:
            by_name.setdefault(kn, []).append(our)

    pairs = []
    for cp in canon_properties:
        sqft = cp.get("warehouseArea")
        sqft_i = int(round(sqft)) if isinstance(sqft, (int, float)) else sqft
        candidates = by_coord.get(_key_coord(cp.get("lat"), cp.get("lng"), sqft_i)) or []
        if not candidates:
            candidates = by_name.get(_key_name(cp.get("park"), sqft_i)) or []
        if not candidates:
            continue
        # a genuine same-building duplicate listing (two brokers, one property): any
        # candidate carries the same underlying facts, prefer the richest description.
        our = max(candidates, key=lambda o: len(o.get("curated_description") or ""))
        pairs.append((cp, our))
    return pairs

def dedupe_props(props):
    """Kato surfaces one match-request PER BROKER, so the identical physical unit often
    arrives as several rows (e.g. the same Urban 8 unit quoted separately by Newmark,
    Harris Lamb and DTRE) - a client-facing longlist must show it once, not 2-3 times
    (found by the G-visual/G-images reviewers: 'Unit 8, Urban 8' etc. inflating the
    property count with what look like duplicate listings). Group by (postcode, size) -
    two DIFFERENT physical units essentially never share an exact sq ft figure - keep the
    entry with the richest curated_description as primary. Shared by both the toolkit
    tracker (dashboard) and the client Excel, so both deliverables list the same set of
    distinct opportunities. The dropped duplicates' broker/agent detail is recorded ONLY
    on the primary's `_dedupe_note` key - an internal audit note, never written into
    "summary"/"description" (client-facing copy must carry zero broker attribution)."""
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
        if extra_notes:
            primary = dict(primary)
            primary["_dedupe_note"] = f"Same unit submitted by multiple brokers - {'; '.join(extra_notes)}."
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
