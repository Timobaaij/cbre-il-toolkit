#!/usr/bin/env python3
"""
Stage 1 - Kato fetch (self-contained, deterministic).

Playwright logs in ONCE to capture the session cookies, then everything else is
plain `requests`: enumerate the longlist, save each property's RAW detail JSON,
and download its media (images resized at source via imgix; brochures as-is).

Idempotent: existing _raw.json and media files are skipped unless --refresh.

Usage:
  python kato_fetch.py --config "C:\\path\\to\\run.yaml" [--refresh]
"""
import os, sys, json, time, argparse, urllib.parse
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_config, requirement_id, sanitize, property_folder,
                    imgix_resize, ensure_image_limits, read_json, write_json, derive, KATO_ORIGIN)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

def login_cookies(email, password, headless):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.goto(f"{KATO_ORIGIN}/login", wait_until="domcontentloaded")
        page.get_by_role("textbox", name="Email Address").fill(email)
        page.get_by_role("textbox", name="Password").fill(password)
        page.get_by_role("button", name="Log in").click()
        # success = redirect away from /login
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=40000)
        except Exception:
            page.wait_for_timeout(4000)
        page.wait_for_timeout(2500)
        if "/login" in page.url:
            body = page.inner_text("body")[:400]
            browser.close()
            raise SystemExit("Login failed (still on /login). If reCAPTCHA blocked it, set headless: false.\n" + body)
        cookies = ctx.cookies()
        browser.close()
    return cookies

def make_session(cookies):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "X-Requested-With": "XMLHttpRequest", "Referer": KATO_ORIGIN + "/"})
    xsrf = None
    for c in cookies:
        if "kato.app" in c.get("domain", ""):
            s.cookies.set(c["name"], c["value"], domain=c["domain"].lstrip("."), path=c.get("path", "/"))
            if c["name"] == "XSRF-TOKEN":
                xsrf = urllib.parse.unquote(c["value"])
    if xsrf:
        s.headers["X-XSRF-TOKEN"] = xsrf
    return s

def get_json(session, url, tries=4):
    for i in range(tries):
        r = session.get(url, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503) and i < tries - 1:
            time.sleep(1.5 * (i + 1)); continue
        raise SystemExit(f"GET {url} -> {r.status_code}: {r.text[:200]}")

