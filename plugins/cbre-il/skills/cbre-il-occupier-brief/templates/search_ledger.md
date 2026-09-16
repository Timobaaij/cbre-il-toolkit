# Search ledger

One line per workstream, from the `SEARCHES_USED:` figure each research agent reports. The RESERVE
row accumulates whatever this thread and the reviewers spend on verification and gap-fill.
`helpers/gate_runner.py budget` reads this file and fails on any cap breach or a total above 60.

| Workstream | Searches | Cap | Notes |
|---|---|---|---|
| A | 0 | 18 | the company and its numbers |
| B | 0 | 16 | the trigger event and the people |
| C | 0 | 12 | peers and industry |
| D | 0 | 8 | regulatory and buildings |
| RESERVE | 0 | 6 | conflict resolution and the QA round |

Total must not exceed 60.

## Gap-fill log

Record every reserve search: what was checked, why, and what it settled.

| Date | Claim ID | What was checked | Outcome |
|---|---|---|---|
