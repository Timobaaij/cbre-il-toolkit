#!/usr/bin/env python3
"""f30_yaml_comments_survive_merge_test.py - merging clusters keeps every comment in project.yaml. (SEAM-4)

THE DEFECT. `intake._merge_clusters_into_yaml` rewrote project.yaml through `yaml.safe_dump`,
which drops EVERY comment in the file. The comment that matters most is the header: it says that
every value in the file is a scaffold guess and that `setup.confirmed` is the only thing that says
otherwise. It exists because of a shipped incident (B63): the scaffold pre-fills all six Stage-0
answers, so the file always looked answered, so a compliant orchestrator skipped the broker form and
every run shipped English chrome, no email ingestion and car drive-times to brokers never asked.
And the destroying pass is the ORDINARY one: cluster keys change on the pass right after the label
agent writes its cache, so the warning was written on pass 1 and destroyed on pass 2 of a normal run.

Pinned here:
  1. after a cluster-key change on a freshly scaffolded file, every line outside the `clusters:`
     block is byte-identical (the header's setup.confirmed warning included) and the merged map
     is what safe_load reads back;
  2. a hand-edited block keeps its leading and inline comments, its blank line, and its key order;
  3. an EMPTY scaffold block (`{}`) gains entries and keeps the header line's inline comment;
  4. a block that is last in the file with no trailing newline stays that way;
  5. CRLF line endings and a UTF-8 BOM survive byte-for-byte;
  6. the broker's HAND-EDITED country for a surviving region is never overwritten by an inferred
     value, blank or not (the old rule let a non-blank inference beat a hand edit);
  7. the documented LIMITATION: '' means "not inferred", so a blank the broker left is re-inferred
     when the index knows the region. Pinned so that a change is a decision, not drift;
  8. the GUARD: when `inputs.clusters` cannot be located unambiguously (an inline flow mapping,
     two top-level `inputs:` blocks, no `inputs:` at all, a body line that is not one entry) the
     file is left byte-identical, the merge reports False, and a WARNING names the reason;
  9. the whole-document `safe_dump(cfg, ...)` fallback is GONE from the merge's source, so the
     guard cannot be quietly re-routed back to it.
Offline.
"""
from __future__ import annotations
import contextlib
import inspect
import io
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


def clusters(**kv) -> dict:
    return {"clusters": {r: {"country": c} for r, c in kv.items()}}


def merge_bytes(existing: bytes, inv: dict):
    """Run the merge on a file written byte-exactly; return (changed, new bytes, stdout)."""
    d = Path(tempfile.mkdtemp(prefix="cbre_f30_"))
    y = d / "project.yaml"
    y.write_bytes(existing)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        changed = IN._merge_clusters_into_yaml(y, inv)
    return changed, y.read_bytes(), buf.getvalue()


def merge(existing: str, inv: dict):
    changed, out, log = merge_bytes(existing.encode("utf-8"), inv)
    return changed, out.decode("utf-8"), log


def outside_block(text: str) -> list[str]:
    """Every line of `text` that is not inside the `clusters:` block (header line included in
    the remainder, its body excluded): the part of the file the merge must not touch."""
    out, in_block = [], False
    for ln in text.split("\n"):
        if in_block:
            body = ln.strip()
            if body and not body.startswith("#") and (len(ln) - len(ln.lstrip(" "))) <= 2:
                in_block = False
            else:
                continue
        out.append(ln)
        if re.match(r"^  clusters:", ln):
            in_block = True
    return out


INV = {"clusters": {"Northgate": {"country": ""}, "Westford": {"country": "XX"}},
       "emails": [], "xlsx": [], "images": [], "present_types": ["pdf"]}

# ---------------------------------------------------------------- 1. the ordinary pass
scaffold = IN.scaffold_yaml(INV, "Acme Retail")
ck("EVERY VALUE BELOW IS A DEFAULT THIS SCAFFOLD GUESSED" in scaffold,
   "precondition: the scaffold carries the setup.confirmed header")
changed, out, log = merge(scaffold, clusters(Northgate="", Westford="XX", Eastbridge=""))
ck(changed is True, "a cluster-key change (a new region) is merged")
ck(outside_block(out) == outside_block(scaffold),
   "every line outside the clusters block is byte-identical after the merge")
for needle in ("EVERY VALUE BELOW IS A DEFAULT THIS SCAFFOLD GUESSED",
               "`setup.confirmed` is the ONLY thing that says otherwise",
               "# set true ONLY after the broker has answered the Stage-0 form",
               "# region -> ISO-2 country (auto-inferred; fix if wrong;",
               "# openrouteservice key -> TRUCKING (HGV) drive times"):
    ck(needle in out, f"comment survives the merge: {needle[:48]!r}")
