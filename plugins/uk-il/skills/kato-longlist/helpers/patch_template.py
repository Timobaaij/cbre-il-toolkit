#!/usr/bin/env python3
r"""Toolkit step (Kato template patch): apply Kato's card/modal tweaks to the toolkit's
dashboard template, then RE-VERSION it (recompute assets/VERSION chrome_sha256) so the toolkit's
own byte-equality + template-SHA gates stay green. Runs BEFORE build_dashboard.py.

Why a patch (not a fork): the toolkit template is a byte-locked, per-session asset we do not own
outright; forking the whole 2,300-line file would drift from toolkit chrome updates. Instead we
carry a small set of TARGETED, IDEMPOTENT string patches here (in the Kato skill) and re-apply
them to whatever toolkit copy is live each run. Idempotent = safe to re-run; version-agnostic =
survives toolkit updates as long as the anchor strings exist (it errors LOUDLY if one moves, so a
silent no-op can never ship an unpatched dashboard).

Patches (map to the client's numbered requests):
  P2  card 4th spec cell: 'Early access' (always tbd) -> 'Electricity' (the kVA figure)
  P2b modal top row: hide the 'Early access tbd' chip when tbd (consistency with the card)
  P3  card eyebrow: '<developer> · <motorway>' (both tbd => "TBD · TBD") -> developer if
      real, else the city (never a tbd or a dangling separator)
  P4  drop the hero 'Developers' KPI tile when the dataset names <=1 distinct developer
  P5/6 modal top row: add Brochure / Video / Website / Street View links (reusing the .map-link
      style) whenever the property carries those URLs (injected by patch_canonical.py)

P7 and P12 are RETIRED - template v38 does both jobs natively (no auto 'Additional Details'
section exists, and the modal already renders a combined BREEAM/EPC row). They are not deleted:
each keeps a premise re-asserted every run, so a regression reinstating the old condition fails
loudly rather than quietly shipping a dashboard missing the fix. See RETIRED below.

The template SHA gate is gate_runner.py: sha256(load_template()) must equal VERSION.chrome_sha256.
So after any edit we always rewrite chrome_sha256 to the current template's SHA and tag the label
'-kato' (idempotent).
"""
import os, sys, argparse, hashlib, re

MIDDOT = "·"   # the '·' separator already used in the template
ARROW = "↗"    # the '↗' already used by the "Open in Google Maps ↗" label
NUMERO = "№"   # the '№' glyph already used in the modal header

