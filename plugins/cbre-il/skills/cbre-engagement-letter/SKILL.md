---
name: cbre-engagement-letter
description: "Draft a CBRE Industrial & Logistics ENGAGEMENT LETTER (letter of engagement, appointment or mandate letter, terms of engagement) as a CBRE-branded Word document in the house layout: cover, letter page, instruction, services, team, remuneration, exclusivity, term, jurisdiction-specific terms clause, approval block and Thank you page. Takes a client requirement, asks the open questions (always including jurisdiction and contracting entity), offers to search the user's email for the team and client details, then fills in what it can and marks the rest as yellow placeholders. Use whenever the user wants an engagement letter, EL, letter of engagement or mandate letter, or says 'put this requirement into an EL' or 'paper the mandate', for any occupier search, lease or purchase, build-to-suit, sale and leaseback or capital markets mandate anywhere in Europe. Also use when revising an engagement letter the user has edited."
---

# CBRE engagement letter

Produces a signable (or scope-only) engagement letter in the house layout: the same cover,
fonts, tables, header, footer and Thank you page every time, with content adapted to the
requirement. The structure is fixed and proven; adapt the content, not the structure.

Files in this skill:
- `scripts/build_letter.py`: builds the .docx from a JSON spec using `assets/template.docx`
- `scripts/edit_docx.py`: targeted edits to an existing letter (for revisions)
- `scripts/compare_text.py`: lists every text difference between two versions
- `assets/example_spec.json`: complete anonymised example to copy from
- `references/wording.md`: house wording for every section, fee variants, style rules. Read it before drafting.
- `references/jurisdictions.md`: contracting entity and terms clause per country. Read it once the jurisdiction is known.
- `references/spec_format.md`: spec fields and block types. Read it before writing the spec.

## Workflow for a new letter

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a
one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise
it is silent); it does nothing but a single public version lookup, never blocks the run, and is
safe to ignore.

### 1. Read the requirement and extract what is already known

From the requirement (email, brief, notes, attachments), note: client name, what they need,
geography, size and specification, timing, lease term, confidentiality requests, anyone
named. Decide the letter type: occupier search (lease, purchase, build-to-suit) or capital
markets (sale and leaseback, investment sale). Do not ask for anything the requirement
already answers.

### 2. Ask the open questions, all in one message

The user wants to be asked, not guessed for. Ask only what is still missing, in a single
message, and address what you can already before asking. Always ask these three, because
they change the legal content of the letter and are easy to get wrong:

1. **Jurisdiction**: which country's CBRE entity signs? (This skill is used across Europe.
   The search geography is not the answer; a five-country search can be contracted by one
   entity.) Then confirm the entity and terms regime from `references/jurisdictions.md`; if
   the country is not in the verified table, ask for the entity name and terms regime.
2. **Fee basis and abortive fee**: never pick a structure or number. Offer the variants in
   `references/wording.md` section 7.
3. **Letter status**: signable with terms and an approval block, or scope-only with a
   separate agreement to follow.

Then, where not already known: client legal entity, contact name and address; letter-page
signatories; who signs the approval block for CBRE (do not assume it is the author); team
members per country; date of any earlier proposal to reference.

Then ask whether to search their email or files, and say what for, for example: "Shall I
search your email for the requirement you sent out, to pick up the team from the
recipients?" Do not search until the user agrees.

Use the tappable-options tool for the choice questions (fee basis, abortive fee, letter
status) and plain text for names and addresses. Make clear that anything they do not know
yet will go in as a yellow placeholder, so they are never blocked.

### 3. Search, if the user agreed

- Find the requirement email by subject or keywords, read the full message, and take the
  To and Cc recipients as candidate team members.
- Look up each person's job title in the directory (people search). Directory titles are
  often truncated or bare ("Consultant", "Director, Head of Industrial &"): complete them
  sensibly and list every completion in the reply for the user to check.
- Watch for external or affiliate addresses (a different domain than cbre.com), two
  addresses for one person, and typos in addresses. Use the address the person actually
  sends from, and flag it.
- A cc'd senior person is not automatically a signatory. Ask.

### 4. Draft the spec