ck(out.count("#") == scaffold.count("#"), "not one comment marker was lost")
m = yaml.safe_load(out)["inputs"]["clusters"]
ck(m == {"Northgate": "", "Westford": "XX", "Eastbridge": ""},
   f"the merged map is what safe_load reads back (got {m!r})")
ck(out.endswith("\n") and not out.endswith("\n\n"), "the single trailing newline is kept")
ck(log == "", "the ordinary pass prints nothing")

# ---------------------------------------------------------------- 2. a hand-edited block
hand = ("# header that must survive\n"
        "setup:\n"
        "  confirmed: true\n"
        "inputs:\n"
        "  clusters:            # the broker's own note on the header line\n"
        "    # the northern estate\n"
        "    Northgate: YY      # hand-set\n"
        "\n"
        "    Westford: ''\n"
        "    # tail comment inside the block\n"
        "  emails:\n"
        "    source: none\n")
changed, out, log = merge(hand, clusters(Northgate="", Westford="XX", Eastbridge=""))
ck(changed is True, "hand-edited: the merge applies (a new region, an inferred country)")
for needle in ("# header that must survive", "  clusters:            # the broker's own note on the header line",
               "    # the northern estate", "    Northgate: YY      # hand-set",
               "    # tail comment inside the block", "  emails:\n    source: none\n"):
    ck(needle in out, f"hand-edited: survives verbatim: {needle.strip()[:44]!r}")
ck(out.count("\n\n") == 1, "hand-edited: the blank line inside the block is kept")
lines = out.split("\n")


def first(prefix: str) -> int:
    return next((i for i, l in enumerate(lines) if l.startswith(prefix)), -1)


ck(0 <= first("    Northgate: YY      # hand-set") < first("    Westford:") < first("    Eastbridge:"),
   "hand-edited: existing entries keep their order; the new one is appended")
m = yaml.safe_load(out)["inputs"]["clusters"]
ck(m == {"Northgate": "YY", "Westford": "XX", "Eastbridge": ""},
   f"hand-edited: broker value kept, blank filled, new region added (got {m!r})")

# ---------------------------------------------------------------- 3. an empty scaffold block
empty_inv = {"clusters": {}, "emails": [], "xlsx": [], "images": [], "present_types": []}
empty = IN.scaffold_yaml(empty_inv, "Acme Retail")
ck(re.search(r"^  clusters:.*\n    \{\}\n", empty, re.M) is not None,
   "precondition: an empty scaffold writes `clusters:` with a `{}` line")
changed, out, log = merge(empty, clusters(Northgate=""))
ck(changed is True and yaml.safe_load(out)["inputs"]["clusters"] == {"Northgate": ""},
   "empty block: the first region lands")
ck("{}" not in out.split("clusters:")[1].split("emails:")[0],
   "empty block: the `{}` placeholder is gone once there are entries")
ck("# region -> ISO-2 country" in out and outside_block(out) == outside_block(empty),
   "empty block: the header line's inline comment and the rest of the file survive")

# ---------------------------------------------------------------- 4. last in file, no trailing newline
tail = "# top\ninputs:\n  clusters:      # c\n    Northgate: ''"
changed, out, log = merge(tail, clusters(Northgate="", Westford=""))
ck(changed is True and not out.endswith("\n"), "no trailing newline in: none out")
ck(out.startswith("# top\ninputs:\n  clusters:      # c\n    Northgate: ''\n    Westford: ''"),
   "no trailing newline: the block is extended in place")

# ---------------------------------------------------------------- 5. CRLF and BOM
crlf = hand.replace("\n", "\r\n").encode("utf-8")
changed, out_b, log = merge_bytes(crlf, clusters(Northgate="", Westford="XX", Eastbridge=""))
ck(changed is True and out_b.count(b"\r\n") == out_b.count(b"\n") and out_b.count(b"\r\n") > 0,
   "CRLF in: CRLF out, every LF still paired with a CR")
ck(yaml.safe_load(out_b.decode("utf-8"))["inputs"]["clusters"]["Eastbridge"] == "",
   "CRLF: the merged map still parses")
