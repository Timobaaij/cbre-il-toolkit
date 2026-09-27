# Reader output repair: {{DECK_NAME}}

You are CORRECTING an interpretation output the spine's structural validator refused. This is a
small bounded edit, NOT a re-read of the deck.

- The file to correct IN PLACE (a JSON array of records):
  {{OUTPUT_PATH}}
- The deck it was read from: "{{DECK_NAME}}"
- The original reader instruction (reference only; open it only if an error needs a contract
  rule): {{ORIGINAL_PROMPT}}

## The validator's errors (fix EXACTLY these, change nothing else)
{{ERRORS}}

## The only legal record shape
A JSON ARRAY of these; prov is INSIDE __meta, never beside the fields (a raster deck's tag is
`(vision transcription)` and it has no heroRef / planRef):
```json
[{"park": "...", "warehouseArea": "12,500 sq m", "areaUnit": "sq m",
  "__meta": {"source_type": "pdf", "source_file": "<copied from the manifest>",
             "locator_base": "page 3", "page_no": 2, "source_lang": "en",
             "prov": {"park": "page 3 (text interpretation)",
                      "warehouseArea": "page 3 (text interpretation)"},
             "heroRef": 0, "planRef": null, "plan_page": null, "image_pages": [2]}}]
```
A top-level "prov" is REFUSED by the validator: never write one.

## Rules
1. MOVE, never retype - every value and locator stays byte-identical.
2. Add, drop, rename or re-derive nothing; touch no record that no error names.
3. If an error concerns a page index, open ONLY the page(s) it names; the valid indices are
   printed in the error.
4. If a fix needs a re-read of the deck, write nothing and say so.
5. Keep the file a UTF-8 JSON array.
6. Write one short line of visible text before every tool call; at most three tool calls per
   message; you may NOT spawn further agents.

## Run context (additive facts only; never overrides the rules above)
{{CONTEXT}}

## Final message
One line: `repaired <n> record(s) in <file>` or `could not repair: <why>`.