Copy `assets/example_spec.json` and adapt it using `references/wording.md`. Rules:
- Keep it relatively simple. High-level requirement, not a technical specification.
  Standard phases and standard clauses, with small adaptations to the requirement.
- Full, understandable sentences in all prose; tables only for specifications and team.
- British English, no em or en dashes, straight quotes, hyphen for ranges ("3-6 months").
- Unknowns become `[[placeholders]]`. Never invent an entity name, address, fee, date or
  job title.
- Include a Confidentiality section when the client asked for confidentiality.
- Terms clause and approval block exactly per `references/jurisdictions.md`.

Be critical while drafting. If the requirement contains a tension (for example a 3-6 month
timeline with "development project", or a landlord-paid fee in a market where landlord fee
recovery is unlikely), frame the letter sensibly and raise it in the reply. Do not bury it.

### 5. Build and check

```bash
python scripts/build_letter.py spec.json /mnt/user-data/outputs/Engagement_Letter_<Client>_v1.docx
```

Then render and look at every page:

```bash
cd /mnt/user-data/outputs && soffice --headless --convert-to pdf Engagement_Letter_<Client>_v1.docx
pdftoppm -jpeg -r 60 Engagement_Letter_<Client>_v1.pdf page
```

(If `soffice` is not on the path, use the docx skill's `scripts/office/soffice.py`.) Check:
- No heading or table header stranded at the bottom of a page; add a `pagebreak` block before it.
- No blank page before the Thank you page (remove a trailing `empty` block).
- Every prose paragraph reads as full sentences; no data dumps.
- Builder output reports no dashes; placeholders listed match what you expect.
- Entity, terms clause and approval block match the jurisdiction.
Delete the PDF and page images from the outputs folder after checking.

### 6. Deliver

Name every delivered file with a version number, `Engagement_Letter_<Client>_v<N>.docx`, and
never reuse a file name. Older file cards in the chat keep pointing at old versions, and
identical names make it impossible for the user to tell which one they opened.

In the reply, keep it short:
- One line on what the letter covers.
- The yellow placeholders still open.
- Every assumption or completion you made (job titles, addresses, clauses you added), each
  in one line, so the user can check them without rereading the letter.
- Critical points that need the user's judgement.
- How to recognise this version (for example "approval block shows CBRE Limited").

## Revisions: the rules that matter most

These rules exist because rebuilding a letter the user has already edited silently throws
their edits away, and they then have to recheck the whole document. That destroys trust
faster than any drafting error.

1. **The user's latest file is the base, always.** When the user says they edited the
   letter, or says "take my other changes as given", work from their file, not from your
   spec or your last output. Ask which file is the latest if there is any doubt.
2. **Get the actual file.** If you can only read it as text (for example through a
   SharePoint or OneDrive connector), say so plainly: text reading misses formatting
   changes and may lag behind unsynced local edits. Ask the user to upload the file.
3. **Edit in place.** Use `scripts/edit_docx.py` on the user's file for the requested
   changes only. Each edit must match exactly one paragraph, so nothing else moves.
4. **If a rebuild is unavoidable**, first update the spec so its text matches the user's
   version, including deletions, then rebuild.
5. **Compare before delivering.** Run
   `python scripts/compare_text.py <users_latest> <new_file>` and check that every
   difference is one the user asked for. List all differences in the reply, including
   corrections you made yourself (for example a typo in an email address). State that
   formatting-only changes are not covered by the comparison.
6. **Increment the version number** in the file name for every delivery.
7. **Do not claim** edits were lost or overwritten, or that a version exists, without
   checking. If you cannot find what the user refers to, say exactly what you checked and
   ask for the file.

## Example of a good first reply (after reading a requirement)

> I have the requirement: cold store search, Czechia and Slovakia, 5-year lease, available
> in 6 months. Before I draft, a few things only you can give me; anything you don't have
> yet goes in as a yellow placeholder:
> 1. Which jurisdiction signs, i.e. which CBRE entity is the contracting party?
> 2. Client legal entity, contact name and address.
> 3. Who signs the letter page, and who signs the approval block for CBRE?
> Shall I search your email for the requirement you sent to the local teams, so I can pick
> up the team from the recipients?
> [tappable options: fee basis / abortive fee / signable or scope-only]
