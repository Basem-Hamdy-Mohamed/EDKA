# EDKA Specification v0.1 (draft)

EDKA is a governance layer for LLM-maintained wikis built from **normative sources**: standards, codes,
regulations, specifications and client requirements. In these sources a wrong number becomes a wrong
design, so "the LLM summarised it" is not good enough.

EDKA builds on the LLM Wiki pattern (raw sources, an LLM-maintained Markdown wiki, a schema file).
It does not replace citation or contradiction tooling such as llm-wiki-compiler or synthadoc. It adds six
things those tools do not model:

| # | Capability | Question it answers |
|---|---|---|
| 1 | **Applicability profiles** | Which sources are binding *for this project*, in what order, and which are excluded? |
| 2 | **Negative evidence** (`sources_silent`) | Which sources were checked and say nothing, and how deeply were they checked? |
| 3 | **Page-level coverage maps** | Has every physical page of the source been placed, skipped with a reason, or not reached yet? |
| 4 | **Transcription mode** | Is this text the source's own words (verbatim) or the LLM's paraphrase? |
| 5 | **Verification status lifecycle** | Who checked these values, against what (page images, text layer), and where is the report? |
| 6 | **Edition and integrity tracking** | Which edition is this? Has the raw file changed since ingest? Which pages are now stale? |

Everything else (folders, page naming, language) is left to the implementation.

---

## 1. Conformance levels

| Level | Required |
|---|---|
| **Core** | Source registry, raw integrity hashes, page frontmatter (`source`, `source_pages`, `transcription`, `verification`), link integrity |
| **Coverage** | Core + one coverage map per source, with no page gaps or overlaps |
| **Synthesis** | Coverage + topic pages with `sources_covered`, `sources_silent` and `conflicts` |
| **Governed** | Synthesis + at least one applicability profile + independent-verification reports |

A wiki states its level in `edka.yaml`. The validator (`tools/edka.py`) checks the stated level.

## 2. Functional layers

EDKA defines **layers**, not folders. The reference layout in §8 is one valid mapping.

| Layer | Responsibility | Mutability |
|---|---|---|
| **Raw** | Original files, exactly as received | Immutable; a new edition is a new file |
| **Registry** | One record per source: identity, edition, hash, kind, transcription mode, status | Changed only by ingest or withdrawal |
| **Source knowledge** | Pages derived from one source; internal structure follows the source | LLM-maintained |
| **Coverage** | Physical page → wiki page or reason | Updated with every ingest |
| **Topics** | Cross-source synthesis per design question | Derived; never the citation target |
| **Profiles** | Binding order and exclusions per project type or jurisdiction | Human-owned |
| **Projects** | One file per project: its profile and its recorded decisions | Human-owned |
| **Evidence** | Verification reports, backups made before corrections | Append-only |
| **Log** | Time-ordered record of ingest, query, lint and correction events | Append-only |

Rules for the boundaries between layers:

1. A topic page **never** holds a value that is not on a source page. Topics link; source pages cite.
2. A citation goes to a **source page plus a physical page** (`⟦p.N⟧`), never to a topic.
3. **Applicability is not a property of a source.** It is a relation between a source and a project.
   NFPA 101 is guidance on a Saudi project and binding where a US authority has adopted it.
   So topic pages are **neutral**: they say what each source says, with no "binding" column and no
   answer for one jurisdiction (the validator rejects both, E018). Profiles are the **only** place where
   precedence lives, and `edka.py view <topic> --profile <name>` renders a topic for one profile.
4. A glossary is **optional**. Definitions stay in the source that gives them. A glossary entry may
   only point to them.

## 3. Source registry (`sources.yaml`)

```yaml
- id: dec-2024                 # readable slug, edition included; never SOURCE_001
  title: Demo Electrical Code
  edition: "2024"
  kind: normative              # normative | guidance | client-requirement | catalogue | other
  raw: raw/dec-2024.md         # path under the raw layer
  sha256: 3f1c...              # written by `edka.py hash`; checked by `edka.py validate`
  pages: 6                     # physical page count (needed for coverage)
  transcription: verbatim      # verbatim | paraphrase  (default for the source's pages)
  folder: sources/dec-2024     # where its knowledge pages live
  status: active               # active | superseded | withdrawn
  supersedes: dec-2018         # optional
  license_note: "fictional demo text, CC0"
  short: ["DEC 2024"]           # names used in prose; topic paragraphs naming them need a ⟦src:⟧ tag
  redistributable: true        # false: raw file is kept outside the repo; hash checked with --raw-root
```

Transcription mode is a risk control. `verbatim` pages may be quoted to a client.
For a `paraphrase` source, the exact wording must come from the raw file, not the wiki.

## 4. Page frontmatter

### 4.1 Source page

```yaml
type: source-page
title: "Voltage drop (DEC 4.2)"
source: dec-2024
source_pages: "3-4"            # physical PDF pages, not printed page numbers
transcription: verbatim        # optional override of the registry default
verification:
  status: independent          # see 4.3
  date: 2026-11-26
  by: verifier-agent-2         # must differ from the author for 'independent'
  ref: evidence/2026-11-26-dec/report.json
updated: 2026-11-26
```

