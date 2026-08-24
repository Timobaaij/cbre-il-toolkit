#!/usr/bin/env python3
"""value_format_clarify_test.py - the value-format remedy is a MECHANISED broker ask.

The gate's remedy used to be SKILL.md prose ("ASK THE BROKER") - the one documented
prose ask, and exactly the kind a mid-tier orchestrator drops. Pinned here, end to
end: the gate emits machine-readable findings; clarify turns them into BLOCKING
broker questions; run.py's bridge converts an ANSWER into an attributed
work/repairs.json entry and a DECLINE ('leave as is') into a waiver the gate
ships-bare-but-notes; a waived value no longer blocks. Offline.
"""
import json
import subprocess
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import clarify as CQ  # noqa: E402
import run as RUN  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_vf_"))
props = [{"id": i, "park": f"Park {i}", "city": "Corby",
          "divisibleFrom": "10,000 sq. m"} for i in range(1, 4)]
props.append({"id": 4, "park": "Park 4", "city": "Corby", "divisibleFrom": "5000"})
canonical = work / "canonical.json"
canonical.write_text(json.dumps({"meta": {}, "properties": props}), encoding="utf-8")


def _gate(extra=()):
    return subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "value-format", str(canonical),
         "--emit-json", str(work / "value_format_findings.json"),
         "--waivers", str(work / "value_format_waivers.json"), *extra],
        capture_output=True, text=True, errors="replace")


# 1) the gate blocks AND emits machine-readable findings
p = _gate()
check("gate-blocks", p.returncode != 0)
findings = json.loads((work / "value_format_findings.json").read_text(encoding="utf-8-sig"))
check("findings-field", findings and findings[0]["field"] == "divisibleFrom")
check("findings-bare", findings[0]["bare"] == [{"id": 4, "value": "5000"}])
check("findings-printed", findings[0]["dominant_printed"] == "sq. m")

# 2) clarify turns them into ONE blocking broker question with the printed unit option
qs = CQ.value_format_questions(findings)
check("one-question", len(qs) == 1)
check("blocking", CQ.is_blocking(qs[0]))
check("asked-of-broker", qs[0]["asked_of"] == "broker")
check("options", qs[0]["options"] == ["sq. m", "leave as is"])

# 3) with no answer, the bridge emits the question as pending (exit-13 material)
n_rep, n_wv, pend = RUN.value_format_clarify(work, canonical)
check("pending", n_rep == 0 and n_wv == 0 and len(pend) == 1)
check("questions-file", (work / "questions.json").exists())

# 4) an ANSWER becomes an attributed repair (idempotent across passes)
(work / "answers.json").write_text(json.dumps({qs[0]["id"]: "sq. m"}), encoding="utf-8")
n_rep, n_wv, pend = RUN.value_format_clarify(work, canonical)
check("repair-written", n_rep == 1 and not pend)
reps = json.loads((work / "repairs.json").read_text(encoding="utf-8-sig"))
check("repair-set", reps[0]["set"] == {"divisibleFrom": "5000 sq. m"})
check("repair-expect", reps[0]["expect"] == {"divisibleFrom": "5000"})
check("repair-attributed", "broker" in reps[0]["verified_by"])
n_rep2, _, _ = RUN.value_format_clarify(work, canonical)
check("repair-idempotent", n_rep2 == 0
      and len(json.loads((work / "repairs.json").read_text(encoding="utf-8-sig"))) == 1)

# 5) a DECLINE becomes a waiver (punctuated/cased variants included), and the
#    waived value no longer blocks the gate
work2 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_vf2_"))
canonical2 = work2 / "canonical.json"
canonical2.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
(work2 / "value_format_findings.json").write_text(
    json.dumps(findings), encoding="utf-8")
(work2 / "answers.json").write_text(json.dumps({qs[0]["id"]: "Leave as is."}),
                                    encoding="utf-8")
