#!/usr/bin/env python3
"""f07_cluster_scaffold_blank_test.py - intake stops minting the '??' sentinel. (F7, clusters half)

THE LIVE FAILURE. intake scaffolded `inputs.clusters` with `??` for every country the CEE-seeded
city index did not know. That token then TRAVELLED: five of seven reading agents on one run said
unprompted that they had been handed '??' and had to derive the country themselves, producing
three different outcomes across seven decks (two country spellings and absent) and one broker
question. Worse, the token was not reliably recognised: seven private unknown-value predicates
disagreed about it and the SHARED reader returned False. The other half of the fix (one shared
predicate that treats '??' as unknown) is A1's; THIS half is: where absence is what is meant,
write absence.

Pinned here:
  1. the scaffold writes an unknown country as '' (`Region: ''`), and that round-trips through
     yaml.safe_load as the empty string a human can see is "not filled";
  2. a KNOWN country is still written, and `market.countries` is seeded only from known ones;
  3. the scaffold's own comment tells the operator what blank means;
  4. the header's `setup.confirmed` warning is untouched (it is correct and load-bearing);
  5. _merge_clusters_into_yaml: writes '' for a new unknown region, keeps a broker-set country,
     treats a LEGACY '??' (a project.yaml from before this fix) and a bare `Region:` (None) as
     the same placeholder, and does NOT rewrite a file whose only difference is that legacy
     spelling - because the rewrite drops every comment in the file;
  6. no '??' literal is left in intake.py outside the merge's legacy-tolerance tuple.
Offline.
"""
from __future__ import annotations
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import intake as IN  # noqa: E402
import yaml  # noqa: E402

fails: list[str] = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


INV = {"clusters": {"Northgate": {"country": ""}, "Westford": {"country": "XX"},
                    "Unit 5: Phase 2": {"country": ""}},
       "emails": [], "xlsx": [], "images": [], "present_types": ["pdf"]}

# ---------------------------------------------------------------- 1-4. the scaffold
text = IN.scaffold_yaml(INV, "Acme Retail")
ck("??" not in text, "the scaffold contains NO '??' token anywhere")
cfg = yaml.safe_load(text)
cl = (cfg.get("inputs") or {}).get("clusters") or {}
ck(cl.get("Northgate") == "" and cl.get("Unit 5: Phase 2") == "",
   "an unknown country round-trips through yaml.safe_load as '' (absence, not a token)")
ck(cl.get("Westford") == "XX", "a known country is still written")
ck(cfg["market"]["countries"] == ["XX"], "market.countries is seeded from KNOWN countries only")
ck(re.search(r"^\s+Northgate: ''\s*$", text, re.M) is not None,
   "the blank reads as `Region: ''` in the file, visibly empty to a human editor")
ck("'' = not inferred" in text and "--geocode" in text,
   "the clusters comment tells the operator what blank means and that --geocode resolves it")
ck("EVERY VALUE BELOW IS A DEFAULT THIS SCAFFOLD GUESSED" in text
   and "`setup.confirmed` is the ONLY thing that says otherwise" in text
   and "confirmed: false" in text,
   "the header's setup.confirmed warning is untouched")

# ---------------------------------------------------------------- 5. the merge
def merge(existing: str, inv: dict):
    d = Path(tempfile.mkdtemp(prefix="cbre_f07_"))
    y = d / "project.yaml"
    y.write_text(existing, encoding="utf-8")
    changed = IN._merge_clusters_into_yaml(y, inv)
    return changed, y.read_text(encoding="utf-8")


# a new unknown region is written blank; the broker's country for a surviving region is kept
changed, out = merge("inputs:\n  clusters:\n    Northgate: YY\n",
                     {"clusters": {"Northgate": {"country": ""}, "Eastbridge": {"country": ""}}})
ck(changed and "??" not in out, "merge: a re-cluster adds the new region with NO '??' token")
m = yaml.safe_load(out)["inputs"]["clusters"]
ck(m == {"Northgate": "YY", "Eastbridge": ""},
   f"merge: the broker-set country survives, the new unknown is '' (got {m!r})")

# a LEGACY '??' in the existing file is a placeholder, not a broker answer: the inferred
# country replaces it
changed, out = merge("inputs:\n  clusters:\n    Westford: '??'\n",
                     {"clusters": {"Westford": {"country": "XX"}}})
ck(changed and yaml.safe_load(out)["inputs"]["clusters"] == {"Westford": "XX"},
   "merge: a legacy '??' is treated as blank and yields to an inferred country")

# a bare `Region:` line (None) is the same placeholder
changed, out = merge("inputs:\n  clusters:\n    Westford:\n",
                     {"clusters": {"Westford": {"country": "XX"}}})
ck(changed and yaml.safe_load(out)["inputs"]["clusters"] == {"Westford": "XX"},
   "merge: a bare `Region:` (None) is treated as blank and yields to an inferred country")

# NO rewrite when the only difference is the legacy spelling of "unknown": safe_dump strips
# every comment, so a cosmetic rewrite has a real cost
legacy = ("# header comment that must survive\n"
          "setup:\n  confirmed: false\ninputs:\n  clusters:\n    Northgate: '??'\n")
changed, out = merge(legacy, {"clusters": {"Northgate": {"country": ""}}})
ck(changed is False and out == legacy,
   "merge: '??' vs '' for the same unknown is NOT a change - the file (and its comments) is left alone")
# and the ordinary no-op is still a no-op
changed, out = merge("inputs:\n  clusters:\n    Northgate: ''\n",
                     {"clusters": {"Northgate": {"country": ""}}})
ck(changed is False, "merge: an identical cluster map is still a no-op")

# ---------------------------------------------------------------- 6. no new minting
src = (ROOT / "helpers" / "intake.py").read_text(encoding="utf-8")
minting = [ln for ln in src.splitlines()
           if re.search(r"""or\s+["']\?\?["']""", ln)]
ck(not minting, f"intake.py no longer writes '??' as a fallback value anywhere ({minting})")
ck('_blank = ("", "??", None)' in src,
   "...but the merge still RECOGNISES a legacy '??' (a pre-F7 project.yaml keeps working)")

print("\nF07 CLUSTER SCAFFOLD BLANK TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
