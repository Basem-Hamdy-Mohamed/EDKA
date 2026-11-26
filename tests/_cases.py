"""Mutation cases from the first independent review (41 ways to break a small wiki). Used by test_hardening.py."""
import os, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import edka  # noqa: E402

def w(root, rel, text, bom=False):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8-sig" if bom else "utf-8", newline="\n")

def build(root):
    if root.exists():
        shutil.rmtree(root)
    w(root, "edka.yaml", "edka_version: \"0.1\"\nlevel: governed\n")
    w(root, "raw/abc-2020.txt", """=== page 1 ===
Accessible Building Code 2020. Cover.
=== page 2 ===
3.1 Ramps. The slope of a ramp shall not exceed 8 %. The clear width of a ramp shall be not less than 1.2 m.
3.2 Protection. Socket circuits shall be protected by a residual current device rated not more than 30 mA.
3.3 Supply. Nominal voltage is 1,000 V maximum. Standby lighting shall operate for 60 minutes.
=== page 3 ===
Index.
""")
    w(root, "raw/gde-2021.txt", """=== page 1 ===
Design Guide 2021.
=== page 2 ===
Ramps should be no steeper than 5 %. A width of 1.5 m is recommended. Standby lighting 2 hours.
""")
    w(root, "sources.yaml", """- id: abc-2020
  title: Accessible Building Code
  edition: "2020"
  kind: normative
  raw: raw/abc-2020.txt
  pages: 3
  transcription: verbatim
  folder: sources/abc-2020
  status: active
  short: ["ABC 2020"]
- id: gde-2021
  title: Design Guide
  edition: "2021"
  kind: guidance
  raw: raw/gde-2021.txt
  pages: 2
  transcription: paraphrase
  folder: sources/gde-2021
  status: active
  short: ["GDE"]
""")
    w(root, "sources/abc-2020/ramps.md", """---
type: source-page
title: "Ramps (ABC 3.1)"
source: abc-2020
source_pages: "2"
verification: {status: author-checked, author: me, date: 2026-11-26}
values:
  - {key: ramp-slope, value: 8, unit: "%", dir: max, page: 2, locator: "3.1"}
  - {key: standby, value: 60, unit: "minutes", dir: min, page: 2, locator: "3.3"}
updated: 2026-11-26
---
Ramp limits.

⟦p.2⟧
> 3.1 Ramps. The slope of a ramp shall not exceed 8 %. The clear width of a ramp shall be not less than 1.2 m.

RCD 30 mA. Standby lighting 60 minutes. Topic: [ramps](../../topics/access/ramps.md)
""")
    w(root, "sources/abc-2020/coverage.md", """---
type: coverage
source: abc-2020
---
| Pages | Wiki page | Treatment |
|---|---|---|
| 1 | — | not-ingested: cover |
| 2 | [ramps.md](ramps.md) | transcribed |
| 3 | — | not-ingested: index |
""")
    w(root, "sources/gde-2021/ramps.md", """---
type: source-page
title: "Ramps (GDE)"
source: gde-2021
source_pages: "2"
verification: {status: author-checked, author: me, date: 2026-11-26}
values:
  - {key: ramp-slope, value: 5, unit: "%", dir: max, page: 2}
  - {key: standby, value: 2, unit: "hours", dir: min, page: 2}
updated: 2026-11-26
---
⟦p.2⟧ The guide recommends ramps no steeper than 5 % and 1.5 m wide. Standby 2 hours.

Topic: [ramps](../../topics/access/ramps.md)
""")
    w(root, "sources/gde-2021/coverage.md", """---
type: coverage
source: gde-2021
---
| Pages | Wiki page | Treatment |
|---|---|---|
| 1 | — | not-ingested: cover |
| 2 | [ramps.md](ramps.md) | summarised |
""")
    w(root, "topics/access/ramps.md", """---
type: topic
title: "Ramp slope"
sources_covered:
  - {source: abc-2020, locators: ["3.1"], depth: raw}
  - {source: gde-2021, locators: ["p2"], depth: raw}
sources_silent: []
conflicts:
  - id: R-1
    between: [abc-2020, gde-2021]
    summary: "code 8 vs guide 5"
    status: resolved-by-profile
derived_from: [sources/abc-2020/ramps.md, sources/gde-2021/ramps.md]
verification: {status: derived}
updated: 2026-11-26
---
What each source says.

| Source | Slope | Width | Page |
|---|---|---|---|
| [ABC](../../sources/abc-2020/ramps.md) | max 8 % | 1.2 m | ⟦p.2⟧ |
| [GDE](../../sources/gde-2021/ramps.md) | max 5 % | 1.5 m | ⟦p.2⟧ |
""")
    w(root, "profiles/home.yaml", """name: home
binding:
  - {source: abc-2020, scope: all}
client: []
reference: [gde-2021]
excluded: []
""")
    w(root, "projects/p1.yaml", """id: p1
profile: home
decisions:
  - id: D-1
    topic: topics/access/ramps.md
    conflict: R-1
    key: ramp-slope
    value: 6
    unit: "%"
    decision: "6 % ramps"
    basis: brief
    date: 2026-11-26
""")
    w(root, "index.md", "[t](topics/access/ramps.md) [a](sources/abc-2020/ramps.md) [g](sources/gde-2021/ramps.md)\n")
    edka.cmd_hash(root)