bom = b"\xef\xbb\xbf" + hand.encode("utf-8")
changed, out_b, log = merge_bytes(bom, clusters(Northgate="", Westford="XX", Eastbridge=""))
ck(changed is True and out_b.startswith(b"\xef\xbb\xbf") and out_b.count(b"\xef\xbb\xbf") == 1,
   "a UTF-8 BOM is kept, once")

# ---------------------------------------------------------------- 6. a hand edit is never overwritten
changed, out, log = merge("inputs:\n  clusters:\n    Northgate: YY\n    Westford: ''\n",
                          clusters(Northgate="XX", Westford="", Eastbridge=""))
m = yaml.safe_load(out)["inputs"]["clusters"]
ck(m.get("Northgate") == "YY",
   f"a hand-edited country beats a DIFFERENT inferred country (got {m.get('Northgate')!r}); "
   f"the index cannot know better than the human who corrected it")
changed, out, log = merge("inputs:\n  clusters:\n    Northgate: YY\n",
                          clusters(Northgate="", Eastbridge=""))
ck(yaml.safe_load(out)["inputs"]["clusters"].get("Northgate") == "YY",
   "a hand-edited country beats a BLANK inference")
changed, out, log = merge("inputs:\n  clusters:\n    Northgate: YY\n", clusters(Northgate="XX"))
ck(changed is False and yaml.safe_load(out)["inputs"]["clusters"] == {"Northgate": "YY"},
   "a hand-edited country alone is not a change: the file is left byte-identical")

# ---------------------------------------------------------------- 7. the documented limitation
changed, out, log = merge("inputs:\n  clusters:\n    Northgate: ''\n    Westford: ''\n",
                          clusters(Northgate="XX", Westford="", Eastbridge=""))
ck(yaml.safe_load(out)["inputs"]["clusters"].get("Northgate") == "XX",
   "LIMITATION, pinned: '' means 'not inferred', so a blank is re-filled when the index knows the "
   "region. The design has no way to say 'the broker cleared this'; config.md says so")

# ---------------------------------------------------------------- 8. the guard
def refused(existing: str, inv: dict, why: str):
    changed, out, log = merge(existing, inv)
    ck(changed is False and out == existing,
       f"guard ({why}): the merge is refused and the file is byte-identical")
    ck("WARNING" in log and "inputs.clusters" in log and "project.yaml" in log,
       f"guard ({why}): a WARNING names project.yaml and inputs.clusters (got {log.strip()[:90]!r})")
    return log


refused("# keep me\ninputs:\n  clusters: {Northgate: XX}\n", clusters(Northgate="XX", Westford=""),
        "inline flow mapping")
refused("# keep me\ninputs:\n  clusters:\n    Northgate: XX\ninputs:\n  emails:\n    source: none\n",
        clusters(Northgate="XX", Westford=""), "two top-level inputs blocks")
refused("# keep me\nclient:\n  name: Acme\n", clusters(Northgate="XX"), "no inputs block")
refused("# keep me\ninputs:\n  clusters:\n    Northgate:\n      country: XX\n",
        clusters(Northgate="XX", Westford=""), "a nested entry is not one region line")
# a body line that is not `Region: country` (a list item) cannot be edited entry by entry
refused("# keep me\ninputs:\n  clusters:\n    - Northgate\n", clusters(Northgate="XX"),
        "a list where a mapping is expected")
# and a missing block under an existing, unambiguous inputs: is inserted, not refused
changed, out, log = merge("# keep me\ninputs:\n  emails:\n    source: none\nqa:\n  fill_threshold: 0.6\n",
                          clusters(Northgate="XX"))
ck(changed is True and yaml.safe_load(out)["inputs"]["clusters"] == {"Northgate": "XX"}
   and out.startswith("# keep me\ninputs:\n  emails:\n    source: none\n")
   and out.endswith("qa:\n  fill_threshold: 0.6\n"),
   "a missing clusters block under ONE inputs: is inserted as its last child; the rest is untouched")

# ---------------------------------------------------------------- 9. the fallback is gone
src = inspect.getsource(IN._merge_clusters_into_yaml)
ck(re.search(r"safe_dump\(\s*cfg\b", src) is None,
   "the merge no longer dumps the whole document (the comment-destroying fallback is gone)")
helper_src = "\n".join(inspect.getsource(f) for n, f in vars(IN).items()
                       if callable(f) and getattr(f, "__module__", "") == IN.__name__
                       and n.startswith("_") and "cluster" in n)
ck(re.search(r"safe_dump\(\s*cfg\b", helper_src) is None,
   "...and none of intake's cluster helpers does either")

print("\nF30 YAML COMMENTS SURVIVE MERGE TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
