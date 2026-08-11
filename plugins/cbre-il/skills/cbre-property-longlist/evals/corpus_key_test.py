#!/usr/bin/env python3
"""corpus_key_test.py - the QA window keys on the CORPUS, not the folder path. (B41)

gate_runner._qa_run_key reads inv["input_hash"] or falls back to inv["folder"]. intake never
published input_hash - it computed the brochure digest inline and threw it away - so the
fallback ALWAYS fired, and inv["folder"] is a constant for a given work dir. The QA window was
therefore blind to every in-place corpus change: swap a deck for a corrected one and the window
still thought it was the same run.

Worse, and the reason the key has to be STABLE as well as sensitive: _qa_load wipes `rounds` on
a key change, so a spurious reset makes qa_carried() return [] and the delivered Gaps Report
SILENTLY loses every carried limitation. A key that is too twitchy is not the safe direction.

Same missing key also made the Stage-0 cluster-label cache permanently unreachable.
Drives the real intake.discover. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import intake as IN  # noqa: E402
import gate_runner as GR  # noqa: E402


def _folder(files: dict):
    d = Path(tempfile.mkdtemp(prefix="cbre_ck_"))
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else str(body).encode("utf-8"))
    return d


BASE = {"Corby/Deck A.pdf": b"%PDF-1.4 A", "Corby/Deck B.pdf": b"%PDF-1.4 B",
        "tracker.xlsx": b"PK\x03\x04 tracker", "note.msg": b"msg"}


def _key(d):
    inv = IN.discover(d) if hasattr(IN, "discover") else None
    return inv


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d1 = _folder(BASE)
    inv = _key(d1)
    ck(isinstance(inv, dict), "intake.discover returns an inventory")
    if not isinstance(inv, dict):
        print(f"\nCORPUS KEY TEST: FAIL ({len(fails)})")
        return 1

    ck(bool(inv.get("input_hash")), f"input_hash is PUBLISHED {ascii(str(inv.get('input_hash')))}")
    ck(bool(inv.get("cluster_input_hash")),
       "cluster_input_hash is published (the Stage-0 cache compares it)")
    ck(inv["input_hash"] != inv["cluster_input_hash"],
       "the two identities are distinct - corpus vs brochure set")

    # STABLE: the same corpus re-discovered gives the same key
    ck(_key(_folder(BASE))["input_hash"] == inv["input_hash"],
       "the same corpus in a DIFFERENT folder gives the SAME key (content, not path)")
    ck(_key(d1)["input_hash"] == inv["input_hash"], "re-discovering is stable")

    # SENSITIVE: a changed file content changes it
    ch = dict(BASE); ch["Corby/Deck A.pdf"] = b"%PDF-1.4 A CORRECTED"
    ck(_key(_folder(ch))["input_hash"] != inv["input_hash"],
       "a CORRECTED deck changes the key (the window must reset)")
    add = dict(BASE); add["Corby/Deck C.pdf"] = b"%PDF-1.4 C"
    ck(_key(_folder(add))["input_hash"] != inv["input_hash"], "a NEW input changes the key")

    # NOT twitchy: noise must not reset the window and lose carried limitations
    noise = dict(BASE); noise["readme.txt"] = b"unclassified noise"
    ck(_key(_folder(noise))["input_hash"] == inv["input_hash"],
       "an UNCLASSIFIED file does NOT change the key (a spurious reset drops every carried "
       "limitation from the Gaps Report)")

    # the brochure key tracks only brochures
    trk = dict(BASE); trk["tracker.xlsx"] = b"PK\x03\x04 tracker CHANGED"
    i2 = _key(_folder(trk))
    ck(i2["cluster_input_hash"] == inv["cluster_input_hash"],
       "a changed TRACKER leaves cluster_input_hash alone (it is the brochure set)")
    ck(i2["input_hash"] != inv["input_hash"], "...but it DOES change the corpus key")

    # WIRING: gate_runner must actually consume it, with no edit of its own
    w = Path(tempfile.mkdtemp(prefix="cbre_ckw_"))
    (w / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    k1 = GR._qa_run_key(w)
    (w / "inventory.json").write_text(json.dumps(_key(_folder(ch))), encoding="utf-8")
    ck(GR._qa_run_key(w) != k1,
       "gate_runner._qa_run_key now MOVES when the corpus changes (it never did before)")
    (w / "inventory.json").write_text(json.dumps({"folder": str(w)}), encoding="utf-8")
    ck(bool(GR._qa_run_key(w)),
       "an OLD inventory.json with no input_hash still resolves (backward compatible)")

    # the cluster cache must accept either spelling rather than silently dropping the cache
    ov = IN._verified_cluster_overrides(
        {"cluster_input_hash": inv["cluster_input_hash"],
         "labels": [{"stem": "Deck A", "region": "Corby", "country": "GB"}]},
        inv["cluster_input_hash"], {"Deck A"})
    ck(ov.get("Deck A"), "a cache keyed under cluster_input_hash is ACCEPTED (alias)")
    ck(not IN._verified_cluster_overrides(
        {"input_hash": "stale", "labels": []}, inv["cluster_input_hash"], {"Deck A"}),
       "a genuinely stale cache is still dropped")

    if fails:
        print(f"\nCORPUS KEY TEST: FAIL ({len(fails)})")
        return 1
    print("\nCORPUS KEY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
