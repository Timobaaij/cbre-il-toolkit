#!/usr/bin/env python3
"""cluster_labels_optin_test.py - the cluster-label agent runs only when asked, and when it runs it
is handed everything on one line per stem. (2026-09-26 test run, fix 1.3.)

THE COST. The label job was auto-dispatched whenever a low-confidence filename stem existed, and
its prompt sent the agent to the 36 KB inventory.json: 74k tokens for 7 stems on the live run,
for a routing label that changes no card field (readers read the country off the deck; geocoding
keys on each record's own address).

WHAT THIS PINS (the helpers run.py calls; the run.py wiring itself is IA-7c's)
  * intake.cluster_label_job returns None unless project.yaml sets inputs.cluster_labels: agent,
    and also None when intake_clusters.SKIP declines it or the cache already exists;
  * with the flag, STEMS carries per stem: the stem, its inputs-relative path, the email it
    arrived with (subject, file, human date, sender when the email index knows it) and the
    current filename label - and a loose file carries no invented email;
  * over 40 stems, the remainder is NAMED on one line, never silently cut;
  * the rendered prompt has no unfilled slot without INVENTORY_PATH.
Offline; synthetic .eml with a PDF attachment, intake.discover, prompts_render.
"""
from __future__ import annotations

import email.message
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import intake as I  # noqa: E402
import prompts_render as PR  # noqa: E402

FAILS: list = []
PDF = b"%PDF-1.4\n% " + b"o" * 22000 + b"\n%%EOF\n"
ON = {"inputs": {"cluster_labels": "agent"}}


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbre_optin_") as td:
        inputs, work = Path(td) / "in", Path(td) / "work"
        inputs.mkdir()
        work.mkdir()
        m = email.message.EmailMessage()
        m["Subject"], m["From"] = "Oporto offer", "Rita Sousa <rita@example-agents.pt>"
        m["Date"] = "Mon, 07 Sep 2026 09:00:00 +0100"
        m.set_content("Deck attached.")
        m.add_attachment(PDF, maintype="application", subtype="pdf", filename="Options-Oporto.pdf")
        (inputs / "offer.eml").write_bytes(m.as_bytes())
        (inputs / "Naves Cataluna.pdf").write_bytes(b"%PDF-1.4\n% cat\n%%EOF\n")
        inv = I.discover(inputs, exclude_dir=work)
        low = sorted(s for c in inv["clusters"].values() if c.get("confidence") == "low"
                     for s in c.get("stems") or [])
        ck("Options-Oporto" in low and "Naves Cataluna" in low,
           f"the fixture has two low-confidence stems ({low})")

        print("== opt-in ==")
        ck(I.cluster_label_job(inv, {}, work) is None, "no flag -> no job")
        ck(I.cluster_label_job(inv, {"inputs": {"cluster_labels": "yes"}}, work) is None,
           "only the value 'agent' opts in")
        ck(I.cluster_label_job(inv, None, work) is None and not I.cluster_labels_opted_in("junk"),
           "an unreadable config is treated as not opted in")
        ck(I.cluster_labels_opted_in({"inputs": {"cluster_labels": " Agent "}}),
           "'agent' is read case- and space-insensitively")
        job = I.cluster_label_job(inv, ON, work)
        ck(isinstance(job, dict) and set(job) == {"STEMS", "OUTPUT_PATH", "CLUSTER_INPUT_HASH"},
           f"with the flag the job carries its slots and NO INVENTORY_PATH ({sorted(job or {})})")
        ck(job and job["CLUSTER_INPUT_HASH"] == inv["cluster_input_hash"]
           and job["OUTPUT_PATH"].endswith(I.CLUSTER_CACHE),
           "...keyed on the brochure-set hash, writing work/intake_clusters.json")

        print("== the STEMS block ==")
        stems = (job or {}).get("STEMS", "")
        print("    " + "\n    ".join(stems.splitlines()))
        op = next((l for l in stems.splitlines() if l.startswith('- "Options-Oporto"')), "")
        saved = [s["file"] for e in inv["email_attachments"] for s in e.get("saved") or []]
        ck(op and saved and f"file: {saved[0]}" in op, "the stem's inputs-relative path is on its line")
        ck('arrived with: "Oporto offer"' in op and "offer.eml" in op and "7 Sep 2026" in op,
           "...with the carrying email's subject, file and date")
        ck('filename label now: "Options-Oporto"' in op, "...and the current filename label")
        nc = next((l for l in stems.splitlines() if l.startswith('- "Naves Cataluna"')), "")
        ck(nc and "arrived with" not in nc and "file: Naves Cataluna.pdf" in nc,
           "a loose file carries no invented email")
        (work / "master_candidates_auto.json").write_text(json.dumps({"emails": [
            {"email_file": "offer.eml", "sender": "Rita Sousa"}]}), encoding="utf-8")
        op2 = next((l for l in I.cluster_label_stems_block(inv, work).splitlines()
                    if l.startswith('- "Options-Oporto"')), "")
        ck("Rita Sousa" in op2, "the sender is added once the email index knows it")

        print("== the prompt renders with these slots ==")
        try:
            out = PR.render("cluster-labels", job or {})
            ck("{{" not in out and "Options-Oporto" in out and "inventory.json" in out
               and "do NOT open inventory.json" in out, "no unfilled slot; the stems are in it")
        except Exception as e:  # noqa: BLE001
            ck(False, f"render failed: {type(e).__name__}: {e}")

        print("== declined, or already answered ==")
        (work / I.CLUSTER_SKIP[0]).write_text("", encoding="utf-8")
        ck(I.cluster_label_job(inv, ON, work) is None, "intake_clusters.SKIP -> no job")
        (work / I.CLUSTER_SKIP[0]).unlink()
        (work / I.CLUSTER_SKIP[1]).write_text("", encoding="utf-8")
        ck(I.cluster_label_job(inv, ON, work) is None, "...either .SKIP spelling")
        (work / I.CLUSTER_SKIP[1]).unlink()
        (work / I.CLUSTER_CACHE).write_text("{}", encoding="utf-8")
        ck(I.cluster_label_job(inv, ON, work) is None, "a cache already on disk -> no job")

    print("== over the cap, the remainder is named ==")
    many = {"clusters": {f"Stem{n:02d}": {"confidence": "low", "stems": [f"Stem{n:02d}"],
                                          "pdfs": [f"Stem{n:02d}.pdf"]} for n in range(45)}}
    blk = I.cluster_label_stems_block(many, None)
    lines = blk.splitlines()
    ck(len(lines) == 41 and lines[-1].startswith("- (+5 more") and '"Stem44"' in lines[-1],
       f"40 stem lines plus one line naming the other 5 ({len(lines)} lines)")

    print()
    if FAILS:
        print(f"CLUSTER LABELS OPT-IN TEST: FAIL ({len(FAILS)})")
        return 1
    print("CLUSTER LABELS OPT-IN TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
