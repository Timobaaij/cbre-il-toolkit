#!/usr/bin/env python3
"""offspec_premerge_test.py - backlog item (a). run.py enumerates grey pairs + field conflicts from
its OWN pre-merge load of the records; without the same _normalise_offspec sweep merge.main applies,
a stray non-canonical OBJECT would surface as a spurious 'field conflict' to the field-decision
sub-agent. This proves the CONTROL (stray object surfaces without the sweep) and the FIX (the sweep
quarantines it to __meta.offspec, so it is never enumerated) - the exact behaviour run.py now wires
in before grey_pairs/conflict_candidates."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import merge as M  # noqa: E402
import match as MM  # noqa: E402


def _base(st):
    return {"city": "Testville", "developer": "Acme Developments", "park": "Alpha Logistics Park",
            "warehouseArea": 25000,
            "__meta": {"source_type": st, "source_file": f"{st}.src", "prov": {}}}


def _pair(extra_a, extra_b):
    a = _base("pdf"); a.update(extra_a)
    b = _base("email"); b.update(extra_b)
    return [a, b]


def _conflict_fields(recs):
    M.compute_file_quality(recs)
    return {c["field"] for c in M.conflict_candidates(MM.dedupe(recs, None))}


# CONTROL: without the pre-merge normalise, a stray non-canonical object 'leaked' whose value
# differs across the two clustered sources IS enumerated as a spurious conflict.
ctrl = _pair({"leaked": {"n": 1}}, {"leaked": {"n": 2}})
assert "leaked" in _conflict_fields(ctrl), "control: stray object should surface WITHOUT the sweep"

# FIX (run.py now applies this before enumeration): the sweep quarantines it -> not a conflict.
fixed = _pair({"leaked": {"n": 1}}, {"leaked": {"n": 2}})
for r in fixed:
    M._normalise_offspec(r)
assert "leaked" not in _conflict_fields(fixed), "fix: the sweep must suppress the stray-object conflict"
# not silently dropped - it is quarantined to __meta.offspec
assert any("leaked" in (r["__meta"].get("offspec") or {}) for r in fixed), "must quarantine, not drop"

print("OFFSPEC PREMERGE TEST: PASS")