def sub(root, rel, a, b, count=1):
    p = root / rel
    t = p.read_text(encoding="utf-8")
    assert a in t, (rel, a)
    p.write_text(t.replace(a, b, count), encoding="utf-8", newline="\n")

CASES = []
def case(name):
    def deco(fn):
        CASES.append((name, fn)); return fn
    return deco

T = "topics/access/ramps.md"; A = "sources/abc-2020/ramps.md"; G = "sources/gde-2021/ramps.md"

@case("00 baseline")
def _(r): pass
@case("01 topic % wrong (8->9) expect E015")
def _(r): sub(r, T, "max 8 %", "max 9 %")
@case("02 topic metre value wrong (1.2 m -> 2.1 m) expect E015")
def _(r): sub(r, T, "1.2 m", "2.1 m")
@case("03 topic swaps values between sources (ABC 5 %, GDE 8 %)")
def _(r): sub(r, T, "max 8 %", "max X %"); sub(r, T, "max 5 %", "max 8 %"); sub(r, T, "max X %", "max 5 %")
@case("04 source page body number wrong vs raw (60->90 minutes; value list too)")
def _(r): sub(r, A, "lighting 60 minutes", "lighting 90 minutes"); sub(r, A, "value: 60", "value: 90")
@case("05 quote inverted with ellipsis (drops 'not')")
def _(r): sub(r, A, "The slope of a ramp shall not exceed 8 %.", "The slope of a ramp shall … exceed 8 %.")
@case("06 quote: 'shall not' -> 'should not' expect E016")
def _(r): sub(r, A, "shall not exceed", "should not exceed")
@case("07 values: unit mA stated in body (30 mA) -> false E023?")
def _(r): sub(r, A, "values:\n", "values:\n  - {key: rcd, value: 30, unit: \"mA\", dir: max, page: 2}\n  - {key: width, value: 1.2, unit: \"m\", dir: min, page: 2}\n")
@case("08 type typo 'sorce-page' + garbage source id")
def _(r): sub(r, A, "type: source-page", "type: sorce-page"); sub(r, A, "source: abc-2020", "source: nope")
@case("09 UPPERCASE filename page with unknown source and no verification")
def _(r): w(r, "sources/abc-2020/NEC110.md", "---\ntype: source-page\nsource: nope\n---\n> invented quote that is nowhere in the raw text 999 %\n[[nonexistent-page]]\n")
@case("10 same key twice on one source page -> crash?")
def _(r): sub(r, A, "values:\n", "values:\n  - {key: ramp-slope, value: 10, unit: \"%\", dir: max, page: 2}\n"); sub(r, A, "RCD 30 mA", "RCD 30 mA, 10 %")
@case("11 updated: 2026-02-30 (invalid date)")
def _(r): sub(r, G, "updated: 2026-11-26", "updated: 2026-02-30")
@case("12 UTF-8 BOM on a page")
def _(r): p = r / G; p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8-sig", newline="\n")
@case("13 broken YAML in profile")
def _(r): sub(r, "profiles/home.yaml", "client: []", "client: [")
@case("14 conflict between unknown ids, status open")
def _(r): sub(r, T, "between: [abc-2020, gde-2021]", "between: [abc-2002, gdx]"); sub(r, T, "resolved-by-profile", "open")
@case("15 resolved-by-profile where only profile excludes one side (expect E011)")
def _(r): sub(r, "profiles/home.yaml", "reference: [gde-2021]\nexcluded: []", "reference: []\nexcluded: [gde-2021]")
@case("16 independent, ref points to missing file, no author")
def _(r): sub(r, A, "{status: author-checked, author: me, date: 2026-11-26}", "{status: independent, by: bob, date: 2026-11-26, ref: evidence/none.json}")
@case("17 coverage: 'transcribed' with no wiki link; page 2 mapped to other page")
def _(r): sub(r, "sources/abc-2020/coverage.md", "[ramps.md](ramps.md) | transcribed", "— | transcribed")
@case("18 source_pages outside the source (300-400) and '2, 3' list")
def _(r): sub(r, A, 'source_pages: "2"', 'source_pages: "300-400"'); sub(r, G, 'source_pages: "2"', 'source_pages: "2, 3"')
@case("19 E018 false alarm: row mentions 'binding' innocently")
def _(r): sub(r, T, "| max 8 % | 1.2 m |", "| max 8 % (non-binding note 4 excluded) | 1.2 m |")
@case("20 E018 evasion: 'Mandatory here?' column and 'For Saudi projects use ABC' prose")
def _(r): sub(r, T, "What each source says.", "For the home jurisdiction the answer is: use the code value; the guide does not apply.")
@case("21 withdrawn source used only through derived_from + table row")
def _(r): sub(r, "sources.yaml", "folder: sources/gde-2021\n  status: active", "folder: sources/gde-2021\n  status: withdrawn"); sub(r, T, "  - {source: gde-2021, locators: [\"p2\"], depth: raw}\n", ""); sub(r, T, "resolved-by-profile", "open")
@case("22 excluded_from_topics source used only through derived_from + row")
def _(r): w(r, "edka.yaml", "level: governed\nexcluded_from_topics: [gde-2021]\n"); sub(r, T, "  - {source: gde-2021, locators: [\"p2\"], depth: raw}\n", ""); sub(r, T, "resolved-by-profile", "open")
@case("23 decision weaker than binding (10 %) expect E024")
def _(r): sub(r, "projects/p1.yaml", "value: 6", "value: 10")
@case("24 decision weaker than stricter CLIENT requirement (guide as client 5 %, decision 6 %)")
def _(r): sub(r, "profiles/home.yaml", "client: []\nreference: [gde-2021]", "client: [gde-2021]\nreference: []")
@case("25 level governed, no profiles/projects/evidence at all")
def _(r): shutil.rmtree(r / "profiles"); shutil.rmtree(r / "projects"); sub(r, T, "resolved-by-profile", "open")
@case("26 duplicate source id in registry")
def _(r): p = r / "sources.yaml"; t = p.read_text(encoding="utf-8"); p.write_text(t + t.split("- id: gde-2021")[0].replace("Accessible Building Code", "Other doc"), encoding="utf-8")
@case("27 page transcription typo 'verbatum' + fake quote")
def _(r): sub(r, A, "source_pages:", "transcription: verbatum\nsource_pages:"); sub(r, A, "> 3.1 Ramps.", "> 3.1 Ramps are optional in all buildings whatsoever.")
@case("28 source both covered and silent")
def _(r): sub(r, T, "sources_silent: []", "sources_silent:\n  - {source: gde-2021, reason: nothing, depth: raw}")
@case("29 type: note without verification (spec 4.2 requires it)")
def _(r): w(r, "notes/lesson.md", "---\ntype: note\ntitle: x\n---\nlesson 99 %\n"); sub(r, "index.md", "[t]", "[n](notes/lesson.md) [t]")
@case("30 thousands separator: page says 1 V where raw says 1,000 V")
def _(r): sub(r, A, "RCD 30 mA.", "RCD 30 mA. Nominal voltage 1 V.")
@case("31 raw file edited after hash (expect E007)")
def _(r): sub(r, "raw/abc-2020.txt", "8 %", "9 %")
@case("32 coverage gap + overlap (expect E008)")
def _(r): sub(r, "sources/abc-2020/coverage.md", "| 3 | — | not-ingested: index |", "| 2 | — | pending |")
@case("33 registry: no 'pages', coverage map only covers page 2")
def _(r): sub(r, "sources.yaml", "  pages: 3\n", ""); sub(r, "sources/abc-2020/coverage.md", "| 1 | — | not-ingested: cover |\n", ""); sub(r, "sources/abc-2020/coverage.md", "| 3 | — | not-ingested: index |\n", "")
@case("34 topic row uses ambiguous wikilink [[ramps]] for guide row; view labels")
def _(r): sub(r, T, "[GDE](../../sources/gde-2021/ramps.md)", "GDE [[ramps]]")
@case("35 independent: author == by differing only by suffix ('agent' vs 'agent ')/ same person different label")
def _(r): sub(r, A, "{status: author-checked, author: me, date: 2026-11-26}", "{status: independent, author: claude, by: claude-2, date: 2026-11-26, ref: index.md}")
@case("36 decision topic written with ./ prefix")
def _(r): sub(r, "projects/p1.yaml", "topic: topics/access/ramps.md", "topic: ./topics/access/ramps.md")
@case("37 W120: paragraph mentions 'GDE' untagged; and source id inside a word")
def _(r): sub(r, T, "What each source says.", "GDE is softer than ABC 2020 here.")
@case("38 missing coverage map entirely at level governed")
def _(r): os.remove(r / "sources/abc-2020/coverage.md")
@case("39 frontmatter number wrong: conflict summary claims 80 %")
def _(r): sub(r, T, "code 8 vs guide 5", "code allows 80 % and guide 50 %")
@case("40 sources.yaml missing entirely")
def _(r): os.remove(r / "sources.yaml")

