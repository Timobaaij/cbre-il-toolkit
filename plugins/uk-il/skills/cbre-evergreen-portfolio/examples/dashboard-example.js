/* =====================================================================
   dashboard-example.js — a complete report/dash.js.

   It rebuilds the reference occupier dashboard (map, lease expiry, rent,
   landlords, asset quality, five findings, unit table) WITHOUT a single
   client fact in it: every number, name and date in the copy is computed
   from the rows at run time. Copy it as a starting point, then cut, reorder
   and invent — see reference/dashboard-engine.md.

   What each part demonstrates is marked  >>
   ===================================================================== */

const A = DASH.api;            // >> the helper kit is usable at config time too

/* ---------------------------------------------------------------------
   Small local helpers. dash.js runs in its own function scope, so these
   names cannot collide with the engine's.
   --------------------------------------------------------------------- */
const leased = rows => rows.filter(r => !r.owned);
const andList = xs => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
const byCount = (rows, key) => A.by(rows, key).sort((a, b) => b.n - a.n || b.sf - a.sf);
const place = r => r.town || r.short;             // >> fields may be null: always have a fallback
const size = r => A.sf(r.size) || "size n/r";
// >> meta.json is free-form: a report may add keys such as clientShort ("Acme" for "Acme Group")
const client = api => api.meta.clientShort || api.meta.client || "the business";
const median = xs => { const s = xs.slice().sort((a, b) => a - b), m = s.length >> 1;
  return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : null; };

/* ---------------------------------------------------------------------
   >> DASH.set: one object, merged. Strings or functions (rows, api).
   Title and findings functions receive ALL units; panel copy and metrics
   receive the VISIBLE units, so they stay true under every filter.
   --------------------------------------------------------------------- */
