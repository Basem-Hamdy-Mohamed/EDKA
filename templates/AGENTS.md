# AGENTS.md — EDKA wiki operating rules

Copy this file to the root of your wiki and adapt the **Project** section. It tells an LLM agent
(Claude Code, Codex, OpenCode, …) how to maintain an EDKA wiki. The rules come from SPEC.md.

## Project
- Domain: <e.g. electrical design of buildings>
- Default profile: `profiles/<name>.yaml`
- Language of summaries: <e.g. English>. Values, clause numbers and quoted text stay in the source language.

## Hard rules
1. **Never edit `raw/`.** A new edition is a new file and a new registry entry.
2. **Never change a number, unit, formula or table value** from what the page image shows. If the source
   is wrong, copy it and add `⚠️ (as printed)`.
3. **Cite source pages, not topics.** Every value carries `⟦p.N⟧` (physical PDF page).
4. **Verbatim means verbatim.** On a page with `transcription: verbatim`, text in `>` blockquotes must
   match the raw text exactly; use `…` for cuts. If you are paraphrasing, do not use a blockquote.
5. **Do not verify your own work.** `status: independent` needs a different agent or person in `by`
   than in `author`, and a report in `evidence/` with a `not_checked` list.
6. **"Silent" is a claim.** Write a `sources_silent` entry only with a reason and the true read depth
   (`raw`, `wiki`, `index`, `not-opened`). Do not write `raw` unless you opened the raw file for this page.
7. **Topics are neutral; precedence lives in profiles.** A topic reports what each source says, with no
   "binding" column and no answer for one jurisdiction. Every table row links to a source page, so
   `edka.py view --profile` can tell which source the row belongs to. To answer for a project, run
   `edka.py view <topic> --profile <project profile>` and answer from that.
8. **Before a correction:** look at the page image, copy the page to `evidence/<date>-backup/`, then add
   `🔎 YYYY-MM-DD` with the old value and the page you checked.
9. **Run the validator before you say "done":** `edka validate . --strict`, with 0 errors. For any code
   you do not understand, run `edka explain <CODE>`.
10. **Never clear E007 by re-hashing.** A changed raw file means its pages must be re-verified first;
    only then `edka hash . --force <id>`.

## Workflows

### Ingest a source
1. Put the file in `raw/`. Run `edka.py new-source . --id <slug-edition> --title … --edition … --raw raw/<file> --pages <N>`.
2. Read the source in full. Create pages under `sources/<id>/`, organised the way the source is organised.
3. Fill in `coverage.md` for every page: `transcribed`, `summarised`, `not-ingested: <reason>`,
   `no-relevant-content: <reason>`.
4. Set `verification: {status: author-checked, author: <you>, date: …}` after you re-read every table
   against the page images.
5. Add a line to `LOG.md`: `## [date] ingest | <source>`.

### Verify (a different agent)
1. Compare every table, number and formula with the page images.
2. Write `evidence/<date>-<id>/report.json` with `pages_checked`, `findings` and `not_checked`.
3. Set `status: independent` (or `independent-partial`) with `by`, `date` and `ref`.

### Synthesise a topic
1. `edka.py new-topic . topics/<branch>/<name>.md --title … --sources a,b`
2. For each covered source, add the locators and `derived_from` pages. Copy values exactly.
3. Confirm or remove every generated `sources_silent` entry. Each needs a real reason and depth.
4. Record every disagreement in `conflicts:` and resolve it with a profile, a project decision, or
   `accepted-difference`.
5. Mark any computed value's line with `⟦calc⟧`.
6. Link every table row to its source page. Start any paragraph that names a source with `⟦src:id,…⟧`.

### Add structured values
On source pages, list the key numbers in `values:` (key, value, unit, dir, page, locator). Use the same
key only for the same quantity measured the same way; if in doubt, use a new key. Every value must also
be written in the page body.

### Record a project decision
When a project departs from its profile, or settles a `resolved-by-project` conflict, add a decision to
`projects/<id>.yaml` with the topic, the conflict id (if any), the decision, its basis document, who
decided and the date. Never write a project's decision into a topic page.

### Answer a question
1. Find the project. Run `edka.py view <topic> --project <id>` (or `--profile <name>` when there is no project file), then open the source pages it links to.
2. Name the profile, cite source pages with `⟦p.N⟧`, and state each value's verification status.
3. Say which sources were checked and found silent.
4. Run `edka.py answer-check . answer.md --profile <name>` on any written answer before you send it. It fails if the
   answer cites a source the profile excludes.