Inline markers in the body:

| Marker | Meaning |
|---|---|
| `⟦p.N⟧` | The physical page that the following text or value comes from |
| `⚠️ (as printed)` | An error in the source itself, copied unchanged |
| `🔎 YYYY-MM-DD` | A correction made after review, with the old value and the page checked |
| `⟦calc⟧` | This line holds a computed value (a sum, a conversion); it is not expected in the source |
| `⟦src:a,b⟧` | (topic pages) this paragraph is about sources a and b; `view` hides it under a profile that excludes either |

Mechanical checks on source pages (when the raw file is available, `--raw-root` for files kept outside the repo):
- every number with a unit must appear in the raw text of the page's `source_pages` (W116; OCR scans may differ,
  which is why values are also checked against page images);
- on `verbatim` pages every `>` blockquote must match the raw text of those pages (E016).

On topic pages, every number with a unit must appear on a page listed in `derived_from` (E015).

### 4.2 Note page

`type: note` marks project knowledge that does not come from a registered source (lessons, clash
patterns, equipment data). It needs `verification` only, and it must not be cited as a source.

### 4.3 Topic page

```yaml
type: topic
title: "Voltage drop limits"
sources_covered:
  - {source: dec-2024, locators: ["4.2", "Table 4-1"], depth: raw}
  - {source: dgd-2019, locators: ["3.1"], depth: wiki}
sources_silent:
  - {source: usc-2022, reason: "utility spec covers the service side only; no voltage-drop clause", depth: raw}
conflicts:
  - id: VD-1
    between: [dec-2024, dgd-2019]
    summary: "DEC caps the total at 4 %; DGD recommends 3 % + 2 %"
    status: resolved-by-profile   # open | resolved-by-profile | resolved-by-project | accepted-difference
derived_from: [sources/dec-2024/ch4-voltage-drop.md, sources/dgd-2019/s3-cable-sizing.md]
verification: {status: derived}
updated: 2026-11-26
```

`depth` records how deeply a source was read for this page:

| depth | Meaning |
|---|---|
| `raw` | The raw file was opened for this page |
| `wiki` | Only the source's wiki pages were read |
| `index` | Only an index or hub listing was read |
| `not-opened` | Listed for completeness; not read |

**Negative evidence is a claim, so it needs its own evidence.** "Source X is silent" with `depth: index`
is a weak claim. The validator flags it so that no one reads it as a strong one.

### 4.4 Verification status

| status | Meaning | Requires |
|---|---|---|
| `unverified` | Not checked | — |
| `author-checked` | The author re-read the values against page images | `date` |
| `sample-audit` | A sample was audited, not every table | `date`, `ref` |
| `independent-partial` | A different agent or person checked some tables or pages | `date`, `by`, `ref` |
| `independent` | A different agent or person checked every table, number and formula | `date`, `by`, `ref` |
| `derived` | A synthesis page; values come from the pages it links to | `derived_from` |

`independent` and `independent-partial` also record `author`; the validator rejects `author == by`.

The `ref` report lists **what was not checked** (`not_checked`). An `independent` status with an empty
`not_checked` is a claim the report must support.

## 5. Coverage map

One per source (`<folder>/coverage.md`). It is a Markdown table so that people can read it and the
validator can parse it:

```markdown
| Pages | Wiki page | Treatment |
|---|---|---|
| 1-2 | — | not-ingested: cover, contents |
| 3-4 | [ch4-voltage-drop.md](ch4-voltage-drop.md) | transcribed |
| 5 | — | no-relevant-content: mechanical clauses |
| 6 | — | pending |
```

Treatment is one of `transcribed`, `summarised`, `not-ingested: <reason>`,
`no-relevant-content: <reason>` or `pending`. The page ranges must cover `1..pages` with no gaps
and no overlaps. `no-relevant-content` (the source has nothing on this) and `not-ingested`
(we chose not to carry it) are different facts and must not be merged.

## 6. Applicability profiles (`profiles/*.yaml`)

```yaml
name: demo-land-building
applies_to: "buildings in Demo Land"
binding:                    # highest precedence first
  - {source: dec-2024, scope: "everything inside the building"}
  - {source: usc-2022, scope: "utility side of the service point"}
client: []                  # client requirements; apply where stricter
reference: [dgd-2019]       # engineering guidance; never overrides binding
excluded: [foreign-code-x]  # hidden when a topic is viewed under this profile
```

One wiki holds several profiles, one per jurisdiction or project type, for example
`saudi-new-building` and `us-ahj-nfpa101-2018`. Rules:

- **The edition is part of the source id.** One US authority may adopt NEC 2017 and another NEC 2023.
  Register each edition as its own source and put the adopted one in `binding`.
- **Local amendments** are registered as their own sources and listed in `binding` above the code they
  amend, or in `client` for client requirements, which apply where stricter.
- A source may appear in only one list of a profile, and every listed source except in `excluded` must
  be registered (E019).