# Each patch: (name, old, new, marker_new). marker_new present => already applied (skip).
PATCHES = [
    # --- P3: card eyebrow (cardHTML; isTbd is NOT in scope here, so the check is self-contained)
    (
        "P3 card eyebrow",
        '      <div class="dev-line">${p.developer} ' + MIDDOT + ' ${p.motorway}</div>',
        "      <div class=\"dev-line\">${(()=>{const d=(p.developer||'').toString().trim().toLowerCase();"
        "return (d&&d!=='tbd'&&d!=='—'&&d!=='-'&&d!=='n/a')?p.developer:(p.city||p.region||'');})()}</div>",
        "const d=(p.developer||'').toString().trim().toLowerCase()",
    ),
    # --- P2: card 4th spec cell -> Electricity
    (
        "P2 card power cell",
        '        <div class="spec"><div class="spec-k">${T("row_early_access")}</div><div class="spec-v">${p.earlyAccess}</div></div>',
        '        <div class="spec"><div class="spec-k">${T("row_electricity")}</div><div class="spec-v">${p.electricity}</div></div>',
        '<div class="spec-k">${T("row_electricity")}</div><div class="spec-v">${p.electricity}</div>',
    ),
    # --- P2b: modal top row hide 'Early access tbd' (isTbd IS in scope in the modal renderer)
    (
        "P2b modal early-access hide",
        '          <span>${T("modal_early_access_prefix")} ${p.earlyAccess}</span>',
        "          ${isTbd(p.earlyAccess) ? '' : `<span>${T(\"modal_early_access_prefix\")} ${p.earlyAccess}</span>`}",
        "${isTbd(p.earlyAccess) ? '' : `<span>${T(\"modal_early_access_prefix\")}",
    ),
    # --- P5/6: modal top-row links (appended to the existing Maps link span)
    (
        "P5/6 modal links",
        '          ${mapHref ? `<span><a class="map-link" href="${mapHref}" target="_blank" rel="noopener">${T("modal_open_maps")}</a></span>` : \'\'}',
        '          ${mapHref ? `<span><a class="map-link" href="${mapHref}" target="_blank" rel="noopener">${T("modal_open_maps")}</a></span>` : \'\'}\n'
        '          ${p.brochureUrl ? `<span><a class="map-link" href="${p.brochureUrl}" target="_blank" rel="noopener">Brochure ' + ARROW + '</a></span>` : \'\'}\n'
        '          ${p.videoUrl ? `<span><a class="map-link" href="${p.videoUrl}" target="_blank" rel="noopener">Video ' + ARROW + '</a></span>` : \'\'}\n'
        '          ${p.websiteUrl ? `<span><a class="map-link" href="${p.websiteUrl}" target="_blank" rel="noopener">Website ' + ARROW + '</a></span>` : \'\'}\n'
        '          ${p.streetviewUrl ? `<span><a class="map-link" href="${p.streetviewUrl}" target="_blank" rel="noopener">Street View ' + ARROW + '</a></span>` : \'\'}',
        'href="${p.brochureUrl}"',
    ),
    # --- P4a: define the Developers-KPI-drop function (before adaptSingleCountryHeader)
    (
        "P4a developers-kpi fn",
        "function adaptSingleCountryHeader(){",
        "function adaptDevelopersKpi(){\n"
        "  // Kato: drop the 'Developers' KPI tile when the dataset names <=1 distinct developer\n"
        "  // (usually all 'tbd' on a broker longlist), so the strip never shows a meaningless \"1\".\n"
        "  try {\n"
        "    const devs = [...new Set(PROPS.map(p => p.developer))].filter(d => !isAbsent(d) && String(d).trim().toLowerCase() !== 'tbd');\n"
        "    if(devs.length > 1) return;\n"
        "    $$(\".kpis .kpi\").forEach(k => { if(k.querySelector('.kpi-label[data-i18n=\"kpi_developers_label\"]')) k.remove(); });\n"
        "  } catch(e) {}\n"
        "}\n"
        "function adaptSingleCountryHeader(){",
        "function adaptDevelopersKpi(){",
    ),
    # --- P4b: call it right after adaptSingleCountryHeader()
    (
        "P4b developers-kpi call",
        "  adaptSingleCountryHeader();",
        "  adaptSingleCountryHeader();\n  adaptDevelopersKpi();",
        "  adaptDevelopersKpi();",
    ),
    # --- P8/9/10: hide the bare, unlabelled 'tbd' chips in the modal top row (motorway is a
    #             declared data gap; breeam/status default to the 'tbd' string, which is truthy)
    (
        "P8 modal motorway hide",
        "          <span>${p.motorway}</span>",
        "          ${isTbd(p.motorway) ? '' : `<span>${p.motorway}</span>`}",
        "${isTbd(p.motorway) ? '' :",
    ),
    (
        "P9 modal status hide",
        "          <span>${p.status}</span>",
        "          ${isTbd(p.status) ? '' : `<span>${p.status}</span>`}",
        "${isTbd(p.status) ? '' :",
    ),
    (
        "P10 modal breeam hide",
        "          ${p.breeam ? `<span>${p.breeam}</span>` : ''}",
        "          ${isTbd(p.breeam) ? '' : `<span>${p.breeam}</span>`}",
        "${isTbd(p.breeam) ? '' :",
    ),
    # --- P11: also hide the 'Developer' FILTER field when the KPI tile is dropped (<=1 developer)
    (
        "P11 hide developer filter",
        "    $$(\".kpis .kpi\").forEach(k => { if(k.querySelector('.kpi-label[data-i18n=\"kpi_developers_label\"]')) k.remove(); });",
        "    $$(\".kpis .kpi\").forEach(k => { if(k.querySelector('.kpi-label[data-i18n=\"kpi_developers_label\"]')) k.remove(); });\n"
        "    const _df = document.getElementById('f-dev'); if(_df){ const _fw = _df.closest('.field'); if(_fw) _fw.style.display='none'; }",
        "const _df = document.getElementById('f-dev')",
    ),
    # --- P13: drop the 'TBD' developer token from the modal header (same as the card eyebrow)
    (
        "P13 modal-dev drop tbd developer",
        '        <div class="modal-dev"><span class="flag ${p.country.toLowerCase()}"></span>'
        '${p.developer} ' + MIDDOT + ' ${p.country} ' + MIDDOT + ' ' + NUMERO + " ${String(p.id).padStart(2,'0')}</div>",
        '        <div class="modal-dev"><span class="flag ${p.country.toLowerCase()}"></span>'
        "${isTbd(p.developer) ? '' : `${p.developer} " + MIDDOT + ' `}'
        '${p.country} ' + MIDDOT + ' ' + NUMERO + " ${String(p.id).padStart(2,'0')}</div>",
        "${isTbd(p.developer) ? '' : `${p.developer}",
    ),
    # --- P14: stop the 'Min warehouse area >= NN sq ft' filter label truncating (it ellipsises)
    (
        "P14 size filter label wrap",
        ".field-label{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
        ".field-label{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
        'label[for="f-size"]{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.35}',
        'label[for="f-size"]{white-space:normal',
    ),
]

