# The Stage-0 broker setup form (ONE `visualize` widget, all five questions)

The broker setup is presented as **ONE `visualize` elicitation widget** — a single box with **all five
questions at once**, submitted together. **Do NOT use `AskUserQuestion`, and NEVER split the questions
into a single-question / one-at-a-time flow or a follow-up.** This is a hard requirement: the broker
answers everything in one form and the run proceeds with zero further setup prompts.

## How to render it
1. Call `mcp__visualize__read_me` with `modules:["elicitation"]` (once per session; internal — do not
   narrate it).
2. Call `mcp__visualize__show_widget` with the form HTML BELOW as `widget_code`, substituting the
   **inferred client name** into the two `{{CLIENT}}` spots (from the inputs folder / `project.yaml`
   `client:`; if genuinely unknown, use a best-guess label — the broker can still pick "Other").
   Title stays `Property longlist details`.
3. Show ALL FIVE groups every time — even a field you could infer (e.g. the client name) is shown as a
   confirmable pill. No shortcuts, no omitted groups.
4. SKIP the whole widget ONLY when `project.yaml` already carries the answers (a non-interactive
   re-run), OR when the `visualize` tool is genuinely unavailable in this environment — in that one
   fallback case present all five in ONE consolidated plain-text message (a single elicitation), still
   never one question at a time.

## The submitted answer
On submit the broker's answers arrive as your next message on one line, e.g.:
`Property longlist details — Client: TEDi Spain · Extras: Drive-time maps, Logistics landmarks · Ors key: (blank) · Emails: Normal CEE · Language: English`
(`(Skipped the form — proceed with defaults or ask me in plain text)` if they skip.) Parse it and
record into `project.yaml` per the mapping in SKILL.md "The broker setup prompt": Client→`client:`,
Extras→`enrichment:` flags, Ors key→`enrichment.ors_api_key`, Emails→`inputs.emails:`
(folder name = the "(other)" text; "Across all of Outlook" = no `folderName`; "No" = skip), Language→
`output.language`. Then proceed to extraction with no further setup questions.

## The form (pass verbatim to `show_widget`; only `{{CLIENT}}` is substituted)
```html
<form class="elicit">
  <div class="elicit-header">
    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M11.586 2a1.5 1.5 0 0 1 1.06.44l2.914 2.914a1.5 1.5 0 0 1 .44 1.06V16.5a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.492-1.347L4 16.5v-13A1.5 1.5 0 0 1 5.5 2zM5.5 3a.5.5 0 0 0-.5.5v13a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5V7h-2.5A1.5 1.5 0 0 1 11 5.5V3zm7.04 10.304a.5.5 0 0 1 .92.392c-.295.69-.871 1.304-1.66 1.304-.487 0-.892-.234-1.2-.574-.309.34-.713.574-1.2.574-.486 0-.892-.233-1.2-.574-.31.34-.714.574-1.2.574a.5.5 0 0 1 0-1c.212 0 .52-.18.74-.696l.034-.067a.5.5 0 0 1 .886.067c.221.516.528.696.74.696.213 0 .52-.18.74-.696l.035-.067a.5.5 0 0 1 .885.067c.22.516.527.696.74.696s.519-.18.74-.696m0-4a.5.5 0 0 1 .92.392c-.295.69-.871 1.304-1.66 1.304-.487 0-.892-.234-1.2-.574-.309.34-.713.574-1.2.574-.486 0-.892-.233-1.2-.574-.31.34-.714.574-1.2.574a.5.5 0 0 1 0-1c.212 0 .52-.18.74-.696l.034-.067a.5.5 0 0 1 .886.067c.221.516.528.696.74.696.213 0 .52-.18.74-.696l.035-.067a.5.5 0 0 1 .885.067c.22.516.527.696.74.696s.519-.18.74-.696M12 5.5a.5.5 0 0 0 .5.5h2.293L12 3.207z"/></svg>
    <span>Property longlist details</span>
  </div>
  <div class="elicit-body">

    <div class="elicit-group">
      <label class="elicit-question">What should I call the client on the dashboard and file names?</label>
      <div class="elicit-pills" data-name="client" data-multi="false">
        <button type="button" class="elicit-pill" data-value="{{CLIENT}}" aria-pressed="true">{{CLIENT}}</button>
        <button type="button" class="elicit-pill" data-value="Other" data-other>Other</button>
      </div>
      <input type="text" class="elicit-other" data-for="client" placeholder="Type the client name" hidden>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">Want me to add any extras? (each adds a little time — the dashboard already has photos, filters, comparison and a map)</label>
      <div class="elicit-pills" data-name="extras" data-multi="true">
        <button type="button" class="elicit-pill" data-value="Drive-time maps" style="border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:flex-start;text-align:left;min-width:210px;box-shadow:0 1px 2px rgba(0,0,0,0.04)">
          <i class="ti ti-truck" style="font-size:20px" aria-hidden="true"></i>
          <span><span style="font-size:13px;font-weight:500">Drive-time maps</span><br><span style="font-size:11px;color:var(--text-muted)">Truck (HGV) time to key ports, airports, motorways, borders</span></span>
        </button>
        <button type="button" class="elicit-pill" data-value="Workforce snapshot" style="border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:flex-start;text-align:left;min-width:210px;box-shadow:0 1px 2px rgba(0,0,0,0.04)">
          <i class="ti ti-users" style="font-size:20px" aria-hidden="true"></i>
          <span><span style="font-size:13px;font-weight:500">Workforce snapshot</span><br><span style="font-size:11px;color:var(--text-muted)">Labour, logistics employment, unemployment per region</span></span>
        </button>
        <button type="button" class="elicit-pill" data-value="Logistics landmarks" style="border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:flex-start;text-align:left;min-width:210px;box-shadow:0 1px 2px rgba(0,0,0,0.04)">
          <i class="ti ti-map-pin" style="font-size:20px" aria-hidden="true"></i>
          <span><span style="font-size:13px;font-weight:500">Logistics landmarks</span><br><span style="font-size:11px;color:var(--text-muted)">Nearby ports, rail terminals, airports, borders on the map</span></span>
        </button>
      </div>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">If drive-time maps are on, got a free openrouteservice API key for real HGV routing? (leave blank for car-based times)</label>
      <textarea class="elicit-textarea" data-name="ors_key" placeholder="Paste ORS key, or leave blank"></textarea>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">Also pull property details from your Outlook emails (landlord / agent offers)?</label>
      <div class="elicit-pills" data-name="emails" data-multi="false">
        <button type="button" class="elicit-pill" data-value="A specific Outlook folder" data-other>A specific Outlook folder</button>
        <button type="button" class="elicit-pill" data-value="Across all of Outlook">Across all of Outlook</button>
        <button type="button" class="elicit-pill" data-value="No">No</button>
      </div>
      <input type="text" class="elicit-other" data-for="emails" placeholder="Name the mail folder (e.g. Inbox, or Normal CEE)" hidden>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">What language should the dashboard chrome be written in? (property data stays as sourced)</label>
      <div class="elicit-pills" data-name="language" data-multi="false">
        <button type="button" class="elicit-pill" data-value="English" aria-pressed="true">English</button>
        <button type="button" class="elicit-pill" data-value="Other" data-other>Another European language</button>
      </div>
      <input type="text" class="elicit-other" data-for="language" placeholder="Name it (e.g. German, Polish, Danish)" hidden>
    </div>

  </div>
  <div class="elicit-footer">
    <button type="button" class="elicit-skip">Skip</button>
    <button type="button" class="elicit-submit">Build the dashboard</button>
  </div>
</form>
```
