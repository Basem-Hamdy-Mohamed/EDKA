# EDKA — Evidence-Driven Knowledge Architecture

**Turn standards, codes and regulations into an AI-maintained wiki you can audit.**
Every number with a unit is tied to the source page it came from and checked against it. Every source's
authority is set per jurisdiction. Every project decision is recorded, and checked never to fall below the code.

For engineers, code consultants and compliance teams who work across several codes or jurisdictions and let an
AI agent maintain the knowledge base. **Status: experimental (v0.2.x).**

```
  SOURCES                     PROFILES                       PROJECTS
  what each document says  →  what binds in a jurisdiction →  what this project decided, and why
  page by page, with a         (Saudi, US AHJ, …)              (checked: never weaker than the code)
  verification status
```

**Why it exists.** LLM wikis ([Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f))
let an agent turn documents into a maintained Markdown knowledge base. That is enough for research notes.
It is not enough for **normative** sources, where a wrong number becomes a wrong design, and where
"which document governs here?" matters as much as "what does it say?". The same NFPA 101 clause is
guidance on a Saudi project and law where a US authority has adopted it. A plain wiki cannot say that.

**What you get.** A short spec, a file contract any agent can follow (`AGENTS.md`), and one CLI that
checks the work. Plain Markdown and YAML; no database, no server, no model calls. It works with Claude,
Codex, Gemini, Cursor, local models, or a person with a text editor.

```bash
git clone https://github.com/Basem-Hamdy-Mohamed/EDKA && cd EDKA && pip install .
edka view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --project hotel-demo
```
```
escape-duration
→ Governs here: 90 minutes (sbc801-2018, binding #1). sll-lg12-2015 (reference) is stricter at 3 hours, not required here.
→ Project decision D-01: 3 h — stricter than the required 90 minutes
```

## Architecture

EDKA is a set of **layers with one job each**. Each layer is written once and only refers to the layer
below it, never copies it. The folders are the reference layout; the layers are what matter.

```
  raw/            RAW              the original files, untouched (sha256 in the registry)
    │
  sources.yaml    REGISTRY         one entry per document and edition: kind, pages, status, hash
    │
  sources/<id>/   SOURCE PAGES     what one document says, with physical page markers (⟦p.N⟧), verbatim or paraphrase,
    │             + COVERAGE       with a map of every physical page: carried, skipped (why) or pending
    │
  topics/         NEUTRAL TOPICS   what every source says on one design question, side by side:
    │                              values, silent sources (with read depth), conflicts — no verdict
    │
  profiles/       PROFILES         what binds in one jurisdiction or project type: binding (in order),
    │                              client, reference, excluded
    │
  projects/       PROJECTS         what one project decided, why, who and when — never below the code
    │
  evidence/       EVIDENCE         verification reports and pre-correction backups (append-only)
  LOG.md          LOG              every ingest, verification, correction and synthesis
```

| Layer | Answers | Written by | Checked by the validator |
|---|---|---|---|
| Raw + registry | Which edition is this, and is the file still the one we read? | ingest | file present, sha256 unchanged, entry complete, ids unique |
| Source pages | What exactly does this document say, and on which page? | agent, then an independent verifier | page markers in range, every number found in the raw page text, verbatim quotes match (no dropped "not"), values repeated in the text |
| Coverage | Did we read every page? | agent | every physical page mapped once; carried pages link their wiki page |
| Neutral topics | What does each source say on this question, and who is silent? | agent | every number matches the source page its row links to; silent sources have a reason and a read depth; no "binding" verdict on the page |
| Profiles | What binds here? | engineer | sources registered, listed once |
| Projects | What did this project decide? | engineer | decision has a basis and date; never weaker than the binding (or stricter client) value |
| Evidence | Who checked it, and against what? | verifier | report exists, names the source, its pages and the verifier, and says what was not checked |

How information flows:

```
 ingest ─► source pages ─► verify ─► topic (neutral) ─► profile ─► project decision ─► view / answer-check
   │            │             │            │                │              │
 hash      coverage map   evidence    conflicts +       precedence     E024: never
          (every page)    report      silent sources    per country    below the code
```

`edka view <topic> --project <id>` is the read side: it joins a neutral topic with a profile and a
project and prints what governs, which value applies, and every decision with its basis.

### What EDKA adds to a plain LLM wiki

| | Question | EDKA mechanism |
|---|---|---|
| 1 | Which sources bind *this* project, in what order, and which are excluded? | **Applicability profiles** (`profiles/*.yaml`) over **neutral topic pages** |
| 2 | Which sources were checked and say nothing, and how deeply were they read? | **Negative evidence**: `sources_silent` with `depth: raw / wiki / index / not-opened` |
| 3 | Has every page of the source been carried, skipped with a reason, or not reached yet? | **Page-level coverage maps** checked for gaps and overlaps |
| 4 | Is this the source's own wording, or the LLM's paraphrase? | **Transcription mode** per source and page |
| 5 | Who checked these values, against what, and where is the report? | **Verification status** with evidence reports |
| 6 | Which edition is this? Has the raw file changed since ingest? | **Registry with editions and sha256**, supersession, stale-topic detection |

