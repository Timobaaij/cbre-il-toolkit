# Failure modes - graceful degradation

The rule: **always degrade and report, never fabricate.** Every degraded case writes a Gaps Report line.

| Situation | Behaviour | Surfaced in |
|---|---|---|
| Partial inputs (a field absent across all sources) | field stays `"tbd"`; record ships if it clears `fill_threshold`; G-honesty confirms the `"tbd"` is genuine | Gaps Report (per property + how to close) |
| No emails / no Excel | those extractors skipped (driven by `inventory.json`); pipeline proceeds | Gaps Report notes absent types |
| No images | record ships without a real photo; a neutral CBRE placeholder is embedded. NOT a free pass: G-images BLOCKS a longlist of >=4 properties that is >=50% placeholders until `placeholder_rate_ok` is explicitly signed off (`reference/gates.md`) | Gaps Report: "no imagery for N properties" |
| Unreadable / scanned brochure | intake classifies it durably (`_classify_unreadable` - a Windows file lock is "could not open", never "corrupt"); a deck with no usable text layer routes to the interpretation sub-agent in `raster` mode (`interpret_prep.py`); fields not invented | Gaps Report: "<file> unreadable - manual entry", with the path |
| EMF/WMF vector image | rasterise the source page; else the CBRE placeholder | Gaps Report: "no imagery for N properties" (placeholder noted) |
| Unmatched asset (a loose image no property claims) | accounted by the `input-accounting` buckets (a loose image is a named bucket, never a silent drop); the Gaps Report's unmatched-asset line honestly reads "Not checked" - nothing populates a meta unmatched-assets field today | Gaps Report |
| Genuinely ambiguous source (unit-silent area/rent, brochure-vs-tracker count mismatch) | CLARIFICATION, not degradation: run.py exits 13 with `work/questions.json` - each question asked ONCE (`asked_of: "agent"` = an isolated reading; `"broker"` = a decision); unanswered -> the run proceeds with the honest gap named in `if_unanswered`, never a guess | the question list + Gaps Report |
| Missing coordinates | `enrich.py --geocode` (Nominatim, cached, `coordsApprox: true`); a compound/unresolvable city is a gap; the map simply omits that marker | Gaps Report |
| OSRM unreachable | `preBaked.distances` omitted; the chrome degrades to its in-browser OSRM then a haversine estimate (the UI labels "estimated") | Gaps Report |
| Conflicting sources | both kept; higher-precedence value wins; loser in `conflict_note` | Gaps Report + ledger |
| Zero property sources | Stage 0 halts before any work with a written explanation; no empty dashboard | direct message to the user |

A render crash from a single bad record is prevented structurally: `merge.canonicalize()` fills every chrome-read key with a sentinel, and the template's `fmt()` returns `"tbd"` for non-numbers (`reference/template-contract.md`).

## A BLOCKING clarification with nobody to answer it (exit 13)

Two exit-13 question kinds do not degrade to a default, because for them the default is the damage: **which source defines the longlist** (the union default shipped 41 cards for a 17-option brief) and **which unit a mixed dataset displays** (a silent majority vote converts the minority by 10.76x). They are re-offered every pass until decided.

That is deliberate, and it is bounded rather than open-ended - the escape is explicit rather than implicit-on-silence:

| situation | what to do | what ships |
|---|---|---|
| a broker is available | put the question to them, record the answer | their decision, named in the Gaps Report |
| the broker has no preference | answer `"skip"` | the stated default, disclosed as an accepted decision |
| headless / cron, nobody to ask | `work/clarify.SKIP_ALL` (or `project.yaml clarify.assume_defaults: true`) | every default, each one named in the Gaps Report |
| the orchestrator just re-runs | nothing changes - the question returns, and after two passes the exit text spells out the decline path | nothing is built, which is the point |

The one thing that no longer resolves a blocking question is silence. Every other clarification kind keeps the original contract: asked once, then it ships as the honest gap named in its `if_unanswered`.