def download(session, url, dest, refresh=False):
    if os.path.exists(dest) and not refresh and os.path.getsize(dest) > 0:
        return ("skip", os.path.getsize(dest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        with session.get(url, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        return ("ok", os.path.getsize(dest))
    except Exception as e:
        if os.path.exists(dest):
            os.remove(dest)
        return ("fail", str(e))

def download_image(session, original_url, dest, max_px, quality, refresh=False, max_bytes=500 * 1024):
    """Fetch an imgix image resized at source; step quality down server-side until <500KB."""
    if os.path.exists(dest) and not refresh and 0 < os.path.getsize(dest) <= max_bytes:
        return ("skip", os.path.getsize(dest))
    last = ("fail", "no attempt")
    for qy in [quality, 60, 50, 40, 32, 25]:
        status, info = download(session, imgix_resize(original_url, max_px, qy), dest, refresh=True)
        last = (status, info)
        if status != "ok":
            continue
        if info <= max_bytes or "imgix.net" not in (original_url or ""):
            break
    if last[0] == "ok":
        # safety net: cap dimensions/size locally for non-imgix or still-oversize files
        ensure_image_limits(dest, max_px, max_bytes=max_bytes, quality=quality)
        return ("ok", os.path.getsize(dest) if os.path.exists(dest) else os.path.getsize(os.path.splitext(dest)[0] + ".jpg"))
    return last

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--refresh", action="store_true", help="re-fetch raw + re-download media")
    args = ap.parse_args()

    cfg = load_config(args.config)
    work = cfg["work_dir"]
    reqid = requirement_id(cfg["kato_url"])
    props_dir = os.path.join(work, "properties")
    os.makedirs(props_dir, exist_ok=True)
    max_px, q = cfg["image_max_px"], cfg["image_quality"]

    print(f"Requirement {reqid} | work_dir={work}", flush=True)
    print("Logging in via Playwright ...", flush=True)
    cookies = login_cookies(cfg["email"], cfg["password"], cfg.get("headless", True))
    s = make_session(cookies)

    # sanity: the list endpoint must authenticate
    list_url = f"{KATO_ORIGIN}/api/acquisitions/{reqid}/availability-schedule?order=group_position"
    data = get_json(s, list_url).get("data", [])
    longlist = [m for m in data if m.get("status") == 1]
    longlist.sort(key=lambda m: (m.get("group_position") if m.get("group_position") is not None else 1e9))
    print(f"Longlist matches (status==1): {len(longlist)} of {len(data)} total", flush=True)

    # idempotency is keyed on match_id via the previous index (stable folder names)
    prev = read_json(os.path.join(props_dir, "_index.json"), {}) or {}
    prev_folder = {p["match_id"]: p["folder"] for p in prev.get("properties", [])}

    index, media_jobs, fetch_report = [], [], {"raw_fetched": 0, "raw_cached": 0}
    for i, li in enumerate(longlist, 1):
        mid = li["id"]
        detail_url = f"{KATO_ORIGIN}/api/acquisitions/availability-schedule/{mid}"
        raw, folder, pdir = None, None, None
        if not args.refresh and mid in prev_folder:
            cand = os.path.join(props_dir, prev_folder[mid])
            if os.path.exists(os.path.join(cand, "_raw.json")):
                raw = read_json(os.path.join(cand, "_raw.json"))
                folder, pdir = prev_folder[mid], cand
                fetch_report["raw_cached"] += 1
        if raw is None:
            raw = get_json(s, detail_url)
            rec0 = derive(raw, li)
            name = rec0["address"].get("name") or li.get("address_name") or f"match-{mid}"
            folder = property_folder(i, name, rec0["address"].get("postcode") or "")
            pdir = os.path.join(props_dir, folder)
            os.makedirs(pdir, exist_ok=True)
            write_json(os.path.join(pdir, "_raw.json"), raw)
            fetch_report["raw_fetched"] += 1
        rec = derive(raw, li)
        write_json(os.path.join(pdir, "_derived.json"), rec)
        index.append({"order": i, "match_id": mid, "folder": folder,
                      "name": rec["address"].get("name"), "postcode": rec["address"].get("postcode"),
                      "for_sale": rec["for_sale"], "to_let": rec["to_let"],
                      "group_position": li.get("group_position")})
        # queue media (documents as-is; images resized at source with a size ladder)
        for d in rec["documents"]:
            fn = sanitize(d.get("name") or os.path.basename(urllib.parse.urlparse(d["url"]).path)) or "file"
            media_jobs.append((d["url"], os.path.join(pdir, "media", fn), "doc"))
        for j, im in enumerate(rec["images"], 1):
            nm = sanitize(im.get("name") or f"image-{j}")
            base, ext = os.path.splitext(nm)
            if not ext:
                ext = ".jpg"
            dest = os.path.join(pdir, "media", "images", f"{j:02d} - {base}{ext}")
            media_jobs.append((im["url"], dest, "image"))
        print(f"  [{i:02d}/{len(longlist)}] {folder}  docs={len(rec['documents'])} imgs={len(rec['images'])}", flush=True)

    write_json(os.path.join(props_dir, "_index.json"),
               {"requirement_id": reqid, "count": len(index), "properties": index})

    # download media (idempotent)
    print(f"Downloading {len(media_jobs)} media files ...", flush=True)
    dl = {"ok": 0, "skip": 0, "fail": 0}
    fails = []
    for k, (url, dest, kind) in enumerate(media_jobs, 1):
        if kind == "image":
            status, info = download_image(s, url, dest, max_px, q, refresh=args.refresh)
        else:
            status, info = download(s, url, dest, refresh=args.refresh)
        dl[status] = dl.get(status, 0) + 1
        if status == "fail":
            fails.append({"url": url, "dest": dest, "error": info})
        if k % 40 == 0:
            print(f"    {k}/{len(media_jobs)}", flush=True)
    fetch_report.update({"properties": len(index), "media": dl, "media_failures": fails[:50]})
    write_json(os.path.join(props_dir, "_fetch_report.json"), fetch_report)
    print(f"DONE. properties={len(index)} raw(fetched={fetch_report['raw_fetched']},cached={fetch_report['raw_cached']}) "
          f"media ok={dl['ok']} skip={dl['skip']} fail={dl['fail']}", flush=True)

if __name__ == "__main__":
    main()
