# EDKA — Evidence-Driven Knowledge Architecture

**Turn standards, codes and regulations into an AI-maintained wiki you can audit.**
Every value traced to its page. Every source's authority set per jurisdiction. Every project decision
recorded, and never below the code.

```
  SOURCES                     PROFILES                       PROJECTS
  what each document says  →  what binds in a jurisdiction →  what this project decided, and why
  page by page, verified      (Saudi, US AHJ, …)              (checked: never weaker than the code)
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
pip install git+https://github.com/Basem-Hamdy-Mohamed/edka
edka view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --project hotel-demo
```
```
escape-duration
→ Governs here: 90 minutes (sbc801-2018, binding #1). sll-lg12-2015 (reference) is stricter at 3 hours, not required here.
→ Project decision D-01: 3 h — stricter than the binding 90 minutes
```

EDKA adds what plain LLM wikis do not model:

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
→ Project decision D-01: 3 h — stricter than the binding 90 minutes
```

A project decision that goes **below** the binding value fails validation (E024).

**Source pages** say what each document says → **profiles** say what binds in a jurisdiction →
**projects** say what was decided and why. Each is written once.

## Quick start

```bash
pip install pyyaml
python tools/edka.py validate examples/demo-wiki        # 0 errors, 0 warnings
python -m unittest discover -s tests -v                 # 54 tests
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

| Code | Check |
|---|---|
| E003 / E014 | Every page points to a registered source; registry entries are complete |
| E006 / E007 | Raw file exists and is unchanged since it was hashed |
| E008 | Coverage map has no page gaps or overlaps (a shared boundary page is allowed) |
| E009 / W105 | Each silent source has a reason and a read depth; shallow reads are flagged as weak |
| E010 / E011 | Conflicts are well-formed; "resolved by profile" needs a profile that makes one side binding |
| E018 | A topic states applicability (a binding column or a per-profile answer) instead of staying neutral |
| E019 | A profile lists an unknown source, or one source twice |
| E012 | A topic uses a source that `edka.yaml` excludes from all topics |
| W118 | Under some profile, no side of a conflict is binding (that profile needs a project decision) |
| E022 / E023 | A structured value is malformed, or is not stated in the page body |
| E024 | A project decision is less strict than the binding requirement |
| W121 | One value key is used with different units or directions (not comparable) |
| E020 / E021 | A `resolved-by-project` conflict with no recorded decision; an invalid project file |
| W119 / W120 | A topic row with no source link; a paragraph naming a source without a `⟦src:⟧` tag |
| E004 / E013 | Verification status is valid; "independent" names a verifier and a report |
| W101 | A topic is older than a source page it was derived from (stale synthesis) |
| W102 | A `⟦p.N⟧` marker falls outside the page's `source_pages` |
| W107 / W108 | A topic relies on a withdrawn or superseded source |
| E015 | A number in a topic does not appear on any page it is derived from |
| E016 | A blockquote on a verbatim page does not match the raw text of its pages |
| W116 | A number on a source page does not appear in the raw text of its pages |
| E017 / W114 | "Independent" verification by the author, or with no author recorded |
| E005 / W103 | Broken links; orphan pages |

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
underlying standards are copyrighted. Only the method, the spec, the tools and fictional examples are
published here.

Running the validator in `--legacy` mode on that wiki (1,821 pages, about 5 seconds) found real defects
that earlier manual audits had missed: a page missing from a coverage map, about 100 links to a renamed
checklist, two topic pages whose frontmatter was not valid YAML, and pages with no verification record.
They were fixed in 86 files, each backed up first. That is why the validator exists.

## Status

v0.1 is a draft. Breaking changes are expected until v1.0. See the [roadmap](ROADMAP.md).

## License

- **Code** (`tools/`, `tests/`, `.github/`): [Apache License 2.0](LICENSE)
- **Spec, documentation and examples**: [Creative Commons Attribution 4.0](LICENSE-docs)

The standards and guides named in the examples belong to their publishers. They are not covered by
these licenses and are not included here (see [NOTICE](NOTICE)).