- A source that must never appear on any topic page, whatever the profile, goes in
  `edka.yaml: excluded_from_topics` (E012).

**Conflicts are resolved per profile.** For `resolved-by-profile`, the governing side under a profile is
the binding source with the highest precedence. A client requirement is added "where stricter". If a
side is excluded by the profile and fewer than two sides remain, the conflict does not apply there.
The validator reports E011 when no profile resolves the conflict, and W118 for each profile under which
no side is binding, because that profile needs a project decision.

`edka.py view` output, per profile:
1. **What governs:** the binding sources that cover the topic, with their scope, and any binding source
   that is **silent** on the topic, with the reason and read depth.
2. **Conflicts:** who governs each one under this profile.
3. **Source values:** the topic's tables with an "Applies here" column, rows ordered by precedence, and
   excluded rows hidden.

### 6.1 Topic pages written for profiles
- Every table row links to the source page it reports (W119), so `view` can label and order it.
- A paragraph that names a registered source (its id or a `short` name) starts with `⟦src:id,…⟧` (W120),
  so `view` can hide it where the source is excluded. Untagged paragraphs are shown everywhere.

### 6.2 Structured values and automatic comparison
A source page may repeat its key numbers in a `values:` list, so that tools can compare them:

```yaml
values:
  - {key: escape-duration, value: 90, unit: "minutes", dir: min, page: 230, locator: "1008.3.4"}
```

- `dir: min` means a minimum requirement (higher is stricter); `dir: max` a maximum (lower is stricter);
  `dir: info` a value that is never compared.
- **The same key means the same quantity measured the same way.** SBC 801's average along the egress
  path and EN 1838's centre-line minimum get different keys, so they are never compared. Choosing keys
  is an engineering judgement and is recorded on the source page.
- Every listed value must also appear in the page body (E023), so the list cannot drift from the text.
- Time units are converted (h ↔ min). Other units must match exactly; a key used with different units
  or directions is reported (W121) and never compared.
- `view` adds **Values compared**: each key's values from every non-excluded source, the strictest one,
  the value that **governs** under the profile (the highest-precedence binding source), any stricter
  client value, and any stricter guidance that is not required.
- A project decision may carry `key`, `value` and `unit`. A decision less strict than the governing
  binding value is an error (E024): a project can go above the code, never below it.

### 6.3 Projects (`projects/*.yaml`)
A profile covers a jurisdiction. A project can still decide differently: a client brief that adopts a
stricter guide, a value no binding source gives, or a choice between two binding sources. Those
decisions are recorded once, per project, with their basis:

```yaml
id: hotel-demo
profile: saudi-new-building
decisions:
  - id: D-01
    topic: topics/lighting/escape-route-illuminance-and-duration.md
    conflict: EL-4                      # optional: a conflict on that topic
    question: "Duration"                # used when there is no conflict id
    decision: "3 hours for all escape lighting"
    basis: "Client design brief, section 4.2"
    by: "lead electrical engineer"
    date: 2026-11-30
```

- A conflict with status `resolved-by-project` must have a decision in at least one project (E020).
- A decision needs `id`, `topic`, `decision`, `basis` and `date`; its topic and conflict must exist,
  and the project's profile must exist (E021).
- `edka.py view <topic> --project <id>` uses the project's profile, shows each decision next to the
  conflict it settles (and what the profile alone would have said), and lists the other decisions on
  the topic.

The chain is: **source pages (what each source says) → profile (what binds in this jurisdiction) →
project (what this project decided, and why)**. Each layer is written once and never copied into the
others.

## 7. Lifecycle events

| Event | Writes |
|---|---|
| **ingest** | raw file, registry entry and hash, source pages, coverage map, log line |
| **verify** | evidence report, `verification` fields, log line |
| **correct** | backup in evidence, `🔎` marker, log line (only after the page image was seen) |
| **synthesise** | topic page with `sources_covered`, `sources_silent`, `conflicts` and `derived_from` |
| **supersede** | new registry entry with `supersedes`; the old entry gets `status: superseded`; its pages stay |
| **withdraw** | `status: withdrawn`; the validator lists every topic that still relies on it |
| **query** | answer cites source pages; the answer states the verification status of each value it uses |
| **lint** | `edka.py validate` report |

## 8. Reference layout

```
my-wiki/
├── edka.yaml          # level, paths
├── sources.yaml       # registry
├── AGENTS.md          # instructions for the LLM (points at this spec)
├── raw/               # immutable originals (git-ignored if not redistributable)
├── sources/<id>/      # pages for one source + coverage.md; internal layout is free
├── topics/<branch>/   # cross-source synthesis
├── profiles/          # applicability profiles, one per jurisdiction or project type
├── projects/          # one file per project: profile + decisions
├── evidence/          # verification reports, pre-correction backups
└── LOG.md
```

No GOVERNANCE/, RETRIEVAL/ or VALIDATION/ folders: governance is the profiles and this spec,
retrieval belongs in AGENTS.md, and validation is a tool, not a folder.