DASH.set({

  /* >> the title band: h1 + a second line in sage, a lede, a meta row */
  title: {
    h1: (rows, api) => api.meta.client || "Portfolio",
    h1Light: (rows, api) => (api.meta.sector || "Property").replace(/\bLogistics\b/, "logistics") + " estate",
    lede: (rows, api) => {
      const m = api.summary(rows);
      const groups = api.group.order.filter(k => k !== api.NR).length;
      const pre = api.pct(api.sum(rows.filter(r => r.quality === "Second Hand (Built Before 2010)")), m.tot);
      // >> landlord shares are of THIRD-PARTY leased floorspace (m.tpSf): an
      //    intra-group landlord is not exposure
      const top = api.pctS(m.topK, m.tpSf);
      const who = client(api);
      // >> api.pluralWord / api.noun: one plural rule ("One landlord holds", "Five landlords hold")
      return api.pluralWord(rows.length, "unit") + " and <b>" + api.msf(m.tot) + " sq ft</b>" +
        (groups > 1 ? " across " + api.word(groups) + " " + api.group.plural : "") +
        " &mdash; but <b>" + api.pctS(m.leasedSf, m.tot) + "%</b> of that floorspace is leased" +
        (pre ? ", <b>" + pre + "%</b> of it is second-hand stock built before 2010," : ",") +
        (m.nll > m.k ? " and <b>" + api.pluralWord(m.k, "landlord").toLowerCase() + " " + api.noun(m.k, "holds", "hold") +
                       " " + top + "%</b> of what " + who + " rents from third parties." :
                       " and it is rented from " + api.plural(m.nll, "third-party landlord") + ".") +
        (m.nll > m.k && +top >= 50 ? " This portfolio's cost and continuity are settled in a handful of rooms, not " +
          api.word(rows.length) + "." : "");
    },
    // >> anything the report adds to meta.json is readable as api.meta.*
    meta: (rows, api) => [
      "Source: EverGreen export, " + api.longDate(api.meta.exportDate || api.asAt),
      rows.length + " records" + (api.meta.fields ? " · " + api.meta.fields + " fields" : ""),
      api.meta.caveat || null
    ]
  },

  /* >> the group dimension: which field, what to call it. Colours default to
     the ordered CBRE palette in floorspace order — pin them only if the
     client has house colours: colours: {"Name": "#hex"} */
  group: { field: "group", label: "Operating company", short: "Company" },

  /* >> the page's words (dashboard-engine.md §3.2): change a word here, never by
     rewriting the page after it renders. Uncomment to try:
  labels: {
    unit: "building", units: "buildings",           // "Showing 12 of 40 buildings", "Every building"
    state: { undated: "No dates recorded" },         // the lease-state words on the map, popup, drawer, CSV
    flagNo: "",                                      // leave the "Cross-docked: no" flags out
    rows: { expiry: "Lease end (as recorded)" }      // relabel any stock drawer row by its key
  },
  popup: { rows: (r, rows, api) => rows.filter(x => x.key !== "tenure") },   // the map popup, as a model
  drawer: { completeness: true },                   // opt in to "Field completeness" (off by default)
  */

  /* >> stock metric ids; custom tiles are {label, value(rows), unit, note(rows)}.
     Listed ids always show (as "—" if this export cannot support them); leave
     `metrics` out and the engine picks up to six that the data can carry. */
  metrics: ["floorspace", "leased", "wault", "expiring", "landlordTop", "lapsed"],

  /* >> stock filters; each disappears by itself if its dimension is flat */
  filters: ["group", "landlord", "region", "tenure"],

  /* >> page order. Drop an id to drop the panel; DASH.panel() adds new ones */
  panels: ["map", "expiry", "rent", "landlords", "quality", "findings", "table"],

  /* >> per-panel copy overrides: title, sub, basis (all may be functions) */
  copy: {
    map: {
      basis: (rows, api) => {
        if (!rows.length) return "";
        const reg = byCount(rows.filter(r => r.region), "region")[0];
        const cor = byCount(rows.filter(r => r.corridor && r.corridor !== "N/A"), "corridor")[0];
        const lead = rows.length === 1 ? "The one unit in view sits in " + (reg ? "the " + reg.k : "an unrecorded region") :
          (reg ? api.Word(reg.n) + " of the " + api.word(rows.length) + " units sit in the " + reg.k : "");
        const road = cor && cor.n > 1 ? " and " + api.word(cor.n) + " sit on the " + cor.k : "";
        const midlands = reg && /Midlands/.test(reg.k) && cor && /^(M1|M6|M69|A14|A5)$/.test(cor.k);
        return (lead ? lead + road + (midlands ? " &mdash; the estate is built around the golden triangle. " : ". ") : "") +
          "Click any unit for its full record" +
          (api.group.enabled ? "; click a " + api.group.short.toLowerCase() + " in the legend to isolate it." : ".");
      }
    },
    rent: {
      sub: (rows, api) => "The rent " + client(api) + " pays is a function of when the deal " +
        "was done, not where the building is. That gap is the reversion."
    },
    landlords: {
      basis: (rows, api) => {
        const L = leased(rows);
        if (!L.length) return "";
        const T = api.thirdParty(rows), all = A.by(T, "landlord"), intra = L.filter(r => r.landlordIntra);
        const k = Math.min(6, all.length), tk = all.slice(0, k).reduce((a, b) => a + b.sf, 0);
        const own = rows.filter(r => r.owned).length, who = client(api);
        // >> totals in m sq ft to 2 dp (api.msfT: exact only under 100,000 sq ft);
        //    the intra-group words come from the labels, so with one occupier they read
        //    "<client> itself", never "a group company"
        return api.plural(all.length, "third-party landlord") + " across the " + api.plural(L.length, "leased unit") + " in view. " +
          (all.length > 1 ? (k === 1 ? "The largest landlord holds" : "The largest " + api.word(k) + " hold") +
            " <b>" + api.msfT(tk) + " sq ft (" + api.pctS(tk, api.sum(T)) +
            "% of what " + who + " rents from third parties)</b>. " : "") +
          (intra.length ? api.plural(intra.length, "lease") + " with " + api.esc(api.label("intraWho")) + " as landlord " +
            api.noun(intra.length, "is", "are") + " shown apart. " : "") +
          (own ? "The " + api.plural(own, "unit") + " " + who + " owns " + api.noun(own, "is", "are") +
            " left out: an owned unit has no landlord view. " : "") +
          "Click a bar to filter.";
      }
    }
  },

  /* >> findings: each item is {h, b, a} or a function returning one (or null
     to drop it when its pattern is not in this export). HTML is allowed;
     numbers come from the rows, never from a typed-in figure. */
  findings: { items: [

    // 1 — the landlord whose leases cluster: one negotiation, not several
    (rows, api) => {
      const cut = api.year + 4;
      // >> api.running(r): the canonical lease state; a lease not yet started never counts
      const cands = A.by(api.thirdParty(rows), "landlord").map(g => {
        const soon = g.rows.filter(r => api.running(r) && r.expiryYear <= cut)
          .sort((a, b) => a.expiry.localeCompare(b.expiry));
        return Object.assign(g, { soon, soonSf: api.sum(soon) });
      }).filter(g => g.soon.length >= 2).sort((a, b) => b.soonSf - a.soonSf);
      const g = cands[0]; if (!g) return null;
      const name = api.llShort(g.k), yrs = new Set(g.soon.map(r => r.expiryYear)).size;
      return {
        h: name + " is one conversation worth " + api.sf(g.soonSf) + " sq ft",
        b: name + " holds <b>" + api.plural(g.n, "unit") + ", " + api.sf(g.sf) + " sq ft</b>, and <b>" +
           api.pct(g.soonSf, g.sf) + "%</b> of it reaches expiry by " + cut + " &mdash; " +
           andList(g.soon.map(r => place(r) + " (" + size(r) + ", " + api.myy(r.expiry) + ")")) + ". " +
           api.Word(g.soon.length) + " renewals, " + api.word(yrs) + " year" + (yrs === 1 ? "" : "s") + ", " +
           api.word(g.soon.length) + " separate negotiations.",
        a: "Consolidate into one portfolio regear. Trade term certainty across all " + api.word(g.n) +
           " for rent and capex."
      };
    },

    // 2 — a campus with no lease on file, and the same single-landlord pattern at scale
    (rows, api) => {
      const parks = A.by(rows.filter(r => r.park), "park");
      const single = g => new Set(g.rows.map(r => r.landlord)).size === 1 && g.rows[0].landlord;
      const blind = parks.filter(g => g.n >= 2 && single(g) && g.rows.every(r => !r.owned && !r.expiry))
        .sort((a, b) => b.n - a.n || b.sf - a.sf)[0];
      if (!blind) return null;
      const ll = blind.rows[0].landlord, town = blind.rows[0].town;
      const big = parks.filter(g => g !== blind && g.n >= 3 && single(g)).sort((a, b) => b.sf - a.sf)[0];
      const own = big ? big.rows.filter(r => r.owned).length : 0;
      return {
        h: api.Word(blind.n) + " units at " + blind.k + " have no lease on file",
        b: "Every one of the " + api.word(blind.n) + (town ? " " + town : "") + " units sits with <b>" + api.llShort(ll) +
           "</b>, and <b>all " + api.word(blind.n) + " have no expiry date recorded</b>." +
           (big ? " " + big.k + " is the same story at scale &mdash; <b>" + api.plural(big.n, "unit") + ", " +
             api.sf(big.sf) + " sq ft, all " + api.llShort(big.rows[0].landlord) + "</b>" +
             (own ? ", though " + api.word(own) + " of those " + api.word(big.n) + (own === 1 ? " is" : " are") +
               " recorded as owned by " + client(api) : "") + "." : ""),
        a: "Single-landlord campus deals. Fix the " + api.llShort(ll) + " file first &mdash; it is the cheapest risk to remove."
      };
    },

    // 3 — old deals against the portfolio's own recent evidence
    (rows, api) => {
      const R = leased(rows).filter(r => r.rent && r.dealYear);
      const since = api.year - 4, recent = R.filter(r => r.dealYear >= since);
      const bench = median(recent.map(r => r.rent));
      if (!bench || recent.length < 2) return null;
      const old = R.filter(r => r.rent <= bench * .8 && r.dealYear < since)
        .sort((a, b) => api.size(b) - api.size(a)).slice(0, 3);
      if (!old.length) return null;
      const latest = R.slice().sort((a, b) => String(b.dealDate).localeCompare(String(a.dealDate)))[0];
      const lead = old[0], rev = (bench - lead.rent) * api.size(lead);
      const far = lead.expiryYear && lead.expiryYear - api.year >= 5;
      return {
        h: api.Word(old.length) + " old deal" + (old.length === 1 ? " carries" : "s carry") + " the reversion",
        b: place(lead) + ", <b>" + size(lead) + " sq ft at " + api.money(lead.rent) + "</b> struck in " + lead.dealYear + ". " +
           old.slice(1).map(r => place(r) + ", " + size(r) + " at " + api.money(r.rent) + " (" + r.dealYear + ").").join(" ") +
           " The most recent comparable in this same portfolio is <b>" + api.money(latest.rent) + "</b>. On " + place(lead) +
           " alone, reversion to " + api.money(bench) + " &mdash; the median of the " + recent.length +
           " deals struck since " + since + " &mdash; is roughly <b>£" + (rev / 1e6).toFixed(1) + "m a year</b>.",
        a: "Budget it now. " + (lead.expiryYear ? place(lead) + " runs to " + lead.expiryYear +
           (far ? ", so the exposure lands at review, not at expiry." : ", so it lands at the renewal.") :
           "Its lease end is not on record, so confirm when the exposure lands.")
      };
    },

    // 4 — a capability that is hard to replace, and where it is (and is not)
    (rows, api) => {
      const cold = rows.filter(r => r.coldStore === true);
      if (cold.length < 2 || !api.group.enabled) return null;
      const by = byCount(cold, r => r._g), tot = api.sum(rows);
      const top2 = by.slice(0, 2), top2n = top2.reduce((a, g) => a + g.n, 0);
      const biggest = A.by(rows, r => r._g)[0];
      const none = biggest && !cold.some(r => r._g === biggest.k);
      return {
        h: "The chilled estate is " + cold.length + " units" + (none ? " and it is not where you would guess" : ""),
        b: "Cold storage is recorded on <b>" + api.plural(cold.length, "unit") + ", " + api.sf(api.sum(cold)) + " sq ft</b>" +
           (top2n >= cold.length * .8 ? " &mdash; almost all of it " + andList(top2.map(g => g.k + " (" + g.n + ")")) : "") + ". " +
           (none ? biggest.k + "'s <b>" + biggest.n + " units and " + api.msf(biggest.sf) + " sq ft record none</b>. " : "") +
           "The group's hardest capability to replace sits in <b>" + api.pct(api.sum(cold), tot) + "%</b> of the floorspace.",
        a: "Treat those " + cold.length + " as strategically immovable. Any exit is a fit-out decision, not a leasing one."
      };
    },

    // 5 — the MEES exposure, with the worked example that makes it real.
    // >> uk-rules.md §1: England and Wales only ("let" = leased, api.inEW);
    //    the 2031 B target is "set to" apply where cost-effective, not yet law;
    //    no EPC on record is "unrated", never a fail
    (rows, api) => {
      const t = api.mees(), rank = { A: 1, B: 2, C: 3, D: 4, E: 5, F: 6, G: 7 };
      const big = leased(rows).filter(r => api.inEW(r) && api.size(r) > t.sqft);
      if (!big.length) return null;
      const rated = big.filter(r => r.epc), ok = rated.filter(r => rank[r.epc] <= rank[t.target]);
      const below = rated.filter(r => rank[r.epc] > rank[t.target]), none = big.length - rated.length;
      if (!none && !below.length) return null;
      const letters = [...new Set(below.map(r => r.epc))].sort();
      const ex = below.filter(r => api.running(r) && r.expiryYear < t.year)
        .sort((a, b) => api.size(b) - api.size(a))[0];
      return {
        h: "EPC " + t.target + " from " + t.year + ": " + (none ? "a " + none + "-unit blind spot" : "the renewals are the moment"),
        b: "Of the <b>" + big.length + " leased units over " + t.m2 + " in England and Wales</b>, " +
           (rated.length < big.length / 2 ? "only " : "") + rated.length + " carry an EPC and <b>" + ok.length + " reach " +
           t.target + " or better</b>. " +
           (below.length ? api.Word(below.length) + (below.length === 1 ? " is " : " are ") + letters.join(" or ") + ". " : "") +
           (none ? "<b>" + none + " have no EPC on record</b> (unrated, not failing). " : "") +
           "From " + t.year + ", let buildings over " + t.m2 + " are set to need EPC " + t.target +
           " where cost-effective: a government target, not yet law." +
           (ex ? " " + place(ex) + " is the worked example &mdash; " + size(ex) + " sq ft, <b>EPC " + ex.epc +
             "</b>, lease ending " + api.monthYear(ex.expiry) + ", so any renewal runs past " + t.year + "." : ""),
        a: (none ? "Commission the " + none + " EPCs, then make" : "Make") +
           (letters.length ? " every " + letters.join(" and ") + " a landlord-funded upgrade in the renewal terms."
                           : " the EPC a condition of every renewal.")
      };
    }
  ] }
});

/* ---------------------------------------------------------------------
   >> DASH.panel: a new panel. Uncomment to add a block beside rent /
   landlords / quality (blocks share a row of up to three). It uses the same
   chart kit as the stock panels, so it looks native with no styling.

DASH.panel({
  id: "cold", after: "quality", layout: "block",
  title: "Where the cold chain sits",
  sub: "Cold storage recorded, by floorspace.",
  when: all => all.some(r => r.coldStore === true) || "Cold storage is not recorded on any unit.",
  render(el, rows, api) {
    const g = api.by(rows.filter(r => r.coldStore === true), r => r._g);
    if (!g.length) return api.empty(el, "No cold store in this selection.", "Nothing in view");
    api.hbars(el, g.map(x => ({ label: x.k, value: x.sf, colour: api.colourOf(x.k),
      title: x.k + " · " + api.sf(x.sf) + " sq ft · " + x.n + " units" })));
  },
  basis: (rows, api) => "Cold storage is recorded as present on " +
    rows.filter(r => r.coldStore === true).length + " of " + rows.length + " units in view; " +
    rows.filter(r => r.coldStore === null).length + " do not record it either way."
});
   --------------------------------------------------------------------- */
