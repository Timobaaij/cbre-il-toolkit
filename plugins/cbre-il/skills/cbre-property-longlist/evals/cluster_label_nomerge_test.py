#!/usr/bin/env python3
"""cluster_label_nomerge_test.py - a cluster label may RENAME a cluster, never MERGE two decks.
(2026-09-26 test run, fix 3.1, intake side.)

THE LIVE DEFECT. A cluster is keyed on its region string, and the Stage-0 label cache gave two
decks the same town. intake put both into ONE cluster, the master list minted one row for two
brochures (two answered row ids gone, one new), the answered sheet stopped matching and exit 17
re-fired on a sheet the broker had finished. Deleting the cache did not undo it either: the
folder-scan resume check skips a missing input, so inventory.json was never re-derived.

WHAT THIS PINS
  * two labels pointing two separate decks at the town a third deck already carries are BOTH
    refused: three clusters, exactly the filename grouping, each refusal recorded in
    inventory["cluster_label_rejected"] and printed as one NOTE line by intake main;
  * the same for two labels pointing at a brand-new town;
  * a label that only RENAMES one deck's cluster still applies, and so does one that SPLITS a
    two-deck filename cluster (neither merges anything);
  * inventory["cluster_cache_sha"] is the cache's byte stamp and `intake.cluster_cache_stamp`
    computes the same value, "" once the cache is deleted or declined with intake_clusters.SKIP;
  * re-running intake after deleting the cache restores the filename keys in a scaffolded
    project.yaml (inputs.clusters) - the rollback is real, not just a flag.
Offline; tiny synthetic "PDFs" (intake never parses them), a real intake.py subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import intake as I  # noqa: E402

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _pdf(p: Path, tag: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4\n% " + tag.encode("utf-8") + b"\n%%EOF\n")


def _cache(cih: str, labels: list) -> dict:
    return {"input_hash": cih, "schema_version": 1, "labels": labels}


def _intake(inputs: Path, work: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HELPERS / "intake.py"), str(inputs),
                           "--out-dir", str(work), "--client", "Example Client"],
                          capture_output=True, text=True, errors="replace")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbre_nomerge_") as td:
        inputs = Path(td) / "in"
        work = Path(td) / "work"
        work.mkdir()
        _pdf(inputs / "Alpha Park 7.pdf", "alpha")
        _pdf(inputs / "20260101-Beta-Park-Brochure_v02.pdf", "beta")
        _pdf(inputs / "Options - Northtown.pdf", "north")
        base = I.discover(inputs, email_attachments=False)
        det_keys = sorted(base["clusters"])
        cih = base["cluster_input_hash"]
        print("== the filename grouping ==")
        ck(len(det_keys) == 3 and "Northtown" in det_keys,
           f"three filename clusters, one of them 'Northtown' ({det_keys})")
        ck(base.get("cluster_label_rejected") == [],
           "cluster_label_rejected is always present, empty without a cache")

        print("== two labels naming the town a third deck already has ==")
        fused = _cache(cih, [{"stem": "Alpha Park 7", "region": "Northtown"},
                             {"stem": "20260101-Beta-Park-Brochure_v02", "region": "Northtown"}])
        inv = I.discover(inputs, cluster_cache=fused, email_attachments=False)
        ck(sorted(inv["clusters"]) == det_keys,
           f"no fusion: the clusters are exactly the filename grouping ({sorted(inv['clusters'])})")
        rej = {r["stem"]: r for r in inv["cluster_label_rejected"]}
        ck(set(rej) == {"Alpha Park 7", "20260101-Beta-Park-Brochure_v02"},
           f"both labels are refused and named ({sorted(rej)})")
        ck(all(r["region"] == "Northtown" and "keep apart" in r["why"]
               and "'Northtown'" in r["why"] for r in rej.values()),
           f"...each with the proposed region and why ({[r['why'] for r in rej.values()][:1]})")
        ck(all(len(c.get("pdfs") or []) == 1 for c in inv["clusters"].values()),
           "every cluster still holds exactly one deck")

        print("== two labels naming a NEW town ==")
        inv2 = I.discover(inputs, cluster_cache=_cache(cih, [
            {"stem": "Alpha Park 7", "region": "Southgate"},
            {"stem": "20260101-Beta-Park-Brochure_v02", "region": "Southgate"}]),
            email_attachments=False)
        ck("Southgate" not in inv2["clusters"] and len(inv2["cluster_label_rejected"]) == 2,
           "a new town two decks would share is refused too")

        print("== a rename is still a rename ==")
        inv3 = I.discover(inputs, cluster_cache=_cache(cih, [
            {"stem": "Alpha Park 7", "region": "Alphaville", "note": "close call"}]),
            email_attachments=False)
        ck("Alphaville" in inv3["clusters"] and inv3["cluster_label_rejected"] == []
           and len(inv3["clusters"]) == 3,
           f"a label that merges nothing applies ({sorted(inv3['clusters'])})")
        ck([n["stem"] for n in inv3["cluster_label_notes"]] == ["Alpha Park 7"],
           "...and its close-call note is kept")
        ck(all(n["stem"] not in rej for n in inv["cluster_label_notes"]),
           "a REFUSED label's note is never published")

    print("== a split of one filename cluster is allowed ==")
    with tempfile.TemporaryDirectory(prefix="cbre_nomerge2_") as td:
        inputs = Path(td) / "in"
        _pdf(inputs / "Options - Madrid.pdf", "m1")
        _pdf(inputs / "New stock - Madrid.pdf", "m2")
        b2 = I.discover(inputs, email_attachments=False)
        ck(list(b2["clusters"]) == ["Madrid"] and len(b2["clusters"]["Madrid"]["pdfs"]) == 2,
           "the filenames group both decks under 'Madrid'")
        s2 = I.discover(inputs, cluster_cache=_cache(b2["cluster_input_hash"], [
            {"stem": "New stock - Madrid", "region": "Madrid North"}]), email_attachments=False)
        ck(sorted(s2["clusters"]) == ["Madrid", "Madrid North"]
           and s2["cluster_label_rejected"] == [],
           f"splitting merges nothing, so it applies ({sorted(s2['clusters'])})")

    print("== intake main: the NOTE line, the cache stamp and the rollback ==")
    with tempfile.TemporaryDirectory(prefix="cbre_nomerge3_") as td:
        inputs = Path(td) / "in"
        work = Path(td) / "work"
        work.mkdir()
        _pdf(inputs / "Alpha Park 7.pdf", "alpha")
        _pdf(inputs / "20260101-Beta-Park-Brochure_v02.pdf", "beta")
        _pdf(inputs / "Options - Northtown.pdf", "north")
        p0 = _intake(inputs, work)
        inv0 = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
        det_keys = sorted(inv0["clusters"])
        ck(p0.returncode == 0 and inv0.get("cluster_cache_sha") == "",
           "no cache -> cluster_cache_sha is ''")
        cache = work / I.CLUSTER_CACHE
        cache.write_text(json.dumps(_cache(inv0["cluster_input_hash"], [
            {"stem": "Alpha Park 7", "region": "Northtown"},
            {"stem": "20260101-Beta-Park-Brochure_v02", "region": "Northtown"}])),
            encoding="utf-8")
        p1 = _intake(inputs, work)
        ck("cluster label(s) refused" in p1.stdout and "never merge two decks" in p1.stdout,
           f"intake main prints the refusal NOTE ({[l for l in p1.stdout.splitlines() if 'refused' in l][:1]})")
        cache.write_text(json.dumps(_cache(inv0["cluster_input_hash"], [
            {"stem": "Alpha Park 7", "region": "Alphaville"}])), encoding="utf-8")
        _intake(inputs, work)
        inv1 = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
        ck(inv1.get("cluster_cache_sha") and inv1["cluster_cache_sha"] == I.cluster_cache_stamp(work),
           f"with a cache, inventory's stamp == intake.cluster_cache_stamp ({inv1.get('cluster_cache_sha')})")
        yml = (work / "project.yaml").read_text(encoding="utf-8")
        ck("Alphaville" in yml, "the applied label reached project.yaml inputs.clusters")
        (work / I.CLUSTER_SKIP[0]).write_text("", encoding="utf-8")
        ck(I.cluster_cache_stamp(work) == "" and I._load_cluster_cache(work) is None,
           "intake_clusters.SKIP declines the cache: stamp '' and the cache is not loaded")
        (work / I.CLUSTER_SKIP[0]).unlink()
        cache.unlink()
        ck(I.cluster_cache_stamp(work) == "" and inv1["cluster_cache_sha"] != "",
           "deleting the cache changes the stamp, so the resume check can see it")
        _intake(inputs, work)
        inv2 = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
        yml2 = (work / "project.yaml").read_text(encoding="utf-8")
        ck(sorted(inv2["clusters"]) == det_keys and inv2.get("cluster_cache_sha") == "",
           "re-running intake re-derives the filename clusters")
        ck("Alphaville" not in yml2 and "Alpha Park 7" in yml2,
           "...and project.yaml inputs.clusters gets the filename key back")

    print()
    if FAILS:
        print(f"CLUSTER LABEL NO-MERGE TEST: FAIL ({len(FAILS)})")
        return 1
    print("CLUSTER LABEL NO-MERGE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