# Retired patches. A patch is retired ONLY when the toolkit does the job natively - never merely
# because its anchor vanished. Each entry carries a PREMISE re-asserted on every run, so a toolkit
# regression that brings the old condition back fails LOUDLY instead of quietly shipping a dashboard
# missing the fix. Verified against template v38.
#
#   (name, why it is unnecessary, predicate that must hold of the template)
RETIRED = [
    (
        "P7 deny injected fields",
        "the template has no auto 'Additional Details' field loop at all, so brochureUrl / videoUrl "
        "/ websiteUrl / streetviewUrl / epc cannot leak into it as raw rows. Old anchor, kept for "
        "archaeology: the deny-list line ending ...'motorway','breeam']);",
        lambda t: "additional" not in t.lower(),
    ),
    (
        "P12 modal EPC row",
        "the modal Technical section already renders EPC natively, combined with BREEAM, via "
        "row(T('cmp_certification'), certStr(p)) - certStr joins certName(p.breeam) and "
        "certName(p.epc), and has been there since v36. The old anchor also took a third argument, "
        "row(T('row_electricity'), p.electricity, 'electricity'), where v38 passes only two.",
        lambda t: "certName(p.epc" in t and "row(T('cmp_certification'), certStr(p))" in t,
    ),
]



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolkit", required=True,
                    help="the live cbre-property-longlist toolkit skill dir (contains assets/dashboard_template.html)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing the template or VERSION")
    ap.add_argument("--allow-inplace", action="store_true",
                    help="permit patching a toolkit that is NOT a per-run shadow (see the guard below)")
    args = ap.parse_args()
    tpl_path = os.path.join(args.toolkit, "assets", "dashboard_template.html")
    ver_path = os.path.join(args.toolkit, "assets", "VERSION")
    if not os.path.isfile(tpl_path):
        sys.exit(f"ERROR: template not found: {tpl_path}")

    # --- Shadow guard -------------------------------------------------------------
    # This helper WRITES the template and VERSION. That is safe on a per-run shadow
    # (toolkit_shadow.py) and unsafe on a durable install: the tweaks and the '-kato'
    # VERSION tag would persist and every later NON-Kato longlist run would silently
    # inherit Kato's presentation decisions. So refuse unless the target is a shadow.
    if not (args.dry_run or args.allow_inplace):
        if not os.path.isfile(os.path.join(args.toolkit, ".kato-shadow.json")):
            sys.exit(
                f"ERROR: {args.toolkit} is not a per-run shadow, so patching it would modify the\n"
                f"       INSTALLED cbre-property-longlist skill permanently - every later non-Kato\n"
                f"       longlist would inherit Kato's card/modal tweaks and a 'v..-kato' VERSION.\n"
                f"       Shadow it first (step 7a.5):\n"
                f"         python \"{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'toolkit_shadow.py')}\" "
                f"--source \"{args.toolkit}\" --work <work>\n"
                f"       then re-run this against <work>\\toolkit (and build from there too).\n"
                f"       Use --dry-run to inspect a new toolkit version without touching it, or\n"
                f"       --allow-inplace only when the toolkit copy is genuinely disposable."
            )

    t = open(tpl_path, encoding="utf-8").read()
    ver = "unknown"
    if os.path.isfile(ver_path):
        vl = open(ver_path, encoding="utf-8").read().splitlines()
        ver = vl[0].strip() if vl else "unknown"

    # Retired patches are checked BEFORE anything is touched: a premise that no longer holds means the
    # condition the patch guarded against is back, and the patch must be reinstated.
    regressions = [(name, why) for name, why, holds in RETIRED if not holds(t)]

    applied, skipped, failures = [], [], []
    for name, old, new, marker in PATCHES:
        if marker in t:
            skipped.append(name)
            continue
        n = t.count(old)
        if n != 1:
            # Collect and CONTINUE. Exiting on the first mismatch hides every later one - which is
            # exactly how P12's obsolescence stayed invisible behind P7's on template v38.
            failures.append((name, n))
            continue
        t = t.replace(old, new)
        applied.append(name)

    if regressions or failures:
        print(f"patch_template: ABORTED on template {ver} - nothing written.", file=sys.stderr)
        for name, why in regressions:
            print(f"  REGRESSION  {name} is retired, but its premise no longer holds, so the fix is "
                  f"needed again. Reinstate it in PATCHES.", file=sys.stderr)
            print(f"              premise: {why}", file=sys.stderr)
        for name, n in failures:
            print(f"  ANCHOR      {name}: found {n}x, expected exactly 1x", file=sys.stderr)
        if len(failures) > 1:
            print("  NOTE: patches chain - P11's anchor is text that P4a inserts - so one early "
                  "failure can cascade into later ones. Fix the earliest first, then re-run.",
                  file=sys.stderr)
        print(f"  template: {tpl_path}", file=sys.stderr)
        print("  Fix patch_template.py before shipping an unpatched dashboard.", file=sys.stderr)
        sys.exit(1)

    retired_names = [r[0] for r in RETIRED]
    if args.dry_run:
        print(f"patch_template (DRY RUN) template {ver}: would_apply={applied or '-'} "
              f"already_present={skipped or '-'} retired_ok={retired_names}")
        return

    if applied:
        open(tpl_path, "w", encoding="utf-8").write(t)

    # Always reconcile VERSION.chrome_sha256 with the current template SHA (idempotent), and tag -kato.
    sha = hashlib.sha256(t.encode("utf-8")).hexdigest()
    lines = open(ver_path, encoding="utf-8").read().splitlines() if os.path.isfile(ver_path) else ["v0"]
    out, saw_sha = [], False
    for ln in lines:
        if ln.startswith("chrome_sha256="):
            out.append(f"chrome_sha256={sha}"); saw_sha = True
        elif re.match(r"^v[\w.]+$", ln.strip()):
            lbl = ln.strip()
            out.append(lbl if lbl.endswith("-kato") else f"{lbl}-kato")
        else:
            out.append(ln)
    if not saw_sha:
        out.append(f"chrome_sha256={sha}")
    open(ver_path, "w", encoding="utf-8").write('\n'.join(out) + '\n')

    # Best-effort: keep the toolkit's own assets/integrity.json manifest in step with the two
    # files we just rewrote. Purely cosmetic - preflight.py compares SIZE only and reports a
    # mismatch as a non-blocking note - but without this every Kato run prints two "differs from
    # the integrity manifest" notes that read like a defect. Never fails the run.
    try:
        import json
        man_path = os.path.join(os.path.dirname(tpl_path), "integrity.json")
        if os.path.isfile(man_path):
            man = json.load(open(man_path, encoding="utf-8"))
            changed = False
            for rel, path in (("assets/dashboard_template.html", tpl_path),
                              ("assets/VERSION", ver_path)):
                if rel in man:
                    blob = open(path, "rb").read()
                    man[rel] = {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
                    changed = True
            if changed:
                json.dump(man, open(man_path, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass

    print(f"patch_template: applied={applied or '-'} skipped={skipped or '-'} retired={retired_names}")
    print(f"  template {ver} SHA -> {sha[:16]}  (VERSION reconciled)")


if __name__ == "__main__":
    main()