Read the full [specification](SPEC.md).

### One wiki, many jurisdictions
Whether a source binds is not a property of the source. It depends on the project. NFPA 101 is guidance
on a Saudi project and binding where a US authority has adopted it. So EDKA topic pages stay neutral, and
each project type gets a profile:

```bash
python tools/edka.py view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --profile saudi-new-building
python tools/edka.py view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --profile us-ahj-nfpa101-2018
```

The same page gives two answers:

| | Saudi new building | US, AHJ adopted NFPA 101-2018 |
|---|---|---|
| Governs | SBC 801 (SBC 401 is binding but silent) | NFPA 101-2018 |
| Escape route | 11 lux average / 1 lux minimum → 6 / 0.6 lux at the end | 10.8 / 1.1 lux → 6.5 / 0.65 lux at the end |
| Duration | 90 minutes | 1½ hours |
| Saudi codes | shown | hidden (excluded) |

A third layer records what one **project** decided. For the illustrative hotel in the example, the
client brief adopts LG12's 3 hours. `--project hotel-demo` shows that decision next to conflict EL-4,
together with what the profile alone would have said:

```bash
python tools/edka.py view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --project hotel-demo
```

With structured values, `view` also compares the numbers and says which one governs:

```
escape-duration
→ Governs here: 90 minutes (sbc801-2018, binding #1). sll-lg12-2015 (reference) is stricter at 3 hours, not required here.
→ Project decision D-01: 3 h — stricter than the required 90 minutes
```

A project decision that goes **below** the binding value fails validation (E024).

**Source pages** say what each document says → **profiles** say what binds in a jurisdiction →
**projects** say what was decided and why. Each is written once.

## Quick start

```bash
pip install pyyaml
python tools/edka.py validate examples/demo-wiki        # 0 errors, 0 warnings
python -m unittest discover -s tests -v                 # 73 tests; they run 89 mutation cases from three independent reviews as sub-tests
```

The [demo wiki](examples/demo-wiki) uses **fictional** sources (a demo code, a superseded edition, a
design guide and a utility spec). In about a dozen files it shows a binding-versus-guidance conflict
resolved by a profile, a silent source with read depth, a superseded edition kept for history, coverage
maps, and an independent verification report. Start at
[`topics/distribution/voltage-drop.md`](examples/demo-wiki/topics/distribution/voltage-drop.md).

A second example, [escape-route lighting](examples/lighting-escape-route), comes from the real private
wiki: SBC 801 (binding in Saudi Arabia) against NFPA 101, BS EN 1838, BS 5266-1 and SLL LG12. It keeps
clause numbers, page numbers and values, and no source text. The registry carries each PDF's SHA-256, so
anyone with a licensed copy can run `--raw-root` and have every number checked against the PDF text.
**Without those PDFs this example cannot be fully reproduced**: the structure, views and project checks run,
but the raw-text and hash checks are skipped (I001). A public-domain example with its PDFs is on the roadmap.

Validate your own wiki:

```bash
python tools/edka.py hash     path/to/wiki    # record raw-file hashes in sources.yaml
python tools/edka.py validate path/to/wiki --json report.json
python tools/edka.py validate path/to/older-wiki --legacy   # tolerant mode for pre-EDKA frontmatter
python tools/edka.py new-source path/to/wiki --id nec-2017 --title "NEC" --edition 2017 --raw raw/nec.pdf --pages 900
python tools/edka.py new-topic  path/to/wiki topics/power/voltage-drop.md --title "Voltage drop" --sources nec-2017
python tools/edka.py view path/to/wiki topics/x.md --profile <name>   # a neutral topic rendered for one project
python tools/edka.py answer-check path/to/wiki answer.md --profile <name>   # cited pages, verification, unsupported numbers, excluded sources
```

An agent operating manual is in [templates/AGENTS.md](templates/AGENTS.md).

## What the validator checks

It **fails closed**: a missing root, `edka.yaml` or registry, an unknown page type, unreadable YAML or an
invalid date is an error, never a silent pass. `edka explain <CODE>` says what any finding means and how to
fix it; `--json` adds the fix to every finding, so an agent can act on it.