n_rep, n_wv, pend = RUN.value_format_clarify(work2, canonical2)
check("waiver-written", n_wv == 1 and n_rep == 0 and not pend)
wv = json.loads((work2 / "value_format_waivers.json").read_text(encoding="utf-8-sig"))
check("waiver-guarded", wv[0].get("expect_value") == "5000")
p2 = subprocess.run(
    [sys.executable, str(HELPERS / "gate_runner.py"), "value-format", str(canonical2),
     "--waivers", str(work2 / "value_format_waivers.json")],
    capture_output=True, text=True, errors="replace")
check("waived-passes", p2.returncode == 0)
check("waived-noted", "BY BROKER DECISION" in p2.stdout)

# 6) a STALE waiver (value no longer matches expect_value - ids can renumber) is
#    NOT applied: the gate blocks again instead of waiving a different property
wv[0]["expect_value"] = "9999"
(work2 / "value_format_waivers.json").write_text(json.dumps(wv), encoding="utf-8")
p3 = subprocess.run(
    [sys.executable, str(HELPERS / "gate_runner.py"), "value-format", str(canonical2),
     "--waivers", str(work2 / "value_format_waivers.json")],
    capture_output=True, text=True, errors="replace")
check("stale-waiver-blocks", p3.returncode != 0 and "waiver NOT applied" in p3.stdout)

# 7) a GARBAGE answer is never concatenated into a client-facing value - it is
#    re-asked with the rejection spelled out
work3 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_vf3_"))
canonical3 = work3 / "canonical.json"
canonical3.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
(work3 / "value_format_findings.json").write_text(json.dumps(findings), encoding="utf-8")
(work3 / "answers.json").write_text(
    json.dumps({qs[0]["id"]: "yes please do that thing"}), encoding="utf-8")
n_rep, n_wv, pend = RUN.value_format_clarify(work3, canonical3)
check("garbage-no-repair", n_rep == 0 and not (work3 / "repairs.json").exists())
check("garbage-reasked", len(pend) == 1 and "neither one of the options" in pend[0]["question"])

# 8) the broker's HAND-FILE is sacred: a malformed repairs.json is never replaced,
#    and a valid-JSON-but-not-a-list one never crashes the bridge
work4 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_vf4_"))
canonical4 = work4 / "canonical.json"
canonical4.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
(work4 / "value_format_findings.json").write_text(json.dumps(findings), encoding="utf-8")
(work4 / "answers.json").write_text(json.dumps({qs[0]["id"]: "sq. m"}), encoding="utf-8")
broken = '[{"id": "hand-001", "why": "hand-written",},]'   # trailing commas: not JSON
(work4 / "repairs.json").write_text(broken, encoding="utf-8")
n_rep, n_wv, pend = RUN.value_format_clarify(work4, canonical4)
check("handfile-preserved", (work4 / "repairs.json").read_text(encoding="utf-8") == broken)
check("handfile-no-repair", n_rep == 0)
(work4 / "repairs.json").write_text('{"not": "a list"}', encoding="utf-8")
n_rep, n_wv, pend = RUN.value_format_clarify(work4, canonical4)   # must not crash
check("dict-file-untouched",
      (work4 / "repairs.json").read_text(encoding="utf-8") == '{"not": "a list"}')

# 9) an OPEN tracker column (not a canonical card field) is advisory, never a
#    block - repairs could never apply to it, so blocking would deadlock
work5 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_vf5_"))
canonical5 = work5 / "canonical.json"
props5 = [{"id": i, "park": f"P{i}", "city": "Corby",
           "truckMilesToHub": "12 miles"} for i in range(1, 4)]
props5.append({"id": 4, "park": "P4", "city": "Corby", "truckMilesToHub": "15"})
canonical5.write_text(json.dumps({"meta": {}, "properties": props5}), encoding="utf-8")
p5 = subprocess.run(
    [sys.executable, str(HELPERS / "gate_runner.py"), "value-format", str(canonical5)],
    capture_output=True, text=True, errors="replace")
check("open-field-advisory", p5.returncode == 0 and "open tracker column" in p5.stdout)

print("VALUE FORMAT CLARIFY TEST: PASS")
