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

# LEDGER: the quarantine's audit row must carry a source_locator. ledger.py REQUIRES one, and merge
# used to hard-code "", so ANY quarantine on a run blocked `ledger validate`. Real merge, real ledger.
import csv  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import ledger as L  # noqa: E402

_d = pathlib.Path(tempfile.mkdtemp(prefix="cbre_offspec_"))
(_d / "inputs").mkdir()
_rec = dict(_base("pdf"), country="GB", leaked={"n": 1})
_rec["__meta"]["locator_base"] = "page 1"
(_d / "r.json").write_text(json.dumps([_rec]), encoding="utf-8")
_p = subprocess.run([sys.executable, str(pathlib.Path(M.__file__)), "--records", str(_d / "r.json"),
                     "--source-dir", str(_d / "inputs"), "--out", str(_d / "c.json"),
                     "--ledger", str(_d / "l.csv")], capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
assert (_d / "l.csv").exists(), f"merge must write a ledger: {(_p.stdout + _p.stderr)[-300:]}"
with open(_d / "l.csv", newline="", encoding="utf-8") as _fh:
    _rows = list(csv.DictReader(_fh))
_off = [r for r in _rows if r.get("record_type") == "offspec"]
assert _off, "the quarantined key must reach the ledger as an offspec row"
assert all(str(r.get("source_locator") or "").strip() for r in _off), \
    f"every offspec row needs a non-empty source_locator: {[r.get('source_locator') for r in _off]}"
assert L.cmd_validate(types.SimpleNamespace(ledger=str(_d / "l.csv"))) == 0, \
    "ledger validate must pass on a run that quarantined an off-spec key"

print("OFFSPEC PREMERGE TEST: PASS")