| Layer | Codes | What fails |
|---|---|---|
| Loading | E000, E001, E002, E025, E029 | wiki/registry missing, bad YAML or date, missing `type`, unknown type, invalid field value |
| Raw + registry | E006, E007, E014, W106 | raw file missing or changed since hashed; incomplete or duplicate entries |
| Source pages | E003, E016, E022, E023, E026, E031, W102, W116, W124 | unknown source; quote not verbatim or an ellipsis drops a negation; value not in the text; bad `source_pages`; number not in the raw page text |
| Coverage | E008, W104, W111, W125 | page gaps or overlaps; carried pages without a wiki page; page not mapped to its wiki page |
| Topics | E009, E010, E012, E015, E018, E030, W101, W105, W107, W108, W119, W120, W122 | a number not on the source page its row links to; silent source without reason or depth; a verdict on a neutral page; withdrawn, superseded or excluded sources (also through rows and `derived_from`) |
| Profiles | E011, E019, W118 | conflicts no profile resolves; unknown or repeated sources |
| Projects | E020, E021, E024 | missing decisions; invalid decisions; a decision weaker than the binding or stricter client value |
| Evidence | E013, E017, E027, W109, W114, W126 | independent claims without verifier, author or report; verifier = author; report does not cover the page |
| Links | E005, W103, W123 | broken links, orphans, letter-case mismatches that fail on Linux |
| Computed lines | E032, I002 | `⟦calc⟧` on a line that shows no arithmetic; every computed line is listed for a human check |
| Topic consistency | E030, E033, W127, W129, W130, W132 | a silent source whose content is reported; a source used but not listed; prose that sounds like a verdict; different values for one key with no conflict recorded; a source never assessed; a decision with a number but no key |
| Level | E028 | the wiki does not meet the `level:` it declares (core, coverage, synthesis, governed); `governed` also requires an independent verification report, no unverified source page and at least one carried coverage row, and turns W104, W106, W109, W114, W119, W126 and W129 into errors |

`--strict` turns warnings into errors, except the heuristic ones (W103, W105, W116, W127, W130) that a
human reviews. `hash` never re-blesses a changed raw file: it needs
`--force <id>` after the pages have been re-verified.

## Limitations

- Choosing value keys (which quantities are "the same") is an engineering judgement, recorded on the page.
- Verification is declared by agents and people. The validator checks that each claim is complete and
  consistent with its report, not that the reviewer looked carefully.
- Numbers are recognised with a unit, including compound units (`W/m²`, `m/s`), hyphenated forms (`90-minute`)
  and `per cent`; add units with `units:` in `edka.yaml`. Bare numbers (`factor 0.8`) are not checked.
- A number is checked against the source page its table row links to, not against the column it sits in:
  two values of the same page swapped between columns are not caught.
- `⟦calc⟧` lines are not compared with sources; they must show their arithmetic and are listed (I002) for a
  human check.
- On scanned PDFs, OCR text can differ from the page image, so missing numbers there are warnings.
- The neutrality check (E018/W127) is a keyword heuristic; a determined author can still write a verdict into a
  topic.
- EDKA has no search engine. Use any retrieval tool; `view` and `answer-check` are the governance layer on top.

## How EDKA relates to other work

EDKA is **not** a fork of the LLM Wiki gist, and it is not affiliated with Andrej Karpathy. It follows
the gist's pattern (raw sources, an LLM-maintained wiki, a schema file) and adds the governance above.

Other projects already do parts of this well. Use them together with EDKA rather than instead of it:

- **Claim-level citations, faithfulness checks and audit trails:**
  [synthadoc](https://github.com/axoviq-ai/synthadoc) and
  [llm-wiki-compiler](https://github.com/atomicstrata/llm-wiki-compiler) are ahead here, with working
  tooling.
- **Contradiction files, confidence scores and claim pages:** several LLM Wiki forks and "v2" write-ups
  propose these.

We did not find any of these to model the six items in the table above. Tell us if we missed a project
that does.

## Origin

EDKA was extracted from a private electrical-engineering wiki: about 1,800 pages over roughly 40
standards, codes, design guides and catalogues (NEC, IEC, BS, NFPA, Saudi building codes, utility
specifications), maintained with Claude Code since 2026. That wiki is **not** published, because the
underlying standards are copyrighted. Only the method, the spec, the tools, a fictional example and a values-only
example (no source text) are published here.

Running the validator in `--legacy` mode on that wiki (1,821 pages, about 5 seconds) found real defects
that earlier manual audits had missed: a page missing from a coverage map, about 100 links to a renamed
checklist, two topic pages whose frontmatter was not valid YAML, and pages with no verification record.
They were fixed in 86 files, each backed up first. That is why the validator exists.

## Status

v0.2.2, experimental. Breaking changes are possible until v1.0. See the [roadmap](ROADMAP.md).

## License

- **Code** (`tools/`, `tests/`, `.github/`): [Apache License 2.0](LICENSE)
- **Spec, documentation and examples**: [Creative Commons Attribution 4.0](LICENSE-docs)

The standards and guides named in the examples belong to their publishers. They are not covered by
these licenses and are not included here (see [NOTICE](NOTICE)).
