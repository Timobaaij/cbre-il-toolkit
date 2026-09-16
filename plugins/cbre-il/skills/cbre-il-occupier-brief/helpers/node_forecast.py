#!/usr/bin/env python3
"""Next-node forecaster: where does an occupier's next distribution node go?

Sector-agnostic and geography-agnostic by construction. Nothing about retail, Europe or
any particular company is hardcoded. The tool knows only: demand points with locations
and start dates, existing nodes, and optionally a peer set. Everything else is a declared
parameter with a stated default, and every default is an assumption you can argue with.

Method, justification and failure modes: reference/node-forecaster.md. Read it first.

WHY A NAIVE MODEL PICKS THE WRONG ANSWER, which is the whole point of this file:

  1. It ranks the network the occupier HAS rather than the one it is ABOUT TO HAVE. A
     cluster of four markets opened this year looks trivial today and dominates in three
     years. Forecast the forward estate or do not bother.
  2. It treats one demand point the same wherever it sits. A node serving five adjacent
     markets earns five times what a node serving one dead-end market earns.
  3. It conflates two different decisions. A node that UNBLOCKS growth gates revenue and
     gets taken now. A node that REDUCES cost on an estate already scaling can wait, and
     usually does. Ranking them together buries the urgent one under the large one.
  4. It locates on demand geometry alone. Observed node choices sit pulled away from the
     demand centroid toward the inbound gateway and the existing trunk. Predict a zone.

USAGE
    python node_forecast.py demand.csv [options]

demand.csv, one row per market, region or customer cluster (trading OR announced OR
merely registered, which is the most useful row in the file):

    market        label
    entry_year    decimal year the occupier started serving it, e.g. 2019.6.
                  A value in the FUTURE models a registered-but-not-trading market.
    demand_now    current demand points (stores, depots, customers, plants, drops).
                  Zero is valid and meaningful for a pipeline market.
    volume        OPTIONAL relative throughput per demand point, default 1.0. Use it when
                  demand points differ in size: a 40,000 sq ft store is not a kiosk, and a
                  plant is not a drop.
    lat, lon      demand-mass centroid of that market, decimal degrees
    km_to_node    distance from that centroid to the NEAREST EXISTING node, by the mode
                  actually used. Road km for road, not great-circle.
    cluster       the set of markets ONE new node could plausibly serve. This is the most
                  consequential judgement in the input: see the reference. Split a market
                  across two rows when part of it is already served.
    served_by     existing node name, or blank if effectively unserved
    mode          road | sea | rail | air | mixed. Affects the cost of distance only.

peers.csv (optional, via --peers), one row per comparable occupier:
    peer, demand_points, nodes, note
  Used to derive the trigger: how many demand points a comparable business runs per node.
  WITHOUT THIS THE TOOL WILL NOT MAKE A TIMING CLAIM, because a trigger asserted from
  nowhere is a guess wearing a number.

OPTIONS, all of them assumptions
    --horizon N        months ahead (default 30: a typical 12 to 18 month lead time plus a
                       year of operation. Change it to the occupier's actual lead time.)
    --threshold KM     distance beyond which a leg starts accruing service debt.
                       Default 700, roughly one single-driver road day in Europe. WRONG for
                       long-haul geographies, rail networks and anything not road.
    --trigger N        demand points per node. Overrides --peers. Provenance unknown if you
                       set it by hand, and the output will say so.
    --rate N           demand points added per year in a market's first years.
    --calibrate        derive that rate from the subject's OWN market history instead.
                       Strongly preferred: it is the difference between a model and a view.
    --young-years N    how long the early-life rate applies (default 3). Set it from where
                       the subject's own growth curve actually bends.
    --inbound NAME,LAT,LON   a candidate inbound gateway. Repeatable, and you should pass
                       several, because which one wins is usually unknown.
    --gateway-weight A,B     how far to pull the demand centroid toward a gateway, as a
                       range (default 0.25,0.55). The output is a ZONE spanning every
                       gateway and both ends of this range. A point estimate here is false.
    --backtest LAT,LON,ASOF  a node the occupier has ALREADY taken, with the decimal year
                       just before they took it. Re-run with the estate as at that date and
                       this reports the cluster hit or miss and the km error. An unvalidated
                       forecast should not reach a client.
    --today N          decimal year to treat as now (default 2026.71)

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

DEFAULT_TODAY = 2026.71


def longpath(path):
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if len(absolute) < 240 or absolute.startswith("\\\\?\\"):
        return absolute
    return "\\\\?\\" + absolute.replace("/", "\\")


def haversine(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def read_demand(path):
    rows = []
    with open(longpath(path), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("market") or "").strip():
                continue
            rows.append({
                "market": r["market"].strip(),
                "entry_year": float(r["entry_year"]),
                "demand_now": float(r.get("demand_now") or 0),
                "volume": float(r.get("volume") or 1.0),
                "lat": float(r["lat"]), "lon": float(r["lon"]),
                "km_to_node": float(r["km_to_node"]),
                "cluster": (r.get("cluster") or r["market"]).strip(),
                "served_by": (r.get("served_by") or "").strip(),
                "mode": (r.get("mode") or "road").strip().lower(),
            })
    if not rows:
        sys.exit("no demand rows in %s" % path)
    return rows


def read_peers(path):
    out = []
    with open(longpath(path), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("peer") or "").strip():
                continue
            dp, n = float(r["demand_points"]), float(r["nodes"])
            if n > 0:
                out.append((r["peer"].strip(), dp, n, dp / n, (r.get("note") or "").strip()))
    return out


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])


def calibrate_rates(rows, today, young_years):
    """Derive early-life and mature growth rates from the subject's own market history.

    Early-life uses markets old enough to have a trend but young enough not to have
    plateaued. Mature uses everything past young_years. Both return None when the subject
    has too little history, and the caller must then say so rather than invent a rate.
    """
    young, old = [], []
    for r in rows:
        age = today - r["entry_year"]
        if r["demand_now"] <= 0:
            continue
        if 1.5 <= age <= max(2.0, young_years + 2.0):
            young.append(r["demand_now"] / age)
        elif age > young_years:
            old.append(r["demand_now"] / age)
    return (median(young), min(young) if young else None, max(young) if young else None,
            median(old))


def project(r, today, horizon_years, young_rate, mature_rate, young_years):
    """Forward demand, piecewise linear across the early-life and mature rates.

    A market whose entry_year is in the future starts from zero on that date, which is how
    a registered-but-not-trading entity is modelled: the single most under-used leading
    indicator in this whole method. Linear on purpose. An exponential fitted to three
    observations is decoration.
    """
    age = today - r["entry_year"]
    if age < 0:
        base, start, end = 0.0, 0.0, max(0.0, age + horizon_years)
    else:
        base, start, end = r["demand_now"], age, age + horizon_years
    y = young_years
    young_span = max(0.0, min(y, end) - min(y, start))
    mature_span = max(0.0, max(y, end) - max(y, start))
    return base + young_rate * young_span + mature_rate * mature_span


def centroid(points, weights):
    """Weighted centroid on a sphere, so it does not skew with longitude."""
    x = y = z = 0.0
    total = sum(weights) or 1.0
    for (la, lo), w in zip(points, weights):
        rla, rlo = math.radians(la), math.radians(lo)
        x += w * math.cos(rla) * math.cos(rlo)
        y += w * math.cos(rla) * math.sin(rlo)
        z += w * math.sin(rla)
    x, y, z = x / total, y / total, z / total
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def pull(lat, lon, g_lat, g_lon, w):
    """Move a point a fraction w of the way toward a gateway, on the sphere."""
    return centroid([(lat, lon), (g_lat, g_lon)], [1.0 - w, w])


def analyse(rows, today, a, young_rate, mature_rate):
    horizon_years = a.horizon / 12.0
    for r in rows:
        r["age"] = today - r["entry_year"]
        r["forward"] = project(r, today, horizon_years, young_rate, mature_rate, a.young_years)
        excess = max(0.0, r["km_to_node"] - a.threshold)
        debt = r["forward"] * r["volume"] * excess
        if r["mode"] in ("sea", "rail", "mixed"):
            debt *= a.sea_discount
        r["debt"] = debt

    clusters = defaultdict(list)
    for r in rows:
        clusters[r["cluster"]].append(r)

    out = []
    for name, members in clusters.items():
        fwd = sum(m["forward"] for m in members)
        now = sum(m["demand_now"] for m in members)
        debt = sum(m["debt"] for m in members)
        youngest = min(m["age"] for m in members)
        unserved = [m for m in members if not m["served_by"]]
        orphan = (len(unserved) == len(members)
                  and min(m["km_to_node"] for m in members) > a.threshold)
        early = youngest <= a.young_years
        if early and orphan:
            tier, why = 1, "growth-enabling: early-life orphan cluster, the trunk gates the programme"
        elif orphan:
            tier, why = 2, "cost-reducing: unserved, but the estate is already scaling on the trunk"
        else:
            tier, why = 3, "partly served: a node trims cost rather than unblocking anything"
        lat, lon = centroid([(m["lat"], m["lon"]) for m in members],
                            [m["forward"] * m["volume"] for m in members])
        out.append({"cluster": name, "tier": tier, "why": why, "now": now, "forward": fwd,
                    "debt": debt, "markets": len(members), "lat": lat, "lon": lon,
                    "per_market": debt / len(members) if members else 0.0})
    out.sort(key=lambda c: (c["tier"], -c["debt"], -c["markets"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("demand")
    ap.add_argument("--peers")
    ap.add_argument("--horizon", type=float, default=30.0)
    ap.add_argument("--threshold", type=float, default=700.0)
    ap.add_argument("--trigger", type=float)
    ap.add_argument("--rate", type=float)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--young-years", type=float, default=3.0, dest="young_years")
    ap.add_argument("--sea-discount", type=float, default=0.35)
    ap.add_argument("--inbound", action="append", default=[], metavar="NAME,LAT,LON")
    ap.add_argument("--gateway-weight", default="0.25,0.55", dest="gw")
    ap.add_argument("--backtest", metavar="LAT,LON,ASOF")
    ap.add_argument("--today", type=float, default=DEFAULT_TODAY)
    a = ap.parse_args(argv)

    gw_lo, gw_hi = [float(x) for x in a.gw.split(",")]
    gateways = []
    for spec in a.inbound:
        p = [x.strip() for x in spec.split(",")]
        if len(p) != 3:
            sys.exit("--inbound wants NAME,LAT,LON, got %r" % spec)
        gateways.append((p[0], float(p[1]), float(p[2])))

    rows = read_demand(a.demand)
    y_med, y_lo, y_hi, m_med = calibrate_rates(rows, a.today, a.young_years)

    if a.calibrate and y_med is None:
        sys.exit("cannot calibrate: the subject has no market between 1.5 and %.1f years old. "
                 "Pass --rate with a stated source instead." % (a.young_years + 2.0))
    young_rate = y_med if a.calibrate else a.rate
    if young_rate is None:
        sys.exit("no early-life growth rate: pass --calibrate or --rate.")
    mature_rate = m_med if m_med is not None else young_rate
    rate_prov = ("calibrated from the subject's own market entries"
                 if a.calibrate else "supplied by hand: state its source in the brief")

    peers = read_peers(a.peers) if a.peers else []
    trigger, trig_prov = None, None
    if a.trigger is not None:
        trigger, trig_prov = a.trigger, "supplied by hand: provenance unknown"
    elif peers:
        trigger = median([p[3] for p in peers])
        trig_prov = "median of %d peer(s): %s" % (
            len(peers), "; ".join("%s %.0f per node" % (p[0], p[3]) for p in peers))

    print("NEXT-NODE FORECAST")
    print("=" * 79)
    print("as at %.2f, horizon %.0f months (to %.2f), service-debt threshold %.0f km (%s)"
          % (a.today, a.horizon, a.today + a.horizon / 12.0, a.threshold, "road-day proxy"))
    print("early-life rate %.1f/yr (observed range %.1f to %.1f), mature rate %.1f/yr"
          % (young_rate, y_lo or young_rate, y_hi or young_rate, mature_rate))
    print("  rate provenance: %s" % rate_prov)
    if trigger:
        print("trigger %.0f demand points per node" % trigger)
        print("  trigger provenance: %s" % trig_prov)
    else:
        print("trigger: NONE SUPPLIED. No timing claim will be made: pass --peers or --trigger.")
    print()

    out = analyse(rows, a.today, a, young_rate, mature_rate)

    print("%-26s %5s %7s %9s %7s %7s" % ("MARKET", "AGE", "NOW", "FORWARD", "KM", "DEBT"))
    print("-" * 79)
    for r in sorted(rows, key=lambda r: (r["cluster"], -r["debt"])):
        print("%-26s %5.1f %7.0f %9.0f %7.0f %6.0fk"
              % (r["market"][:26], r["age"], r["demand_now"], r["forward"],
                 r["km_to_node"], r["debt"] / 1000.0))
    print()

    print("RANKED CLUSTERS")
    print("=" * 79)
    for i, c in enumerate(out, 1):
        print("%d. %s   [tier %d] %s" % (i, c["cluster"], c["tier"], c["why"]))
        line = ("   demand %.0f now, %.0f forward, across %d market(s); debt %.0fk, %.0fk per market"
                % (c["now"], c["forward"], c["markets"], c["debt"] / 1000.0,
                   c["per_market"] / 1000.0))
        print(line)
        if trigger:
            if c["forward"] >= trigger:
                print("   trigger CROSSED inside the horizon (%.0f vs %.0f)" % (c["forward"], trigger))
            else:
                gap = trigger - c["forward"]
                extra_months = 12.0 * gap / max(1e-9, young_rate * c["markets"])
                print("   trigger not crossed in horizon: %.0f short, about %.0f more months at "
                      "the current opening rate" % (gap, extra_months))
        print("   demand centroid %.2f, %.2f" % (c["lat"], c["lon"]))
        if gateways and c["tier"] <= 2:
            print("   landing zone, demand centroid pulled %.0f to %.0f per cent toward each gateway:"
                  % (gw_lo * 100, gw_hi * 100))
            for gname, glat, glon in gateways:
                p1 = pull(c["lat"], c["lon"], glat, glon, gw_lo)
                p2 = pull(c["lat"], c["lon"], glat, glon, gw_hi)
                print("     via %-22s %.2f, %.2f  to  %.2f, %.2f  (spread %.0f km)"
                      % (gname, p1[0], p1[1], p2[0], p2[1],
                         haversine(p1[0], p1[1], p2[0], p2[1])))
        print()

    if a.backtest:
        p = [x.strip() for x in a.backtest.split(",")]
        if len(p) != 3:
            sys.exit("--backtest wants LAT,LON,ASOF")
        b_lat, b_lon, asof = float(p[0]), float(p[1]), float(p[2])
        print("BACK-TEST against a node the occupier actually took")
        print("=" * 79)
        print("Re-run the same input as at %.2f and compare. The estate rows are today's, so" % asof)
        print("this is an optimistic test of the LOCATION step and a fair test of the RANKING")
        print("step only if you also roll the demand_now column back. Do both and say which.")
        by = analyse(rows, asof, a, young_rate, mature_rate)
        top = by[0]
        err = haversine(top["lat"], top["lon"], b_lat, b_lon)
        print()
        print("top cluster as at %.2f: %s (tier %d)" % (asof, top["cluster"], top["tier"]))
        print("demand-centroid error against the actual site: %.0f km" % err)
        best = (err, "demand centroid, no gateway pull")
        for gname, glat, glon in gateways:
            for w in (gw_lo, (gw_lo + gw_hi) / 2.0, gw_hi):
                q = pull(top["lat"], top["lon"], glat, glon, w)
                e = haversine(q[0], q[1], b_lat, b_lon)
                print("  with %.0f per cent pull toward %-20s error %.0f km" % (w * 100, gname, e))
                if e < best[0]:
                    best = (e, "%.0f per cent toward %s" % (w * 100, gname))
        print()
        print("best location rule on this single observation: %s, %.0f km error" % (best[1], best[0]))
        print("ONE observation calibrates nothing. Report the error, carry it as the forecast's")
        print("own error bar, and do not tune the parameters until it vanishes: that is fitting")
        print("noise. If the occupier has two or more past nodes, test against all of them.")
    else:
        print("NO BACK-TEST RUN. Pass --backtest with a node the occupier has already taken.")
        print("A forecast with no measured error bar is a view, and it should be labelled one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
